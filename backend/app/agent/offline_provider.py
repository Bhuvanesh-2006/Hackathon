"""Deterministic, rule-based planner used when no LLM is configured.

This is NOT an LLM. It maps a fixed set of question patterns to SQL templates so the app can be
demonstrated and tested offline. The UI and benchmark label results produced by it as
"offline rule-based". Its SQL goes through exactly the same validation and execution path.
"""
from __future__ import annotations

import re
from functools import lru_cache

from app.agent.models import AgentPlan, ChartSpec
from app.agent.providers import LLMProvider, PlanContext

WRITE_WORDS = re.compile(r"\b(delete|drop|truncate|insert into|alter table|grant|attach|remove all|overwrite)\b", re.I)
UNSUPPORTED_TOPICS = re.compile(
    r"\b(profit|margin|cost of goods|costs?|cogs|forecast|predict|next (month|year|quarter)|stock levels?|"
    r"inventory|warehouse|employee|staff|salar(y|ies)|marketing|campaign|ad spend|website traffic|"
    r"weather|competitor|tax(es)?|vat)\b",
    re.I,
)

COUNTRY_ALIASES = {
    "uk": "United Kingdom", "u.k.": "United Kingdom", "britain": "United Kingdom",
    "england": "United Kingdom", "ireland": "EIRE", "usa": "USA",
    "united states": "USA", "holland": "Netherlands",
}


