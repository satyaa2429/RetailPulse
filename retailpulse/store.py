"""SQLite storage. Every live event and stock movement is one transaction."""
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import json
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products (
 sku TEXT PRIMARY KEY, name TEXT NOT NULL, price_minor INTEGER NOT NULL CHECK(price_minor>0),
 currency TEXT NOT NULL, stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0),
 stock_initialized INTEGER NOT NULL DEFAULT 0,
 lead_days INTEGER NOT NULL DEFAULT 3 CHECK(lead_days BETWEEN 1 AND 14),
 buffer_units INTEGER NOT NULL DEFAULT 10 CHECK(buffer_units>=0),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 revision INTEGER NOT NULL DEFAULT 0, introduced_on TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events (
 event_id TEXT PRIMARY KEY, sku TEXT NOT NULL REFERENCES products(sku),
 kind TEXT NOT NULL CHECK(kind IN ('sale','receipt')),
 quantity INTEGER NOT NULL CHECK(quantity>0), unit_price_minor INTEGER NOT NULL CHECK(unit_price_minor>=0),
 occurred_at TEXT NOT NULL, business_date TEXT NOT NULL, source TEXT NOT NULL,
 affects_stock INTEGER NOT NULL CHECK(affects_stock IN (0,1))
);
CREATE TABLE IF NOT EXISTS anomaly_checks (
 event_id TEXT PRIMARY KEY REFERENCES events(event_id), flagged INTEGER NOT NULL,
 score REAL, method TEXT NOT NULL, checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bills (
 bill_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, business_date TEXT NOT NULL,
 customer_name TEXT NOT NULL, shop_name TEXT NOT NULL, currency TEXT NOT NULL,
 total_minor INTEGER NOT NULL CHECK(total_minor>0), source TEXT NOT NULL,
 request_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bill_lines (
 bill_id TEXT NOT NULL REFERENCES bills(bill_id), line_no INTEGER NOT NULL,
 event_id TEXT NOT NULL UNIQUE REFERENCES events(event_id), sku TEXT NOT NULL,
 product_name TEXT NOT NULL, quantity INTEGER NOT NULL, unit_price_minor INTEGER NOT NULL,
 line_total_minor INTEGER NOT NULL, PRIMARY KEY(bill_id,line_no)
);
CREATE INDEX IF NOT EXISTS idx_events_day ON events(business_date,sku,kind);
CREATE VIEW IF NOT EXISTS daily_sales AS
 SELECT business_date AS day, sku, SUM(quantity) AS units,
 SUM(quantity*unit_price_minor) AS revenue_minor
 FROM events WHERE kind='sale' GROUP BY business_date,sku;
CREATE TABLE IF NOT EXISTS actions (
 action_id TEXT PRIMARY KEY, kind TEXT NOT NULL, created_at TEXT NOT NULL,
 request_json TEXT NOT NULL, response_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_movements (
 movement_id TEXT PRIMARY KEY, sku TEXT NOT NULL REFERENCES products(sku),
 kind TEXT NOT NULL CHECK(kind IN ('opening','adjustment','return')),
 quantity_delta INTEGER NOT NULL, stock_after INTEGER NOT NULL CHECK(stock_after>=0),
 reason TEXT NOT NULL, reference_id TEXT NOT NULL, created_at TEXT NOT NULL,
 business_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS returns (
 return_id TEXT PRIMARY KEY, bill_id TEXT NOT NULL REFERENCES bills(bill_id),
 kind TEXT NOT NULL CHECK(kind IN ('return','cancellation')),
 created_at TEXT NOT NULL, business_date TEXT NOT NULL, reason TEXT NOT NULL,
 restock INTEGER NOT NULL CHECK(restock IN (0,1)), refund_minor INTEGER NOT NULL CHECK(refund_minor>0),
 request_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS return_lines (
 return_id TEXT NOT NULL REFERENCES returns(return_id), line_no INTEGER NOT NULL,
 original_line_no INTEGER NOT NULL, sku TEXT NOT NULL REFERENCES products(sku),
 product_name TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0),
 unit_price_minor INTEGER NOT NULL, refund_minor INTEGER NOT NULL,
 PRIMARY KEY(return_id,line_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_bill_cancellation ON returns(bill_id) WHERE kind='cancellation';
CREATE INDEX IF NOT EXISTS idx_returns_day ON returns(business_date);
CREATE VIEW IF NOT EXISTS net_daily_sales AS
 SELECT day,sku,SUM(gross_units) AS gross_units,SUM(returned_units) AS returned_units,
 SUM(gross_revenue_minor) AS gross_revenue_minor,SUM(refund_minor) AS refund_minor,
 SUM(gross_units-returned_units) AS net_units,
 SUM(gross_revenue_minor-refund_minor) AS net_revenue_minor
 FROM (
  SELECT day,sku,units AS gross_units,0 AS returned_units,revenue_minor AS gross_revenue_minor,0 AS refund_minor FROM daily_sales
  UNION ALL
  SELECT r.business_date,l.sku,0,l.quantity,0,l.refund_minor FROM returns r JOIN return_lines l USING(return_id)
 ) GROUP BY day,sku;
"""


class ConflictError(ValueError):
    pass


def positive_int(value, label="Quantity", maximum=1_000_000):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{label} must be a whole number from 1 to {maximum:,}.")
    return value


def nonnegative_int(value, label="Stock", maximum=1_000_000):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{label} must be a whole number from 0 to {maximum:,}.")
    return value


def text_value(value, label, maximum=150, required=True):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    value = value.strip()
    if (required and not value) or len(value)>maximum or any(ord(c)<32 for c in value):
        raise ValueError(f"{label} must be plain text, up to {maximum} characters.")
    return value


def whatsapp_number(value):
    """Store international digits; local Indian mobile numbers use country code 91."""
    value = text_value(value, "WhatsApp number", 40, required=False)
    if not value:
        return ""
    if not re.fullmatch(r"\+?[0-9 ()-]+", value):
        raise ValueError("Enter a WhatsApp number using digits, with a country code for numbers outside India.")
    digits = re.sub(r"[ ()-]", "", value)
    international = digits.startswith(("+", "00"))
    if digits.startswith("+"):
        digits = digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]
    if not international and len(digits) == 10:
        if digits[0] not in "6789":
            raise ValueError("For an Indian mobile, enter 10 digits. For another number, include + and its country code.")
        digits = "91" + digits
    elif not international and len(digits) < 11:
        raise ValueError("Enter a 10-digit Indian mobile number, or include + and the country code.")
    if not re.fullmatch(r"[1-9][0-9]{7,14}", digits) or (digits.startswith("91") and len(digits) != 12):
        raise ValueError("Check the WhatsApp number and country code. Indian numbers need 10 digits after +91.")
    return digits


def safe_id(value, label="Request ID"):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",value):
        raise ValueError(f"{label} must use letters, numbers, hyphens or underscores (up to 64).")
    return value


def money_minor(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > 1_000_000:
            raise ValueError("Price must be positive and no more than 1,000,000.")
        minor = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if minor < 1:
            raise ValueError("Price must be at least 0.01.")
        return minor
    except (InvalidOperation, TypeError):
        raise ValueError("Enter a valid price.") from None


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "retailpulse.sqlite3"
        if self.path.exists() and self.path.stat().st_size:
            with closing(sqlite3.connect(self.path)) as old:
                version = old.execute("PRAGMA user_version").fetchone()[0]
                if version>5: raise ValueError("This database needs a newer RetailPulse version.")
                if version < 5:
                    backup_dir = self.directory / "backups"
                    backup_dir.mkdir(exist_ok=True)
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    with closing(sqlite3.connect(backup_dir/f"pre-upgrade-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3")) as target:
                        old.backup(target)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            columns = {r[1] for r in conn.execute("PRAGMA table_info(products)")}
            if "active" not in columns:
                conn.execute("ALTER TABLE products ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))")
            if "revision" not in columns:
                conn.execute("ALTER TABLE products ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
            if "introduced_on" not in columns:
                conn.execute("ALTER TABLE products ADD COLUMN introduced_on TEXT NOT NULL DEFAULT ''")
            if "pricing_json" not in {r[1] for r in conn.execute("PRAGMA table_info(bills)")}:
                conn.execute("ALTER TABLE bills ADD COLUMN pricing_json TEXT NOT NULL DEFAULT '{}'")
            conn.execute("CREATE TABLE IF NOT EXISTS payment_orders (order_id TEXT PRIMARY KEY, request_json TEXT NOT NULL, pricing_json TEXT NOT NULL, config_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL)")
            conn.execute("DROP VIEW IF EXISTS daily_sales")
            conn.execute("CREATE VIEW daily_sales AS SELECT e.business_date AS day,e.sku,SUM(e.quantity) AS units,SUM(COALESCE(l.line_total_minor,e.quantity*e.unit_price_minor)) AS revenue_minor FROM events e LEFT JOIN bill_lines l ON l.event_id=e.event_id WHERE e.kind='sale' GROUP BY e.business_date,e.sku")
            conn.execute("PRAGMA user_version=5")
            conn.execute("INSERT OR IGNORE INTO metadata VALUES (?,?)",("store_id",json.dumps(str(uuid.uuid4()))))

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def metadata(self):
        with self.connect() as conn:
            return {row["key"]: json.loads(row["value"]) for row in conn.execute("SELECT * FROM metadata")}

    @staticmethod
    def set_metadata(conn, values):
        conn.executemany("INSERT OR REPLACE INTO metadata VALUES (?,?)",
                         [(key, json.dumps(value)) for key, value in values.items()])

    def today(self):
        return datetime.now(ZoneInfo(self.metadata().get("timezone", "Asia/Kolkata"))).date()

    def rows(self, sql, params=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def assert_empty(self):
        if self.rows("SELECT sku FROM products LIMIT 1"):
            raise ValueError("This data folder already contains a project. Choose another --data-dir.")

    def record(self, payload, kind, source="live", detector=None):
        if kind not in ("sale", "receipt"):
            raise ValueError("Unknown event type.")
        sku = str(payload.get("sku", "")).strip()
        event_id = str(payload.get("event_id", "")).strip()
        if not event_id or len(event_id) > 100 or not sku:
            raise ValueError("Provide a product and an event_id of at most 100 characters.")
        quantity = positive_int(payload.get("quantity"))
        now = datetime.now(timezone.utc)
        day = self.today().isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            product = conn.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
            if product is None:
                raise ValueError("Unknown product.")
            price = money_minor(payload.get("unit_price")) if kind == "sale" else 0
            existing = conn.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if existing:
                if (existing["sku"], existing["kind"], existing["quantity"], existing["unit_price_minor"]) != (sku, kind, quantity, price):
                    raise ConflictError("This event_id was already used for a different event.")
                return {"event_id": event_id, "duplicate": True, "stock": product["stock"]}
            if kind == "sale" and not product["active"]:
                raise ConflictError("This product is archived. Restore it before selling it.")
            if kind == "sale" and (not product["stock_initialized"] or product["stock"] < quantity):
                raise ConflictError("Insufficient recorded stock. Add a stock receipt first.")
            change = -quantity if kind == "sale" else quantity
            conn.execute("UPDATE products SET stock=stock+?,stock_initialized=1 WHERE sku=?", (change, sku))
            conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",
                         (event_id, sku, kind, quantity, price, now.isoformat(), day, source, 1))
            check = detector.check(sku, quantity, price) if kind == "sale" and detector else None
            if check:
                conn.execute("INSERT INTO anomaly_checks VALUES (?,?,?,?,?)", (event_id, int(check["flagged"]), check["score"], check["method"], now.isoformat()))
            return {"event_id": event_id, "duplicate": False, "stock": product["stock"] + change, "anomaly": check}

    def update_policy(self, payload):
        sku = str(payload.get("sku", ""))
        lead = positive_int(payload.get("lead_days"), "Lead time", 14)
        buffer = payload.get("buffer_units")
        if isinstance(buffer, bool) or not isinstance(buffer, int) or not 0 <= buffer <= 1_000_000:
            raise ValueError("Buffer stock must be a whole number from 0 to 1,000,000.")
        action_id = safe_id(payload["request_id"]) if "request_id" in payload else None
        request = {"sku":sku,"lead_days":lead,"buffer_units":buffer}
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if action_id:
                existing = self._existing_action(conn,action_id,"restock_policy",request)
                if existing: return existing
            updated = conn.execute("UPDATE products SET lead_days=?,buffer_units=?,revision=revision+1 WHERE sku=?", (lead, buffer, sku))
            if not updated.rowcount:
                raise ValueError("Unknown product.")
            if action_id: return self._save_action(conn,action_id,"restock_policy",request,{"updated":True},datetime.now(timezone.utc).isoformat())
        return {"updated": True}


    def checkout(self, payload, detector=None, payment_order=None):
        """Commit the full basket, stock changes and immutable bill in one transaction."""
        import re
        bill_id = payload.get("bill_id", "")
        if not isinstance(bill_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", bill_id):
            raise ValueError("Provide a bill_id using letters, numbers, hyphens or underscores (up to 64).")
        customer = payload.get("customer_name", "")
        shop = payload.get("shop_name", self.metadata().get("shop_name", "Satya Shop"))
        phone = whatsapp_number(payload.get("customer_phone", ""))
        if not isinstance(customer,str) or not isinstance(shop,str):
            raise ValueError("Shop and customer names must be text.")
        customer,shop = customer.strip(),shop.strip()
        if not shop or len(shop) > 100 or len(customer) > 100 or any(ord(c) < 32 for c in customer+shop):
            raise ValueError("Shop and customer names must be plain text, up to 100 characters.")
        items = payload.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            raise ValueError("A bill needs 1 to 50 items.")
        lines, seen = [], set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each item must be a JSON object.")
            sku = item.get("sku", "")
            if not isinstance(sku, str) or not sku or sku in seen:
                raise ValueError("Select each product once and combine its quantities.")
            seen.add(sku)
            lines.append({"sku":sku, "quantity":positive_int(item.get("quantity")), "unit_price_minor":money_minor(item.get("unit_price"))})
        request = {"customer_name":customer,"shop_name":shop,"items":lines}
        if "billing_options" in payload:
            request["billing_options"] = payload["billing_options"]
        if payment_order:
            request["payment"] = {"method":payload.get("payment_method","cash"),"confirmation":"cashier confirmed receipt","order_id":payment_order}
        # Omit an empty optional phone to preserve retries of bills saved by older versions.
        if phone:
            request["customer_phone"] = phone
        now = datetime.now(timezone.utc).isoformat()
        day = self.today().isoformat()
        meta = self.metadata()
        source = "demo" if meta.get("mode") == "demo" else "live"
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT request_json FROM bills WHERE bill_id=?", (bill_id,)).fetchone()
            if existing and "shop_name" not in payload:
                request["shop_name"] = json.loads(existing["request_json"])["shop_name"]
            request_json = json.dumps(request, sort_keys=True)
            if existing:
                if existing["request_json"] != request_json:
                    raise ConflictError("This bill_id was already used for a different basket.")
                duplicate = True
            else:
                products = {}
                for line in lines:
                    product = conn.execute("SELECT * FROM products WHERE sku=?",(line["sku"],)).fetchone()
                    if not product:
                        raise ValueError("Unknown product: " + line["sku"])
                    if not product["active"]:
                        raise ConflictError("This product is archived: " + product["name"])
                    if not product["stock_initialized"] or product["stock"] < line["quantity"]:
                        raise ConflictError("Insufficient stock for " + product["name"] + ". Add stock first.")
                    products[line["sku"]] = product
                currencies = {r["currency"] for r in products.values()}
                if len(currencies) != 1:
                    raise ValueError("A bill must use one currency.")
                from .commerce import price
                currency = currencies.pop()
                if payment_order:
                    order = conn.execute("SELECT * FROM payment_orders WHERE order_id=?",(payment_order,)).fetchone()
                    if not order or order["status"]!='pending': raise ConflictError("Payment order is not pending.")
                    pricing = json.loads(order["pricing_json"])
                    conn.execute("UPDATE payment_orders SET status='paid' WHERE order_id=?",(payment_order,))
                else:
                    pricing = price(lines,meta.get("billing",{}),payload.get("billing_options",{}))
                if pricing["gst_mode"]!='off' and currency!='INR': raise ValueError("GST billing supports INR only.")
                total = pricing["total_minor"]
                conn.execute("INSERT INTO bills (bill_id,created_at,business_date,customer_name,shop_name,currency,total_minor,source,request_json,pricing_json) VALUES (?,?,?,?,?,?,?,?,?,?)",(bill_id,now,day,customer,shop,currency,total,source,request_json,json.dumps(pricing)))
                for index, line in enumerate(lines):
                    sku,quantity,price = line["sku"],line["quantity"],line["unit_price_minor"]
                    event_id = "bill:" + bill_id + ":" + str(index)
                    if conn.execute("SELECT 1 FROM events WHERE event_id=?",(event_id,)).fetchone():
                        raise ConflictError("Bill event ID conflicts with an existing transaction.")
                    conn.execute("UPDATE products SET stock=stock-? WHERE sku=?",(quantity,sku))
                    conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?)",(event_id,sku,"sale",quantity,price,now,day,"live",1))
                    conn.execute("INSERT INTO bill_lines VALUES (?,?,?,?,?,?,?,?)",(bill_id,index,event_id,sku,pricing["lines"][index].get("product_name",products[sku]["name"]),quantity,price,pricing["lines"][index]["total_minor"]))
                    if detector:
                        check = detector.check(sku,quantity,price)
                        conn.execute("INSERT INTO anomaly_checks VALUES (?,?,?,?,?)",(event_id,int(check["flagged"]),check["score"],check["method"],now))
                duplicate = False
        bill = self.get_bill(bill_id)
        bill["duplicate"] = duplicate
        return bill

    def get_bill(self, bill_id):
        with self.connect() as conn:
            conn.execute("BEGIN")
            row = conn.execute("SELECT bill_id,created_at,business_date,customer_name,shop_name,currency,total_minor,source,request_json,pricing_json FROM bills WHERE bill_id=?", (bill_id,)).fetchone()
            if not row:
                raise KeyError("Bill not found.")
            bill = dict(row)
            request = json.loads(bill.pop("request_json"))
            bill["customer_phone"] = request.get("customer_phone", "")
            bill["payment"] = request.get("payment")
            bill["pricing"] = json.loads(bill.pop("pricing_json"))
            bill["items"] = [dict(row) for row in conn.execute("SELECT line_no,sku,product_name,quantity,unit_price_minor,line_total_minor FROM bill_lines WHERE bill_id=? ORDER BY line_no", (bill_id,))]
            returned = {row["original_line_no"]:row["quantity"] for row in conn.execute("SELECT l.original_line_no,SUM(l.quantity) AS quantity FROM return_lines l JOIN returns r USING(return_id) WHERE r.bill_id=? GROUP BY l.original_line_no",(bill_id,))}
            for line in bill["items"]:
                line["returned_quantity"] = returned.get(line["line_no"],0)
                line["remaining_quantity"] = line["quantity"]-line["returned_quantity"]
            bill["returns"] = [dict(row) for row in conn.execute("SELECT return_id,kind,created_at,reason,restock,refund_minor FROM returns WHERE bill_id=? ORDER BY created_at",(bill_id,))]
            bill["refund_minor"] = sum(r["refund_minor"] for r in bill["returns"])
            bill["net_total_minor"] = bill["total_minor"]-bill["refund_minor"]
            bill["status"] = "cancelled" if any(r["kind"]=="cancellation" for r in bill["returns"]) else "returned" if bill["items"] and all(l["remaining_quantity"]==0 for l in bill["items"]) else "partially_returned" if bill["returns"] else "active"
            return bill

    @staticmethod
    def _existing_action(conn, action_id, kind, request):
        row = conn.execute("SELECT * FROM actions WHERE action_id=?",(action_id,)).fetchone()
        if row:
            if row["kind"]!=kind or row["request_json"]!=json.dumps(request,sort_keys=True):
                raise ConflictError("This request ID was used for a different action.")
            return {**json.loads(row["response_json"]),"duplicate":True}

    @staticmethod
    def _save_action(conn, action_id, kind, request, result, now):
        conn.execute("INSERT INTO actions VALUES (?,?,?,?,?)",(action_id,kind,now,json.dumps(request,sort_keys=True),json.dumps(result)))
        return {**result,"duplicate":False}

    def initialize_shop(self, payload):
        action_id = safe_id(payload.get("request_id"))
        name = text_value(payload.get("shop_name"),"Shop name",100)
        currency = payload.get("currency","INR")
        if not isinstance(currency,str) or not re.fullmatch(r"[A-Z]{3}",currency):
            raise ValueError("Use a three-letter currency such as INR.")
        zone_name = text_value(payload.get("timezone","Asia/Kolkata"),"Timezone",60)
        try:
            zone = ZoneInfo(zone_name)
        except (ValueError,KeyError):
            raise ValueError("Unknown timezone.") from None
        request = {"shop_name":name,"currency":currency,"timezone":zone_name}
        now = datetime.now(timezone.utc)
        today = now.astimezone(zone).date()
        from datetime import timedelta
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = self._existing_action(conn,action_id,"setup",request)
            if existing: return existing
            if conn.execute("SELECT 1 FROM products LIMIT 1").fetchone() or conn.execute("SELECT 1 FROM metadata WHERE key='mode'").fetchone():
                raise ConflictError("This database already has a setup. Start in a separate empty shop folder.")
            self.set_metadata(conn,{"shop_name":name,"currency":currency,"timezone":zone_name,"mode":"live",
                "source":"Your shop's recorded sales","continuous_recording":True,
                "coverage_start":today.isoformat(),"coverage_end":(today-timedelta(days=1)).isoformat(),"created_at":now.isoformat()})
            return self._save_action(conn,action_id,"setup",request,{"shop_name":name,"configured":True},now.isoformat())

    def rename_shop(self, payload):
        """Change the saved name for future bills without rewriting original receipts."""
        action_id = safe_id(payload.get("request_id"))
        name = text_value(payload.get("shop_name"), "Shop name", 100)
        expected = text_value(payload.get("expected_shop_name"), "Previous shop name", 100, required=False)
        request = {"shop_name": name, "expected_shop_name": expected}
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = self._existing_action(conn, action_id, "shop_name", request)
            if existing:
                return existing
            if not conn.execute("SELECT 1 FROM metadata WHERE key='mode'").fetchone():
                raise ConflictError("Set up your shop first, then change its name here.")
            row = conn.execute("SELECT value FROM metadata WHERE key='shop_name'").fetchone()
            current = json.loads(row["value"]) if row else ""
            if current != expected:
                raise ConflictError("The shop name changed in another window. Refresh the page and try again.")
            self.set_metadata(conn, {"shop_name": name})
            return self._save_action(conn, action_id, "shop_name", request, {"shop_name": name}, now)

    def save_product(self, payload, edit=False):
        action_id = safe_id(payload.get("request_id"))
        sku = payload.get("sku","")
        if not isinstance(sku,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,59}",sku):
            raise ValueError("Item code needs 1-60 letters, numbers, dots, hyphens or underscores.")
        name = text_value(payload.get("name"),"Product name")
        price = money_minor(payload.get("unit_price"))
        lead = positive_int(payload.get("lead_days",3),"Lead time",14)
        buffer = nonnegative_int(payload.get("buffer_units",10),"Buffer stock")
        active = payload.get("active",True)
        if not isinstance(active,bool): raise ValueError("Active must be true or false.")
        request = {"sku":sku,"name":name,"price_minor":price,"lead_days":lead,"buffer_units":buffer,"active":active}
        if edit: request["expected_revision"] = nonnegative_int(payload.get("expected_revision"),"Product revision",2**31-1)
        else: request["opening_stock"] = nonnegative_int(payload.get("opening_stock",0),"Opening stock")
        now = datetime.now(timezone.utc).isoformat()
        day = self.today().isoformat()
        kind = "edit_product" if edit else "add_product"
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = self._existing_action(conn,action_id,kind,request)
            if existing: return existing
            meta = {r["key"]:json.loads(r["value"]) for r in conn.execute("SELECT * FROM metadata")}
            if "mode" not in meta: raise ConflictError("Set up your shop before adding products.")
            old = conn.execute("SELECT * FROM products WHERE sku=?",(sku,)).fetchone()
            if edit:
                if old is None: raise ValueError("Unknown product.")
                if old["revision"]!=request["expected_revision"]: raise ConflictError("This product changed. Reload it before saving.")
                conn.execute("UPDATE products SET name=?,price_minor=?,lead_days=?,buffer_units=?,active=?,revision=revision+1 WHERE sku=?",(name,price,lead,buffer,int(active),sku))
            else:
                if old: raise ConflictError("This item code already exists. Edit the existing product.")
                stock = request["opening_stock"]
                conn.execute("INSERT INTO products (sku,name,price_minor,currency,stock,stock_initialized,lead_days,buffer_units,active,revision,introduced_on) VALUES (?,?,?,?,?,?,?,?,?,?,?)",(sku,name,price,meta.get("currency","INR"),stock,1,lead,buffer,int(active),1,day))
                conn.execute("INSERT INTO stock_movements VALUES (?,?,?,?,?,?,?,?,?)",("opening:"+action_id,sku,"opening",stock,stock,"Counted opening stock",action_id,now,day))
            product = dict(conn.execute("SELECT * FROM products WHERE sku=?",(sku,)).fetchone())
            return self._save_action(conn,action_id,kind,request,{"product":product,"before":dict(old) if old else None},now)

    def adjust_stock(self, payload):
        action_id = safe_id(payload.get("request_id"))
        sku = text_value(payload.get("sku"),"Product code",60)
        counted = nonnegative_int(payload.get("counted_stock"),"Counted stock")
        expected = nonnegative_int(payload.get("expected_stock"),"Expected stock",2**31-1)
        reason = text_value(payload.get("reason"),"Reason",200)
        request = {"sku":sku,"counted_stock":counted,"expected_stock":expected,"reason":reason}
        now = datetime.now(timezone.utc).isoformat()
        day = self.today().isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = self._existing_action(conn,action_id,"adjust_stock",request)
            if existing: return existing
            row = conn.execute("SELECT * FROM products WHERE sku=?",(sku,)).fetchone()
            if row is None: raise ValueError("Unknown product.")
            if row["stock"]!=expected: raise ConflictError("Stock changed since you loaded the count. Reload and check it before saving.")
            change = counted-row["stock"]
            conn.execute("UPDATE products SET stock=?,stock_initialized=1 WHERE sku=?",(counted,sku))
            conn.execute("INSERT INTO stock_movements VALUES (?,?,?,?,?,?,?,?,?)",("adjustment:"+action_id,sku,"adjustment",change,counted,reason,action_id,now,day))
            return self._save_action(conn,action_id,"adjust_stock",request,{"sku":sku,"stock":counted,"previous_stock":row["stock"],"quantity_delta":change},now)

    def return_bill(self, payload, cancel=False):
        return_id = safe_id(payload.get("return_id"),"Return ID")
        bill_id = safe_id(payload.get("bill_id"),"Bill ID")
        reason = text_value(payload.get("reason"),"Reason",200)
        restock = payload.get("restock",True)
        if not isinstance(restock,bool): raise ValueError("Restock must be true or false.")
        requested = []
        if not cancel:
            items = payload.get("items")
            if not isinstance(items,list) or not 1<=len(items)<=50: raise ValueError("Select at least one returned item.")
            seen = set()
            for line in items:
                if not isinstance(line,dict): raise ValueError("Each returned item must be an object.")
                index = nonnegative_int(line.get("line_no"),"Bill line",49)
                if index in seen: raise ValueError("Select each bill line only once.")
                seen.add(index)
                requested.append({"line_no":index,"quantity":positive_int(line.get("quantity"))})
            requested.sort(key=lambda l:l["line_no"])
        kind = "cancellation" if cancel else "return"
        request_json = json.dumps({"bill_id":bill_id,"reason":reason,"restock":restock,"items":requested,"kind":kind},sort_keys=True)
        now = datetime.now(timezone.utc).isoformat()
        day = self.today().isoformat()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT request_json FROM returns WHERE return_id=?",(return_id,)).fetchone()
            if existing:
                if existing["request_json"]!=request_json: raise ConflictError("This return ID was used for a different return.")
                duplicate = True
            else:
                bill = conn.execute("SELECT * FROM bills WHERE bill_id=?",(bill_id,)).fetchone()
                if bill is None: raise ValueError("Bill not found.")
                if conn.execute("SELECT 1 FROM returns WHERE bill_id=? AND kind='cancellation'",(bill_id,)).fetchone(): raise ConflictError("This bill is already cancelled.")
                originals = {r["line_no"]:dict(r) for r in conn.execute("SELECT * FROM bill_lines WHERE bill_id=?",(bill_id,))}
                returned = {r["original_line_no"]:r["quantity"] for r in conn.execute("SELECT l.original_line_no,SUM(l.quantity) AS quantity FROM return_lines l JOIN returns r USING(return_id) WHERE r.bill_id=? GROUP BY l.original_line_no",(bill_id,))}
                if cancel:
                    requested = [{"line_no":i,"quantity":l["quantity"]-returned.get(i,0)} for i,l in originals.items() if l["quantity"]>returned.get(i,0)]
                    if not requested: raise ConflictError("All items have already been returned.")
                lines = []
                for item in requested:
                    original = originals.get(item["line_no"])
                    if original is None: raise ValueError("Returned item does not belong to this bill.")
                    if item["quantity"]>original["quantity"]-returned.get(item["line_no"],0): raise ConflictError("Return quantity exceeds the remaining sold quantity for "+original["product_name"]+".")
                    lines.append({**original,"return_quantity":item["quantity"]})
                for line in lines:
                    prior = returned.get(line["line_no"],0)
                    line["refund"] = line["line_total_minor"]*(prior+line["return_quantity"])//line["quantity"] - line["line_total_minor"]*prior//line["quantity"]
                total = sum(l["refund"] for l in lines)
                conn.execute("INSERT INTO returns VALUES (?,?,?,?,?,?,?,?,?)",(return_id,bill_id,kind,now,day,reason,int(restock),total,request_json))
                for index,line in enumerate(lines):
                    qty,sku = line["return_quantity"],line["sku"]
                    conn.execute("INSERT INTO return_lines VALUES (?,?,?,?,?,?,?,?)",(return_id,index,line["line_no"],sku,line["product_name"],qty,line["unit_price_minor"],line["refund"]))
                    if restock:
                        conn.execute("UPDATE products SET stock=stock+? WHERE sku=?",(qty,sku))
                        stock = conn.execute("SELECT stock FROM products WHERE sku=?",(sku,)).fetchone()[0]
                        conn.execute("INSERT INTO stock_movements VALUES (?,?,?,?,?,?,?,?,?)",(f"return:{return_id}:{index}",sku,"return",qty,stock,reason,return_id,now,day))
                duplicate = False
        result = self.get_return(return_id)
        result["duplicate"] = duplicate
        return result

    def get_return(self, return_id):
        with self.connect() as conn:
            conn.execute("BEGIN")
            row = conn.execute("SELECT r.*,b.shop_name,b.customer_name,b.currency,b.source FROM returns r JOIN bills b USING(bill_id) WHERE return_id=?",(return_id,)).fetchone()
            if row is None: raise KeyError("Return not found.")
            result = dict(row)
            result.pop("request_json")
            result["items"] = [dict(r) for r in conn.execute("SELECT * FROM return_lines WHERE return_id=? ORDER BY line_no",(return_id,))]
            return result


    def billing_settings(self, payload):
        from .commerce import settings
        clean = settings(payload,{r["sku"] for r in self.rows("SELECT sku FROM products")})
        if clean["gst_mode"]!='off' and self.metadata().get("currency","INR")!='INR':
            raise ValueError("GST billing supports INR only.")
        with self.connect() as conn:
            self.set_metadata(conn,{"billing":clean})
        return clean

    def create_payment_order(self, payload):
        from .commerce import price, payment_uri
        items = payload.get("items")
        if not isinstance(items,list) or not 1<=len(items)<=50: raise ValueError("Choose 1 to 50 items.")
        order_id=safe_id(payload.get('bill_id'),'Bill ID')
        existing=self.rows("SELECT * FROM payment_orders WHERE order_id=?",(order_id,))
        if existing:
            from .commerce import payment_uri
            previous=json.loads(existing[0]['request_json'])
            if any(previous.get(key)!=value for key,value in payload.items()): raise ConflictError("This payment ID belongs to a different basket.")
            if existing[0]['status']=='cancelled': raise ConflictError("Payment request was cancelled.")
            pricing=json.loads(existing[0]['pricing_json']); config=json.loads(existing[0]['config_json']); method=previous.get('payment_method','cash')
            currency=self.rows("SELECT currency FROM products WHERE sku=?",(previous['items'][0]['sku'],))[0]['currency']
            return {'order_id':order_id,'pricing':pricing,'currency':currency,'payment_method':method,
                'upi_uri':payment_uri(config['upi_id'],previous['shop_name'],pricing['total_minor'],order_id) if method=='upi' else None}
        config = self.metadata().get("billing",{})
        lines=[];seen=set();currencies=set()
        for item in items:
            if not isinstance(item,dict): raise ValueError("Invalid basket item.")
            sku=item.get("sku")
            if not isinstance(sku,str) or sku in seen: raise ValueError("Select each item once.")
            seen.add(sku)
            found=self.rows("SELECT * FROM products WHERE sku=?",(sku,))
            if not found or not found[0]["active"]: raise ValueError("Choose an active product.")
            product=found[0]; quantity=positive_int(item.get("quantity"));currencies.add(product["currency"])
            if not product["stock_initialized"] or product["stock"]<quantity: raise ConflictError("Insufficient stock for "+product["name"])
            lines.append({"sku":sku,"quantity":quantity,"unit_price_minor":money_minor(item.get("unit_price")),"product_name":product["name"]})
        if len(currencies)!=1: raise ValueError("Choose products in one currency.")
        currency=currencies.pop()
        pricing=price(lines,config,payload.get("billing_options",{}))
        if pricing["gst_mode"]!='off' and currency!='INR': raise ValueError("GST supports INR only.")
        method=payload.get("payment_method","cash")
        if method not in ('cash','upi'): raise ValueError("Choose cash or UPI.")
        if method=='upi' and (currency!='INR' or not config.get('upi_id')): raise ValueError("Save your UPI ID first. UPI requires INR.")
        request={**payload,"bill_id":order_id,"shop_name":self.metadata().get("shop_name","Satya Shop")}
        request['customer_phone']=whatsapp_number(payload.get('customer_phone',''))
        for field in ('customer_name','shop_name'):
            value=request.get(field,'')
            if not isinstance(value,str) or len(value)>100 or any(ord(c)<32 for c in value): raise ValueError("Invalid customer or shop name.")
        with self.connect() as conn:
            inserted=conn.execute("INSERT OR IGNORE INTO payment_orders VALUES (?,?,?,?,?,?)",(order_id,json.dumps(request),json.dumps(pricing),json.dumps(config),'pending',datetime.now(timezone.utc).isoformat())).rowcount
        if not inserted: return self.create_payment_order(payload)
        return {'order_id':order_id,'pricing':pricing,'currency':currency,'payment_method':method,
            'upi_uri':payment_uri(config['upi_id'],request['shop_name'],pricing['total_minor'],order_id) if method=='upi' else None}

    def confirm_payment_order(self, payload, detector=None):
        if payload.get('received') is not True: raise ValueError("Confirm payment receipt first.")
        order_id=safe_id(payload.get('order_id'),'Order ID')
        rows=self.rows("SELECT * FROM payment_orders WHERE order_id=?",(order_id,))
        if not rows: raise ValueError("Payment order not found.")
        if rows[0]['status']=='cancelled': raise ConflictError("This payment request was cancelled.")
        request=json.loads(rows[0]['request_json'])
        return self.checkout(request,detector=detector,payment_order=order_id)

    def cancel_payment_order(self,payload):
        order_id=safe_id(payload.get('order_id'),'Order ID')
        with self.connect() as conn:
            row=conn.execute("SELECT status FROM payment_orders WHERE order_id=?",(order_id,)).fetchone()
            if not row: raise ValueError("Payment order not found.")
            if row[0]=='paid': raise ConflictError("Payment already confirmed. Use a return if needed.")
            conn.execute("UPDATE payment_orders SET status='cancelled' WHERE order_id=?",(order_id,))
        return {'cancelled':True}
