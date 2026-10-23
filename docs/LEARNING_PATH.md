# Understand and build RetailPulse step by step

Work through this in VS Code. Run the app first, then inspect and explain each component. Completing a stage means you can explain the decision and verify its behavior, not only run the command.

## 1. Define the business problem

Shop owners need to know what sold, how much stock remains, and what to order before the supplier arrives. Our target is **units sold per product per calendar day**. Our users are shop owners or inventory staff.

Example: if a product is expected to sell 12, 15 and 10 units during a three-day lead time, the shop needs 37 units plus its chosen buffer, adjusted for any sales already recorded today.

Deliverable: explain this problem and the input/output in two sentences. Do not call the system a profit predictor; purchase costs are absent.

## 2. Inspect data quality

Open `data.py`. Run the demo, then the separate UCI import. Inspect `quality_report.json` and compare accepted rows with excluded rows. Explain cancelled invoices, negative quantities, exact duplicate rows, missing product information, and the final partial day.

Try an invalid own-store CSV row. The importer must report the row and leave the database empty. Preserve actual transaction dates and currency; moving historical dates into the present would change the meaning of the data.

Deliverable: a data-quality table with each rule, row count and justification for your chosen real dataset.

## 3. Work with SQL

Open `store.py` and `sql/business_queries.sql`. Identify the product primary key and event primary key. Explain why inventory and event insertion must commit together.

Use SQLite with VS Code or a SQLite browser. Run daily revenue, best-selling products and stock-policy queries. Validate one day's revenue by hand from exported sale quantities and unit prices.

Deliverable: SQL results for five concrete business questions.

## 4. Analyze sales before modelling

Export `daily_sales.csv`. In a notebook, explore product volumes, weekday differences, unusually large transactions and days with no sales. Build a dense daily calendar before interpreting missing days.

Useful questions: Which products are intermittent? Does the weekend change sales? Do a few products dominate revenue? Could missing days mean missing records rather than no customers?

Deliverable: three charts and three findings supported by the real data. Mark demo findings as synthetic.

## 5. Build and evaluate the forecasting model

Open `forecast.py`. Explain the lags and why rolling features need to use only previous dates. Compare a Random Forest with previous-week sales and the trailing 28-day average.

Explain each validation window and the untouched final test period. Read the test that changes only test-period truth and checks that model selection stays the same. Show why a random row split can expose later information to earlier predictions.

Deliverable: a comparison table with validation MAE and separate test MAE/RMSE/WAPE for your dataset. Report whichever method wins. Do not tune after repeatedly looking at the final test; create a new untouched test period if you do.

## 6. Connect prediction to an action

Explain the restock formula and the user-specified buffer. Demonstrate a sale, receipt and policy change. Attempt a sale that exceeds stock; it must fail without changing the database. Resend the same event ID; it must not deduct twice.

Deliverable: a short demonstration of a sale changing revenue, inventory and its stock target.

## 7. Deploy and document

Follow `DEPLOYMENT.md` for your chosen host. Keep the data folder persistent. Connect a real transaction sender using `API.md`, preserving event IDs during retries. Refresh the forecast after each completed business day and record errors as actual future days arrive.

Deliverables: GitHub repository, screenshots of the app, a deployed URL if you have a hosting account, a model card and a two-minute demo video. A PBIX report is optional; the web dashboard already demonstrates the application.

## What to explain in an interview

- Who uses the system and which inventory decision it helps.
- How you handled cancellations and incomplete dates.
- How you prevented future information entering training or recursive forecasts.
- Why the winning method was chosen from validation rather than test results.
- How transactions, stock updates and duplicate retries stay consistent.
- Which limitations require additional real data: stockouts, returns, promotions and supplier reliability.

After you have run and understood the actual pipeline, an accurate project description is: “Built a retail sales forecasting and inventory planning application with Python, SQL, chronological model evaluation, live transaction ingestion and a browser dashboard.” Add measured real-data results only after completing that experiment.
