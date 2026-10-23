from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from tempfile import TemporaryDirectory
import json
import unittest
from pypdf import PdfReader
from retailpulse.store import Store, ConflictError
from retailpulse.web import Application
from retailpulse.billing import receipt_pdf

class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name)
        with self.store.connect() as c:
            self.store.set_metadata(c,{"mode":"demo","currency":"INR","timezone":"Asia/Kolkata"})
            c.executemany('INSERT INTO products (sku,name,price_minor,currency,stock,stock_initialized,lead_days,buffer_units) VALUES (?,?,?,?,?,?,?,?)',[("S1","Tea",1050,"INR",20,1,3,5),("S2","Coffee",2000,"INR",10,1,3,5)])
        self.payload={"bill_id":"test-bill-1","shop_name":"Village Store","customer_name":"Sai","items":[{"sku":"S1","quantity":3,"unit_price":"10.50"},{"sku":"S2","quantity":2,"unit_price":"20.00"}]}

    def test_checkout_saves_full_basket_and_correct_total(self):
        bill=self.store.checkout(self.payload)
        self.assertEqual(bill["total_minor"],7150)
        self.assertEqual([r['stock'] for r in self.store.rows('SELECT stock FROM products ORDER BY sku')],[17,8])
        self.assertEqual(len(self.store.rows('SELECT * FROM events')),2)
        self.assertEqual(len(bill['items']),2)
        self.assertEqual(bill['source'],'demo')

    def test_parallel_retries_commit_once(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:self.store.checkout(self.payload),range(12)))
        self.assertEqual(sum(not r['duplicate'] for r in results),1)
        self.assertEqual(len(self.store.rows('SELECT * FROM bills')),1)
        self.assertEqual(len(self.store.rows('SELECT * FROM events')),2)
        self.assertEqual(self.store.rows("SELECT stock FROM products WHERE sku='S1'")[0]['stock'],17)

    def test_second_line_shortage_leaves_every_table_unchanged(self):
        self.payload['items'][1]['quantity']=11
        with self.assertRaises(ConflictError):self.store.checkout(self.payload)
        self.assertEqual([r['stock'] for r in self.store.rows('SELECT stock FROM products ORDER BY sku')],[20,10])
        for table in ('bills','bill_lines','events','anomaly_checks'):
            self.assertEqual(self.store.rows(f'SELECT COUNT(*) AS n FROM {table}')[0]['n'],0)

    def test_changed_retry_and_duplicate_sku_do_not_decrement(self):
        self.store.checkout(self.payload)
        self.payload['items'][0]['quantity']=4
        with self.assertRaises(ConflictError):self.store.checkout(self.payload)
        self.payload['bill_id']='bill-2';self.payload['items'].append(self.payload['items'][0])
        with self.assertRaises(ValueError):self.store.checkout(self.payload)
        self.assertEqual(len(self.store.rows('SELECT * FROM events')),2)

    def test_bill_preserves_product_name_price_and_pdf(self):
        self.store.checkout(self.payload)
        with self.store.connect() as c:c.execute("UPDATE products SET name='Different Tea',price_minor=9900 WHERE sku='S1'")
        bill=self.store.get_bill(self.payload['bill_id'])
        self.assertEqual(bill['items'][0]['product_name'],'Tea')
        self.assertEqual(bill['items'][0]['unit_price_minor'],1050)
        text=''.join(page.extract_text() for page in PdfReader(BytesIO(receipt_pdf(bill))).pages)
        for wanted in ('Village Store','Sai','Tea','INR 71.50','DEMO TRANSACTION'):
            self.assertIn(wanted,text)
        self.assertNotIn('Different Tea',text)

    def test_anomaly_failure_rolls_back_entire_checkout(self):
        class Broken:
            def check(self,*args):raise RuntimeError('detector unavailable')
        with self.assertRaises(RuntimeError):self.store.checkout(self.payload,detector=Broken())
        self.assertEqual(len(self.store.rows('SELECT * FROM bills')),0)
        self.assertEqual(self.store.rows("SELECT stock FROM products WHERE sku='S1'")[0]['stock'],20)

    def test_api_pdf_auth_validation_and_manifest(self):
        app=Application(self.temp.name,token='secret')
        def request(path,method='GET',payload=None,auth=True):
            raw=json.dumps(payload).encode() if payload else b'';captured={}
            environ={'PATH_INFO':path,'REQUEST_METHOD':method,'CONTENT_LENGTH':str(len(raw)),'wsgi.input':BytesIO(raw)}
            if auth:environ['HTTP_AUTHORIZATION']='Bearer secret'
            body=b''.join(app(environ,lambda status,headers:captured.update(status=status,headers=dict(headers))))
            return captured,body
        headers,body=request('/api/checkout','POST',self.payload)
        self.assertTrue(headers['status'].startswith('200'))
        headers,body=request('/api/bills/test-bill-1.pdf',auth=False)
        self.assertTrue(headers['status'].startswith('401'))
        headers,body=request('/api/bills/test-bill-1.pdf')
        self.assertEqual(headers['headers']['Content-Type'],'application/pdf')
        self.assertTrue(body.startswith(b'%PDF'))
        self.assertTrue(request('/api/bills/missing.pdf')[0]['status'].startswith('404'))
        bad=dict(self.payload,customer_name=123,bill_id='new')
        self.assertTrue(request('/api/checkout','POST',bad)[0]['status'].startswith('400'))
        headers,body=request('/manifest.webmanifest',auth=False)
        self.assertEqual(headers['headers']['Content-Type'],'application/manifest+json; charset=utf-8')
        self.assertEqual(json.loads(body)['display'],'standalone')
        state=json.loads(request('/api/state')[1]);self.assertEqual(state['recent_bills'][0]['bill_id'],'test-bill-1')

if __name__=='__main__':unittest.main()
