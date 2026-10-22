"""Initialise / verify local databases.

Usage (from backend/):  python -m scripts.init_db

* Verifies data/retail.duckdb exists, opens it read-only and checks the schema matches the
  allowlist the agent is given (fails loudly if the preparation script needs re-running).
* Creates the app-state SQLite file (query history, benchmark runs) if missing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import history  # noqa: E402
from app.benchmarks import runner  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database.connection import dataset_available, fetch_metadata, run_query  # noqa: E402
from app.database.schema_catalog import ALLOWED_COLUMNS, ALLOWED_TABLE  # noqa: E402


def main() -> int:
    settings = get_settings()
    history.list_history(limit=1)  # creates query_history table
    runner.last_completed_run()  # creates benchmark_runs table
    print(f"App state database ready: {settings.app_db_path}")

    if not dataset_available():
        print(f"Dataset database missing: {settings.duckdb_path}\nRun: python -m scripts.prepare_data --excel PATH")
        return 1
    cols = {r[0] for r in run_query(
        "SELECT column_name FROM information_schema.columns WHERE table_name = ?", [ALLOWED_TABLE]).rows}
    missing = ALLOWED_COLUMNS - cols
    if missing:
        print(f"Schema mismatch, missing columns {sorted(missing)}. Re-run scripts.prepare_data.")
        return 1
    meta = fetch_metadata()
    print(f"Dataset OK: {meta['row_count']:,} rows, {meta['min_invoice_date']} .. {meta['max_invoice_date']} "
          f"(prepared {meta['prepared_at']}, {meta.get('overlap_rows_removed', 0):,} worksheet-overlap rows removed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
