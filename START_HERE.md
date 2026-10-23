# Version 0.8 update

See [UPDATE_V08.md](UPDATE_V08.md) for the current 3-day fast forecast and payment-before-bill flow. The 90-day workflow below applies to the optional model comparison.

# Satya Shop / RetailPulse 0.7: start your shop

**Shop name and WhatsApp bills:** read [SATYA_SHOP.md](SATYA_SHOP.md). Save Satya Shop in Checkout & bills, enter the customer's WhatsApp number, create the bill and click WhatsApp bill. Review the draft and tap Send in WhatsApp.

This version has a horizontal top menu, an ivory/petrol/lime/orange palette, a daily sales ledger and a receipt-style checkout, with no sidebar. Products, stock counts, returns, refunds, WhatsApp drafts and backups remain available.

## First start on Windows

1. Finish pending bills and make and download a backup in the old app.
2. Stop the old server and simulator using Ctrl+C. Extract the updated project ZIP into a new folder.
3. Double-click **INSTALL_SATYA_SHOP.cmd**. First setup needs internet and Python 3.11-3.13 with the Windows py launcher and Tcl/Tk.
4. If asked about existing records, choose **Yes** and select the old data folder containing `retailpulse.sqlite3`. Choose **No** only for a new empty shop. Existing installed data is reused automatically.
5. Use the new **Satya Shop** desktop icon. For a new shop, enter your shop name, then add products with the opening stock you counted.
6. Open **Checkout & bills** to record purchases. VS Code and a terminal window are not needed.

Read [DESKTOP_APP.md](DESKTOP_APP.md) for importing custom data folders, updates and troubleshooting. The icon starts a local background process. Clicking it again reuses the running shop. After restarting Windows, click the icon again. The launcher normally uses port 18741 and chooses another free port if needed. Chrome or Edge opens an app window; otherwise your default browser opens.

Closing the app window leaves the background process running. To stop it after finishing bills and training, use **Start → Satya Shop → Quit Satya Shop**. Your computer must be on and awake. The Windows installer and native browser layout remain unverified here; see [docs/VERIFICATION.md](docs/VERIFICATION.md).

## Add, edit and archive products

Use a unique item code such as SOAP01. Item codes stay fixed so older records keep referring to the same product.

- **Add item** saves the price, restock settings and counted opening stock.
- **Edit** changes its name, current price and restock settings. Earlier bills keep their original names and prices.
- Uncheck **Available for new sales** and save to archive an item. It stays in the history, but new sales are blocked. Check it again to restore the item.
- Opening stock is entered only when adding an item. Use **Stock received** for new deliveries, and **Count and correct stock** for corrections.

## Record a customer purchase

Select a product, quantity and unit price; click **Add item**. Add the other products, then click **Create bill**. The entire basket, stock deduction and bill save together. A shortage rejects the complete basket.

Enter the customer’s WhatsApp number before creating the bill to save it with that bill. Use **WhatsApp bill**, check the number and click **Open WhatsApp**; tap **Send** in WhatsApp. You can also use WhatsApp beside a recent bill. Download the bill PDF or open it to print, and attach the PDF manually in the chat if wanted. Payment collection is separate from this app. It does not verify payments or automatically send messages.

Checkout already records the sales. Do not enter that same purchase again in the separate Record sale form. Use checkout when you need a bill and later returns. The standalone sale form creates no itemized bill; its older sales cannot be returned through the bill return screen.

If a connection fails, keep the tab open and retry the saved request. Requests stay in the tab's session storage, with their original ID and shop identity. The same request does not create a second deduction or refund. A request from another shop database stays blocked. Resolve it in its original database before proceeding; do not clear pending browser storage without confirming the saved result.

## Stock deliveries and physical counts

For a delivery, open **Stock → Receive stock**, select the product, enter only the newly received quantity and click **Add stock**. If the app has 47 units and 20 arrive, enter 20; the result is 67.

For a correction, use **Stock → Count & correct**. Select a product, enter its actual counted total and a reason. Saving records the difference and the new balance. If another sale changes stock after you loaded the count, the app rejects the stale correction. Click **Load latest stock**, check your count, then save again.

Stock corrections do not create sales or refunds. Their reasons and quantities remain in the history.

## Returns and bill corrections

Click **View / return** beside a recent bill, or paste its ID into **Find bill**.

1. Enter the quantity being returned for each item. Zero means that item is not being returned.
2. Enter a reason.
3. Keep **Add returned items back to stock** checked for items that can be sold again. Uncheck it for damaged or unusable items. Use separate returns when only some items can be restocked.
4. Click **Save selected return**. The refund uses the original bill's unit prices, even if the catalog price has changed.
5. Download the return PDF from recent returns. The shop handles the actual refund payment separately.

The app prevents returning more than the quantity originally sold. Earlier returns are counted, and simultaneous requests cannot return the same remaining units twice.