@lru_cache
def _countries() -> list[str]:
    from app.database.connection import run_query

    try:
        res = run_query("SELECT DISTINCT country FROM transactions WHERE country IS NOT NULL")
        return sorted((r[0] for r in res.rows), key=len, reverse=True)
    except Exception:
        return []


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class OfflineRuleProvider(LLMProvider):
    name = "offline"
    model = "rule-based templates (no LLM)"
    is_llm = False
    fallback_reason: str | None = None

    def status(self) -> dict:
        return {
            "provider": self.name, "model": self.model, "is_llm": False, "configured": True,
            "note": self.fallback_reason or "Offline demo mode selected",
        }

    # ------------------------------------------------------------------ parsing helpers
    @staticmethod
    def _top_n(q: str, default: int = 10) -> int:
        m = re.search(r"\b(?:top|best|first|largest|biggest)\s+(\d{1,3})\b", q) or re.search(
            r"\b(\d{1,3})\s+(?:products?|items?|customers?|countries|markets?)\b", q
        )
        return max(1, min(int(m.group(1)), 100)) if m else default

    @staticmethod
    def _year(q: str) -> int | None:
        m = re.search(r"\b(19\d\d|20\d\d)\b", q)
        return int(m.group(1)) if m else None

    @staticmethod
    def _country(q: str) -> str | None:
        low = q.lower()
        for c in _countries():
            if re.search(r"\b" + re.escape(c.lower()) + r"\b", low):
                return c
        for alias, country in COUNTRY_ALIASES.items():
            if re.search(r"(?<![\w.])" + re.escape(alias) + r"(?![\w])", low):
                return country
        return None

    @staticmethod
    def _metric(q: str) -> str:
        if re.search(r"\b(invoices?|orders?|order count|purchases|transactions)\b", q) and not re.search(r"\b(revenue|sales value|spend)\b", q):
            return "invoices"
        if re.search(r"\b(units?|quantity|volume|pieces)\b", q):
            return "units"
        if re.search(r"\bgross\b", q):
            return "gross"
        return "net"

    # ------------------------------------------------------------------ main entry
    def plan(self, system: str, user: str, context: PlanContext) -> AgentPlan:
        from app.agent.context import THOSE, ConversationState, is_follow_up

        state = context.state or ConversationState()
        new_text = context.question.strip()
        q = new_text
        if context.clarification:
            # Option labels carry explanations in parentheses; only the metric name matters here.
            q = f"{q} by {re.sub(r'\(.*?\)', '', context.clarification).strip()}"
        follow_up = context.rerun or is_follow_up(new_text)
        root = state.root_question or next((t.question for t in reversed(context.history) if t.sql), None)
        if follow_up and root and root.strip().lower() != new_text.lower():
            q = f"{root} {q}"
        ql = q.lower()
        new_l = new_text.lower()

        if WRITE_WORDS.search(ql):
            return AgentPlan(intent="unsupported", explanation="Request asks to modify data.",
                             unsupported_reason="RetailPilot has read-only access and cannot modify, delete or create data.")
        if UNSUPPORTED_TOPICS.search(ql):
            return AgentPlan(
                intent="unsupported", explanation="The dataset has no field that can answer this.",
                unsupported_reason="The dataset contains invoices (quantities, prices, customers, countries) only. "
                "It has no cost, margin, inventory, marketing or forecast data.",
            )

        # Active filters: conversation state (minus removed ones), overridden by what this question says.
        active = {k: v for k, v in state.filters.items() if k not in state.removed}
        text_for_filters = new_l if follow_up else ql
        if not context.rerun:
            year_new = self._year(text_for_filters)
            if year_new:
                active["year"] = year_new
            country_new = self._country(text_for_filters)
            if country_new:
                active["country"] = country_new
        if THOSE.search(new_l) and state.last_keys:
            col = state.last_keys["column"]
            key = {"stock_code": "stock_codes", "customer_id": "customer_ids", "country": "countries"}[col]
            active[key] = list(state.last_keys["values"])
        if context.comparison:
            active.pop("date_from", None)
            active.pop("date_to", None)

        filters: list[str] = []
        scope = []
        if active.get("year"):
            filters.append(f"invoice_year = {int(active['year'])}")
            scope.append(str(active["year"]))
        if active.get("country"):
            filters.append(f"country = {_sql_str(str(active['country']))}")
            scope.append(str(active["country"]))
        if active.get("date_from"):
            filters.append(f"invoice_date >= TIMESTAMP {_sql_str(str(active['date_from'])[:10])}")
        if active.get("date_to"):
            filters.append(f"invoice_date < TIMESTAMP {_sql_str(str(active['date_to'])[:10])}")
        if active.get("date_from") or active.get("date_to"):
            scope.append(f"{active.get('date_from', 'start')} to {active.get('date_to', 'end')}")
        for key, col in (("stock_codes", "stock_code"), ("customer_ids", "customer_id"), ("countries", "country")):
            vals = [str(v) for v in active.get(key) or [] if re.fullmatch(r"[A-Za-z0-9 ._'-]{1,40}", str(v))]
            if vals:
                filters.append(f"{col} IN ({', '.join(_sql_str(v) for v in vals)})")
                scope.append(f"{len(vals)} {col.replace('_', ' ')}s from the previous result"
                             if THOSE.search(new_l) else f"{len(vals)} {col.replace('_', ' ')}s")
        if active.get("customer_id"):
            filters.append(f"customer_id = {_sql_str(str(active['customer_id']))}")
        n = self._top_n(ql)
        metric = self._metric(ql)
        scope_txt = f" ({', '.join(scope)})" if scope else ""

        def where(*extra: str) -> str:
            parts = list(extra) + filters
            return ("WHERE " + " AND ".join(parts)) if parts else ""

        if context.comparison:
            return self._comparison_plan(ql, context.comparison, filters, n, metric, scope_txt)

        net = "ROUND(SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION')), 2)"
        gross = "ROUND(SUM(line_amount) FILTER (WHERE line_type = 'SALE'), 2)"

        if re.search(r"\b(hours?|hourly|weekdays?|day of (the )?week|weekends?|quarters?|quarterly|seasons?)\b", ql):
            return AgentPlan(
                intent="unsupported", explanation="Grouping not available offline.",
                unsupported_reason="Offline mode cannot group by hour, weekday or quarter. Configure an LLM provider "
                "for this question, or ask by day, month or year.",
            )

        # Day-level questions: "On which date ... maximum revenue?"
        if re.search(r"\b(date|dates|day|days|daily|when)\b", ql):
            code = re.search(r"\b(\d{5}[a-z]{0,2})\b", ql)
            day_net = "ROUND(SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION')), 2)"
            if code or re.search(r"each of the top|best day for each|per product|for each product", ql):
                product_filter = [f"upper(stock_code) = {_sql_str(code.group(1).upper())}"] if code else []
                limit_products = "" if code else f"\n  ORDER BY total_net DESC\n  LIMIT {n}"
                sql = f"""WITH totals AS (
  SELECT stock_code, SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION')) AS total_net
  FROM transactions
  {where("item_type = 'PRODUCT'", *product_filter)}
  GROUP BY stock_code{limit_products}
),
daily AS (
  SELECT stock_code, ANY_VALUE(description) AS description, CAST(invoice_date AS DATE) AS invoice_day,
         {day_net} AS day_net_revenue_gbp
  FROM transactions
  {where("item_type = 'PRODUCT'", "stock_code IN (SELECT stock_code FROM totals)")}
  GROUP BY stock_code, invoice_day
)
SELECT d.stock_code, d.description, d.invoice_day AS best_day, d.day_net_revenue_gbp AS best_day_net_revenue_gbp,
       ROUND(t.total_net, 2) AS total_net_revenue_gbp
FROM daily AS d JOIN totals AS t ON d.stock_code = t.stock_code
QUALIFY ROW_NUMBER() OVER (PARTITION BY d.stock_code ORDER BY d.day_net_revenue_gbp DESC) = 1
ORDER BY total_net_revenue_gbp DESC"""
                who = f"product {code.group(1).upper()}" if code else f"each of the top {n} products by net revenue"
                return AgentPlan(intent="analytical", sql=sql,
                                 explanation=f"Best invoice day for {who}{scope_txt}, by net revenue that day "
                                 "(sales minus cancellations dated the same day).",
                                 business_rules=["net_revenue", "cancellations", "non_product"],
                                 chart=ChartSpec(type="bar", x="description", y=["best_day_net_revenue_gbp"]))
            if re.search(r"\b(products?|items?)\b", ql) and not re.search(r"across all products", ql):
                sql = f"""SELECT stock_code, ANY_VALUE(description) AS description, CAST(invoice_date AS DATE) AS invoice_day,
       {day_net} AS net_revenue_gbp
FROM transactions
{where("item_type = 'PRODUCT'")}
GROUP BY stock_code, invoice_day
ORDER BY net_revenue_gbp DESC
LIMIT {n}"""
                return AgentPlan(intent="analytical", sql=sql,
                                 explanation=f"Top {n} product-and-day combinations{scope_txt} by net revenue. Net is used "
                                 "because some large orders were invoiced and cancelled on the same day.",
                                 business_rules=["net_revenue", "cancellations", "non_product"],
                                 chart=ChartSpec(type="bar", x="description", y=["net_revenue_gbp"]))
            sql = f"""SELECT CAST(invoice_date AS DATE) AS invoice_day,
       {day_net} AS net_revenue_gbp,
       COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE') AS orders
FROM transactions
{where("item_type = 'PRODUCT'")}
GROUP BY invoice_day
ORDER BY net_revenue_gbp DESC
LIMIT {n}"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Top {n} invoice days{scope_txt} by net product revenue across all products.",
                             business_rules=["net_revenue", "orders"],
                             chart=ChartSpec(type="bar", x="invoice_day", y=["net_revenue_gbp"]))

        if re.search(r"\b(postage|shipping|fees?|non[- ]product|adjustments?|manual|discounts?|carriage)\b", ql):
            sql = f"""SELECT item_type,
       COUNT(*) AS lines,
       ROUND(SUM(line_amount), 2) AS amount_gbp
