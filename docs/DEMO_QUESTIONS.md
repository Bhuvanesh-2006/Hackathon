# Demo script

These questions are in a suggested order for a 5-minute demo. Expected values were measured on the prepared dataset (1,044,848 rows).

| # | Ask | What to point out |
|---|---|---|
| 1 | *Which products generated the highest revenue?* | "Revenue" defaults to **net** revenue (sales − cancellations, products only). REGENCY CAKESTAND 3 TIER leads at £314,513.47. Show the SQL tab, then Copy SQL and Export CSV. |
| 2 | *Who are our best customers?* | The agent **asks back**: net revenue, gross revenue, or number of invoices? Pick *Number of invoices*. Customer 14911 (EIRE) ranks first with 373 invoices. |
| 3 | *now only for Germany* | A follow-up in the same conversation adds `country = 'Germany'` to the previous query. |
| 4 | *Which products had the most returned units?* | PAPER CRAFT, LITTLE BIRDIE: 80,995 units on **one** cancelled invoice, a single order that was entered and then cancelled. Only C invoices count as returns; the 3,393 stock write-off lines do not. |
| 5 | *How much revenue was associated with cancelled invoices?* | £1,465,303.66 across 8,292 cancellation invoices, shown as a positive amount. |
| 6 | *What were the monthly revenue trends?* | A line chart. Peaks fall in November 2010 and 2011; December 2011 is partial because the data ends on 9 Dec. |
| 6b | *On which invoice date the product has generated maximum revenue* | The product is not named, so the agent offers three readings. Pick *The single product and day*: PICNIC BASKET WICKER SMALL on 2011-06-10, £39,673.45 net. By gross sales the answer would be PAPER CRAFT, LITTLE BIRDIE on 2011-12-09 (£168,469.60), an order cancelled the same day that earned £0. |
| 7 | *How much net revenue came from transactions with a missing customer ID?* | £2,569,366.77. These lines stay in totals but are excluded from customer rankings. |
| 8 | *What is our profit margin by product?* | **Unsupported**: the data has no cost field, so the agent declines instead of inventing margins. |
| 9 | *Delete all cancelled invoices* | Refused. Even if a model produced `DELETE`, the validator and the read-only connection would block it. |
| 10 | Benchmark page → **Run benchmark** | 20 trap questions (4 multi-turn) and 15 security probes checked against independent reference SQL. Execution success and result correctness are reported separately. |

Other good questions: *Which countries generated the highest revenue?* · *How many orders were placed in 2010?* · *Top 5 customers by gross revenue in 2011* · *What is the net total of postage charges?* · *Average order value in the United Kingdom*.

## v1.1 additions to show
| Ask / do | What to point out |
|---|---|
| *what is the max revenue* | Asks which level (month, day, product, customer, country, or largest order). Pick **Largest single order**: invoice 581483, £168,469.60, flagged as cancelled in full; 5 of the top 10 orders were later cancelled. |
| *Which products generated the most revenue?* → *Only in the UK* → *Compare with the previous month* | The third question asks which period (none is set). Pick *November 2011 vs October 2011*. The UK filter chip stays; remove it with × and the question re-runs without it. |
| *How many units of those products were returned?* | "Those products" = the 10 stock codes of the previous answer (see the SQL). |
| Overview → Anomaly alerts → **Investigate** on the cancelled-value spike (week of 2011-12-05) | £203,705 vs £11,052 expected. The product breakdown shows PAPER CRAFT, LITTLE BIRDIE contributing 87.9% of the change. Contributions reconcile; labelled descriptive, not causal. |
| **Ask the analyst** on that anomaly | The conversation opens scoped to that week (date chip). |
| Evidence tab on any answer | Filters, date range, grouping, source rows scanned, limitations, "not independently verified". |
