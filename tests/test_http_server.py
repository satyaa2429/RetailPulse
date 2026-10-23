"""Exercise the running HTTP server, beyond direct WSGI calls."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.request import Request, urlopen
from zipfile import ZipFile
from wsgiref.simple_server import make_server, WSGIRequestHandler
import json
import unittest
from retailpulse.web import Application,ThreadedServer


class QuietHandler(WSGIRequestHandler):
    def log_message(self,*args): pass


class HTTPTests(unittest.TestCase):
    def test_shop_workflow_over_actual_http(self):
        with TemporaryDirectory() as folder:
            app=Application(folder)
            server=make_server("127.0.0.1",0,app,server_class=ThreadedServer,handler_class=QuietHandler)
            thread=Thread(target=server.serve_forever,kwargs={"poll_interval":.05},daemon=True)
            thread.start()
            base=f"http://127.0.0.1:{server.server_port}"
            def call(path,payload=None):
                req=Request(base+path,data=None if payload is None else json.dumps(payload).encode(),headers={} if payload is None else {"Content-Type":"application/json"})
                with urlopen(req,timeout=5) as response:
                    body=response.read()
                    return json.loads(body) if response.headers.get_content_type()=="application/json" else body
            try:
                state=call("/api/state")
                self.assertTrue(state["shop_setup_required"])
                sid=state["metadata"]["store_id"]
                call("/api/setup",{"request_id":"http-setup","shop_name":"QA Sample Store","store_id":sid})
                product=call("/api/products",{"request_id":"http-product","sku":"SOAP01","name":"Soap bar","unit_price":"30","opening_stock":50,"store_id":sid})["product"]
                call("/api/checkout",{"bill_id":"http-bill","shop_name":"QA Sample Store","customer_phone":"9000000000","items":[{"sku":"SOAP01","quantity":3,"unit_price":"30"}],"store_id":sid})
                self.assertEqual(call("/api/bills/http-bill")["customer_phone"],"919000000000")
                call("/api/shop/name",{"request_id":"http-name","shop_name":"Satya Shop","expected_shop_name":"QA Sample Store","store_id":sid})
                self.assertEqual(call("/api/state")["metadata"]["shop_name"],"Satya Shop")
                self.assertEqual(call("/api/bills/http-bill")["shop_name"],"QA Sample Store")
                self.assertEqual(call("/api/state")["products"][0]["stock"],47)
                call("/api/returns",{"return_id":"http-return","bill_id":"http-bill","reason":"Sample return","restock":True,"items":[{"line_no":0,"quantity":1}],"store_id":sid})
                state=call("/api/state")
                self.assertEqual((state["products"][0]["stock"],state["summary"]["revenue_today_minor"]),(48,6000))
                call("/api/bills/cancel",{"return_id":"http-cancel","bill_id":"http-bill","reason":"Correct the bill","restock":True,"store_id":sid})
                self.assertEqual(call("/api/bills/http-bill")["status"],"cancelled")
                self.assertEqual(call("/api/state")["products"][0]["stock"],50)
                call("/api/products/edit",{"request_id":"http-edit","sku":"SOAP01","name":"Soap 100g","unit_price":"35","expected_revision":product["revision"],"active":False,"store_id":sid})
                call("/api/stock/adjust",{"request_id":"http-count","sku":"SOAP01","expected_stock":50,"counted_stock":47,"reason":"Damaged stock count","store_id":sid})
                backup=call("/api/backups",{"store_id":sid})
                raw=call("/api/backups/"+backup["filename"])
                with ZipFile(BytesIO(raw)) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertIn("retailpulse.sqlite3",archive.namelist())
                self.assertTrue(call("/api/returns/http-return.pdf").startswith(b"%PDF"))
                self.assertIn(b"net_revenue_minor",call("/api/export?table=net_daily_sales"))
                html=call("/")
                for name in [b'id="shop-setup"',b'id="product-form"',b'id="return-form"',b'id="count-form"',b'id="backups"',b'id="shop-name-form"',b'id="bill-share"',b'id="bill-customer-phone"']:
                    self.assertIn(name,html)
                self.assertIn(b'retailpulse_action',call("/app.js"))
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)