FROM transactions
{where("item_type <> 'PRODUCT'")}
GROUP BY item_type
ORDER BY amount_gbp DESC"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Totals of non-product lines{scope_txt} by category (all line types, signed amounts).",
                             business_rules=["non_product", "currency"],
                             chart=ChartSpec(type="bar", x="item_type", y=["amount_gbp"]))

        # Returns / returned units by product
        if re.search(r"\breturn(s|ed)?\b", ql) and re.search(r"\b(product|item|stock)", ql):
            sql = f"""SELECT stock_code, ANY_VALUE(description) AS description,
       -SUM(quantity) AS returned_units,
       COUNT(DISTINCT invoice) AS return_invoices
FROM transactions
{where("line_type = 'CANCELLATION'", "item_type = 'PRODUCT'")}
GROUP BY stock_code
ORDER BY returned_units DESC
LIMIT {n}"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Top {n} products by returned units{scope_txt}: units on cancellation ('C') invoices of product lines. Stock write-offs are not counted as returns.",
                             business_rules=["returned_units", "cancellations", "negative_quantities", "non_product"],
                             chart=ChartSpec(type="bar", x="description", y=["returned_units"]))

        if re.search(r"\b(cancel\w*|returns?|refund\w*)\b", ql):
            if re.search(r"\b(how many|number of|count)\b", ql):
                sql = f"""SELECT COUNT(DISTINCT invoice) AS cancellation_invoices,
       COUNT(*) AS cancellation_lines,
       -SUM(quantity) AS cancelled_units
