"""Curated, verified question -> SQL examples used as retrieved few-shot context for the LLM.

Every example is validated by the SQL validator and executed against the dataset in
tests/test_retrieval.py. None of these questions is a benchmark question (also enforced by a
test), so the benchmark measures generalisation rather than recall of a retrieved answer.
"""
from __future__ import annotations

EXAMPLES: list[dict[str, str]] = [
    {"id": "ex_gross_by_country_2010", "question": "Gross sales by country in 2010, top 5",
     "sql": "SELECT country, ROUND(SUM(line_amount) FILTER (WHERE line_type = 'SALE' AND item_type = 'PRODUCT'), 2) AS gross_revenue_gbp "
            "FROM transactions WHERE invoice_year = 2010 GROUP BY country ORDER BY gross_revenue_gbp DESC LIMIT 5"},
    {"id": "ex_units_by_product_germany", "question": "Most sold products by units in Germany",
     "sql": "SELECT stock_code, ANY_VALUE(description) AS description, SUM(quantity) FILTER (WHERE line_type = 'SALE') AS units_sold "
            "FROM transactions WHERE item_type = 'PRODUCT' AND country = 'Germany' GROUP BY stock_code ORDER BY units_sold DESC LIMIT 10"},
    {"id": "ex_weekly_net_2011", "question": "Weekly net revenue during 2011",
     "sql": "SELECT CAST(date_trunc('week', invoice_date) AS DATE) AS week_start, "
            "ROUND(SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION')), 2) AS net_revenue_gbp "
            "FROM transactions WHERE item_type = 'PRODUCT' AND invoice_year = 2011 GROUP BY week_start ORDER BY week_start"},
    {"id": "ex_month_compare_products", "question": "Compare product net revenue in November 2011 with October 2011",
     "sql": "SELECT stock_code, ANY_VALUE(description) AS description, "
            "ROUND(SUM(line_amount) FILTER (WHERE invoice_month = DATE '2011-11-01'), 2) AS net_revenue_2011_11_gbp, "
            "ROUND(SUM(line_amount) FILTER (WHERE invoice_month = DATE '2011-10-01'), 2) AS net_revenue_2011_10_gbp, "
            "ROUND(COALESCE(SUM(line_amount) FILTER (WHERE invoice_month = DATE '2011-11-01'), 0) - "
            "COALESCE(SUM(line_amount) FILTER (WHERE invoice_month = DATE '2011-10-01'), 0), 2) AS change_gbp "
            "FROM transactions WHERE item_type = 'PRODUCT' AND line_type IN ('SALE','CANCELLATION') "
            "AND invoice_month IN (DATE '2011-10-01', DATE '2011-11-01') GROUP BY stock_code ORDER BY net_revenue_2011_11_gbp DESC NULLS LAST LIMIT 10"},
    {"id": "ex_cancel_rate_by_country", "question": "Cancellation rate by country for countries with over 100 orders",
     "sql": "SELECT country, COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE') AS orders, "
            "ROUND(100 * -SUM(line_amount) FILTER (WHERE line_type = 'CANCELLATION') / SUM(line_amount) FILTER (WHERE line_type = 'SALE'), 2) AS cancellation_rate_pct "
            "FROM transactions GROUP BY country HAVING COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE') > 100 ORDER BY cancellation_rate_pct DESC"},
    {"id": "ex_returned_value_products", "question": "Products with the highest value of cancelled lines",
     "sql": "SELECT stock_code, ANY_VALUE(description) AS description, ROUND(-SUM(line_amount), 2) AS cancelled_value_gbp, "
            "COUNT(DISTINCT invoice) AS cancellation_invoices FROM transactions WHERE line_type = 'CANCELLATION' AND item_type = 'PRODUCT' "
            "GROUP BY stock_code ORDER BY cancelled_value_gbp DESC LIMIT 10"},
    {"id": "ex_customer_count_month", "question": "Number of active customers per month",
     "sql": "SELECT strftime(invoice_month, '%Y-%m') AS month, COUNT(DISTINCT customer_id) FILTER (WHERE line_type = 'SALE') AS customers "
            "FROM transactions GROUP BY month ORDER BY month"},
    {"id": "ex_aov_country", "question": "Average order value by country",
     "sql": "SELECT country, ROUND(SUM(line_amount) / COUNT(DISTINCT invoice), 2) AS avg_order_value_gbp, COUNT(DISTINCT invoice) AS orders "
            "FROM transactions WHERE line_type = 'SALE' AND item_type = 'PRODUCT' GROUP BY country ORDER BY avg_order_value_gbp DESC LIMIT 10"},
    {"id": "ex_new_customers_2011", "question": "How many customers made their first purchase in 2011",
     "sql": "WITH first_purchase AS (SELECT customer_id, MIN(invoice_date) AS first_date FROM transactions "
            "WHERE has_customer AND line_type = 'SALE' GROUP BY customer_id) "
            "SELECT COUNT(*) AS new_customers FROM first_purchase WHERE first_date >= TIMESTAMP '2011-01-01' AND first_date < TIMESTAMP '2012-01-01'"},
    {"id": "ex_repeat_customers", "question": "Share of customers who ordered more than once",
     "sql": "WITH per_customer AS (SELECT customer_id, COUNT(DISTINCT invoice) AS orders FROM transactions "
            "WHERE has_customer AND line_type = 'SALE' GROUP BY customer_id) "
            "SELECT COUNT(*) AS customers, COUNT(*) FILTER (WHERE orders > 1) AS repeat_customers, "
            "ROUND(100.0 * COUNT(*) FILTER (WHERE orders > 1) / COUNT(*), 1) AS repeat_share_pct FROM per_customer"},
    {"id": "ex_stock_adjustments", "question": "Units written off as stock adjustments by year",
     "sql": "SELECT invoice_year, -SUM(quantity) AS units_written_off, COUNT(*) AS lines FROM transactions "
            "WHERE line_type = 'STOCK_ADJUSTMENT' GROUP BY invoice_year ORDER BY invoice_year"},
    {"id": "ex_fees_by_type", "question": "Total fees and manual adjustments by type",
     "sql": "SELECT item_type, stock_code, ROUND(SUM(line_amount), 2) AS amount_gbp, COUNT(*) AS lines FROM transactions "
            "WHERE item_type IN ('FEE','MANUAL_ADJUSTMENT') GROUP BY item_type, stock_code ORDER BY amount_gbp"},
    {"id": "ex_daily_best_day_2010", "question": "Best trading day of 2010 by net revenue",
     "sql": "SELECT CAST(invoice_date AS DATE) AS invoice_day, ROUND(SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION')), 2) AS net_revenue_gbp "
            "FROM transactions WHERE item_type = 'PRODUCT' AND invoice_year = 2010 GROUP BY invoice_day ORDER BY net_revenue_gbp DESC LIMIT 1"},
    {"id": "ex_weekday_revenue", "question": "Net revenue by day of week",
     "sql": "SELECT dayname(invoice_date) AS weekday, ROUND(SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION')), 2) AS net_revenue_gbp "
            "FROM transactions WHERE item_type = 'PRODUCT' GROUP BY weekday ORDER BY net_revenue_gbp DESC"},
    {"id": "ex_quarterly_revenue", "question": "Quarterly net revenue",
     "sql": "SELECT invoice_year, quarter(invoice_date) AS quarter, ROUND(SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION')), 2) AS net_revenue_gbp "
            "FROM transactions WHERE item_type = 'PRODUCT' GROUP BY invoice_year, quarter ORDER BY invoice_year, quarter"},
    {"id": "ex_customer_top_eire", "question": "Biggest customers in Ireland by gross sales",
     "sql": "SELECT customer_id, ROUND(SUM(line_amount) FILTER (WHERE line_type = 'SALE'), 2) AS gross_revenue_gbp "
            "FROM transactions WHERE country = 'EIRE' AND has_customer AND item_type = 'PRODUCT' GROUP BY customer_id ORDER BY gross_revenue_gbp DESC LIMIT 10"},
    {"id": "ex_those_products_units", "question": "Units sold for stock codes 22423 and 85123A",
     "sql": "SELECT stock_code, ANY_VALUE(description) AS description, SUM(quantity) FILTER (WHERE line_type = 'SALE') AS units_sold "
            "FROM transactions WHERE stock_code IN ('22423', '85123A') GROUP BY stock_code ORDER BY units_sold DESC"},
    {"id": "ex_date_range", "question": "Net revenue between 1 and 15 March 2011",
     "sql": "SELECT ROUND(SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION') AND item_type = 'PRODUCT'), 2) AS net_revenue_gbp "
            "FROM transactions WHERE invoice_date >= TIMESTAMP '2011-03-01' AND invoice_date < TIMESTAMP '2011-03-16'"},
]

