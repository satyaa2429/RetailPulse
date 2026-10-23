# Version 0.8 update

See [UPDATE_V08.md](../UPDATE_V08.md) for the current 3-day fast forecast and payment-before-bill flow. The 90-day workflow below applies to the optional model comparison.

# Model card

## Purpose

Forecast daily recorded product sales and assist restock planning. The forecast is advisory; it does not automatically purchase stock.

## Inputs and target

Target: positive units sold per product per complete calendar day. Forecast training uses gross positive sales. Live returns are recorded separately; the dashboard and net_daily_sales export subtract recorded refunds on their return dates. Historical import excludes returns and therefore does not reconstruct historical net revenue.

Features: product one-hot indicators, lagged sales at 1/7/14/28 days, earlier 7/28-day means, earlier 7-day standard deviation, weekday and month cycles. No customer identity is retained or needed.

## Methods

- Weekly seasonal baseline: repeat sales observed seven days earlier.
- Trailing 28-day average: fixed mean of the last 28 actual daily sales.
- Random Forest: 100 trees, maximum depth 12, minimum leaf size 3, seed 42.

The selected method can be a baseline. Random Forest is not assumed to improve the result.

## Evaluation design

Minimum history: 90 completed days. Reserve the final 14 days for a separate test. Use the preceding three non-overlapping 7-day windows for expanding-history validation. Fit the forest separately at each origin. Choose the lowest validation MAE, report all separate test metrics, then refit the chosen method on all completed history for serving.

Forecasts are recursive. Later horizons use earlier predictions, not hidden future actuals. All products share date cutoffs. Current incomplete-day sales are excluded. For UCI, product selection uses an early period that ends before validation and the final possibly partial date is omitted.

Metrics: daily product-level MAE and RMSE, plus aggregate WAPE. A large-volume SKU can dominate aggregate WAPE, so inspect per-product test predictions as well. The initial system has no calibrated prediction intervals or service-level guarantees.

## Data variants

The included executable demo is synthetic. UCI importer handles real historical UK retailer sales in GBP. Own-store importer requires a complete user-provided CSV and explicit coverage endpoint; live operation requires every subsequent sale to be recorded.

Demo scores do not establish real-shop usefulness. UCI tests do not establish accuracy for a present-day Indian shop. The real UCI network download is supplied as a command; local tests verify importer behavior on controlled Excel fixtures.

## Known limits

- Recorded sales are affected by stock availability; unobserved lost demand is absent.
- Missing calendar days are treated as zero sales, assuming a complete log.
- Public data lacks inventory, supplier lead-time observations, promotions and costs.
- Product creation, stock reconciliation and returns of checkout bills are implemented. Purchase orders, multi-store operations and historical refund reconstruction are not implemented.
- Newly added products are excluded from forecast training until they have 90 completed days; imported products use their declared historical coverage.
- Short or new-product histories may be unreliable; importing less than 90 calendar days does not enable training.
- The horizon is 14 days. Targets are unavailable if forecast coverage does not contain the required lead days.
- User-configured buffer stock is a policy parameter, not calibrated statistical safety stock.
- Positive-sales metrics do not estimate profitability or refund-adjusted net revenue.

## Operation

Sales and receipts update immediately. Forecast refresh is a separate batch job after business-day completion. New events do not instantly retrain the forest. The deployment uses a single WSGI process with threads and SQLite transactions; scale-out requires redesigning storage and the training job lock.