FROM transactions
{where("line_type = 'CANCELLATION'")}"""
                expl = f"Counts cancellation invoices (invoice starting with 'C'){scope_txt}; each invoice is one return/cancellation transaction."
            else:
                sql = f"""SELECT ROUND(-SUM(line_amount), 2) AS cancelled_value_gbp,
       COUNT(DISTINCT invoice) AS cancellation_invoices,
       -SUM(quantity) AS cancelled_units
FROM transactions
{where("line_type = 'CANCELLATION'")}"""
                expl = f"Value of all cancellation ('C') invoice lines{scope_txt} as a positive GBP amount, including non-product lines."
            return AgentPlan(intent="analytical", sql=sql, explanation=expl,
                             business_rules=["cancellations", "returned_units", "currency"],
                             chart=ChartSpec(type="none"))

        if re.search(r"\b(missing|unknown|without (a )?customer|no customer|anonymous|guest)\b", ql):
            sql = f"""SELECT CASE WHEN has_customer THEN 'Known customer' ELSE 'Missing customer ID' END AS customer_status,
       COUNT(*) AS lines,
       {net} AS net_revenue_gbp
FROM transactions
{where("item_type = 'PRODUCT'")}
GROUP BY customer_status
ORDER BY customer_status"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Net product revenue{scope_txt} split by whether the line has a customer ID.",
                             business_rules=["missing_customers", "net_revenue"],
                             chart=ChartSpec(type="pie", x="customer_status", y=["net_revenue_gbp"]))

        extreme = bool(re.search(r"\b(max|maximum|highest|peak|largest|biggest|best|record)\b", ql))

        # Largest single orders. Cancellations live on separate 'C' invoices, so each order is checked
        # for later cancellations of the same products by the same customer.
        if extreme and re.search(r"\b(single order|orders?|invoices?|baskets?)\b", ql) \
                and not re.search(r"\b(how many|number of|count)\b", ql):
            sql = f"""WITH orders AS (
  SELECT invoice, ANY_VALUE(customer_id) AS customer_id, ANY_VALUE(country) AS country,
         MIN(invoice_date) AS invoice_date, ROUND(SUM(line_amount), 2) AS order_value_gbp
  FROM transactions
  {where("line_type = 'SALE'", "item_type = 'PRODUCT'")}
  GROUP BY invoice
  ORDER BY order_value_gbp DESC
  LIMIT {n}
)
SELECT o.invoice, o.customer_id, o.country, o.invoice_date, o.order_value_gbp,
       ROUND(COALESCE((SELECT -SUM(c.line_amount) FROM transactions AS c
                       WHERE c.line_type = 'CANCELLATION' AND c.customer_id = o.customer_id
                         AND c.invoice_date >= o.invoice_date
                         AND c.stock_code IN (SELECT s.stock_code FROM transactions AS s WHERE s.invoice = o.invoice)), 0), 2)
         AS later_cancelled_same_products_gbp
FROM orders AS o
ORDER BY o.order_value_gbp DESC"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Top {n} single orders{scope_txt} by product sale value. Cancellations are recorded on "
                             "separate 'C' invoices, so later_cancelled_same_products_gbp shows cancellations of the same "
                             "products by the same customer on or after the order date (it can include other orders, and "
                             "cannot be checked when the customer ID is missing).",
                             business_rules=["orders", "gross_revenue", "cancellations", "missing_customers"],
                             chart=ChartSpec(type="bar", x="invoice", y=["order_value_gbp"]))

        if re.search(r"\b(month|monthly|trend|over time|per month|by month)\b", ql):
            order = "net_revenue_gbp DESC" if extreme else "month"
            sql = f"""SELECT strftime(invoice_month, '%Y-%m') AS month,
       {net} AS net_revenue_gbp,
       COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE') AS orders
