# Current shop and demo launchers

Use START_RETAILPULSE.cmd for your empty real shop, START_DEMO.cmd for examples, and SIMULATE_RETAILPULSE.cmd for generated demo transactions. See [../START_HERE.md](../START_HERE.md). The commands below are optional demo setup commands.

# Real-time streaming version

Use a NEW folder for simulated streaming; do not overwrite or simulate against real shop data.

Windows: open PowerShell in the folder containing requirements.txt. If your existing environment is in the parent directory, substitute ..\.venv for .venv.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m retailpulse --data-dir stream-demo demo
.\.venv\Scripts\python.exe -m retailpulse --data-dir stream-demo serve
```

Open http://127.0.0.1:8000. In a SECOND PowerShell window in the same project folder:

```powershell
.\.venv\Scripts\python.exe -m retailpulse --data-dir stream-demo simulate --interval 2
```

Ctrl+C stops the stream. Every twelfth transaction injects an unusual quantity and price; detection may flag it but is not guaranteed. Receipts refill DEMO stock automatically. All generated events carry source=simulated.

Flow: simulator (or billing API) -> validation -> atomic SQLite sale/stock/anomaly record -> dashboard polling each second. Detection is synchronous per sale. Browser updates have approximately one-second polling delay, plus processing time. This is a local shop pilot with streaming capability. No external POS is connected by default.

Demo mode uses a separately generated synthetic transaction reference (500 typical purchases per product, quantities 1–4 at listed prices); the old demo daily aggregates are not individual purchases. This proves streaming mechanics, not real detection accuracy. On real data, Isolation Forest fits on up to 2,000 prior non-simulated sales per product at process startup; 50 samples required. Features are log(quantity) and log(unit price); configured contamination=2% is an assumption, not measured fraud prevalence. Scores below zero create review alerts. Demo mode additionally flags quantity above 4 or a price different from the listed demo price using explicit rules, because tree models do not reliably extrapolate beyond their training range. No labelled anomaly accuracy has been established. Restart server/simulator to refresh anomaly reference models. Forecasts still use completed days; refresh manually with the dashboard button. New simulated sales affect demo daily totals.

Real billing: use POST /api/sales with event_id, sku, quantity, unit_price. Configure known stock first; keep stable event IDs for retries. Incoming billing timestamps are recorded as server receipt time in this prototype. Configure RETAILPULSE_API_TOKEN before network access. See API.md. Only run one simulator per demo folder.

SQLite + threaded local WSGI is suitable for learning. Production requires authenticated billing integration, HTTPS hosting, monitoring, backups, volume/load testing and a deployment database appropriate to concurrency.
