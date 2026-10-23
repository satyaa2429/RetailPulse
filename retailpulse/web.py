"""Portable WSGI API and dashboard; runs locally or under Gunicorn."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server
import csv
import errno
import hmac
import io
import json
import math
import os
import threading
from urllib.parse import parse_qs
from .store import Store, ConflictError

STATIC = Path(__file__).parent / "static"


def read_forecast(store):
    path = store.directory / "forecast.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def snapshot(store):
    meta = store.metadata()
    today = store.today()
    today_string = today.isoformat()
    complete_through = (today-timedelta(days=1)).isoformat() if meta.get("continuous_recording") else meta.get("coverage_end", today_string)
    artifact = read_forecast(store)
    forecast_rows = artifact["rows"] if artifact else []
    # All SQL reads share a snapshot, so a concurrent sale cannot mix old stock with new revenue.
    with store.connect() as conn:
        conn.execute("BEGIN")
        product_rows = [dict(row) for row in conn.execute("SELECT * FROM products ORDER BY name")]
        today_rows = [dict(row) for row in conn.execute("SELECT sku,units,revenue_minor FROM daily_sales WHERE day=?",(today_string,))]
        history_rows = [dict(row) for row in conn.execute("SELECT day,sku,units,revenue_minor FROM daily_sales ORDER BY day")]
        recent = [dict(row) for row in conn.execute("SELECT e.*,p.name FROM events e JOIN products p ON p.sku=e.sku ORDER BY e.occurred_at DESC LIMIT 15")]
        refunds = dict(conn.execute("SELECT COALESCE(SUM(r.refund_minor),0) AS refund_minor FROM returns r WHERE business_date=?",(today_string,)).fetchone())
        returned_units = conn.execute("SELECT COALESCE(SUM(l.quantity),0) FROM return_lines l JOIN returns r USING(return_id) WHERE r.business_date=?",(today_string,)).fetchone()[0]
        has_completed_sales = bool(conn.execute("SELECT 1 FROM events WHERE kind='sale' AND business_date<=? LIMIT 1",(complete_through,)).fetchone())
    today_sales = {row["sku"]: row for row in today_rows}
    forecast_map = {(row["sku"], row["date"]): row["predicted_units"] for row in forecast_rows}
    is_current = bool(forecast_rows and any(row["date"] == today_string for row in forecast_rows))
    for product in product_rows:
        sku = product["sku"]
        product["has_completed_sales"] = any(row["sku"]==sku and row["units"]>0 for row in history_rows if row["day"]<=complete_through)
        product["sold_today"] = today_sales.get(sku, {}).get("units", 0)
        dates = [(today+timedelta(days=i)).isoformat() for i in range(product["lead_days"])]
        complete = all((sku, day) in forecast_map for day in dates)
        product.update({"reorder_point": None, "suggested_order": None, "next_7_days": None, "stock_status": "Unconfigured"})
        if is_current:
            next_week = [forecast_map.get((sku, (today+timedelta(days=i)).isoformat())) for i in range(7)]
            if all(value is not None for value in next_week):
                product["next_7_days"] = round(sum(next_week), 1)
        if complete and product["stock_initialized"]:
            remaining = sum(forecast_map[sku, day] for day in dates)
            remaining -= min(forecast_map[sku, today_string], product["sold_today"])
            point = math.ceil(remaining+product["buffer_units"])
            product["reorder_point"] = point
            product["suggested_order"] = max(0, point-product["stock"])
            product["stock_status"] = "Restock" if product["suggested_order"] else "Covered"
        elif product["stock_initialized"]:
            product["stock_status"] = "Forecast unavailable"
        if not product["active"]:
            product.update({"stock_status":"Archived","reorder_point":None,"suggested_order":None,"next_7_days":None})
    # Use the model reference for historical datasets, preserving genuine old timestamps.
    reference = artifact["train_through"] if artifact else complete_through
    history_start = (datetime.fromisoformat(reference).date()-timedelta(days=59)).isoformat()
    recent_history_start = (datetime.fromisoformat(complete_through).date()-timedelta(days=59)).isoformat()
    history_rows = [row for row in history_rows if history_start <= row["day"] <= reference or recent_history_start <= row["day"] <= complete_through]
    return {"setup_required": not bool(product_rows), "shop_setup_required": not bool(meta.get("mode")), "metadata": meta, "business_date": today_string,
        "updated_at": datetime.now(timezone.utc).isoformat(), "forecast_current": is_current,
        "forecast_readiness":{"required_days":3,"complete_through":complete_through,"has_completed_sales":has_completed_sales},
        "summary": {"revenue_today_minor": sum(row["revenue_minor"] for row in today_rows)-refunds["refund_minor"],
            "gross_revenue_today_minor":sum(row["revenue_minor"] for row in today_rows),"refund_today_minor":refunds["refund_minor"],"returned_units_today":returned_units,
            "units_today": sum(row["units"] for row in today_rows), "products": sum(p["active"] for p in product_rows),
            "restock_products": sum(row["stock_status"] == "Restock" for row in product_rows)},
        "products": product_rows, "history": history_rows, "forecast": artifact, "recent_events": recent}


def csv_output(rows):
    if not rows:
        return b""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    for row in rows:
        # A CSV downloaded into Excel must treat product names as text, not formulas.
        safe = {key: ("'"+value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value)
                for key, value in row.items()}
        writer.writerow(safe)
    return output.getvalue().encode("utf-8-sig")


def export_rows(store, table):
    if table == "sales":
        return store.rows("SELECT event_id,business_date,occurred_at,sku,quantity,unit_price_minor,quantity*unit_price_minor AS revenue_minor,source FROM events WHERE kind='sale' ORDER BY occurred_at")
    if table == "daily_sales":
        return store.rows("SELECT * FROM daily_sales ORDER BY day,sku")
    if table == "net_daily_sales":
        return store.rows("SELECT * FROM net_daily_sales ORDER BY day,sku")
    if table == "returns":
        return store.rows("SELECT r.return_id,r.bill_id,r.kind,r.created_at,r.business_date,r.reason,r.restock,l.sku,l.product_name,l.quantity,l.unit_price_minor,l.refund_minor FROM returns r JOIN return_lines l USING(return_id) ORDER BY r.created_at,l.line_no")
    if table == "stock_movements":
        return store.rows("SELECT * FROM stock_movements ORDER BY created_at")
    if table == "inventory":
        return snapshot(store)["products"]
    artifact = read_forecast(store)
    if table in ("forecast", "holdout"):
        return artifact["rows" if table == "forecast" else "holdout_rows"] if artifact else []
    raise ValueError("Choose sales, daily_sales, net_daily_sales, returns, stock_movements, inventory, forecast or holdout.")


class Application:
    def __init__(self, directory=None, token=None, desktop=False):
        self.store = Store(directory or os.environ.get("RETAILPULSE_DATA_DIR", "data"))
        self.token = token if token is not None else os.environ.get("RETAILPULSE_API_TOKEN", "")
        self.desktop_mode = desktop
        from .stream import Detector
        self.detector = Detector(self.store)
        self.training = False
        self.training_error = None
        self.lock = threading.Lock()
        from .backups import BackupManager
        self.backups = BackupManager(self.store)

    def __call__(self, environ, start_response):
        def response(status, body, content_type="application/json; charset=utf-8", extra=()):
            if not isinstance(body, bytes):
                body = json.dumps(body, allow_nan=False).encode("utf-8")
            headers = [("Content-Type", content_type), ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                ("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; frame-ancestors 'none'"), *extra]
            start_response(status, headers)
            return [body]
        path, method = environ.get("PATH_INFO", "/"), environ.get("REQUEST_METHOD", "GET")
        public_files = {"/":"index.html", "/app.js":"app.js", "/style.css":"style.css", "/manifest.webmanifest":"manifest.webmanifest", "/sw.js":"sw.js", "/icon-192.png":"icon-192.png", "/icon-512.png":"icon-512.png", "/offline.html":"offline.html"}
        if path in public_files and method == "GET":
            filename = public_files[path]
            mime = {".html":"text/html", ".js":"application/javascript", ".css":"text/css", ".png":"image/png", ".webmanifest":"application/manifest+json"}[Path(filename).suffix]
            return response("200 OK", (STATIC/filename).read_bytes(), mime+"; charset=utf-8")
        if path == "/api/status" and method == "GET":
            return response("200 OK", {"ok": True, "authentication_required": bool(self.token)})
        if self.token:
            supplied = environ.get("HTTP_AUTHORIZATION", "")
            if not hmac.compare_digest(supplied, "Bearer "+self.token):
                return response("401 Unauthorized", {"error": "Enter the project access token."})
        try:
            if path == "/api/state" and method == "GET":
                state = snapshot(self.store)
                state["anomaly_alerts"] = self.store.rows("SELECT a.*,e.sku,e.quantity,e.source,e.occurred_at,p.name FROM anomaly_checks a JOIN events e USING(event_id) JOIN products p ON p.sku=e.sku WHERE a.flagged=1 ORDER BY a.checked_at DESC LIMIT 20")
                state["stream_events"] = self.store.rows("SELECT e.*,p.name,a.flagged,a.score,a.method FROM events e JOIN products p ON p.sku=e.sku LEFT JOIN anomaly_checks a USING(event_id) WHERE e.source IN ('live','simulated','demo') ORDER BY e.occurred_at DESC LIMIT 30")
                state["recent_bills"] = self.store.rows("SELECT bill_id,customer_name,total_minor,currency,source,created_at FROM bills ORDER BY created_at DESC LIMIT 10")
                for bill in state["recent_bills"]:
                    saved = self.store.get_bill(bill["bill_id"])
                    bill.update({k:saved[k] for k in ("refund_minor","net_total_minor","status")})
                state["recent_returns"] = self.store.rows("SELECT r.return_id,r.bill_id,r.kind,r.created_at,r.reason,r.restock,r.refund_minor,b.currency FROM returns r JOIN bills b USING(bill_id) ORDER BY r.created_at DESC LIMIT 10")
                state["stock_movements"] = self.store.rows("SELECT m.*,p.name FROM stock_movements m JOIN products p USING(sku) ORDER BY m.created_at DESC LIMIT 10")
                state["backup_status"] = self.backups.status()
                state.update({"training": self.training, "training_error": self.training_error, "desktop_mode": self.desktop_mode})
                return response("200 OK", state)
            if path == "/api/backups" and method == "GET":
                return response("200 OK",self.backups.status())
            if path.startswith("/api/backups/") and method == "GET":
                from .backups import BACKUP_NAME
                filename = path.removeprefix("/api/backups/")
                if not BACKUP_NAME.fullmatch(filename): raise ValueError("Invalid backup filename.")
                file = self.store.directory/"backups"/filename
                if not file.is_file(): return response("404 Not Found",{"error":"Backup not found."})
                return response("200 OK",file.read_bytes(),"application/zip",[("Content-Disposition",f'attachment; filename="{filename}"')])
            if path.startswith("/api/returns/") and method == "GET":
                from .store import safe_id
                return_id = path.removeprefix("/api/returns/")
                pdf = return_id.endswith(".pdf")
                if pdf: return_id=return_id[:-4]
                safe_id(return_id,"Return ID")
                try: saved = self.store.get_return(return_id)
                except KeyError: return response("404 Not Found",{"error":"Return not found."})
                if pdf:
                    from .billing import return_pdf
                    return response("200 OK",return_pdf(saved),"application/pdf",[("Content-Disposition",f'attachment; filename="RetailPulse-return-{return_id}.pdf"')])
                return response("200 OK",saved)
            if path.startswith("/api/bills/") and method == "GET":
                bill_id = path.removeprefix("/api/bills/")
                pdf = bill_id.endswith(".pdf")
                if pdf:
                    bill_id = bill_id[:-4]
                import re
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}",bill_id):
                    raise ValueError("Invalid bill ID.")
                try:
                    bill = self.store.get_bill(bill_id)
                except KeyError:
                    return response("404 Not Found", {"error":"Bill not found."})
                if pdf:
                    from .billing import receipt_pdf
                    return response("200 OK", receipt_pdf(bill), "application/pdf", [("Content-Disposition",f'attachment; filename="RetailPulse-{bill_id}.pdf"')])
                return response("200 OK",bill)
            if path == "/api/export" and method == "GET":
                table = parse_qs(environ.get("QUERY_STRING", "")).get("table", ["daily_sales"])[0]
                payload = csv_output(export_rows(self.store, table))
                return response("200 OK", payload, "text/csv; charset=utf-8", [("Content-Disposition", f'attachment; filename="{table}.csv"')])
            if method == "POST" and path in ("/api/sales", "/api/receipts", "/api/policy", "/api/train", "/api/checkout", "/api/payment/quote", "/api/payment/confirm", "/api/payment/cancel", "/api/payment/qr", "/api/billing/settings", "/api/setup", "/api/shop/name", "/api/products", "/api/products/edit", "/api/stock/adjust", "/api/returns", "/api/bills/cancel", "/api/backups"):
                length = int(environ.get("CONTENT_LENGTH") or 0)
                if length > 32768:
                    return response("413 Payload Too Large", {"error": "Event payload is too large."})
                payload = json.loads(environ["wsgi.input"].read(length) or b"{}")
                if not isinstance(payload, dict):
                    raise ValueError("The request body must be a JSON object.")
                if payload.get("store_id") and payload["store_id"]!=self.store.metadata().get("store_id"):
                    return response("409 Conflict",{"error":"This pending request belongs to a different shop database. Open the original shop to resolve it.","code":"STORE_MISMATCH"})
                if path == "/api/setup": return response("200 OK",self.store.initialize_shop(payload))
                if path == "/api/shop/name": return response("200 OK",self.store.rename_shop(payload))
                if path in ("/api/products","/api/products/edit"): return response("200 OK",self.store.save_product(payload,edit=path.endswith("/edit")))
                if path == "/api/stock/adjust": return response("200 OK",self.store.adjust_stock(payload))
                if path in ("/api/returns","/api/bills/cancel"): return response("200 OK",self.store.return_bill(payload,cancel=path.endswith("/cancel")))
                if path == "/api/backups":
                    try: return response("200 OK",self.backups.create())
                    except Exception: return response("500 Internal Server Error",{"error":"Backup failed. Check the backup section for details."})
                if path == "/api/billing/settings": return response("200 OK",self.store.billing_settings(payload))
                if path == "/api/payment/quote": return response("200 OK",self.store.create_payment_order(payload))
                if path == "/api/payment/confirm": return response("200 OK",self.store.confirm_payment_order(payload,self.detector))
                if path == "/api/payment/cancel": return response("200 OK",self.store.cancel_payment_order(payload))
                if path == "/api/payment/qr":
                    from .commerce import qr_svg, payment_uri
                    orders=self.store.rows("SELECT * FROM payment_orders WHERE order_id=?",(payload.get("order_id"),))
                    if not orders or orders[0]["status"]!='pending': raise ValueError("Payment request is not pending.")
                    order=orders[0];config=json.loads(order["config_json"]);request=json.loads(order["request_json"]);pricing=json.loads(order["pricing_json"])
                    if request.get("payment_method")!='upi': raise ValueError("This payment uses cash.")
                    return response("200 OK",qr_svg(payment_uri(config["upi_id"],request["shop_name"],pricing["total_minor"],order["order_id"])),"image/svg+xml")
                if path == "/api/checkout":
                    return response("200 OK", self.store.checkout(payload,detector=self.detector))
                if path == "/api/train":
                    with self.lock:
                        if self.training:
                            raise ConflictError("Forecast training is already running.")
                        self.training, self.training_error = True, None
                    threading.Thread(target=self._train, args=(payload.get("compare_models") is True,), daemon=True).start()
                    return response("202 Accepted", {"training": True})
                if path == "/api/policy":
                    return response("200 OK", self.store.update_policy(payload))
                return response("200 OK", self.store.record(payload, "sale" if path == "/api/sales" else "receipt", detector=self.detector))
        except ConflictError as error:
            return response("409 Conflict", {"error": str(error)})
        except (ValueError, TypeError, KeyError) as error:
            return response("400 Bad Request", {"error": str(error)})
        return response("404 Not Found", {"error": "Route not found."})

    def _train(self, compare=False):
        try:
            from .forecast import train
            train(self.store,compare=compare)
        except Exception as error:
            self.training_error = str(error)
        finally:
            self.training = False


class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def serve(store_directory, host="127.0.0.1", port=8000, open_browser=False, find_port=False):
    app = Application(store_directory)
    if host not in ("127.0.0.1", "localhost", "::1") and not app.token:
        raise ValueError("Set RETAILPULSE_API_TOKEN before binding to a network interface.")
    server = None
    for candidate in range(port, min(65536,port+(10 if find_port else 1))):
        try:
            server = make_server(host,candidate,app,server_class=ThreadedServer)
            port = server.server_port
            break
        except OSError as error:
            if not find_port or error.errno not in (errno.EADDRINUSE,10048): raise
    if server is None: raise ValueError("The requested ports are busy. Stop older servers or choose another --port.")
    with server:
        app.backups.start()
        print(f"RetailPulse is ready at http://{host}:{port}", flush=True)
        if open_browser:
            import webbrowser
            timer = threading.Timer(1.0,lambda:webbrowser.open(f"http://{host}:{port}"))
            timer.daemon = True
            timer.start()
        try: server.serve_forever()
        finally:
            app.backups.stop()
            try: app.backups.create("auto")
            except Exception: pass


def create_app():
    """Gunicorn entry point: retailpulse.web:create_app()."""
    if os.environ.get("RETAILPULSE_REQUIRE_TOKEN") == "1" and not os.environ.get("RETAILPULSE_API_TOKEN"):
        raise ValueError("Configure RETAILPULSE_API_TOKEN for this deployment.")
    app = Application()
    app.backups.start()
    return app
