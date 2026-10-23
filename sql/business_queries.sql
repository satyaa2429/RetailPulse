-- Run against data/retailpulse.sqlite3. Currency uses minor units: divide by 100.0.
-- 1. Daily revenue and units. Positive sales only; excluded returns are not deducted.
SELECT day, SUM(units) AS units_sold, SUM(revenue_minor)/100.0 AS sales_revenue
FROM daily_sales GROUP BY day ORDER BY day;

-- 2. Best-selling products, using recorded sales.
SELECT p.sku,p.name,SUM(d.units) AS units_sold,SUM(d.revenue_minor)/100.0 AS sales_revenue
FROM daily_sales d JOIN products p ON p.sku=d.sku
GROUP BY p.sku,p.name ORDER BY units_sold DESC LIMIT 10;

-- 3. Current inventory and user-configured restock policy.
SELECT sku,name,stock,stock_initialized,lead_days,buffer_units FROM products ORDER BY name;

-- 4. Actual live events, distinct from loaded historical transactions.
SELECT event_id,occurred_at,business_date,sku,kind,quantity,source
FROM events WHERE source='live' ORDER BY occurred_at DESC LIMIT 25;

-- 5. Product contribution to total recorded sales revenue.
SELECT p.name,SUM(d.revenue_minor)/100.0 AS sales_revenue,
  ROUND(100.0*SUM(d.revenue_minor)/(SELECT SUM(revenue_minor) FROM daily_sales),2) AS revenue_share_percent
FROM daily_sales d JOIN products p ON p.sku=d.sku GROUP BY p.sku,p.name ORDER BY sales_revenue DESC;


-- 6. Daily recorded revenue after returns, dated when each return is recorded.
SELECT day,SUM(gross_revenue_minor)/100.0 AS gross_sales,
 SUM(refund_minor)/100.0 AS recorded_refunds,
 SUM(net_revenue_minor)/100.0 AS sales_after_refunds
FROM net_daily_sales GROUP BY day ORDER BY day;

-- 7. Returns and cancellations keep the original bill.
SELECT return_id,bill_id,kind,business_date,reason,restock,refund_minor/100.0 AS recorded_refund
FROM returns ORDER BY created_at DESC;

-- 8. Physical stock corrections and returned stock.
SELECT movement_id,sku,kind,quantity_delta,stock_after,reason,business_date
FROM stock_movements ORDER BY created_at DESC;
