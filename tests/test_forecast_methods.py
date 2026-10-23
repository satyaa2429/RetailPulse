from tempfile import TemporaryDirectory
from pathlib import Path
import json
import unittest
import numpy as np
from retailpulse.forecast import smooth_forecast,train,METHODS
from retailpulse.store import Store

class ForecastMethodsTests(unittest.TestCase):
    def test_weekly_pattern_is_preserved_and_zero_sales_are_finite(self):
        pattern=[5,5,5,5,5,15,15]
        np.testing.assert_allclose(smooth_forecast(pattern*8,14,True),pattern*2,atol=1e-8)
        np.testing.assert_allclose(smooth_forecast([0]*28,14,True),[0]*14)
        self.assertIn('Exponential smoothing',METHODS)
        self.assertIn('Holt-Winters',METHODS)
        self.assertIn('Random Forest',METHODS)
        with self.assertRaises(ValueError):smooth_forecast([1]*13,14,True)

    def test_short_comparison_uses_separate_validation_and_test(self):
        import pandas as pd
        with TemporaryDirectory() as directory:
            store=Store(directory)
            with store.connect() as c:
                store.set_metadata(c,{'coverage_start':'2026-01-01','coverage_end':'2026-01-28','continuous_recording':False,'source':'Test fixture'})
                c.execute("INSERT INTO products (sku,name,price_minor,currency,stock,stock_initialized,introduced_on) VALUES ('A','Rice',100,'INR',100,1,'2026-01-01')")
                for i,day in enumerate(pd.date_range('2026-01-01',periods=28)):
                    day=day.date().isoformat();quantity=15 if i%7>=5 else 5
                    c.execute('INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)',(f'e-{i}','A','sale',quantity,100,day+'T12:00:00+00:00',day,'live',1))
            train(store,compare=True)
            first=json.loads((Path(directory)/'forecast.json').read_text())['product_methods']['A']
            self.assertEqual(set(first['comparison']['holdout_comparison']),{'Exponential smoothing','Holt-Winters'})
            with store.connect() as c:c.execute("UPDATE events SET quantity=quantity*100 WHERE business_date>='2026-01-22'")
            train(store,compare=True)
            second=json.loads((Path(directory)/'forecast.json').read_text())['product_methods']['A']
            self.assertEqual(first['method'],second['method'])
            self.assertEqual(first['comparison']['validation_comparison'],second['comparison']['validation_comparison'])
            self.assertGreater(second['holdout_score']['mae'],first['holdout_score']['mae'])
