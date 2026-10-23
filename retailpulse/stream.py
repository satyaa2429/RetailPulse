"""Continuous labelled simulation and transaction-level anomaly inference."""
import random
import time
import uuid
import numpy as np
from sklearn.ensemble import IsolationForest
from .store import Store, ConflictError

class Detector:
    def __init__(self, store):
        self.models = {}
        self.demo_prices = {}
        self.demo = store.metadata().get("mode") == "demo"
        for product in store.rows("SELECT sku FROM products"):
            sku = product["sku"]
            rows = store.rows("SELECT quantity,unit_price_minor FROM events WHERE sku=? AND kind='sale' AND source!='simulated' ORDER BY occurred_at DESC LIMIT 2000", (sku,))
            if self.demo:
                price = store.rows("SELECT price_minor FROM products WHERE sku=?", (sku,))[0]["price_minor"]
                self.demo_prices[sku] = price
                rng = random.Random(42)
                rows = [{"quantity": rng.randint(1,4), "unit_price_minor": price} for _ in range(500)]
            if len(rows) >= 50:
                features = [[np.log1p(r["quantity"]), np.log1p(r["unit_price_minor"])] for r in rows]
                self.models[sku] = IsolationForest(n_estimators=80, contamination=0.02, random_state=42, n_jobs=1).fit(features)

    def check(self, sku, quantity, price):
        model = self.models.get(sku)
        if model is None:
            return {"flagged": False, "score": None, "method": "Insufficient reference data (50 sales required)"}
        score = float(model.decision_function([[np.log1p(quantity), np.log1p(price)]])[0])
        return {"flagged": score < 0 or (self.demo and (quantity > 4 or price != self.demo_prices[sku])), "score": score, "method": "Isolation Forest; " + ("synthetic reference + demo quantity/price bounds" if self.demo else "prior transaction reference")}

def simulate(directory, interval=2.0, count=None):
    if interval < 0.2:
        raise ValueError("Interval must be at least 0.2 seconds.")
    store = Store(directory)
    if store.metadata().get("mode") != "demo":
        raise ValueError("Simulator requires a demo-only data directory. Never run it against real shop inventory.")
    detector = Detector(store)
    print("SIMULATED stream started. Ctrl+C stops it. Demo stock receipts are also simulated.", flush=True)
    index = 0
    while count is None or index < count:
        product = random.choice(store.rows("SELECT * FROM products"))
        quantity = random.randint(1, 4)
        price = product["price_minor"] / 100
        injected = index % 12 == 11
        if injected:
            quantity = 60
            price *= 5
        if product["stock"] < quantity:
            store.record({"event_id": str(uuid.uuid4()), "sku": product["sku"], "quantity": 200}, "receipt", source="simulated")
        result = store.record({"event_id": str(uuid.uuid4()), "sku": product["sku"], "quantity": quantity, "unit_price": price}, "sale", source="simulated", detector=detector)
        print(f"SIMULATED {product['sku']} x{quantity} | injected={injected} | flagged={result['anomaly']['flagged']}", flush=True)
        index += 1
        if count is None or index < count:
            time.sleep(interval)
