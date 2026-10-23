"""Saved shop branding, optional contacts, and safe retries across the upgrade."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from pypdf import PdfReader
from retailpulse.backups import create_backup, restore_backup
from retailpulse.billing import receipt_pdf
from retailpulse.store import Store, ConflictError, whatsapp_number


class ShopContactTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "shop")
        self.store.initialize_shop({"request_id": "setup", "shop_name": "Original Shop"})
        self.store.save_product({"request_id": "item", "sku": "TEA", "name": "Tea", "unit_price": "20", "opening_stock": 30})
        self.bill = {"bill_id": "first-bill", "shop_name": "Original Shop", "customer_name": "Test customer",
                     "items": [{"sku": "TEA", "quantity": 2, "unit_price": "20"}]}
        self.rename = {"request_id": "rename", "shop_name": "Satya Shop", "expected_shop_name": "Original Shop"}

    def test_saved_name_survives_restart_and_old_bill_keeps_its_header(self):
        self.store.checkout(self.bill)
        identity = self.store.metadata()["store_id"]
        self.store.rename_shop(self.rename)
        reopened = Store(self.store.directory)
        self.assertEqual(reopened.metadata()["shop_name"], "Satya Shop")
        self.assertEqual(reopened.metadata()["store_id"], identity)
        current = reopened.checkout({"bill_id": "new-bill", "items": self.bill["items"]})
        self.assertEqual(current["shop_name"], "Satya Shop")
        old = reopened.get_bill("first-bill")
        self.assertEqual(old["shop_name"], "Original Shop")
        for bill, name in [(old, "Original Shop"), (current, "Satya Shop")]:
            text = "".join(p.extract_text() for p in PdfReader(BytesIO(receipt_pdf(bill))).pages)
            self.assertIn(name, text)

    def test_rename_retry_is_audited_once_and_cannot_overwrite_a_later_name(self):
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda _: self.store.rename_shop(self.rename), range(8)))
        self.assertEqual(sum(not r["duplicate"] for r in results), 1)
        self.assertEqual(len(self.store.rows("SELECT * FROM actions WHERE kind='shop_name'")), 1)
        self.store.rename_shop({"request_id": "rename-again", "shop_name": "Satya Market", "expected_shop_name": "Satya Shop"})
        self.assertTrue(self.store.rename_shop(self.rename)["duplicate"])
        self.assertEqual(self.store.metadata()["shop_name"], "Satya Market")
        with self.assertRaises(ConflictError):
            self.store.rename_shop({**self.rename, "request_id": "stale"})
        with self.assertRaises(ConflictError):
            self.store.rename_shop({**self.rename, "shop_name": "Changed retry"})

    def test_invalid_or_unconfigured_name_change_leaves_records_unchanged(self):
        for name in ["", "\n", 1, "a" * 101, "Bad\x00name"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.store.rename_shop({**self.rename, "shop_name": name})
        empty = Store(Path(self.temp.name) / "empty")
        with self.assertRaises(ConflictError):
            empty.rename_shop({"request_id": "rename", "shop_name": "Satya Shop", "expected_shop_name": ""})
        self.assertEqual(self.store.metadata()["shop_name"], "Original Shop")
        self.assertEqual(self.store.rows("SELECT stock FROM products")[0]["stock"], 30)

    def test_number_formats_and_invalid_contact_cannot_commit_a_sale(self):
        for raw in ["9000000000", "+91 90000-00000", "0091 (90000) 00000", "919000000000"]:
            self.assertEqual(whatsapp_number(raw), "919000000000")
        self.assertEqual(whatsapp_number("+1 (202) 555-0100"), "12025550100")
        self.assertEqual(whatsapp_number(" "), "")
        for raw in [None, 9000000000, "12345", "1234567890", "+91 90000", "9" * 16,
                    "+9000000", "9000000000 ext 2", "https://wa.me/9000000000", "++919000000000", "\u0669" * 10]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.store.checkout({**self.bill, "customer_phone": raw})
        self.assertEqual(self.store.rows("SELECT stock FROM products")[0]["stock"], 30)
        self.assertEqual(self.store.rows("SELECT * FROM bills"), [])

    def test_contact_is_saved_and_equivalent_retries_commit_only_once(self):
        requests = [{**self.bill, "customer_phone": raw} for raw in ["9000000000", "+91 90000 00000"] * 4]
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(self.store.checkout, requests))
        self.assertEqual(sum(not r["duplicate"] for r in results), 1)
        self.assertEqual(Store(self.store.directory).get_bill("first-bill")["customer_phone"], "919000000000")
        with self.assertRaises(ConflictError):
            self.store.checkout({**self.bill, "customer_phone": "9000000001"})
        self.assertEqual(self.store.rows("SELECT stock FROM products")[0]["stock"], 28)
        self.assertEqual(len(self.store.rows("SELECT * FROM events")), 1)

    def test_previous_version_bill_retry_accepts_an_empty_optional_phone(self):
        self.store.checkout(self.bill)
        request = json.loads(self.store.rows("SELECT request_json FROM bills")[0]["request_json"])
        self.assertEqual(set(request), {"shop_name", "customer_name", "items"})
        self.assertTrue(self.store.checkout({**self.bill, "customer_phone": ""})["duplicate"])
        self.assertEqual(self.store.get_bill("first-bill")["customer_phone"], "")
        self.assertEqual(self.store.rows("PRAGMA user_version")[0]["user_version"], 5)
        self.assertEqual(self.store.rows("SELECT stock FROM products")[0]["stock"], 28)

    def test_retry_without_explicit_name_keeps_original_bill_after_rename(self):
        request = {"bill_id": "default-name", "items": self.bill["items"]}
        self.store.checkout(request)
        self.store.rename_shop(self.rename)
        result = self.store.checkout(request)
        self.assertTrue(result["duplicate"])
        self.assertEqual(result["shop_name"], "Original Shop")
        self.assertEqual(self.store.rows("SELECT stock FROM products")[0]["stock"], 28)

    def test_backup_restore_keeps_shop_name_and_immutable_customer_contact(self):
        self.store.checkout({**self.bill, "customer_phone": "9000000000"})
        self.store.rename_shop(self.rename)
        result = create_backup(self.store)
        destination = Path(self.temp.name) / "restored"
        restore_backup(self.store.directory / "backups" / result["filename"], destination)
        restored = Store(destination)
        self.assertEqual(restored.metadata()["shop_name"], "Satya Shop")
        bill = restored.get_bill("first-bill")
        self.assertEqual((bill["shop_name"], bill["customer_phone"]), ("Original Shop", "919000000000"))


if __name__ == "__main__":
    unittest.main()
