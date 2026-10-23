# Version 0.8 update

See [UPDATE_V08.md](../UPDATE_V08.md) for the current 3-day fast forecast and payment-before-bill flow. The 90-day workflow below applies to the optional model comparison.

# Connect a transaction sender

The manual developer server normally runs at `http://127.0.0.1:8000`. The desktop launcher normally uses `http://127.0.0.1:18741` and saves its chosen port in `%LOCALAPPDATA%\SatyaShop\run\server.json`. Use the running app window's origin; a fallback port may be selected. A POS or script can send each new sales line as it happens. In a deployment, replace the local address with your HTTPS host and send `Authorization: Bearer YOUR_TOKEN`.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/status` | Availability and whether authentication is required |
| GET | `/api/state` | Revenue, inventory, forecasts and latest events |
| POST | `/api/sales` | Record a sale and decrement stock atomically |
| POST | `/api/receipts` | Record received stock |
| POST | `/api/policy` | Change supplier lead days and buffer units |
| POST | `/api/train` | Start one forecast refresh in the background |
| GET | `/api/export?table=daily_sales` | CSV export; also sales, inventory, forecast, holdout |

## Sales event

```json
{"event_id":"bill001-line01","sku":"RP001","quantity":3,"unit_price":"65.00"}
```

Quantity must be a positive integer. Unit price is a positive decimal amount in the store currency. The server timestamps the event when received and uses the configured business timezone. This live endpoint is not a backdated or offline-events importer.

Response:

```json
{"event_id":"bill001-line01","duplicate":false,"stock":71}
```

Persist a stable event ID in the sender and reuse it on a retry. An identical duplicate returns `duplicate:true` without moving stock again. A conflicting payload with the same ID returns HTTP 409. Insufficient or unconfigured stock also returns 409, without saving the event or changing stock. Validation failures return HTTP 400.

Example from Windows PowerShell:

```powershell
$sale = @{event_id="bill001-line01";sku="RP001";quantity=3;unit_price="65.00"} | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/sales -Method Post -ContentType "application/json" -Body $sale
```

## Receipt and policy

```json
{"event_id":"receipt001-line01","sku":"RP001","quantity":20}
```

Receipts use the same idempotency rule. For a newly imported store, the first receipt establishes known stock from zero; count the actual opening inventory first.

```json
{"sku":"RP001","lead_days":3,"buffer_units":15}
```

Lead days range from 1 to 14. Buffer units are a non-negative whole number. Forecast refresh takes an empty JSON object and returns HTTP 202. `/api/state` reports `training` and `training_error`.

External POS integration is available through these endpoints but is not connected to any real POS by default.

## Itemized checkout and digital bills

See APP_AND_BILLS.md for POST /api/checkout, GET /api/bills/BILL_ID and GET /api/bills/BILL_ID.pdf.


## Shop workflows (0.4)

GET /api/state includes shop_setup_required, metadata.store_id, product active/revision/introduced_on fields, gross revenue/refunds/net revenue, return history, stock movements and backup status. Send this store_id with all writes; a mismatch is HTTP 409 with code STORE_MISMATCH, and the client retains the original pending request.

- POST /api/setup: request_id, shop_name, currency (default INR), timezone (default Asia/Kolkata). Only an empty unconfigured database can be initialized.
- POST /api/products: request_id, sku, name, unit_price, opening_stock, lead_days, buffer_units, active (boolean). Currency comes from shop settings.
- POST /api/products/edit: request_id, sku, name, unit_price, lead_days, buffer_units, active, expected_revision. Item code/currency/opening stock stay fixed. Reload after a revision conflict.
- POST /api/stock/adjust: request_id, sku, counted_stock, expected_stock, reason. Stale balance rejects the complete correction.
- POST /api/returns: return_id, bill_id, reason, restock (boolean), items [{line_no,quantity}]. Bill JSON supplies zero-based line_no. Server uses immutable original names/prices and checks remaining quantities inside the transaction.
- POST /api/bills/cancel: return_id, bill_id, reason, restock. Refunds all remaining quantities, once. Correct the purchase by creating a new bill.
- GET /api/returns/RETURN_ID and /api/returns/RETURN_ID.pdf: saved return and PDF.
- POST /api/backups with {}: synchronous manual consistent backup. GET /api/backups lists status; GET /api/backups/FILENAME.zip downloads an authorized backup.
- GET /api/export?table=net_daily_sales, returns or stock_movements: additional CSV tables. daily_sales remains gross purchases for forecasting.

Use a stable request_id/return_id for retries. Setup, product actions, policies with request_id, stock counts, bills and returns replay the same result without a second change. A changed payload with the same ID returns 409. API clients using /api/policy should include request_id to retain revision idempotency. Authentication applies to every new route when a token is configured.

Original bills keep their original items. Bill JSON adds status, refund_minor, net_total_minor, returns, and remaining_quantity per line. No actual payment is collected or refunded by these endpoints.


## Saved shop name and customer contact (0.6)

`POST /api/shop/name` accepts `request_id`, `store_id`, `shop_name` and `expected_shop_name`. Send the exact previously loaded metadata name (or an empty string if absent). An identical retry returns `duplicate:true`; a changed retry or stale previous name returns 409. Changes are recorded in `actions` and update only the shop-name metadata. Existing bill headers stay immutable. Configure an empty shop using `/api/setup` first.

`POST /api/checkout` now accepts optional `customer_phone` as text. Ten-digit Indian mobile numbers are normalized to country code 91; international numbers use a country code, with optional leading + or 00. Spaces, hyphens and parentheses are accepted. Invalid numbers reject the checkout without saving sales or moving stock. The normalized number participates in the immutable retry payload. Omit it or send an empty string for walk-in customers; older phone-free bill retries remain compatible.

`GET /api/bills/BILL_ID` includes `customer_phone`, stored as international digits, or an empty string for an older bill. The contact is stored in the existing `bills.request_json`; no phone column or schema upgrade is required. If checkout omits `shop_name`, new bills use the saved shop name. A retry without an explicit name retains that bill's original name, even after a shop rename. Clients should still persist the exact original request for retries.

The frontend reads a saved bill and opens WhatsApp's `https://wa.me/NUMBER?text=ENCODED_MESSAGE` click-to-chat URL after an explicit click. This is a recipient's chat with a draft, not a server send endpoint. It sends no bill a second time through checkout. No delivery status or automatically attached PDF is supplied. PDF downloads continue through the authenticated existing PDF route; attach the file in the chat manually. Official link format: https://faq.whatsapp.com/5913398998672934.

## Desktop launcher (0.7)

`GET /api/state` includes `desktop_mode` as a boolean. The frontend uses it to display desktop branding and hide the separate browser-install prompt. Existing shop API routes and write validation are unchanged.

The loopback-only desktop worker exposes `GET /_satya_desktop/status` and `POST /_satya_desktop/stop` for the launcher. Both require its random `X-Satya-Launcher-Key` header and matching runtime identity. These are private process controls, not POS endpoints. Stop refuses while forecast training is active. Runtime records contain a local control key; do not publish or distribute them.
