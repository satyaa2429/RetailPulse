"""Completed-day history and readiness shown by the shop interface."""
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest
from retailpulse.store import Store
from retailpulse.web import snapshot


class DashboardHistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory()
        self.store=Store(self.folder.name)
        self.day=date(2026,1,1)
        with patch.object(self.store,"today",return_value=self.day):
            self.store.initialize_shop({"request_id":"setup","shop_name":"Test shop"})
            self.store.save_product({"request_id":"item","sku":"TEA","name":"Tea","unit_price":"20","opening_stock":50})
            self.store.checkout({"bill_id":"bill","shop_name":"Test shop","items":[{"sku":"TEA","quantity":2,"unit_price":"20"}]})

    def tearDown(self):
        self.folder.cleanup()

    def at(self,day):
        with patch.object(self.store,"today",return_value=day):
            return snapshot(self.store)

    def test_today_is_not_a_completed_sales_day(self):
        state=self.at(self.day)
        self.assertEqual(state["summary"]["units_today"],2)
        self.assertEqual(state["history"],[])
        self.assertFalse(state["forecast_readiness"]["has_completed_sales"])

    def test_history_appears_after_the_day_ends_without_training(self):
        state=self.at(self.day+timedelta(days=1))
        self.assertEqual([(row["day"],row["units"]) for row in state["history"]],[(self.day.isoformat(),2)])
        self.assertEqual(state["forecast_readiness"]["complete_through"],self.day.isoformat())
        self.assertTrue(state["forecast_readiness"]["has_completed_sales"])
        self.assertIsNone(state["forecast"])

    def test_sales_readiness_includes_older_sales_outside_the_chart_window(self):
        state=self.at(self.day+timedelta(days=95))
        self.assertEqual(state["history"],[])
        self.assertTrue(state["forecast_readiness"]["has_completed_sales"])

    def test_stale_forecast_keeps_its_history_and_recent_completed_sales(self):
        newer=self.day+timedelta(days=94)
        with patch.object(self.store,"today",return_value=newer):
            self.store.checkout({"bill_id":"new-bill","shop_name":"Test shop","items":[{"sku":"TEA","quantity":3,"unit_price":"20"}]})
        Path(self.folder.name,"forecast.json").write_text(json.dumps({"train_through":self.day.isoformat(),"rows":[]}),encoding="utf-8")
        state=self.at(newer+timedelta(days=1))
        self.assertEqual({row["day"]:row["units"] for row in state["history"]},{self.day.isoformat():2,newer.isoformat():3})
        self.assertEqual(state["forecast_readiness"]["complete_through"],newer.isoformat())
