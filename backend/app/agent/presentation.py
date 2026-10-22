"""Chart selection and deterministic answer summaries computed from the actual result rows.

The summary never contains numbers the query did not return.
"""
from __future__ import annotations

import re
from typing import Any

from app.agent.models import ChartSpec

NUMERIC_TYPES = re.compile(r"^(BIGINT|INTEGER|HUGEINT|SMALLINT|TINYINT|UBIGINT|UINTEGER|DOUBLE|FLOAT|REAL|DECIMAL.*)$", re.I)
TEMPORAL_HINT = re.compile(r"(month|date|year|day|week|quarter|period)", re.I)
MONEY_HINT = re.compile(r"(gbp|revenue|amount|value|sales|price|spend)", re.I)


def is_numeric(col_type: str) -> bool:
    return bool(NUMERIC_TYPES.match(col_type.strip()))


def choose_chart(suggested: ChartSpec | None, columns: list[str], types: list[str], rows: list[list[Any]]) -> dict | None:
    if not rows or len(columns) < 2:
        return None
    numeric = [c for c, t in zip(columns, types) if is_numeric(t)]
    non_numeric = [c for c, t in zip(columns, types) if not is_numeric(t)]

    if suggested and suggested.type == "none":
        return None
    if suggested and suggested.type != "none" and suggested.x in columns:
        ys = [y for y in suggested.y if y in numeric and y != suggested.x]
        if ys:
            ctype = suggested.type
            if ctype == "pie" and len(rows) > 8:
                ctype = "bar"
            return {"type": ctype, "x": suggested.x, "y": ys[:2], "title": suggested.title}

    # Automatic choice from the result shape.
    if len(rows) < 2 or not numeric:
        return None
    temporal = [c for c, t in zip(columns, types) if "DATE" in t.upper() or "TIME" in t.upper() or TEMPORAL_HINT.search(c)]
    x = temporal[0] if temporal else (non_numeric[-1] if non_numeric else None)
    if x is None:
        return None
    ys = [c for c in numeric if c != x and not re.search(r"(_id|code|rank)$", c)]
    if not ys:
        return None
    if temporal:
        return {"type": "line", "x": x, "y": ys[:2], "title": None}
    if len(rows) <= 50:
        return {"type": "bar", "x": x, "y": ys[:1], "title": None}
    return None


def label(column: str) -> str:
    return re.sub(r"_gbp$", "", column).replace("_", " ")


def fmt_value(column: str, value: Any) -> str:
    if value is None:
        return "no value"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        if MONEY_HINT.search(column) and not re.search(r"(units|count|lines|invoices|orders)", column, re.I):
            return f"{'-' if value < 0 else ''}£{abs(value):,.2f}"
        if isinstance(value, float) and not value.is_integer():
            return f"{value:,.2f}"
        return f"{int(value):,}"
    return str(value)


def summarize(columns: list[str], types: list[str], rows: list[list[Any]], truncated: bool) -> str:
    if not rows:
        return "The query ran successfully but returned no rows for these filters."
    if len(rows) == 1:
        parts = [f"{label(c)}: {fmt_value(c, v)}" for c, v in zip(columns, rows[0])]
        return "; ".join(parts) + "."
    numeric_idx = [i for i, t in enumerate(types) if is_numeric(t) and not re.search(r"(_id|code)$", columns[i])]
    label_idx = [i for i, t in enumerate(types) if not is_numeric(t)]
    head = f"Returned {len(rows):,}{'+' if truncated else ''} rows."
    if numeric_idx and label_idx:
        li = label_idx[-1] if columns[label_idx[0]].endswith(("_id", "code")) and len(label_idx) > 1 else label_idx[0]
        if columns[label_idx[0]] in ("customer_id",):
            li = label_idx[0]
        named = [i for i in label_idx if columns[i] in ("description", "product", "product_name", "name")]
        if named:
            li = named[0]
        money_idx = [i for i in numeric_idx if MONEY_HINT.search(columns[i])]
        ni = money_idx[0] if money_idx else numeric_idx[0]
        first = rows[0]
        head += f" First row: {first[li]} with {label(columns[ni])} {fmt_value(columns[ni], first[ni])}."
        if len(rows) <= 60 and all(isinstance(r[ni], (int, float)) for r in rows if r[ni] is not None):
            vals = [r[ni] for r in rows if r[ni] is not None]
            if vals and MONEY_HINT.search(columns[ni]):
                head += f" Total across returned rows: {fmt_value(columns[ni], sum(vals))}."
    return head


def result_caveats(columns: list[str], rows: list[list[Any]]) -> list[str]:
    """Warnings derived from the returned rows themselves (never invented)."""
    out: list[str] = []
    if "later_cancelled_same_products_gbp" in columns and rows:
        i = columns.index("later_cancelled_same_products_gbp")
        v = columns.index("order_value_gbp") if "order_value_gbp" in columns else None
        flagged = [r for r in rows if isinstance(r[i], (int, float)) and r[i] > 0]
        if flagged:
            first = rows[0]
            if isinstance(first[i], (int, float)) and first[i] > 0 and v is not None:
                out.append(f"Warning: the top order ({first[0]}) was followed by {fmt_value('gbp', first[i])} of "
                           f"cancellations of the same products by the same customer"
                           + (", i.e. it was cancelled in full." if abs(first[i] - first[v]) < 0.01 else "."))
            out.append(f"{len(flagged)} of {len(rows)} orders have later cancellations of the same products.")
    return out
