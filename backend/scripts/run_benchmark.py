"""Run the benchmark suite from the command line.

Usage (from backend/):  python -m scripts.run_benchmark [--json]
Uses the configured provider (LLM_PROVIDER / ANTHROPIC_API_KEY from backend/.env).
Exit code 0 when every case passes, 1 otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.benchmarks.runner import _save_run, run_sync  # noqa: E402
from app.database.connection import dataset_available  # noqa: E402


def main() -> int:
    if not dataset_available():
        print("Dataset not loaded: the benchmark cannot run. Run scripts.prepare_data first.")
        return 2
    run = run_sync()
    if "--json" in sys.argv:
        print(json.dumps(run, indent=2, default=str))
    else:
        agent = f"{run['provider']} / {run['model']}" + ("" if run["is_llm"] else "  (NOT an LLM)")
        print(f"Agent under test: {agent}\n")
        for r in run["results"]:
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"[{mark}] {r['id']} {r['question']}\n       {r['reason']}")
        print()
        for k, v in (run["summary"] or {}).items():
            pct = "n/a" if v["rate"] is None else f"{v['rate'] * 100:.1f}%"
            print(f"{k:24s} {v['passed']}/{v['total']}  {pct}")
    if run["status"] == "completed":
        _save_run(run)
    return 0 if run["summary"] and run["summary"]["overall"]["passed"] == run["summary"]["overall"]["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
