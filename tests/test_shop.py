"""Shop records, stock integrity, return limits, migrations and recoverable backups."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from pathlib import Path
import json
import sqlite3
import tempfile
import time
import unittest
from zipfile import ZipFile
from pypdf import PdfReader
from retailpulse.store import Store, ConflictError
from retailpulse.web import Application, snapshot
from retailpulse.backups import create_backup, restore_backup, list_backups, BackupManager
from retailpulse.billing import return_pdf, receipt_pdf


class ShopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/"shop")
        self.setup={"request_id":"setup-1","shop_name":"Village Store","currency":"INR","timezone":"Asia/Kolkata"}
        self.store.initialize_shop(self.setup)
        for sku,name,price,stock in [("S1","Tea","10.50",20),("S2","Coffee","20.00",10)]:
            self.store.save_product({"request_id":"add-"+sku,"sku":sku,"name":name,"unit_price":price,"opening_stock":stock})
        self.basket={"bill_id":"bill-1","shop_name":"Village Store","customer_name":"Customer","items":[{"sku":"S1","quantity":5,"unit_price":"10.50"},{"sku":"S2","quantity":2,"unit_price":"20.00"}]}

    def tearDown(self): self.temp.cleanup()
    def stock(self,sku="S1"): return self.store.rows("SELECT stock FROM products WHERE sku=?",(sku,))[0]["stock"]
    def return_request(self,id="return-1",quantity=2,restock=True):
        return {"return_id":id,"bill_id":"bill-1","reason":"Customer return","restock":restock,"items":[{"line_no":0,"quantity":quantity}]}

    def test_setup_does_not_add_sample_sales_and_retries_once(self):
        self.assertEqual(self.store.rows("SELECT * FROM events"),[])
        self.assertTrue(self.store.initialize_shop(self.setup)["duplicate"])
        self.assertEqual(self.store.metadata()["mode"],"live")
        with self.assertRaises(ConflictError):self.store.initialize_shop({**self.setup,"shop_name":"Other"})
        with self.assertRaises(ConflictError):self.store.initialize_shop({**self.setup,"request_id":"setup-2"})
        from retailpulse.stream import simulate
        with self.assertRaises(ValueError):simulate(self.store.directory,count=1)

    def test_parallel_product_retries_save_opening_stock_once(self):
        request={"request_id":"add-3","sku":"S3","name":"Soap","unit_price":"35.00","opening_stock":15}
        with ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:self.store.save_product(request),range(4)))
        self.assertEqual(sum(not r["duplicate"] for r in results),1)
        self.assertEqual(self.stock("S3"),15)
        self.assertEqual(len(self.store.rows("SELECT * FROM stock_movements WHERE sku='S3'")),1)
        with self.assertRaises(ConflictError):self.store.save_product({**request,"request_id":"other-add"})

    def test_edit_archive_preserves_existing_bill_and_return_can_restock(self):
        self.store.checkout(self.basket)
        product=self.store.rows("SELECT * FROM products WHERE sku='S1'")[0]
        edit={"request_id":"edit-1","sku":"S1","name":"New tea name","unit_price":"50.00","active":False,"expected_revision":product["revision"]}
        self.store.save_product(edit,edit=True)
        self.assertTrue(self.store.save_product(edit,edit=True)["duplicate"])
        bill=self.store.get_bill("bill-1")
        self.assertEqual((bill["items"][0]["product_name"],bill["items"][0]["unit_price_minor"]),("Tea",1050))
        with self.assertRaises(ConflictError):self.store.checkout({**self.basket,"bill_id":"bill-2"})
        with self.assertRaises(ConflictError):self.store.record({"event_id":"sale-new","sku":"S1","quantity":1,"unit_price":"50"},"sale")
        returned=self.store.return_bill(self.return_request())
        self.assertEqual(returned["refund_minor"],2100)
        self.assertEqual(self.stock(),17)

    def test_stale_product_edit_is_rejected(self):
        product=self.store.rows("SELECT * FROM products WHERE sku='S1'")[0]
        self.store.update_policy({"sku":"S1","lead_days":4,"buffer_units":20})
        with self.assertRaises(ConflictError):self.store.save_product({"request_id":"stale-edit","sku":"S1","name":"Tea","unit_price":"99","expected_revision":product["revision"]},edit=True)
        self.assertEqual(self.store.rows("SELECT price_minor FROM products WHERE sku='S1'")[0]["price_minor"],1050)

    def test_policy_retry_does_not_increment_revision_twice(self):
        request={"request_id":"policy-1","sku":"S1","lead_days":4,"buffer_units":20}
        self.store.update_policy(request)
        revision=self.store.rows("SELECT revision FROM products WHERE sku='S1'")[0]["revision"]
        self.assertTrue(self.store.update_policy(request)["duplicate"])
        self.assertEqual(self.store.rows("SELECT revision FROM products WHERE sku='S1'")[0]["revision"],revision)

    def test_invalid_product_values_cannot_change_records(self):
        request={"request_id":"bad-add","sku":"S3","name":"Soap","unit_price":"35","opening_stock":10}
        for fields in [{"opening_stock":-1},{"opening_stock":True},{"unit_price":"NaN"},{"unit_price":"0"},{"sku":"../x"},{"name":"\n"},{"active":"yes"},{"lead_days":0}]:
            with self.subTest(fields=fields),self.assertRaises(ValueError):self.store.save_product({**request,**fields})
        self.assertEqual(len(self.store.rows("SELECT * FROM products")),2)

    def test_physical_count_is_audited_and_idempotent(self):
        request={"request_id":"count-1","sku":"S1","counted_stock":0,"expected_stock":20,"reason":"Damaged stock"}
        result=self.store.adjust_stock(request)
        self.assertEqual((result["stock"],result["quantity_delta"]),(0,-20))
        self.assertTrue(self.store.adjust_stock(request)["duplicate"])
        row=self.store.rows("SELECT * FROM stock_movements WHERE kind='adjustment'")[0]
        self.assertEqual((row["quantity_delta"],row["reason"]),(-20,"Damaged stock"))
        self.assertEqual(snapshot(self.store)["summary"]["revenue_today_minor"],0)

    def test_count_cannot_overwrite_stock_changed_by_a_sale(self):
        self.store.record({"event_id":"sale-1","sku":"S1","quantity":1,"unit_price":"10.50"},"sale")
        with self.assertRaises(ConflictError):self.store.adjust_stock({"request_id":"stale-count","sku":"S1","expected_stock":20,"counted_stock":18,"reason":"Physical count"})
        self.assertEqual(self.stock(),19)
        self.assertFalse(self.store.rows("SELECT * FROM stock_movements WHERE kind='adjustment'"))

    def test_partial_return_updates_exact_refund_net_sales_and_stock(self):
        self.store.checkout(self.basket)
        result=self.store.return_bill(self.return_request())
        self.assertEqual(result["refund_minor"],2100)
        self.assertEqual(self.stock(),17)
        bill=self.store.get_bill("bill-1")
        self.assertEqual((bill["status"],bill["total_minor"],bill["net_total_minor"]),("partially_returned",9250,7150))
        self.assertEqual(bill["items"][0]["remaining_quantity"],3)
        summary=snapshot(self.store)["summary"]
        self.assertEqual((summary["gross_revenue_today_minor"],summary["refund_today_minor"],summary["revenue_today_minor"]),(9250,2100,7150))
        gross=self.store.rows("SELECT units FROM daily_sales WHERE sku='S1'")[0]["units"]
        net=self.store.rows("SELECT net_units,net_revenue_minor FROM net_daily_sales WHERE sku='S1'")[0]
        self.assertEqual((gross,net["net_units"],net["net_revenue_minor"]),(5,3,3150))

    def test_damaged_return_records_refund_without_restock(self):
        self.store.checkout(self.basket)
        self.store.return_bill(self.return_request(restock=False))
        self.assertEqual(self.stock(),15)
        self.assertFalse(self.store.rows("SELECT * FROM stock_movements WHERE kind='return'"))

    def test_parallel_identical_returns_commit_once(self):
        self.store.checkout(self.basket)
        with ThreadPoolExecutor(4) as pool:results=list(pool.map(lambda _:self.store.return_bill(self.return_request()),range(4)))
        self.assertEqual(sum(not r["duplicate"] for r in results),1)
        self.assertEqual(self.stock(),17)
        self.assertEqual(len(self.store.rows("SELECT * FROM returns")),1)

    def test_concurrent_distinct_returns_cannot_exceed_original_quantity(self):
        self.store.checkout(self.basket)
        def attempt(id):
            try:return self.store.return_bill(self.return_request(id,3))
            except ConflictError:return None
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(attempt,["r-a","r-b"]))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.stock(),18)

    def test_invalid_second_return_line_rolls_back_entire_return(self):
        self.store.checkout(self.basket)
        request=self.return_request()
        request["items"].append({"line_no":1,"quantity":3})
        with self.assertRaises(ConflictError):self.store.return_bill(request)
        self.assertEqual((self.stock(),self.stock("S2")),(15,8))
        self.assertFalse(self.store.rows("SELECT * FROM returns"))
        self.assertFalse(self.store.rows("SELECT * FROM return_lines"))

    def test_changed_retry_is_rejected_without_second_refund(self):
        self.store.checkout(self.basket)
        self.store.return_bill(self.return_request())
        with self.assertRaises(ConflictError):self.store.return_bill(self.return_request(quantity=1))
        self.assertEqual(self.store.get_bill("bill-1")["refund_minor"],2100)

    def test_cancellation_after_partial_return_refunds_only_remaining_items(self):
        self.store.checkout(self.basket)
        self.store.return_bill(self.return_request())
        request={"return_id":"cancel-1","bill_id":"bill-1","reason":"Wrong bill","restock":True}
        result=self.store.return_bill(request,cancel=True)
        self.assertEqual(result["refund_minor"],7150)
        self.assertTrue(self.store.return_bill(request,cancel=True)["duplicate"])
        self.assertEqual((self.stock(),self.stock("S2")),(20,10))
        bill=self.store.get_bill("bill-1")
        self.assertEqual((bill["status"],bill["net_total_minor"]),("cancelled",0))
        with self.assertRaises(ConflictError):self.store.return_bill(self.return_request("after-cancel",1))
        with self.assertRaises(ConflictError):self.store.return_bill({**request,"return_id":"cancel-2"},cancel=True)
        text=" ".join(page.extract_text() for page in PdfReader(BytesIO(receipt_pdf(bill))).pages)
        self.assertIn("CANCELLED",text)

    def test_return_pdf_shows_original_bill_and_exact_refund(self):
        self.store.checkout(self.basket)
        returned=self.store.return_bill(self.return_request())
        text=" ".join(page.extract_text() for page in PdfReader(BytesIO(return_pdf(returned))).pages)
        for word in ["RETURN RECORD","bill-1","return-1","Tea","21.00","Customer return"]:self.assertIn(word,text)

    def test_return_of_previous_day_sale_reduces_today_without_rewriting_history(self):
        self.store.checkout(self.basket)
        yesterday=(self.store.today()-timedelta(days=1)).isoformat()
        with self.store.connect() as conn:conn.execute("UPDATE events SET business_date=? WHERE kind='sale'",(yesterday,))
        self.store.return_bill(self.return_request())
        self.assertEqual(snapshot(self.store)["summary"]["revenue_today_minor"],-2100)
        self.assertEqual(self.store.rows("SELECT SUM(revenue_minor) AS revenue FROM daily_sales WHERE day=?",(yesterday,))[0]["revenue"],9250)

    def test_backup_restores_bills_returns_stock_and_store_identity(self):
        self.store.checkout(self.basket)
        self.store.return_bill(self.return_request())
        saved=create_backup(self.store)
        target=Path(self.temp.name)/"restored"
        restore_backup(self.store.directory/"backups"/saved["filename"],target)
        restored=Store(target)
        self.assertEqual(restored.metadata()["store_id"],self.store.metadata()["store_id"])
        self.assertEqual(restored.get_bill("bill-1")["net_total_minor"],7150)
        self.assertEqual(restored.rows("SELECT stock FROM products WHERE sku='S1'")[0]["stock"],17)
        self.assertTrue(restored.return_bill(self.return_request())["duplicate"])
        with self.assertRaises(ValueError):restore_backup(self.store.directory/"backups"/saved["filename"],target)

    def test_backup_while_sales_continue_is_an_atomic_snapshot(self):
        self.store.adjust_stock({"request_id":"count-big","sku":"S1","expected_stock":20,"counted_stock":200,"reason":"Counted opening balance"})
        def write_sales():
            for i in range(30):self.store.record({"event_id":f"s-{i}","sku":"S1","quantity":1,"unit_price":"10.50"},"sale")
        with ThreadPoolExecutor(1) as pool:
            future=pool.submit(write_sales)
            saved=create_backup(self.store)
            future.result()
        target=Path(self.temp.name)/"restored-live"
        restore_backup(self.store.directory/"backups"/saved["filename"],target)
        restored=Store(target)
        sold=restored.rows("SELECT COALESCE(SUM(quantity),0) AS q FROM events WHERE kind='sale'")[0]["q"]
        stock=restored.rows("SELECT stock FROM products WHERE sku='S1'")[0]["stock"]
        self.assertEqual(stock,200-sold)
        self.assertEqual(restored.rows("PRAGMA integrity_check")[0]["integrity_check"],"ok")

    def test_automatic_backup_retention_keeps_manual_files(self):
        create_backup(self.store,"manual")
        for _ in range(4):create_backup(self.store,"auto",retain_auto=2)
        rows=list_backups(self.store)
        self.assertEqual(sum(r["kind"]=="auto" for r in rows),2)
        self.assertEqual(sum(r["kind"]=="manual" for r in rows),1)

    def test_backup_manager_runs_on_start_and_again_on_schedule(self):
        manager=BackupManager(self.store,interval_seconds=.05)
        manager.start()
        deadline=time.monotonic()+2
        while len(list_backups(self.store))<2 and time.monotonic()<deadline:time.sleep(.02)
        manager.stop()
        self.assertGreaterEqual(len(list_backups(self.store)),2)
        self.assertIsNone(manager.error)
        time.sleep(.1)

    def test_invalid_backup_cannot_install_a_database(self):
        file=Path(self.temp.name)/"bad.zip"
        with ZipFile(file,"w") as archive:
            archive.writestr("../retailpulse.sqlite3","bad")
            archive.writestr("backup_info.json",'{"format":1}')
        target=Path(self.temp.name)/"bad-restore"
        with self.assertRaises(ValueError):restore_backup(file,target)
        self.assertFalse((target/"retailpulse.sqlite3").exists())

    def test_api_authorization_returns_backup_download_and_store_mismatch(self):
        app=Application(self.store.directory,token="secret")
        def call(path,body=None,authorized=True):
            encoded=json.dumps(body).encode() if body is not None else b""
            status=[]
            result=b"".join(app({"PATH_INFO":path,"REQUEST_METHOD":"POST" if body is not None else "GET","CONTENT_LENGTH":str(len(encoded)),"wsgi.input":BytesIO(encoded),"HTTP_AUTHORIZATION":"Bearer secret" if authorized else ""},lambda s,h:status.append(s)))
            return status[0],result
        self.assertEqual(call("/api/checkout",self.basket)[0],"200 OK")
        returned=json.loads(call("/api/returns",self.return_request())[1])
        self.assertEqual(returned["refund_minor"],2100)
        self.assertEqual(call("/api/returns/return-1.pdf",authorized=False)[0],"401 Unauthorized")
        self.assertTrue(call("/api/returns/return-1.pdf")[1].startswith(b"%PDF"))
        self.assertEqual(call("/api/returns/missing.pdf")[0],"404 Not Found")
        backup=json.loads(call("/api/backups",{})[1])
        path="/api/backups/"+backup["filename"]
        self.assertEqual(call(path,authorized=False)[0],"401 Unauthorized")
        self.assertTrue(call(path)[1].startswith(b"PK"))
        status,_=call("/api/stock/adjust",{"request_id":"wrong-store","store_id":"other-shop","sku":"S1","expected_stock":17,"counted_stock":0,"reason":"Count"})
        self.assertEqual(status,"409 Conflict")
        self.assertEqual(self.stock(),17)
        state=json.loads(call("/api/state")[1])
        self.assertEqual(state["summary"]["revenue_today_minor"],7150)

    def test_new_product_does_not_get_a_zero_history_forecast(self):
        from retailpulse.forecast import daily_matrix
        yesterday=(self.store.today()-timedelta(days=1)).isoformat()
        start=(self.store.today()-timedelta(days=120)).isoformat()
        with self.store.connect() as conn:
            self.store.set_metadata(conn,{"coverage_start":start})
            conn.execute("UPDATE products SET introduced_on=? WHERE sku='S1'",(start,))
            conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",("old-sale","S1","sale",1,1050,yesterday,yesterday,"store_csv",0))
        panel=daily_matrix(self.store)
        self.assertIn("S1",panel.columns)
        self.assertNotIn("S2",panel.columns)


class MigrationTests(unittest.TestCase):
    def test_old_database_is_backed_up_and_extended_without_losing_bills(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/"retailpulse.sqlite3"
            with sqlite3.connect(file) as conn:
                conn.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE products(sku TEXT PRIMARY KEY,name TEXT,price_minor INTEGER,currency TEXT,stock INTEGER,stock_initialized INTEGER,lead_days INTEGER,buffer_units INTEGER);
                CREATE TABLE events(event_id TEXT PRIMARY KEY,sku TEXT,kind TEXT,quantity INTEGER,unit_price_minor INTEGER,occurred_at TEXT,business_date TEXT,source TEXT,affects_stock INTEGER);
                CREATE TABLE bills(bill_id TEXT PRIMARY KEY,created_at TEXT,business_date TEXT,customer_name TEXT,shop_name TEXT,currency TEXT,total_minor INTEGER,source TEXT,request_json TEXT);
                CREATE TABLE bill_lines(bill_id TEXT,line_no INTEGER,event_id TEXT UNIQUE,sku TEXT,product_name TEXT,quantity INTEGER,unit_price_minor INTEGER,line_total_minor INTEGER,PRIMARY KEY(bill_id,line_no));
                INSERT INTO products VALUES('S1','Tea',1050,'INR',19,1,3,5);
                INSERT INTO metadata VALUES('mode','"demo"');
                INSERT INTO events VALUES('e1','S1','sale',1,1050,'2026-10-01','2026-10-01','live',1);
                INSERT INTO bills VALUES('old-bill','2026-10-01','2026-10-01','','Shop','INR',1050,'demo','{}');
                INSERT INTO bill_lines VALUES('old-bill',0,'e1','S1','Tea',1,1050,1050);
                """)
            store=Store(directory)
            self.assertEqual(store.get_bill("old-bill")["total_minor"],1050)
            self.assertEqual(store.rows("SELECT stock,active,revision FROM products")[0],{"stock":19,"active":1,"revision":0})
            backups=list((Path(directory)/"backups").glob("pre-upgrade-*.sqlite3"))
            self.assertEqual(len(backups),1)
            with sqlite3.connect(backups[0]) as old:
                self.assertEqual(old.execute("SELECT stock FROM products").fetchone()[0],19)
                self.assertNotIn("active",{r[1] for r in old.execute("PRAGMA table_info(products)")})
            Store(directory)
            self.assertEqual(len(list((Path(directory)/"backups").glob("pre-upgrade-*.sqlite3"))),1)


if __name__=="__main__":unittest.main()
