from tempfile import TemporaryDirectory
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import unittest
from pypdf import PdfReader
from retailpulse.store import Store, ConflictError
from retailpulse.forecast import train
from retailpulse.commerce import qr_svg
from retailpulse.billing import receipt_pdf

class EarlyPaymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name)
        self.store.initialize_shop({'request_id':'setup-test','shop_name':'Satya Shop','currency':'INR','timezone':'Asia/Kolkata'})
        with self.store.connect() as c:
            self.store.set_metadata(c,{'coverage_start':(self.store.today()-timedelta(days=4)).isoformat()})
            c.execute("INSERT INTO products (sku,name,price_minor,currency,stock,stock_initialized,introduced_on) VALUES ('A','Rice',10000,'INR',30,1,?)",((self.store.today()-timedelta(days=4)).isoformat(),))
        self.payload={'bill_id':'pay-1','customer_name':'','customer_phone':'','items':[{'sku':'A','quantity':3,'unit_price':'100'}],'payment_method':'cash','billing_options':{'discount_type':'percent','discount_value':'10','supply_type':'local'}}

    def test_no_sale_until_confirmed_and_retries_commit_once(self):
        quote=self.store.create_payment_order(self.payload)
        self.assertEqual(quote['pricing']['total_minor'],27000)
        self.assertFalse(self.store.rows('SELECT * FROM bills'))
        self.assertEqual(self.store.rows('SELECT stock FROM products')[0]['stock'],30)
        with self.assertRaises(ValueError):self.store.confirm_payment_order({'order_id':'pay-1','received':False})
        with ThreadPoolExecutor(max_workers=4) as pool:
            bills=list(pool.map(lambda _:self.store.confirm_payment_order({'order_id':'pay-1','received':True}),range(6)))
        self.assertEqual(sum(not b['duplicate'] for b in bills),1)
        self.assertEqual(self.store.rows('SELECT stock FROM products')[0]['stock'],27)
        self.assertEqual(self.store.rows('SELECT revenue_minor FROM daily_sales')[0]['revenue_minor'],27000)

    def test_tax_discount_pdf_qr_and_partial_refund_reconcile(self):
        self.store.billing_settings({'upi_id':'satya@bank','gst_mode':'exclusive','gstin':'37ABCDE1234F1Z5','rates':{'A':'5'}})
        self.payload['payment_method']='upi'
        quote=self.store.create_payment_order(self.payload)
        self.assertEqual(quote['pricing']['total_minor'],28350)
        self.assertIn('am=283.50',quote['upi_uri'])
        self.assertIn(b'<svg',qr_svg(quote['upi_uri']))
        self.store.billing_settings({'upi_id':'other@bank','gst_mode':'off','rates':{}})
        self.assertEqual(self.store.create_payment_order(self.payload)['pricing']['total_minor'],28350)
        bill=self.store.confirm_payment_order({'order_id':'pay-1','received':True})
        text=''.join(p.extract_text() for p in PdfReader(BytesIO(receipt_pdf(bill))).pages)
        self.assertIn('Discount:',text);self.assertIn('GSTIN:',text);self.assertIn('INR 283.50',text)
        refunds=[]
        for i in range(3):
            record=self.store.return_bill({'return_id':f'refund-{i}','bill_id':'pay-1','reason':'test','restock':True,'items':[{'line_no':0,'quantity':1}]})
            refunds.append(record['refund_minor'])
        self.assertEqual(sum(refunds),28350)

    def test_inclusive_gst_and_invalid_discounts(self):
        self.store.billing_settings({'gst_mode':'inclusive','gstin':'37ABCDE1234F1Z5','rates':{'A':'5'}})
        q=self.store.create_payment_order(self.payload)['pricing']
        self.assertEqual(q['total_minor'],27000)
        self.assertEqual(q['taxable_minor']+q['tax_minor'],q['total_minor'])
        for value in ('100','101','NaN','-1'):
            p={**self.payload,'bill_id':'invalid','billing_options':{'discount_type':'percent','discount_value':value}}
            with self.assertRaises(ValueError):self.store.create_payment_order(p)

    def test_cancellation_and_shortage_do_not_create_bill(self):
        self.store.create_payment_order(self.payload)
        self.store.cancel_payment_order({'order_id':'pay-1'})
        with self.assertRaises(ConflictError):self.store.confirm_payment_order({'order_id':'pay-1','received':True})
        self.payload['bill_id']='pay-2';self.store.create_payment_order(self.payload)
        with self.store.connect() as c:c.execute('UPDATE products SET stock=0')
        with self.assertRaises(ConflictError):self.store.confirm_payment_order({'order_id':'pay-2','received':True})
        self.assertFalse(self.store.rows('SELECT * FROM bills'))

    def test_each_product_history_and_today_exclusion(self):
        with self.store.connect() as c:
            c.execute("INSERT INTO products (sku,name,price_minor,currency,stock,stock_initialized,introduced_on) VALUES ('B','New',100,'INR',20,1,?)",(self.store.today().isoformat(),))
            for offset,sku in ((4,'A'),(1,'A'),(0,'B')):
                day=(self.store.today()-timedelta(days=offset)).isoformat()
                c.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",(f'e-{offset}',sku,'sale',4,10000,day+'T12:00:00+00:00',day,'live',1))
        train(self.store)
        artifact=json.loads((self.store.directory/'forecast.json').read_text())
        self.assertEqual({r['sku'] for r in artifact['rows']},{'A'})
        self.assertEqual(artifact['product_methods']['A']['complete_days'],4)
        self.assertEqual(artifact['rows'][0]['predicted_units'],2)
        self.assertIsNone(artifact['evaluation'])

if __name__=='__main__':unittest.main()
