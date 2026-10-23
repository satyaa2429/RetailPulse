# Version 0.8 update

See [UPDATE_V08.md](UPDATE_V08.md) for the current 3-day fast forecast and payment-before-bill flow. The 90-day workflow below applies to the optional model comparison.

# Satya Shop / RetailPulse 0.7: your shop, from a desktop icon

**New in 0.7:** a top menu, an ivory/petrol/lime/orange palette, a daily sales ledger and a receipt-style checkout. Install once on Windows, then click the **Satya Shop** desktop icon. It starts the shop in the background; VS Code and an open terminal are no longer needed. Read [DESKTOP_APP.md](DESKTOP_APP.md) for installation and importing your existing records.

The eight task screens use horizontal navigation with no sidebar. Product search, stock actions, basket totals, forecast readiness, returns and backups remain available. Save your shop name and share itemized WhatsApp bill drafts; you review and tap Send yourself. Download and attach PDFs separately. Read [SATYA_SHOP.md](SATYA_SHOP.md) for billing steps.

Start with **[START_HERE.md](START_HERE.md)**. Extract the ZIP and double-click **INSTALL_SATYA_SHOP.cmd**. Choose your old data folder if you have records; for a new shop, enter your shop name and counted opening stock. Installed records live in `%LOCALAPPDATA%\SatyaShop\data`, separately from the code. **START_RETAILPULSE.cmd** also installs or opens this desktop app. **START_DEMO.cmd** opens a separate sample database using the developer environment.

This update includes product creation/editing/archiving, itemized checkout, saved PDF bills, partial returns, bill cancellation, refund records, stock count corrections and consistent automatic backups. Existing databases are extended with a pre-upgrade copy; old bills are preserved. The app is a local shop pilot, with no public deployment or confirmed production use.

The original data science guide below describes demo experiments and optional historical imports. You do not need a historical CSV to start billing in the new shop screen. Forecasts require 90 complete days; new products are held out of training until they have 90 complete days.

# RetailPulse

**Live sales, product sales forecasting, and inventory planning for a small shop.**

A shop owner records a sale, sees stock change immediately, and checks how much stock is needed during the supplier's lead time. The project combines Python, SQL, data validation, time-series machine learning, a browser dashboard, HTTP APIs, and deployment configuration.

This version is runnable locally. It contains a clearly labelled synthetic demo, a separate real historical-data importer, and a CSV importer for your own shop. It has not been published to a public cloud service.

## Start on Windows

