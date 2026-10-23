"""Tests for money, stock integrity, idempotency and future-data leakage."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
import numpy as np
import pandas as pd
from retailpulse.store import Store, ConflictError, money_minor
from retailpulse.data import import_uci, import_sales
from retailpulse.forecast import daily_matrix, recursive_forecast, metrics, train, atomic_json
from retailpulse.web import Application, snapshot, csv_output


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        with self.store.connect() as conn:
            self.store.set_metadata(conn, {"currency":"INR", "timezone":"Asia/Kolkata", "source":"Test fixture", "mode":"demo"})
            conn.execute("INSERT INTO products (sku,name,price_minor,currency,stock,stock_initialized,lead_days,buffer_units) VALUES (?,?,?,?,?,?,?,?)", ("S1","Tea",1050,"INR",100,1,3,5))

    def payload(self, **changes):
        return {"sku":"S1", "quantity":3, "unit_price":"10.50", "event_id":"order-1", **changes}

    def test_sale_updates_stock_and_revenue_exactly(self):
        result = self.store.record(self.payload(), "sale")
        self.assertEqual(result["stock"],97)
        state = snapshot(self.store)
        self.assertEqual(state["summary"]["revenue_today_minor"],3150)
        self.assertEqual(state["summary"]["units_today"],3)

    def test_retries_in_parallel_record_one_sale(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _:self.store.record(self.payload(),"sale"),range(12)))
        self.assertEqual(sum(not result["duplicate"] for result in results),1)
        self.assertEqual(self.store.rows("SELECT stock FROM products")[0]["stock"],97)
        self.assertEqual(self.store.rows("SELECT COUNT(*) AS n FROM events")[0]["n"],1)

    def test_conflicting_retry_and_insufficient_stock_are_rolled_back(self):
        self.store.record(self.payload(),"sale")
        with self.assertRaises(ConflictError):
            self.store.record(self.payload(quantity=4),"sale")
        with self.assertRaises(ConflictError):
            self.store.record(self.payload(quantity=100,event_id="order-2"),"sale")
        self.assertEqual(self.store.rows("SELECT stock FROM products")[0]["stock"],97)
        self.assertEqual(len(self.store.rows("SELECT * FROM events")),1)

    def test_invalid_values_cannot_mutate_inventory(self):
        for quantity in (0,-1,1.5,True,"2",1_000_001):
            with self.subTest(quantity=quantity),self.assertRaises(ValueError):
                self.store.record(self.payload(quantity=quantity),"sale")
        for price in ("nan","inf","bad","-1","0"):
            with self.subTest(price=price),self.assertRaises(ValueError):
                self.store.record(self.payload(unit_price=price),"sale")
        self.assertEqual(self.store.rows("SELECT stock FROM products")[0]["stock"],100)

    def test_receipt_is_idempotent_and_initializes_unknown_stock(self):
        with self.store.connect() as conn:
            conn.execute("UPDATE products SET stock=0,stock_initialized=0")
        payload = self.payload(quantity=8,event_id="receipt-1")
        self.store.record(payload,"receipt")
        self.store.record(payload,"receipt")
        product = self.store.rows("SELECT * FROM products")[0]
        self.assertEqual((product["stock"],product["stock_initialized"]),(8,1))

    def test_reorder_point_subtracts_sales_already_recorded_today(self):
        today = self.store.today()
        rows = [{"sku":"S1","date":(today+timedelta(days=i)).isoformat(),"predicted_units":10} for i in range(14)]
        atomic_json(self.store.directory/"forecast.json",{"rows":rows,"train_through":(today-timedelta(days=1)).isoformat()})
        self.store.record(self.payload(),"sale")
        item = snapshot(self.store)["products"][0]
        self.assertEqual(item["reorder_point"],10*3-3+5)
        self.store.update_policy({"sku":"S1","lead_days":2,"buffer_units":0})
        self.assertEqual(snapshot(self.store)["products"][0]["reorder_point"],17)

    def test_stale_forecasts_do_not_create_restock_recommendations(self):
        atomic_json(self.store.directory/"forecast.json",{"rows":[{"sku":"S1","date":"2011-12-09","predicted_units":500}],"train_through":"2011-12-08"})
        state=snapshot(self.store)
        self.assertFalse(state["forecast_current"])
        self.assertIsNone(state["products"][0]["suggested_order"])

    def test_money_rounds_in_minor_units(self):
        self.assertEqual(money_minor("12.345"),1235)
        self.assertEqual(money_minor("0.01"),1)

    def test_wsgi_auth_validation_and_csv(self):
        app = Application(self.temp.name,token="example-secret")
        def request(path,method="GET",body=None,authorized=True):
            captured={}
            def start_response(status,headers):
                captured.update(status=status,headers=dict(headers))
            environ={"PATH_INFO":path,"REQUEST_METHOD":method,"QUERY_STRING":"table=daily_sales","wsgi.input":BytesIO(json.dumps(body).encode() if body else b"")}
            environ["CONTENT_LENGTH"]=str(len(environ["wsgi.input"].getvalue()))
            if authorized:environ["HTTP_AUTHORIZATION"]="Bearer example-secret"
            return captured,b"".join(app(environ,start_response))
        result,_=request("/api/state",authorized=False)
        self.assertTrue(result["status"].startswith("401"))
        result,body=request("/api/sales","POST",self.payload())
        self.assertTrue(result["status"].startswith("200"))
        self.assertEqual(json.loads(body)["stock"],97)
        result,_=request("/api/sales","POST",self.payload(quantity=-1))
        self.assertTrue(result["status"].startswith("400"))
        result,body=request("/api/export")
        self.assertTrue(result["status"].startswith("200"))
        self.assertIn(b"3150",body)

    def test_current_day_is_excluded_and_missing_sales_days_are_zero(self):
        today=self.store.today()
        with self.store.connect() as conn:
            self.store.set_metadata(conn,{"coverage_start":(today-timedelta(days=90)).isoformat(),"coverage_end":(today-timedelta(days=1)).isoformat(),"continuous_recording":True})
            conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",("history","S1","sale",7,1050,"2020-01-01T00:00:00+00:00",(today-timedelta(days=90)).isoformat(),"historical",0))
        self.store.record(self.payload(),"sale")
        panel=daily_matrix(self.store)
        self.assertEqual(len(panel),90)
        self.assertEqual(panel.index[-1].date(),today-timedelta(days=1))
        self.assertEqual(panel.S1.sum(),7)
        self.assertEqual(panel.S1.iloc[1],0)


class ForecastTests(unittest.TestCase):
    def test_weekly_baseline_repeats_only_available_history(self):
        panel=pd.DataFrame({"S1":np.arange(1,36)},index=pd.date_range("2026-01-01",periods=35))
        predicted=recursive_forecast(panel,14,"Weekly seasonal baseline")
        self.assertEqual(predicted.S1.tolist(),list(range(29,36))*2)

    def test_zero_total_wape_is_undefined(self):
        score=metrics([0,0],[1,1])
        self.assertEqual(score["mae"],1)
        self.assertIsNone(score["wape_percent"])

    def test_changing_test_truth_cannot_change_model_selection(self):
        class ZeroForest:
            def predict(self,x):return np.zeros(len(x))
        with TemporaryDirectory() as directory:
            store=Store(directory)
            with store.connect() as conn:store.set_metadata(conn,{"source":"Test fixture"})
            panel=pd.DataFrame({"S1":np.ones(100)},index=pd.date_range("2026-01-01",periods=100))
            with patch("retailpulse.forecast.daily_matrix",return_value=panel),patch("retailpulse.forecast.fit_forest",return_value=ZeroForest()):
                from retailpulse.forecast import train_mature
                first=train_mature(store)
            modified=panel.copy();modified.iloc[-14:]=100
            with patch("retailpulse.forecast.daily_matrix",return_value=modified),patch("retailpulse.forecast.fit_forest",return_value=ZeroForest()):
                second=train_mature(store)
            self.assertEqual(first["selected_method"],second["selected_method"])
            self.assertEqual(first["validation_comparison"],second["validation_comparison"])
            self.assertGreater(second["holdout_comparison"][first["selected_method"]]["mae"],0)
            self.assertLess(second["validation_windows"][-1]["predict_through"],second["holdout_period"]["from"])


class ImportTests(unittest.TestCase):
    def test_store_csv_validates_unique_line_ids_and_requires_complete_recent_log(self):
        with TemporaryDirectory() as directory:
            store=Store(Path(directory)/"store")
            today=store.today()
            file=Path(directory)/"sales.csv"
            yesterday=(today-timedelta(days=1)).isoformat()
            row={"event_id":"line-1","timestamp":yesterday+"T12:00:00","sku":"P1","product_name":"Rice","quantity":"2","unit_price":"65.50"}
            pd.DataFrame([row,row]).to_csv(file,index=False)
            report=import_sales(store,file,yesterday,continuous=True)
            self.assertEqual(report["accepted_rows"],1)
            self.assertEqual(store.metadata()["mode"],"live")
            self.assertEqual(store.rows("SELECT stock_initialized FROM products")[0]["stock_initialized"],0)
            other=Store(Path(directory)/"other")
            pd.DataFrame([row,{**row,"quantity":"3"}]).to_csv(file,index=False)
            with self.assertRaisesRegex(ValueError,"Duplicate event_id"):
                import_sales(other,file,yesterday)
            self.assertEqual(other.rows("SELECT * FROM products"),[])

    def test_import_preserves_dates_currency_and_filters_invalid_rows(self):
        columns=["InvoiceNo","StockCode","Description","Quantity","InvoiceDate","UnitPrice"]
        rows=[
            ["1","12345","Tea",4,"2011-01-01 10:00",2.5],
            ["1","12345","Tea",4,"2011-01-01 10:00",2.5],
            ["2","12345","Tea",5,"2011-01-02 10:00",2.5],
            ["C3","12345","Tea",5,"2011-01-02 11:00",2.5],
            ["4","12345","Tea",-2,"2011-01-02 12:00",2.5],
            ["5","POST","Postage",1,"2011-01-02 12:00",3.5],
            ["6","12345","Tea",9,"2011-01-03 10:00",2.5],
        ]
        with TemporaryDirectory() as directory:
            file=Path(directory)/"fixture.xlsx"
            pd.DataFrame(rows,columns=columns).to_excel(file,index=False)
            store=Store(Path(directory)/"store")
            report=import_uci(store,file,1)
            self.assertEqual(report["exact_duplicate_rows_removed"],1)
            self.assertEqual(report["cancellation_rows_excluded"],1)
            self.assertEqual(report["invalid_or_non_product_rows_excluded"],2)
            self.assertEqual(report["accepted_rows"],2)
            product=store.rows("SELECT * FROM products")[0]
            self.assertEqual((product["currency"],product["stock_initialized"]),("GBP",0))
            self.assertEqual(daily_matrix(store).index[-1].date().isoformat(),"2011-01-02")
            with self.assertRaises(ValueError):import_uci(store,file)

    def test_csv_names_cannot_be_excel_formulas(self):
        output=csv_output([{"name":"=HYPERLINK(\"x\")","stock":2}]).decode("utf-8-sig")
        self.assertIn("'=HYPERLINK",output)


if __name__=="__main__":unittest.main()
