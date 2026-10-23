# Verification record

## Current desktop and interface update 0.7, 6 October 2026

71 Python tests pass. Ten new desktop tests cover a real detached worker surviving its parent launcher's exit, repeated and parallel opens reusing one worker, restart on the saved port with bills and stock preserved, occupied ports, authenticated shutdown, malformed runtime records, OS-held import locks, SQLite WAL snapshots, original-record preservation, refusal to overwrite installed data, invalid/future database schema rejection and browser argument construction.

`node tests/frontend_smoke.cjs` passes using a minimal DOM with a mocked API/window. It verifies the top navigation and removal of sidebar controls, all eight task screens, desktop-mode branding and browser-install button hiding, basket/draft retention and the existing WhatsApp sharing checks. JavaScript syntax and Python compilation pass. No personal records or virtual environment are included in the project download.

Process lifecycle and database checks ran in Linux. Windows PowerShell installation, desktop and Start menu shortcuts, Chrome/Edge app windows and real WhatsApp handoff were not executed here. The browser preview attempt timed out, so rendered appearance and device interaction remain unverified. No real message was sent and no public deployment was performed.

Run the code checks after installing requirements-dev.txt in the development environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check retailpulse/static/app.js
node --check retailpulse/static/sw.js
node tests/frontend_smoke.cjs
```

Node is needed only for development checks, not everyday shop use. See DESKTOP_APP.md for setup.

## Satya Shop / WhatsApp update 0.6, 5 October 2026

61 Python tests pass. The eight new regression tests cover saved-name persistence, immutable old bill and PDF headers, audit/idempotency and stale-name conflicts, invalid-number atomic rollback, equivalent contact retries, earlier phone-free requests, name-free retries after renaming, and contact preservation through backup/restore. The existing actual HTTP workflow now exercises shop renaming and saved customer numbers.

`node tests/frontend_smoke.cjs` passes using a minimal DOM and mocked local API/window. It checks retained shop-name drafts, saved branding and new-bill names, contact validation and clearing between customers, international-number normalization, encoded WhatsApp draft contents, freshly fetched return totals, recipient overrides without database writes, sample labels, popup blocking and network failures. It also retains dashboard/navigation regression checks. JavaScript syntax and all 179 unique HTML IDs/control references pass validation.

These checks do not verify native browser or WhatsApp behaviour. The previous local preview was blocked with ERR_BLOCKED_BY_CLIENT. Windows launchers, device rendering, app installation, signing into WhatsApp, an actual chat handoff and delivery remain unverified. No real customer message was sent and no public deployment was performed. The messaging feature is a user-initiated draft, with PDF attachment done manually.

Reproduce the code checks from the project folder:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/frontend_smoke.cjs
```

Node is needed only for the development smoke check, not to run the Python shop app.

## Interface update 0.5, 5 October 2026

53 Python tests pass. Four new history checks verify that today's sales stay out of complete-day charts, completed sales become visible without forecast training, older sales still count for readiness, and stale forecast history is retained alongside recent completed sales.

JavaScript syntax, all 163 unique HTML IDs and their control references were checked. A minimal DOM fixture executed the frontend and checked eight task screens, basket and unfinished-form retention, unchanged DOM during polling, escaped product search, status filters, keyboard stock tabs, new/archived product forecast status, bill-to-return navigation, drawer controls, connection recovery and calendar boundaries. This fixture does not validate native browser behaviour or layout.

The generated demo was trained successfully with 365 days and eight products. Browser preview of the local server was blocked with `ERR_BLOCKED_BY_CLIENT`; desktop/mobile rendering, Windows launchers and PWA installation remain unverified. No deployment or real-shop pilot was performed.

## Earlier verification records

Verified on 30 September 2026 with Python 3.12.14, NumPy 2.3.5, pandas 2.2.3 and scikit-learn 1.8.0.

## Completed checks

- 16 automated functional tests passed.
- Actual HTTP integration passed: sale, stock deduction, revenue calculation, identical retry, oversell rejection, stock receipt and policy update.
- Dashboard HTML, JavaScript and CSS were served successfully.
- Daily-sales and forecast CSV downloads succeeded.
- JavaScript passed Node's syntax check.
- Demo generation and the complete forecasting pipeline ran successfully on 365 generated days across eight products.
- The importer was tested with controlled UCI-format Excel fixtures and own-store CSV fixtures.
- Chronological model-selection tests confirm that changing only test-period truth cannot change selection.

## Demo experiment

Synthetic demonstration data, original seed 42, completed history through 29 September 2026. The earlier validation windows selected Random Forest.

| Method | Separate test MAE | Separate test RMSE | Separate test WAPE |
|---|---:|---:|---:|
| Weekly seasonal baseline | 4.4107 | 5.8187 | 25.918% |
| 28-day average | 4.4585 | 5.5900 | 26.199% |
| Random Forest | 3.4683 | 4.5424 | 20.380% |

The separate test covered 16–29 September 2026. These values measure the generated demonstration, not actual shop performance. A new run ending on different dates can produce different values.

## Checks still to perform in your environment

- Open the dashboard on desktop and mobile. Automated browser visual checking was unavailable because the browser executable could not be downloaded in this environment.
- Run the supplied Windows commands on your Windows Python installation.
- Download the full real UCI dataset and run its own evaluation; its network download was not executed here.
- Build the Docker image and deploy it on your chosen host. Neither a Docker execution nor a public deployment is claimed.
- Connect and evaluate a complete real-shop sales log before using forecasts for purchases.

## App and billing upgrade

23 tests pass. PDF sample rendered and reviewed. Native Windows launch scripts and PWA installation remain unverified; see APP_AND_BILLS.md for precise scope.


## Shop workflows update, 4 October 2026

49 automated tests pass, including an actual threaded HTTP server workflow: empty shop setup, product creation, bill, partial return, cancellation, catalog edit/archive, physical stock count, return PDF, CSV, and consistent backup ZIP. New cases also cover concurrent returns, over-return rollback, immutable bill prices, stale product/count conflicts, archive rules, old-schema migration with a pre-upgrade copy, recovery and backup scheduling/retention. The original 23 checks still pass.

JavaScript syntax and all 117 unique HTML control IDs were checked. The demo return PDF and cancelled-bill PDF were rendered and visually reviewed. Browser navigation to the local app was blocked by ERR_BLOCKED_BY_CLIENT, so interactive browser layout, PWA installation, phone use and actual Windows launcher execution remain unverified. An actual shop pilot and any public deployment have not been performed.
