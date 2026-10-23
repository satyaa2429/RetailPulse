# Satya Shop 0.7: a new interface and desktop launcher

## What changed

- Horizontal top navigation for all eight screens; no sidebar or mobile side drawer.
- Ivory pages, deep petrol text, a lime sales ledger and warm orange accents.
- Large serif headings, numbered navigation and a distinctive shop stamp.
- A receipt-style checkout with the basket total always visible on desktop.
- Product search, stock tabs, forecast readiness, returns, activity and backups remain available.
- A Windows desktop icon that starts the shop without VS Code or an open terminal.

The top menu scrolls horizontally on narrower screens. Switching screens keeps the current basket and unfinished form values in the same window. A status label identifies your own shop records or sample data.

## Keep your existing records

1. Finish pending actions and download a backup from the old shop.
2. Stop the old server and any simulator using Ctrl+C.
3. Extract the updated project ZIP into a new folder. Keep the old folder.
4. Double-click **INSTALL_SATYA_SHOP.cmd**. If asked, choose **Yes** and select the old data folder containing `retailpulse.sqlite3`.
5. Open **Satya Shop** using its new desktop icon and check your products, stock and bills.

The installer can find shop-data beside itself automatically. For another location, select it in the folder dialog or pass its full path to INSTALL_SATYA_SHOP.cmd. Original records are kept. An existing installed database is reused automatically. Application updates do not overwrite installed records.

Read [DESKTOP_APP.md](DESKTOP_APP.md) for setup, permanent data locations, updates and troubleshooting. Read [SATYA_SHOP.md](SATYA_SHOP.md) for shop names and WhatsApp bills.

## Forecasts still need history

Forecasting still requires 90 complete days of recorded sales coverage. New products wait for 90 complete days. Today's sales enter the completed-day chart tomorrow. Record every purchase: missing dates are assumed to have zero sales.

Billing, stock, PDFs, returns and backups work before forecasts are ready. No external fonts or paid hosting or messaging service was added.

## If you still see the old colours

Finish your current bills, close shop windows and run the new installer. Then open the new Satya Shop desktop icon. In a browser window, press Ctrl+F5 to refresh cached files.

## Checked here

71 Python tests pass, including shop workflows, detached startup, repeated/parallel opens, restart with saved bills and safe SQLite imports. The frontend logic smoke check passes for top navigation, basket/draft retention, stock tabs, polling, forecast readiness, returns and WhatsApp drafts.

The lifecycle tests ran in Linux. The Windows installer, shortcuts and actual browser app window remain unverified here. The browser preview attempt timed out, so visual appearance and device rendering still need a real browser check.
