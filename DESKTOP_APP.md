# Satya Shop 0.7: click the icon and open your shop

The app now has a top menu, an ivory/petrol/lime/orange palette, a daily sales ledger and a receipt-style checkout. There is no sidebar or hidden side drawer.

## Install once on Windows

1. In your current shop, finish pending bills and download a backup from **Backups & exports**.
2. Stop the old server with **Ctrl+C**. Close its shop windows and any simulator.
3. Extract the updated ZIP into a new folder.
4. Double-click **INSTALL_SATYA_SHOP.cmd**. Wait for package setup to finish; the first setup needs internet.
5. If asked whether you already have records, choose **Yes** and select your old **shop-data** folder. Choose the folder containing `retailpulse.sqlite3`. If you used a custom data folder, select that folder. The installer can also find `shop-data` beside itself automatically.
6. When setup finishes, use the new **Satya Shop** icon on your desktop.

The installer also adds **Satya Shop** to the Windows Start menu. Python 3.11, 3.12 or 3.13 with the Windows Python launcher and Tcl/Tk must be installed for initial setup. Your existing Python environment can be used to prepare the installed environment. Chrome or Edge gives the app its own window; otherwise it opens in your default browser.

You can select the source folder directly by running this from the extracted folder, replacing the example with your actual old data folder:

```powershell
.\INSTALL_SATYA_SHOP.cmd "C:\Users\saisr\Downloads\your-old-project\shop-data"
```

## Everyday use

Click **Satya Shop** on the desktop or Start menu. It starts the shop in the background and opens the interface. VS Code and a terminal window are not needed.

- Closing VS Code does not stop an app opened through this desktop icon.
- Clicking the icon again opens the running shop and keeps the same records.
- After restarting Windows, click the icon again; it starts the shop automatically.
- Closing the shop window leaves its local background process running. To stop it completely, open **Start → Satya Shop → Quit Satya Shop**, or run **QUIT_SATYA_SHOP.cmd**. Finish pending bills and forecast training before quitting.
- Billing and stock work without internet after installation. Opening WhatsApp needs your internet connection.

Your computer must be on and awake while using this local shop. Phone access while the computer is switched off would need a separate hosted service; this update does not add one or its charges.

## Your records have a permanent home

The installer copies the application into:

```text
%LOCALAPPDATA%\SatyaShop\app
```

Your database, forecasts and backups are kept separately in:

```text
%LOCALAPPDATA%\SatyaShop\data
```

You can paste the second path into File Explorer, or use **Start → Satya Shop → Shop records and backups**. The database is `retailpulse.sqlite3`.

Import uses SQLite's backup operation, including committed changes in its WAL, and preserves bill IDs, stock, shop identity, customer numbers, saved forecasts and backups. Your original data folder is kept. An existing installed database is never overwritten by an import. When updating an already installed shop, its installed data is reused automatically.

Use the app's **Backups & exports** screen to make and download a copy regularly. The project ZIP contains application code; it does not contain the records from your laptop.

## Shop name and WhatsApp bills

In **Checkout & bills**, save **Satya Shop** under Shop name. New bills use the saved name. Original bills keep their original names.

Enter the customer's optional WhatsApp number, create the bill, click **WhatsApp bill**, review the number and message, then click **Open WhatsApp** and tap **Send** in the chat. Indian mobile numbers can be entered as 10 digits. For another country, include + and the country code. Download the PDF and attach it separately if wanted. No paid messaging API was added.

## Update later

Extract a newer ZIP and run **INSTALL_SATYA_SHOP.cmd** again after finishing your current bills and closing shop windows. It updates the application, recreates the shortcuts and keeps your installed data. Keep the old data folder and downloaded backups until you have checked your records in the installed app.

## If setup or opening fails

Run **INSTALL_SATYA_SHOP.cmd** again to see its error. The launcher also records startup errors in:

```text
%LOCALAPPDATA%\SatyaShop\logs\desktop.log
```

If setup asks for a new shop even though you have records, check that you selected the correct old data folder. If an empty installed shop was already started by mistake, keep both folders and use the backup/restore workflow instead of overwriting a database.

The normal developer command, `python -m retailpulse --data-dir shop-data serve`, still runs in its terminal. For everyday use, open the installed desktop icon.

## Checked here

71 Python tests pass, including an actual detached worker surviving its launcher exit, repeat/parallel opens, stable-port restart with saved bills and stock, occupied ports, authenticated shutdown, stale runtime records and safe database imports. The frontend logic smoke check passes for all eight screens, top navigation, basket/draft retention and WhatsApp sharing.

The lifecycle tests ran in Linux. Windows PowerShell setup, shortcut creation, browser app-window launching and an actual WhatsApp handoff are not executed here. The browser preview attempt timed out, so native browser appearance remains unverified. No sample shop data is included in this download.
