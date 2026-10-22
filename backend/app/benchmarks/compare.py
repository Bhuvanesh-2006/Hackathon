"""Order-insensitive, tolerance-based comparison of agent results against reference results."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

DATE_LIKE = re.compile(r"^(\d{4})-(\d{2})(-\d{2})?([ T]00:00:00)?$")


@dataclass
class Comparison:
    passed: bool
    reason: str


def norm_key(v: Any) -> str:
    s = "" if v is None else str(v).strip()
    m = DATE_LIKE.match(s)
    if m and (m.group(3) in (None, "-01")):
        return f"{m.group(1)}-{m.group(2)}"
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    return s.lower()


def num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    try:
        return float(str(v).replace(",", "").replace("£", ""))
    except ValueError:
        return None


def close(a: float, b: float, rel: float, abs_: float) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)


def fmt(x: float) -> str:
    return f"{x:,.2f}"


def compare_scalar(expected: dict[str, Any], columns: list[str], rows: list[list[Any]], value_columns: list[str],
                   rel: float, abs_: float) -> Comparison:
    if not rows:
        return Comparison(False, "Agent returned no rows; a single value was expected.")
    cells = [num(v) for row in rows[:5] for v in row]
    cells = [c for c in cells if c is not None]
    notes = []
    for col in value_columns:
        exp_v = num(expected.get(col))
        if exp_v is None:
            return Comparison(False, f"Reference value '{col}' is empty.")
        if any(close(c, exp_v, rel, abs_) for c in cells):
            continue
        if any(close(abs(c), abs(exp_v), rel, abs_) for c in cells):
            notes.append(f"{col} matches in magnitude but with the opposite sign")
            continue
        got = ", ".join(fmt(c) for c in cells[:4]) or "no numeric values"
        return Comparison(False, f"Expected {col} = {fmt(exp_v)}; agent returned {got}.")
    return Comparison(True, "Value matches reference" + (f" ({'; '.join(notes)})" if notes else "") + ".")


def compare_keyed(expected_cols: list[str], expected_rows: list[list[Any]], columns: list[str], rows: list[list[Any]],
                  key_columns: list[str], value_columns: list[str], top_n: int | None, rel: float, abs_: float) -> Comparison:
    if not rows:
        return Comparison(False, "Agent returned no rows.")
    agent_rows = rows[:top_n] if top_n else rows
    best_reason = "No result column contains the expected keys."
    for key_col in key_columns:
        ki = expected_cols.index(key_col)
        expected_keys = [norm_key(r[ki]) for r in expected_rows]
        expected_set = set(expected_keys)
        for aj, _acol in enumerate(columns):
            agent_keys = [norm_key(r[aj]) for r in agent_rows]
            overlap = expected_set & set(agent_keys)
            if len(overlap) < max(1, len(expected_set) // 2):
                continue
            missing = [k for k in expected_keys if k not in agent_keys]
            extra = [k for k in agent_keys if k not in expected_set]
            if top_n and (missing or extra):
                best_reason = (f"Top-{top_n} set differs from reference. Missing: {', '.join(missing[:3]) or '-'}; "
                               f"unexpected: {', '.join(extra[:3]) or '-'}.")
                continue
            if missing:
                best_reason = f"Missing expected keys: {', '.join(missing[:5])}."
                continue
            # Find a numeric column matching every expected value.
            for val_col in value_columns:
                vi = expected_cols.index(val_col)
                exp_by_key = {norm_key(r[ki]): num(r[vi]) for r in expected_rows}
                agent_by_key: dict[str, list[Any]] = {norm_key(r[aj]): r for r in agent_rows}
                matched_col = None
                first_mismatch = None
                for ci in range(len(columns)):
                    if ci == aj:
                        continue
                    ok = True
                    for k, ev in exp_by_key.items():
                        av = num(agent_by_key[k][ci])
                        if ev is None or av is None or not close(av, ev, rel, abs_):
                            ok = False
                            if first_mismatch is None and av is not None and ev is not None:
                                first_mismatch = f"{k}: expected {fmt(ev)}, got {fmt(av)} (column {columns[ci]})"
                            break
                    if ok:
                        matched_col = columns[ci]
                        break
                if matched_col is None:
                    best_reason = f"Keys match but values differ. {first_mismatch or 'No numeric column matches.'}"
                    break
            else:
                return Comparison(True, f"All {len(expected_set)} keyed rows match reference (key '{columns[aj]}').")
    return Comparison(False, best_reason)
