"""Convert the UCI Online Retail II Excel workbook into a local DuckDB database.

Usage (from the backend/ directory):
    python -m scripts.prepare_data [--excel PATH_TO_online_retail_II.xlsx]

Steps:
1. Read both sheets of the workbook ("Year 2009-2010", "Year 2010-2011"), caching the raw
   rows as Parquet so subsequent runs are fast.
2. Normalise types (invoice / stock code as text, customer id as text without ".0").
3. Remove the second worksheet's copy of the period both worksheets contain (2010-12-01 ..
   2010-12-09), after verifying it is an exact duplicate. This is the only removal; it is
   recorded in dataset_metadata.
4. Classify every row (line_type, item_type, has_customer). No other rows are discarded.
5. Write table `transactions` plus a `dataset_metadata` table to data/retail.duckdb.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.database.business_rules import (  # noqa: E402
    classify_item_type,
    classify_line_type,
)

RAW_COLUMNS = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]


def read_workbook(excel_path: Path, cache_path: Path) -> pd.DataFrame:
    if cache_path.exists() and cache_path.stat().st_mtime >= excel_path.stat().st_mtime:
        print(f"Using cached raw parquet: {cache_path}")
        return pd.read_parquet(cache_path)
    print(f"Reading workbook {excel_path} (this can take several minutes)...")
    t0 = time.time()
    sheets = pd.read_excel(excel_path, sheet_name=None, dtype={"Invoice": str, "StockCode": str})
    frames = []
    for name, df in sheets.items():
        missing = [c for c in RAW_COLUMNS if c not in df.columns]
        if missing:
            raise SystemExit(f"Sheet {name!r} is missing expected columns {missing}. Is this the Online Retail II workbook?")
        df = df[RAW_COLUMNS].copy()
        df["source_sheet"] = name
        df["source_row"] = range(2, len(df) + 2)  # Excel row number (header is row 1)
        frames.append(df)
        print(f"  sheet {name!r}: {len(df):,} rows")
    raw = pd.concat(frames, ignore_index=True)
    raw["Customer ID"] = raw["Customer ID"].astype("Float64")
    for col in ("Invoice", "StockCode", "Description", "Country"):
        # A few cells are stored as numbers in Excel; keep text columns as text (NULLs preserved).
        raw[col] = raw[col].map(lambda v: None if pd.isna(v) else str(v)).astype("string")
    raw.to_parquet(cache_path, index=False)
    print(f"Read workbook in {time.time() - t0:.0f}s; cached to {cache_path}")
    return raw


def transform(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame()
    df["invoice"] = raw["Invoice"].astype(str).str.strip()
    df["stock_code"] = raw["StockCode"].astype(str).str.strip()
    df["description"] = raw["Description"].astype("string").str.strip()
    df["quantity"] = raw["Quantity"].astype("int64")
    df["invoice_date"] = pd.to_datetime(raw["InvoiceDate"])
    df["unit_price"] = raw["Price"].astype("float64")
    cust = raw["Customer ID"]
    df["customer_id"] = cust.map(lambda v: None if pd.isna(v) else str(int(v))).astype("string")
    df["country"] = raw["Country"].astype("string").str.strip()
    df["source_sheet"] = raw["source_sheet"]
    df["source_row"] = raw["source_row"].astype("int64")

    df["line_amount"] = (df["quantity"] * df["unit_price"]).round(4)
    df["line_type"] = [
        classify_line_type(i, q, p) for i, q, p in zip(df["invoice"], df["quantity"], df["unit_price"])
    ]
    item_map = {code: classify_item_type(code) for code in df["stock_code"].unique()}
    df["item_type"] = df["stock_code"].map(item_map)
    df["is_cancellation"] = df["line_type"] == "CANCELLATION"
    df["has_customer"] = df["customer_id"].notna()
    df["invoice_month"] = df["invoice_date"].dt.to_period("M").dt.to_timestamp().dt.date
    df["invoice_year"] = df["invoice_date"].dt.year.astype("int32")
    return df


OVERLAP_KEYS = ["invoice", "stock_code", "description", "quantity", "invoice_date", "unit_price", "customer_id", "country"]


def remove_sheet_overlap(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """The two worksheets overlap: both contain 2010-12-01 .. 2010-12-09.

    Loading both copies would double count that week. We verify that the second sheet's rows in
    the overlapping window are an exact multiset copy of the first sheet's rows, then keep only
    the first copy. The number of removed rows is recorded in dataset_metadata.
    """
    sheets = list(dict.fromkeys(df["source_sheet"]))
    if len(sheets) < 2:
        return df, {"overlap_rows_removed": 0}
    first, second = sheets[0], sheets[1]
    window_start = df.loc[df["source_sheet"] == second, "invoice_date"].min()
    window_end = df.loc[df["source_sheet"] == first, "invoice_date"].max()
    if window_start > window_end:
        return df, {"overlap_rows_removed": 0}
    in_window = (df["invoice_date"] >= window_start) & (df["invoice_date"] <= window_end)
    a = df[in_window & (df["source_sheet"] == first)]
    b = df[in_window & (df["source_sheet"] == second)]
    counts_a = a[OVERLAP_KEYS].astype(str).value_counts()
    counts_b = b[OVERLAP_KEYS].astype(str).value_counts()
    if not counts_a.equals(counts_b.reindex(counts_a.index)) or len(counts_a) != len(counts_b):
        raise SystemExit("Sheets overlap but the overlapping rows differ; refusing to deduplicate silently.")
    kept = df.drop(index=b.index)
    info = {
        "overlap_window_start": str(window_start),
        "overlap_window_end": str(window_end),
        "overlap_rows_removed": int(len(b)),
        "overlap_sheet_removed": second,
        "source_rows_total": int(len(df)),
    }
    return kept, info


def write_duckdb(df: pd.DataFrame, db_path: Path, excel_path: Path, overlap_info: dict) -> None:
    tmp_path = db_path.with_suffix(".tmp.duckdb")
    if tmp_path.exists():
        tmp_path.unlink()
    con = duckdb.connect(str(tmp_path))
    con.register("df_view", df)
    con.execute(
        """
        CREATE TABLE transactions AS
        SELECT
            invoice::VARCHAR            AS invoice,
            stock_code::VARCHAR         AS stock_code,
            description::VARCHAR        AS description,
            quantity::BIGINT            AS quantity,
            invoice_date::TIMESTAMP     AS invoice_date,
            invoice_month::DATE         AS invoice_month,
            invoice_year::INTEGER       AS invoice_year,
            unit_price::DOUBLE          AS unit_price,
            line_amount::DOUBLE         AS line_amount,
            customer_id::VARCHAR        AS customer_id,
            has_customer::BOOLEAN       AS has_customer,
            country::VARCHAR            AS country,
            line_type::VARCHAR          AS line_type,
            item_type::VARCHAR          AS item_type,
            is_cancellation::BOOLEAN    AS is_cancellation,
            source_sheet::VARCHAR       AS source_sheet,
            source_row::BIGINT          AS source_row
        FROM df_view
        ORDER BY invoice_date, invoice, source_row
        """
    )
    con.unregister("df_view")
    stats = con.execute(
        "SELECT COUNT(*), MIN(invoice_date), MAX(invoice_date) FROM transactions"
    ).fetchone()
    meta = {
        "source_file": excel_path.name,
        "source_file_size_bytes": excel_path.stat().st_size,
        "prepared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "row_count": int(stats[0]),
        "min_invoice_date": str(stats[1]),
        "max_invoice_date": str(stats[2]),
        **overlap_info,
    }
    dup = con.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT (invoice, stock_code, description, quantity, invoice_date, "
        "unit_price, customer_id, country)) FROM transactions"
    ).fetchone()[0]
    meta["exact_duplicate_rows_retained"] = int(dup)
    con.execute("CREATE TABLE dataset_metadata (key VARCHAR, value VARCHAR)")
    con.executemany("INSERT INTO dataset_metadata VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()])
    con.close()
    if db_path.exists():
        db_path.unlink()
    tmp_path.rename(db_path)
    print(json.dumps(meta, indent=2))


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--excel", type=Path, default=settings.source_excel_path)
    args = parser.parse_args()
    excel_path: Path = args.excel
    if not excel_path.exists():
        raise SystemExit(
            f"Workbook not found at {excel_path}.\n"
            "Download 'online_retail_II.xlsx' from the UCI page "
            "https://archive.ics.uci.edu/dataset/502/online+retail+ii, unzip it, and pass --excel PATH."
        )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    raw = read_workbook(excel_path, settings.data_dir / "online_retail_ii_raw.parquet")
    df = transform(raw)
    df, overlap_info = remove_sheet_overlap(df)
    print(f"Sheet overlap: {overlap_info}")
    print(df["line_type"].value_counts().to_string())
    print(df["item_type"].value_counts().to_string())
    write_duckdb(df, settings.duckdb_path, excel_path, overlap_info)
    print(f"DuckDB database written to {settings.duckdb_path}")


if __name__ == "__main__":
    main()
