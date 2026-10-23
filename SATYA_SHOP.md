# Satya Shop: name and WhatsApp bills

## Update without losing your shop data

1. In your current app, make and download a backup from **Backups & exports**.
2. Finish any pending bill or action. Stop the old server and simulator with **Ctrl+C**.
3. Extract this updated ZIP into a new folder. Keep your old project folder.
4. Double-click **INSTALL_SATYA_SHOP.cmd**. If asked about existing records, choose **Yes** and select the old data folder containing `retailpulse.sqlite3`. If it finds `shop-data` beside the installer, it imports that folder automatically.
5. Use the new **Satya Shop** desktop icon. VS Code and a terminal window are not needed. Press **Ctrl+F5** if old files appear in a browser window.

For a custom data folder, select that folder in the installer or pass its full path to `INSTALL_SATYA_SHOP.cmd`. See [DESKTOP_APP.md](DESKTOP_APP.md). A project download does not contain the records on your laptop. Original records are kept; an already installed database is reused. Check your records before removing an older project folder.

## Save the name Satya Shop

1. Open **Checkout & bills**.
2. At the top, enter **Satya Shop** under **Shop name**.
3. Click **Save shop name**.

The saved name appears in the app and on new bills and PDFs. It stays saved after restarting. Earlier bills keep the name used when they were created. A brand-new setup already has Satya Shop filled in.

## Send a bill to the customer's WhatsApp number

1. Enter the customer name and **Customer WhatsApp number** while making a bill. The number is optional for customers who do not want WhatsApp.
2. For an Indian mobile, enter its 10 digits. For another country, include **+** and the country code.
3. Add the items and click **Create bill**.
4. Click **WhatsApp bill**. Check the number and the bill preview.
5. Click **Open WhatsApp**. Choose WhatsApp Web or the WhatsApp app if prompted. Check the recipient and message, then tap **Send**.

The message includes the saved bill number, shop name, date, customer, items, quantities, prices and total. Reopening sharing fetches the saved bill; opening WhatsApp fetches it again so recorded returns and refunds appear in the message. It does not create another sale.

Use **WhatsApp** beside a bill in **Recent bills** to share an older bill. A saved customer number is filled in. For an older bill without a saved number, enter it in the sharing panel. Changing the recipient in this panel only changes where you open the chat; it does not rewrite the bill's saved contact.

## Send the PDF too

Click **Download this bill PDF**, then attach the downloaded file in the customer's WhatsApp chat and tap **Send**. The WhatsApp link prepares a text message; it does not attach the PDF automatically. A `127.0.0.1` link from your laptop is not a customer download link.

## Cost and storage

This sharing feature uses WhatsApp's ordinary [click-to-chat link](https://faq.whatsapp.com/5913398998672934). There is no paid messaging API, subscription or automatic sending service in this update. Your normal internet connection and WhatsApp account are needed.

The shop name and optional customer number stay in your local SQLite database. The number is stored with the immutable bill request in the existing `bills.request_json` column, and is included in database backups. There is no new database schema migration for this update. No sample customer bills or phone numbers are added to your shop.

If the browser blocks the new tab, allow pop-ups for the local shop address and retry. If WhatsApp says a number is unavailable, check its country code and whether that customer uses WhatsApp. The app checks the number format; it cannot confirm that the account exists or that a message was delivered.

## Checked

71 Python tests pass, including saved-name changes, original bill/PDF preservation, contact retries, backup/restore, the desktop process lifecycle and an actual HTTP workflow. `node tests/frontend_smoke.cjs` checks frontend logic with a minimal DOM fixture, including top navigation, message contents, fresh refund totals, recipient overrides and blocked-tab/network failures.

Windows launcher execution, native browser appearance, app installation and an actual WhatsApp handoff remain unverified here. No real WhatsApp message was sent during these checks.
