# Optional Power BI report

The browser dashboard is included. A Power BI `.pbix` file is not included; use these exported tables to create one yourself.

Run:

```powershell
.\.venv\Scripts\python.exe -m retailpulse export
```

Import `daily_sales.csv`, `inventory.csv`, `forecast.csv` and `holdout.csv` from `data/exports` into Power BI Desktop. Monetary columns ending in `_minor` are paise for INR or pence for GBP; divide by 100. Keep different datasets/currencies in separate reports.

| Table | Grain | Useful visuals |
|---|---|---|
| daily_sales | Day × SKU | Revenue trend, units trend, best-selling products |
| inventory | SKU snapshot | On-hand units, stock target, suggested order |
| forecast | Future day × SKU | Forecast chart and product slicer |
| holdout | Test day × SKU | Actual vs predicted sales and absolute error |

Create a unique SKU dimension from inventory's SKU and product name. Relate it one-to-many to the other tables. For historical/future date comparisons, create a date dimension spanning both actual and forecast dates and relate it to the relevant day/date columns.

Example measures after naming the imported table `daily_sales`:

```dax
Sales Revenue = DIVIDE(SUM(daily_sales[revenue_minor]), 100)
Units Sold = SUM(daily_sales[units])
```

Example test measure after adding a numeric absolute-error calculated column to `holdout`:

```dax
Absolute Error = ABS(holdout[actual_units] - holdout[predicted_units])
MAE = AVERAGE(holdout[Absolute Error])
WAPE = DIVIDE(SUM(holdout[Absolute Error]), SUM(holdout[actual_units]))
```

Format WAPE as a percentage. The browser's WAPE is displayed as percent units (for example 20.38); the DAX result is a ratio (0.2038 before percent formatting).

CSV imports are snapshots. Re-export and refresh to update this report; the browser dashboard supplies the immediate five-second refresh behavior.