# Short notes retrieved alongside examples. The full schema and every business rule are always in
# the system prompt; these notes only add emphasis for the question at hand.
NOTES: list[dict[str, str]] = [
    {"id": "note_net_default", "text": "Revenue or sales without a qualifier means net revenue: SALE plus CANCELLATION lines of PRODUCT items."},
    {"id": "note_returns_semantics", "text": "Returns: 'C' invoices mix order cancellations and returns; 11% of customer-linked cancellation lines have no earlier sale in the data. Stock adjustments are not returns."},
    {"id": "note_customers", "text": "Customer questions: filter has_customer = true and say that unattributed revenue is excluded."},
    {"id": "note_dates", "text": "Data covers 2009-12-01 to 2011-12-09. December 2011 is partial. Compare equal-length windows."},
    {"id": "note_profit", "text": "There is no cost data. Profit, margin and cost questions are unsupported."},
    {"id": "note_weekdays", "text": "The shop does not trade on Saturdays and closes over Christmas; compare per trading day when windows differ."},
    {"id": "note_non_product", "text": "Postage (POST, DOT, C2), fees, manual adjustments, discounts and gift vouchers are not products."},
    {"id": "note_compare_periods", "text": "For 'compare with the previous month' use FILTER clauses per month and report both values and the change."},
]
