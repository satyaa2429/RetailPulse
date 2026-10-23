# Version 0.8 update

See [UPDATE_V08.md](../UPDATE_V08.md) for the current 3-day fast forecast and payment-before-bill flow. The 90-day workflow below applies to the optional model comparison.

# Satya Shop 0.7: desktop app and digital bills

Use [../DESKTOP_APP.md](../DESKTOP_APP.md) to install the Windows desktop launcher, import old records and open Satya Shop without VS Code. Current installed records live in `%LOCALAPPDATA%\SatyaShop\data`.

Read [../SATYA_SHOP.md](../SATYA_SHOP.md) for saved shop names, customer numbers and WhatsApp bills. Sharing opens a draft message for you to review and send. Download and attach the PDF separately. Read [../START_HERE.md](../START_HERE.md) for products, stock, returns and backups.

## Archived installation notes: versions 0.3 and 0.4

The commands and test counts below describe older releases. Their startup and installation instructions are superseded by DESKTOP_APP.md. PDF and browser-app scope remain useful background.

# App installation and digital bills

## Start on Windows

Extract RetailPulse_App_Billing.zip into a new folder. The ZIP places requirements.txt and START_RETAILPULSE.cmd at its root to avoid nested project folders.

Stop older servers using Ctrl+C before starting this one. Double-click START_RETAILPULSE.cmd. First use creates a Python environment, installs dependencies, creates labelled demo data only if no database exists, and opens http://127.0.0.1:8000. Python 3 and the py launcher must already be installed. First setup requires internet for package downloads. Keep the launcher window open. The Windows launch scripts have been inspected but not executed in Windows here.

Preserve existing data: stop the old server and simulator, copy the complete stream-demo folder into this new project folder before starting it. Do not copy a database while it is still running. SQLite automatically adds the new bills and bill_lines tables; existing records remain. The launcher does not rerun demo creation on an existing database.

For manual use from the folder containing requirements.txt:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# For a NEW demo folder only:
.\.venv\Scripts\python.exe -m retailpulse --data-dir stream-demo demo
.\.venv\Scripts\python.exe -m retailpulse --data-dir stream-demo serve --open
```

SIMULATE_RETAILPULSE.cmd optionally starts continuous simulated sales in a second terminal. Stop the simulator while testing exact checkout stock quantities.

## Install the web app

On desktop Chrome or Edge, open the running dashboard. Use Install RetailPulse when offered, or the browser install menu. The app opens in a standalone window with an icon. This is an installable web app (PWA), not a native Android APK. Installation UI depends on the browser.

Mobile installation needs an HTTPS host reachable from the phone, or a local development server on that phone. A phone's 127.0.0.1 is the phone itself, not your laptop. HTTPS deployment has not been done. This installation does not bundle the Python server into your phone or make it run automatically.

The service worker caches only the offline connection page, stylesheet and icons. API data and bills are never cached. Checkout requires the server and database to be reachable; offline transactions are not queued. If the server stops, the app shows a connection page.

## Give a bill to a customer

Open Checkout & digital bills, enter your shop name, optionally enter a customer name, select products and quantities, and click Add to bill. Create bill & record sale saves the basket and reduces stock once. Use Download PDF or Open PDF to print. Attach the downloaded PDF manually in WhatsApp or email. No automatic message sending or messaging integration is included.

Do not record the same purchase using both the old Record sale form and checkout. Checkout already records its sales. Payment collection is separate; this app does not charge a bank account or verify a payment. PDFs are simple itemized sales records; tax calculation and statutory invoice fields are not included.

Saved bills preserve their original names and prices. Recent bills appear below checkout and can be downloaded again. Each bill includes its ID, timestamp, customer, items, quantities, unit prices and total. Demo bills are prominently labelled DEMO TRANSACTION - SAMPLE BILL. This version uses English PDF labels and bundled DejaVu Sans fonts.

If the connection fails during checkout, retry the same request; its bill ID is retained in the tab's session storage. Do not clear session storage or start another basket while its result is uncertain. A rejected basket can be edited after a 400/409 response. Checkout and stock commit in one database transaction.

## API

POST /api/checkout:

```json
{"bill_id":"bill-unique-001","shop_name":"My Store","customer_name":"Customer","items":[{"sku":"RP001","quantity":2,"unit_price":"65.00"}]}
```

Use a stable bill ID for retries. Conflicting retries are rejected; each SKU appears once. GET /api/bills/BILL_ID returns the saved JSON and GET /api/bills/BILL_ID.pdf returns the PDF. Access tokens protect bill endpoints when configured. Customers receive files, not access to the store dashboard. Never make the full dashboard public just to share a bill.

## Verification

49 functional tests pass: atomic basket saves, exact totals, parallel retries, conflicting retries, insufficient stock, rollback on anomaly failure, immutable receipt lines, authorized PDF downloads, manifest serving, plus the original 16 tests. PDF text and the rendered sample were reviewed. Desktop browser installation, mobile installation and the Windows launch scripts remain unverified. The browser preview did not finish loading.

Run tests after installing requirements-dev.txt: python -m unittest discover -s tests -v.

PWA reference: https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable
