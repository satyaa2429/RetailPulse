# Satya Shop 0.8.1 — three forecast methods and payment checkout

## Install the update
1. Download a backup in your current app.
2. Close the app and run `QUIT_SATYA_SHOP.cmd` from your old app folder, or use **Quit Satya Shop** in the Windows Start menu.
3. Extract this ZIP. Open the extracted **RetailPulse** folder and double-click `INSTALL_SATYA_SHOP.cmd`.
4. Open the **Satya Shop** desktop icon. Existing installed records stay in `%LOCALAPPDATA%\SatyaShop\data`.
5. If you previously used a development data folder instead, select that folder when asked about existing records. It must contain `retailpulse.sqlite3`.

The database upgrades to schema 5 and creates a pre-upgrade database backup. Old application versions cannot open the upgraded database. Keep the downloaded backup for recovery. The Windows installer needs a local Windows trial; automated checks here run on Linux.

## Forecasts without a 90-day wait
- Default **Fast** mode starts after **3 complete calendar days** for an active product with a saved sale within its recording period.
- 3–6 days: recent daily average. 7 or more days: exponential smoothing with a fixed smoothing factor of 0.3. Zero-sale days count within the declared complete recording period. Today is excluded.
- Every product builds its own history. New items do not reset older items.
- Early predictions are estimates from limited data, not proven more accurate than Random Forest. With at least 14 days, the last 7 days are held out to measure errors, then the estimate is refitted using all completed days.
- **Compare all eligible methods** is optional. With 28–89 complete days, each eligible item compares exponential smoothing and additive weekly Holt-Winters using 7 validation days followed by 7 untouched test days. With at least 90 complete days, both methods and Random Forest are compared together, along with the weekly and 28-day average baselines, using the same validation windows and separate 14-day test. Younger eligible products still get fast estimates.
- Holt-Winters is implemented locally with a 7-day seasonal period and fixed level/trend/seasonal coefficients of 0.3/0.1/0.2. Parameters are not automatically tuned. It captures a changing level, linear trend and weekly additive seasonality. Predictions are clipped at zero. No new Python dependency was added.
- Click **Refresh forecast** after a completed business day. This version does not automatically retrain after every bill.

## Discounts, GST and payment
1. In Checkout, save your real receiving UPI ID. The app checks its format, not whether the account exists or belongs to you. Verify the payee and receiving account before use.
2. GST starts **off**. For an appropriately registered shop, enter GSTIN, choose prices including GST or adding GST, and configure each product's actual tax rate. GSTIN format is checked; registration and tax classification are not verified. This is a calculation and sales-receipt feature, not GST filing, statutory invoice certification or e-invoicing.
3. Add the customer's actual purchases. Leave customer name and phone empty for a walk-in customer.
4. Enter an amount or percentage discount. Choose local (CGST/SGST) or interstate (IGST) supply and cash or UPI.
5. Click **Prepare payment**. The server calculates and freezes the amount. For UPI, the app displays a locally generated QR with receiving ID, amount and reference. Stock is not reserved or deducted yet.
6. Check the money arrived in your own bank/UPI app (or collect cash). Tick the confirmation box and click **Payment received · give bill**. Only then are the bill, sale and stock deduction saved together. Download, print or share the bill via WhatsApp.

Payment confirmation is manual. Scanning a QR does not prove payment success. The app has no bank connection or payment gateway. If stock changes while payment is pending and checkout fails, resolve the stock issue or refund separately; do not collect the money again. Pending requests are recovered in the same browser session. Close/reopen recovery across browser sessions is not guaranteed: keep that checkout open until resolved.

Discount is applied before tax and allocated across items in integer paise. Inclusive GST is split from the discounted price; exclusive GST is added to it. Receipts preserve the calculated totals. Partial returns allocate the actual amount charged across returned quantities, including rounding, and full returns reconcile exactly. Refund transfers are handled separately.

Sales amount reports include the actual charged total, including GST where enabled. Tax accounting and credit-note filing require separate handling. Per-product GST rates must be reviewed when adding new products. Ordinary cash and UPI checkout work without GST.

## Verification
Python tests cover existing features and new early forecasts, payment gating, confirmation retries, frozen tax/discount pricing, QR content, PDFs, cancellation, shortage and partial-refund reconciliation. JavaScript checks cover two-step checkout and existing controls. No real payment, WhatsApp message or tax filing was sent.