Use Python 3.11–3.13; Python 3.12 is recommended. Extract the ZIP and open the **RetailPulse** folder in VS Code. Open a PowerShell terminal in that folder.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m retailpulse demo
.\.venv\Scripts\python.exe -m retailpulse serve
```

Open **http://127.0.0.1:8000** in your browser. Demo creation trains forecasts and may take a little time. Keep the terminal running. Press Ctrl+C to stop the app.

The direct virtual-environment Python commands work without changing PowerShell execution policy. If `python` is not recognized, install Python first or use `py` for the first command. If port 8000 is occupied, append `--port 8001` to the serve command.

Demo setup is a one-time command per data folder. To reopen the existing project, run only `serve`. To create a second demo without overwriting the first:

```powershell
.\.venv\Scripts\python.exe -m retailpulse --data-dir data-demo-2 demo
.\.venv\Scripts\python.exe -m retailpulse --data-dir data-demo-2 serve
```

## What works

| Feature | Behavior |
|---|---|
| Shop name | Save a name for future bills; original bills keep their original names |
| WhatsApp bills | Save an optional customer number and open a bill draft; tap Send in WhatsApp |
| Record a sale | Saves the transaction, revenue and stock deduction together |
| Duplicate protection | Repeating the same event ID does not deduct stock again |
| Record a stock receipt | Adds stock and records an auditable receipt |
| Product management | Adds, edits and archives products; earlier bills keep their original details |
| Returns and cancellation | Saves original-price refund records and optional restocking |
| Counted stock | Saves a reason and checks that the loaded balance is still current |
| Backups | Consistent snapshots on startup, hourly, normal local shutdown, and on request |
| Live dashboard | Refreshes every second; refreshes immediately after form submissions |
| Product forecast | Predicts the next 14 complete daily totals using prior daily sales |
| Model comparison | Compares Random Forest, previous-week sales, and a 28-day average |
| Honest evaluation | Three validation windows select the model; a separate final 14-day test reports errors |
| Restock policy | Uses your lead days, buffer stock, known stock and remaining expected sales |
| CSV export | Exports sales, daily sales, inventory, forecasts and test predictions |
| Real-store input | Imports your own transaction CSV without silently discarding invalid rows |
| Deployment | Dockerfile, Gunicorn entry point, persistent-data and token instructions |

## Try the working demo

1. Note today's revenue and A5 Notebook's stock.
2. Record a sale of three notebooks. Revenue increases by three times the unit price; stock decreases by three.
3. Add 20 units through **Stock received**. Stock increases by 20.
4. Change a product's lead days and buffer. Its stock target changes.
5. Select another product in the sales chart.
6. Export daily sales or forecasts for Excel or Power BI.
7. Inspect the model's separate test scores. A baseline is allowed to win if it forecasts better.

The demo includes 365 generated days and eight products priced in INR. All metrics measured on it describe **synthetic data**, not performance at a real shop. Demo sales saved through the app remain part of the demo.

## Use the real public dataset

UCI's **Online Retail** dataset contains 541,909 historical transaction rows from a UK retailer, dated 1 December 2010 to 9 December 2011. Unit prices are in GBP. These are real historical transactions, not a live sales feed.

```powershell
.\.venv\Scripts\python.exe -m retailpulse download-uci
.\.venv\Scripts\python.exe -m retailpulse --data-dir data-uci import-uci --file downloads/Online_Retail.xlsx
.\.venv\Scripts\python.exe -m retailpulse --data-dir data-uci train
.\.venv\Scripts\python.exe -m retailpulse --data-dir data-uci serve
```

If the download is blocked, download the Excel file yourself from the UCI page and pass its path to `--file`. The app selects up to 12 products from an earlier training period, excludes exact duplicates, cancelled transactions, non-positive sales, invalid rows and non-product codes, and excludes the final possibly partial calendar day. `quality_report.json` records the changes. Customer identifiers are not stored in the database.

UCI does not supply stock balances, supplier lead times, stockout histories or promotions. Inventory starts unconfigured. Its forecasts retain the original historical dates; the app disables current restock suggestions for those old forecasts.

Attribution: Chen, D. (2015). *Online Retail [Dataset]. UCI Machine Learning Repository*. https://doi.org/10.24432/C5BW33. License: CC BY 4.0. Source: https://archive.ics.uci.edu/dataset/352/online+retail.

## Use a real shop's own sales

Export the shop's full sales log as CSV with these columns:

```csv
event_id,timestamp,sku,product_name,quantity,unit_price
bill001-line01,2026-09-28T10:30:00+05:30,TEA001,Tea 250g,2,120.00
bill001-line02,2026-09-28T10:30:00+05:30,SOAP01,Soap Bar,1,35.00
bill002-line01,2026-09-29T16:15:00+05:30,TEA001,Tea 250g,1,120.00
```

Use a distinct event ID for **each sales line**, including different products in the same bill. Naive timestamps use the configured store timezone. Include at least **90 calendar days** for forecasting; a shorter log supports import and live recording but cannot train this model. The example above explains the format and is too short for training.

Declare the last date for which the complete sales log is available. Continuous mode requires a complete log through yesterday and recording **every subsequent sale** in this app or through its API:

```powershell
.\.venv\Scripts\python.exe -m retailpulse --data-dir data-shop import-sales --file shop_sales.csv --complete-through 2026-09-29 --currency INR --timezone Asia/Kolkata --continuous
.\.venv\Scripts\python.exe -m retailpulse --data-dir data-shop train
.\.venv\Scripts\python.exe -m retailpulse --data-dir data-shop serve
```

Replace the date with your actual complete date. If the log is older, omit `--continuous`; forecasts will be based on that historical endpoint. Missing calendar dates are interpreted as zero sales, so an incomplete log must be fixed before using it for forecasts.

Enter the current counted stock using **Stock received** before recording new sales. This establishes opening inventory separately from old transactions. After that, use receipts for actual new stock and record every sale. Use Count and correct stock for reconciliation. Checkout bills support returns and cancellation; see START_HERE.md. Historical CSV lines have no itemized bills attached.

## Forecasts and restock calculations

The predictors use sales 1, 7, 14 and 28 days earlier, shifted 7/28-day averages, a shifted 7-day standard deviation, calendar cycles and product identity. Current incomplete-day totals are excluded from training. During multi-day forecasts, predicted values become the next lag inputs; unseen future actual sales are never inserted.

Earlier training → three 7-day validation windows → separate 14-day test → refit on all completed history → next 14-day forecast.

The method with the lowest **validation MAE** is selected. Test results do not choose the method. MAE measures average absolute daily units error; RMSE penalizes larger errors; WAPE measures total absolute error divided by total actual units. WAPE is undefined when all actual sales are zero.

For a product:

```text
remaining lead-time sales = sum of forecast daily sales over lead days
                           - min(today's forecast, today's recorded sales)
target stock             = ceil(remaining lead-time sales + configured buffer)
suggested order          = max(0, target stock - current on-hand stock)
```

The buffer is a user-chosen policy, not a statistically calibrated service level. The model forecasts recorded sales. It cannot infer lost demand when a shop runs out of stock. Refresh forecasts after the business day closes; the refresh uses completed dates and does not learn continuously after every sale.

## Project files

| File | Purpose |
|---|---|
| `retailpulse/store.py` | SQL schema, validation, atomic stock updates and duplicate handling |
| `retailpulse/data.py` | Demo generator, UCI downloader/importer, own-sales importer |
| `retailpulse/forecast.py` | Lag features, baseline comparison, validation and test, forecasts |
| `retailpulse/desktop.py` | Background worker, desktop launch, safe data import and process controls |
| `INSTALL_SATYA_SHOP.cmd` | Windows per-user setup and desktop/Start menu shortcuts |
| `retailpulse/web.py` | WSGI HTTP API, consistent dashboard snapshots and exports |
| `retailpulse/static/` | Browser interface, styling and live updates |
| `tests/test_project.py` | Functional tests for the behaviors that could corrupt results |
| `sql/business_queries.sql` | SQL business questions |
| `docs/LEARNING_PATH.md` | Build and understand the project in stages |
| `docs/API.md` | Connect a POS or transaction sender |
| `docs/DEPLOYMENT.md` | Docker and cloud deployment steps |
| `docs/MODEL_CARD.md` | Scope, evaluation and limitations |
| `docs/POWER_BI.md` | Use the exported tables in Power BI |

Installed runtime files live in `%LOCALAPPDATA%\SatyaShop\data`; manual CLI runs use their chosen data folder. Runtime files include: SQLite database, forecast/evaluation JSON, data-quality reports, backup ZIPs, and optional CSV exports. They are excluded from Git by default.

## Verify and export

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m retailpulse export
```

The default export folder is `data/exports`. Use the same `--data-dir` if working with another dataset. No actual shop data, public cloud deployment or automated POS connection is included by default; those require your sales log and chosen hosting environment.