FROM transactions
{where("item_type = 'PRODUCT'")}
GROUP BY month
ORDER BY {order}"""
            note = " Ranked from highest to lowest; December 2011 is partial (data ends 9 Dec)." if extreme else ""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Monthly net product revenue{scope_txt} (sales minus cancellations) and order count.{note}",
                             business_rules=["net_revenue", "orders", "period"],
                             chart=ChartSpec(type="bar" if extreme else "line", x="month", y=["net_revenue_gbp"]))

        metric_sql = {
            "net": (net, "net_revenue_gbp", "net revenue"),
            "gross": (gross, "gross_revenue_gbp", "gross revenue"),
            "units": ("SUM(quantity) FILTER (WHERE line_type = 'SALE')", "units_sold", "units sold"),
            "invoices": ("COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE')", "invoices", "number of invoices"),
        }[metric]
        rule_for_metric = {"net": "net_revenue", "gross": "gross_revenue", "units": "units_sold", "invoices": "orders"}[metric]

        if re.search(r"\b(countr(y|ies)|markets?|regions?|nations?)\b", ql):
            sql = f"""SELECT country,
       {metric_sql[0]} AS {metric_sql[1]}
FROM transactions
{where("item_type = 'PRODUCT'")}
GROUP BY country
ORDER BY {metric_sql[1]} DESC
LIMIT {n}"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Top {n} countries by {metric_sql[2]}{scope_txt} over product lines.",
                             business_rules=[rule_for_metric, "non_product"],
                             chart=ChartSpec(type="bar", x="country", y=[metric_sql[1]]))

        if re.search(r"\bcustomers?\b", ql):
            sql = f"""SELECT customer_id,
       ANY_VALUE(country) AS country,
       {metric_sql[0]} AS {metric_sql[1]}
FROM transactions
{where("item_type = 'PRODUCT'", "has_customer")}
GROUP BY customer_id
ORDER BY {metric_sql[1]} DESC
LIMIT {n}"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Top {n} customers by {metric_sql[2]}{scope_txt}. Lines without a customer ID are excluded from this ranking.",
                             business_rules=[rule_for_metric, "missing_customers"],
                             chart=ChartSpec(type="bar", x="customer_id", y=[metric_sql[1]]))

        if re.search(r"\b(products?|items?|sku|stock codes?|sellers?|selling)\b", ql):
            sql = f"""SELECT stock_code,
       ANY_VALUE(description) AS description,
       {metric_sql[0]} AS {metric_sql[1]}
FROM transactions
{where("item_type = 'PRODUCT'")}
GROUP BY stock_code
ORDER BY {metric_sql[1]} DESC
LIMIT {n}"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Top {n} products by {metric_sql[2]}{scope_txt}. Postage, fees and adjustments are excluded.",
                             business_rules=[rule_for_metric, "non_product"],
                             chart=ChartSpec(type="bar", x="description", y=[metric_sql[1]]))

        if re.search(r"\b(average order|aov|order value|basket)\b", ql):
            sql = f"""SELECT ROUND(SUM(line_amount) / COUNT(DISTINCT invoice), 2) AS avg_order_value_gbp,
       COUNT(DISTINCT invoice) AS orders
FROM transactions
{where("line_type = 'SALE'", "item_type = 'PRODUCT'")}"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Average gross product value per order{scope_txt} (cancellations not deducted).",
                             business_rules=["gross_revenue", "orders"], chart=ChartSpec(type="none"))

        if re.search(r"\b(how many|number of|count)\b.*\b(orders?|invoices?)\b", ql):
            sql = f"""SELECT COUNT(DISTINCT invoice) AS orders
