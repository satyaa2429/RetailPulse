"""Explicit synthetic demonstration and a separate real historical-data importer."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import math
import urllib.request
import zipfile
import numpy as np
import pandas as pd
from .store import money_minor

PRODUCTS = [
    ("RP001", "A5 Notebook", 65, 9), ("RP002", "Blue Ball Pen", 10, 22),
    ("RP003", "Tea · 250 g", 120, 7), ("RP004", "Soap Bar", 35, 13),
    ("RP005", "Rice · 1 kg", 60, 10), ("RP006", "Water · 1 L", 20, 27),
    ("RP007", "Snack Pack", 30, 20), ("RP008", "Shampoo · 100 ml", 85, 6),
]


def seed_demo(store, days=365):
    store.assert_empty()
    if not 90 <= days <= 1825:
        raise ValueError("Demo history must be between 90 and 1,825 days.")
    rng = np.random.default_rng(42)
    today = store.today()
    start = today - timedelta(days=days)
    with store.connect() as conn:
        store.set_metadata(conn, {"source": "Synthetic demonstration — not real customer data",
            "mode": "demo", "timezone": "Asia/Kolkata", "currency": "INR",
            "coverage_start": start.isoformat(), "coverage_end": (today-timedelta(days=1)).isoformat(),
            "continuous_recording": True, "created_at": datetime.now(timezone.utc).isoformat()})
        for index, (sku, name, price, rate) in enumerate(PRODUCTS):
            stock = int(rate * (1.1 if index in (2, 6) else 8))
            conn.execute("INSERT INTO products (sku,name,price_minor,currency,stock,stock_initialized,lead_days,buffer_units) VALUES (?,?,?,?,?,?,?,?)",
                         (sku, name, price*100, "INR", stock, 1, 3, int(rate*1.5)))
            for offset in range(days):
                day = start + timedelta(days=offset)
                weekly = 1.45 if day.weekday() >= 5 else (0.78 if day.weekday() == 0 else 1.0)
                seasonal = 1 + 0.16 * math.sin(2 * math.pi * offset / 180 + index)
                units = int(rng.poisson(rate * weekly * seasonal * (1 + 0.0003*offset)))
                if units:
                    moment = datetime.combine(day, datetime.min.time(), ZoneInfo("Asia/Kolkata")).replace(hour=16)
                    conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)", (
                        f"demo-{day}-{sku}", sku, "sale", units, price*100,
                        moment.astimezone(timezone.utc).isoformat(), day.isoformat(), "synthetic", 0))
    # These are illustrative live events, also explicitly marked by the demo dataset mode.
    for sku, _, price, _ in PRODUCTS[:4]:
        store.record({"sku": sku, "quantity": 2, "unit_price": price, "event_id": f"demo-today-{sku}"}, "sale")


def download_uci(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "Online_Retail.xlsx"
    if target.exists():
        return target
    url = "https://archive.ics.uci.edu/static/public/352/online+retail.zip"
    archive = destination / "online_retail.zip"
    request = urllib.request.Request(url, headers={"User-Agent": "RetailPulse/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        with zipfile.ZipFile(archive) as bundle:
            members = [name for name in bundle.namelist() if name.lower().endswith(".xlsx")]
            if len(members) != 1:
                raise ValueError("Expected one Excel file in the UCI download.")
            target.write_bytes(bundle.read(members[0]))
    finally:
        archive.unlink(missing_ok=True)
    return target


def import_uci(store, filename, top_products=12):
    store.assert_empty()
    if not 1 <= top_products <= 100:
        raise ValueError("Choose between 1 and 100 products.")
    raw = pd.read_excel(filename, dtype={"InvoiceNo": str, "StockCode": str})
    required = {"InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice"}
    if not required.issubset(raw.columns):
        raise ValueError(f"Missing UCI columns: {sorted(required-set(raw.columns))}")
    report = {"input_rows": len(raw), "dataset": "UCI Online Retail", "currency": "GBP"}
    frame = raw.drop_duplicates().copy()
    report["exact_duplicate_rows_removed"] = len(raw)-len(frame)
    frame["InvoiceDate"] = pd.to_datetime(frame.InvoiceDate, errors="coerce")
    frame["Quantity"] = pd.to_numeric(frame.Quantity, errors="coerce")
    frame["UnitPrice"] = pd.to_numeric(frame.UnitPrice, errors="coerce")
    cancelled = frame.InvoiceNo.str.upper().str.startswith("C", na=False)
    report["cancellation_rows_excluded"] = int(cancelled.sum())
    frame = frame[~cancelled].copy()
    valid = (frame.InvoiceDate.notna() & np.isfinite(frame.Quantity) & np.isfinite(frame.UnitPrice)
             & (frame.Quantity > 0) & (frame.Quantity % 1 == 0) & (frame.UnitPrice >= 0.005)
             & (frame.UnitPrice <= 1_000_000) & frame.StockCode.str.fullmatch(r"\d{5}[A-Za-z]*", na=False))
    report["invalid_or_non_product_rows_excluded"] = int((~valid).sum())
    frame = frame[valid].copy()
    if frame.empty:
        raise ValueError("No valid positive product sales were found.")
    start = frame.InvoiceDate.min().date()
    # The final calendar day can be partial. Exclude it for both training and evaluation.
    end = frame.InvoiceDate.max().date()-timedelta(days=1)
    frame = frame[frame.InvoiceDate.dt.date <= end].copy()
    report["last_partial_day_excluded"] = (end+timedelta(days=1)).isoformat()
    if frame.empty:
        raise ValueError("The file needs at least two calendar days of sales.")
    selection_end = max(start, min(start+timedelta(days=max(0,int((end-start).days*0.65))),end-timedelta(days=35)))
    ranking = frame[frame.InvoiceDate.dt.date <= selection_end].groupby("StockCode").Quantity.sum()
    selected = ranking.nlargest(top_products).index.tolist()
    if not selected:
        raise ValueError("No products appear in the initial training period.")
    frame = frame[frame.StockCode.isin(selected)].copy()
    report.update({"products_selected": selected, "selection_uses_dates_through": selection_end.isoformat(),
        "accepted_rows": len(frame), "coverage_start": start.isoformat(), "coverage_end": end.isoformat(),
        "notes": "Positive sales only; returns and cancelled rows are excluded. Inventory is not in this dataset."})
    with store.connect() as conn:
        store.set_metadata(conn, {"source": "UCI Online Retail — real historical transactions (2010–2011)",
            "mode": "historical", "timezone": "Europe/London", "currency": "GBP",
            "coverage_start": start.isoformat(), "coverage_end": end.isoformat(),
            "continuous_recording": False, "quality_report": report})
        for sku in selected:
            item = frame[frame.StockCode == sku]
            descriptions = item.Description.dropna().astype(str)
            name = descriptions.iloc[-1] if len(descriptions) else sku
            price = money_minor(float(item.UnitPrice.median()))
            conn.execute("INSERT INTO products (sku,name,price_minor,currency,stock,stock_initialized,lead_days,buffer_units) VALUES (?,?,?,?,?,?,?,?)", (sku, name, price, "GBP", 0, 0, 3, 10))
        records = []
        for row in frame.itertuples():
            timestamp = row.InvoiceDate.to_pydatetime().replace(tzinfo=ZoneInfo("Europe/London"))
            identity = "|".join(str(value) for value in (
                row.InvoiceNo, row.StockCode, row.Quantity, row.UnitPrice, row.InvoiceDate, row.Description,
                getattr(row, "CustomerID", ""), getattr(row, "Country", "")))
            event_id = "uci-"+hashlib.sha256(identity.encode()).hexdigest()
            records.append((event_id, row.StockCode, "sale", int(row.Quantity), money_minor(row.UnitPrice),
                            timestamp.astimezone(timezone.utc).isoformat(), timestamp.date().isoformat(), "uci", 0))
        conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)", records)
    (store.directory / "quality_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def import_sales(store, filename, complete_through, currency="INR", store_timezone="Asia/Kolkata", continuous=False):
    """Import a store's own complete sales log; fail clearly rather than silently discard rows."""
    store.assert_empty()
    if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
        raise ValueError("Use a three-letter currency code such as INR, GBP or USD.")
    zone = ZoneInfo(store_timezone)
    end = datetime.fromisoformat(complete_through).date()
    today = datetime.now(zone).date()
    if end >= today:
        raise ValueError("The complete-through date must be before today; today's sales are incomplete.")
    if continuous and end != today-timedelta(days=1):
        raise ValueError("Continuous mode needs a complete sales log through yesterday.")
    frame = pd.read_csv(filename, dtype=str, keep_default_na=False)
    columns = {"event_id", "timestamp", "sku", "product_name", "quantity", "unit_price"}
    if not columns.issubset(frame.columns):
        raise ValueError(f"Missing store CSV columns: {sorted(columns-set(frame.columns))}")
    if frame.empty:
        raise ValueError("The store CSV is empty.")
    records, products, seen = [], {}, {}
    for index, row in enumerate(frame.itertuples(), start=2):
        try:
            sku, name, event_id = row.sku.strip(), row.product_name.strip(), row.event_id.strip()
            if not sku or len(sku)>60 or not name or len(name)>150 or not event_id or len(event_id)>100:
                raise ValueError("Provide valid SKU, product_name and a unique event_id for each sales line.")
            quantity = Decimal(row.quantity)
            if not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value() or quantity>1_000_000:
                raise ValueError("Quantity must be a positive whole number, at most 1,000,000.")
            timestamp = datetime.fromisoformat(row.timestamp)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=zone)
            timestamp = timestamp.astimezone(zone)
            if timestamp.date()>end:
                raise ValueError("A sale is later than the declared complete-through date.")
            price = money_minor(row.unit_price)
            record = ("store-"+event_id, sku, "sale", int(quantity), price,
                      timestamp.astimezone(timezone.utc).isoformat(), timestamp.date().isoformat(), "store_csv", 0)
            if event_id in seen:
                if seen[event_id] != record:
                    raise ValueError("Duplicate event_id refers to different sales. Use a unique sales-line ID.")
                continue
            seen[event_id]=record
            records.append(record)
            products[sku]=(sku,name,price,currency,0,0,3,10)
        except (ValueError, InvalidOperation) as error:
            raise ValueError(f"CSV row {index}: {error}") from None
    start = min(record[6] for record in records)
    report = {"input_rows":len(frame), "accepted_rows":len(records), "duplicate_retries_skipped":len(frame)-len(records),
        "coverage_start":start,"coverage_end":end.isoformat(),"products":len(products),"currency":currency,
        "notes":"Inventory opening balances must be entered separately. Missing dates mean zero sales only if this is a complete log."}
    with store.connect() as conn:
        store.set_metadata(conn, {"source":"Store sales CSV — user-provided data", "mode":"live" if continuous else "historical_store",
            "timezone":store_timezone,"currency":currency,"coverage_start":start,"coverage_end":end.isoformat(),
            "continuous_recording":continuous,"quality_report":report})
        conn.executemany("INSERT INTO products (sku,name,price_minor,currency,stock,stock_initialized,lead_days,buffer_units) VALUES (?,?,?,?,?,?,?,?)",list(products.values()))
        conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",records)
    (store.directory/"quality_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report