To correct a wrong bill, enter the reason and click **Cancel remaining bill**. Review the displayed amount and stock option. Cancellation refunds only the quantities that have not already been returned. The original bill stays in history and its PDF shows CANCELLED. Create the replacement purchase as a new bill in checkout. There is no silent rewrite of the original items.

## What the totals mean

**Sales after refunds today** is today's recorded gross sales minus refunds recorded today. It is not profit or a payment balance. Returning a purchase from an earlier day can make today's amount negative. Historical gross sales stay unchanged; returns are dated when recorded.

**Units sold today** counts gross sold units. Returned units are shown separately. Forecasts use gross recorded purchases, rather than negative return totals. CSV exports include gross daily sales, sales after refunds, return lines and stock corrections.

## Backups and recovery

A consistent SQLite backup runs on server start, every hour while it stays open, and on a normal stop using Quit Satya Shop. A manual developer server also backs up on Ctrl+C. The latest 48 automatic ZIP backups are kept. Manual backups remain until you remove them.

Click **Make backup now**, then **Download ZIP**. Keep a copy on another drive or device: backups in the installed data folder stay on the same laptop. MAKE_BACKUP.cmd is an advanced helper for a developer data folder; it does not select the installed shop automatically. The dashboard shows backup errors so you can correct them and retry.

Each backup contains the database, backup information, and the saved forecast if one exists. It includes bills, returns, stock and product history as of the snapshot. Unsaved baskets are not database records and are not backed up. No automatic cloud upload is included.

To review a recovered backup, quit the installed app and restore into a **new empty data folder**. Open PowerShell and run:

```powershell
$shopRoot = Join-Path $env:LOCALAPPDATA "SatyaShop"
$shopPython = Join-Path $shopRoot ".venv\Scripts\python.exe"
$recovered = Join-Path $shopRoot "restored-shop"
Set-Location (Join-Path $shopRoot "app")
& $shopPython -m retailpulse --data-dir $recovered restore-backup --file "C:\path\your-shop-backup.zip"
& $shopPython -m retailpulse --data-dir $recovered serve --open --find-port
```

Replace the quoted path with your actual data backup ZIP, not the project download ZIP. Recovery validates the database and refuses to overwrite an existing data folder. This review server needs its terminal open and does not replace installed records. After checking the recovered records, stop it with Ctrl+C and keep both folders. To use recovered records with the desktop icon, first quit the installed app, rename its `data` folder to an unused name such as `data-before-recovery`, then rename `restored-shop` to `data`. Keep the original folder and backup ZIP.

## Your records and the separate demo

Installed shop records: **%LOCALAPPDATA%\SatyaShop\data\retailpulse.sqlite3**. Forecast: **data\forecast.json**, once trained. Backups: **data\backups\** under the same installed home. Use the Start menu shortcut **Shop records and backups** to open it.

**START_DEMO.cmd** opens sample records in **stream-demo**. **SIMULATE_RETAILPULSE.cmd** generates labelled sample transactions in that demo only. It refuses to run on your live shop database.

To keep your older demo, stop its server and simulator and copy the entire stream-demo folder into this new extracted project. Then open START_DEMO.cmd. The new tables and product columns are added automatically, and a pre-upgrade SQLite copy is saved first. Existing sales and bills remain. The original metadata still labels it as demo; it is not converted into actual shop history.

To import an old shop on first installation, select its entire data folder in the installer or pass its full path to `INSTALL_SATYA_SHOP.cmd`. Read [DESKTOP_APP.md](DESKTOP_APP.md). Back up a running database with the backup button or SQLite backup API rather than copying only its .sqlite3 file.

## Predictions and remaining limits

Billing and stock work immediately after setup. Forecasting needs at least 90 complete days of recorded sales. Newly added products wait for 90 completed days before entering forecast training. Record every purchase so missing calendar dates can honestly represent zero sales. Refresh forecasts after a completed business day; training is not automatic after every sale.

Anomaly detection uses quantities and prices and needs 50 earlier sales per product in a real shop. Its reference models load when the server starts; restart to refresh them. Alerts are review signals, and their accuracy has not been measured on a real shop.

This is a local single-shop pilot. It has not been validated in actual daily shop operation. Separate staff roles, tax calculations, purchase-cost/profit accounting, multiple branches, automatic customer messaging, offline checkout queues and public HTTPS hosting are not included. The Windows desktop icon starts its Python backend; installing through a browser alone does not start it. Phone deployment and PWA installation remain unverified.

## Checks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

71 Python tests cover forecasting/imports, product edits, counts, returns, retries, migrations, backups, recovery, completed-day history, shop names and contacts, an actual HTTP workflow, detached startup, duplicate clicks and safe data imports. The frontend smoke check covers top navigation and existing bill-sharing logic. PDF samples are in examples/. See docs/VERIFICATION.md for remaining Windows/browser limits.