FROM transactions
{where("line_type = 'SALE'")}"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Distinct invoices with at least one sale line{scope_txt}; cancellation invoices are not orders.",
                             business_rules=["orders"], chart=ChartSpec(type="none"))

        if re.search(r"\b(units?|quantity)\b", ql):
            sql = f"""SELECT SUM(quantity) AS units_sold
FROM transactions
{where("line_type = 'SALE'", "item_type = 'PRODUCT'")}"""
            return AgentPlan(intent="analytical", sql=sql, explanation=f"Product units on sale lines{scope_txt}.",
                             business_rules=["units_sold"], chart=ChartSpec(type="none"))

        if re.search(r"\b(revenue|sales|turnover|income|takings|sold)\b", ql):
            sql = f"""SELECT {gross} AS gross_revenue_gbp,
       ROUND(-SUM(line_amount) FILTER (WHERE line_type = 'CANCELLATION'), 2) AS product_cancelled_value_gbp,
       {net} AS net_revenue_gbp
FROM transactions
{where("item_type = 'PRODUCT'")}"""
            return AgentPlan(intent="analytical", sql=sql,
                             explanation=f"Total product revenue{scope_txt}: gross, cancellations of product lines, and net "
                             "(GBP). Cancellations of fees and manual adjustments are not product revenue, so the "
                             "all-lines cancelled value on the dashboard is higher.",
                             business_rules=["gross_revenue", "net_revenue", "cancellations"],
                             chart=ChartSpec(type="none"))

        return AgentPlan(
            intent="unsupported", explanation="Question not recognised.",
            unsupported_reason="Offline mode understands a fixed set of question types (revenue, products, "
            "customers, countries, monthly trends, cancellations, returns, missing customers, non-product "
            "lines). Configure an LLM provider for open-ended questions.",
        )

    def _comparison_plan(self, ql: str, cmp, filters: list[str], n: int, metric: str, scope_txt: str) -> AgentPlan:
        (c0, c1), (p0, p1) = cmp.current, cmp.previous
        measure = {
            "units": ("SUM(quantity) FILTER (WHERE line_type = 'SALE' AND {w})", "units"),
            "invoices": ("COUNT(DISTINCT invoice) FILTER (WHERE line_type = 'SALE' AND {w})", "orders"),
            "gross": ("ROUND(SUM(line_amount) FILTER (WHERE line_type = 'SALE' AND {w}), 2)", "gross_revenue_gbp"),
        }.get(metric, ("ROUND(SUM(line_amount) FILTER (WHERE line_type IN ('SALE','CANCELLATION') AND {w}), 2)",
                       "net_revenue_gbp"))
        cur_w = f"invoice_date >= TIMESTAMP '{c0}' AND invoice_date < TIMESTAMP '{c1}'"
        prev_w = f"invoice_date >= TIMESTAMP '{p0}' AND invoice_date < TIMESTAMP '{p1}'"
        lo, hi = min(c0, p0), max(c1, p1)
        base = ["item_type = 'PRODUCT'", f"invoice_date >= TIMESTAMP '{lo}'", f"invoice_date < TIMESTAMP '{hi}'"] + filters
        if re.search(r"\bcustomers?\b", ql):
            dims, group, label = "customer_id, ANY_VALUE(country) AS country", "customer_id", "customer"
            base.append("has_customer")
        elif re.search(r"\b(countr(y|ies)|markets?)\b", ql):
            dims, group, label = "country", "country", "country"
        elif re.search(r"\b(products?|items?|sellers?|selling)\b", ql):
            dims, group, label = "stock_code, ANY_VALUE(description) AS description", "stock_code", "product"
        else:
            dims, group, label = None, None, "total"
        name = measure[1]
        select_dims = f"{dims},\n         " if dims else ""
        group_sql = f"\n  GROUP BY {group}" if group else ""
        order = f"\nORDER BY current_{name} DESC NULLS LAST\nLIMIT {n}" if group else ""
        sql = f"""WITH periods AS (
  SELECT {select_dims}{measure[0].format(w=cur_w)} AS current_{name},
         {measure[0].format(w=prev_w)} AS previous_{name}
  FROM transactions
  WHERE {' AND '.join(base)}{group_sql}
)
SELECT *, ROUND(COALESCE(current_{name}, 0) - COALESCE(previous_{name}, 0), 2) AS change
FROM periods{order}"""
        rule = {"net_revenue_gbp": "net_revenue", "gross_revenue_gbp": "gross_revenue", "units": "units_sold"}.get(name, "orders")
        return AgentPlan(intent="analytical", sql=sql,
                         explanation=f"{name.replace('_gbp', '').replace('_', ' ').capitalize()} by {label}{scope_txt}: "
                         f"current period {c0} to {c1} vs previous period {p0} to {p1} (end dates exclusive). "
                         "Ranked by the current period.",
                         business_rules=[rule, "period"],
                         chart=ChartSpec(type="bar" if group else "none",
                                         x="description" if label == "product" else (group or None),
                                         y=[f"current_{name}", f"previous_{name}"]))
