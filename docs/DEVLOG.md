# Developer log

## 2026-10-22 — v1.1: trust, proactive insights, context

### Audit (before coding)
| Feature | Status found | Evidence |
|---|---|---|
| React/TS/MUI, FastAPI, DuckDB, SQLGlot, Recharts | Implemented | `frontend/src`, `backend/app` |
| DeepSeek API | **Missing** | Only the Anthropic and offline providers existed |
| BGE-large + FAISS retrieval | **Missing** | No embeddings, index or example library anywhere |
| A. Anomaly detection | Missing | |
| B. Contribution analysis | Missing | |
| C. Follow-ups with context | Partial | Last 4 turns sent to the model; no structured state, chips, "those", or comparisons |
| D. Evidence-backed answers | Partial | SQL, rules and timings existed; no filters, date range, grouping, source rows or limitations |
| E. Forecasting | Missing | |
| F. Reliability | Mostly implemented | Validator, read-only DB, timeout and retry existed; no security metric, multi-turn cases or curated example set |
| G. UX | Implemented | Responsive layout and empty/loading/error states existed; extended for the new features |

### Added
- **Providers:** `DeepSeekProvider` (JSON mode, schema-validated; malformed output becomes an error) and `LLM_PROVIDER=auto`.
- **Retrieval:** `agent/examples.py` holds 18 verified SQL examples and 8 notes. `agent/retrieval.py` provides BGE-large-en-v1.5 + FAISS `IndexFlatIP`, with a keyword fallback. It is used for LLM providers only.
- **Context:** `agent/context.py` keeps conversation state in SQLite and extracts filters from the executed SQL's syntax tree. It handles comparison parsing, previous windows and "those" resolution. The planner and prompts are state-aware.
- **Evidence:** `agent/evidence.py` derives filters, date range, grouping, source row count, limitations and verification status.
- **Insights:** `insights/anomalies.py`, `insights/contribution.py` and `insights/forecast.py`.
- **API:** `/api/insights/anomalies[/{id}]`, `/api/insights/contribution`, `/api/insights/forecast`, `/api/conversations` (POST/GET/PATCH), `/api/knowledge/status|search`, and `rerun` on `/api/agent/query`.
- **Benchmark:** cases B16–B20 (multi-turn, ambiguous period, max revenue) and `benchmarks/security.py` (15 probes) with separate rates.
- **UI:** Anomalies page (list, chart, investigation, evidence, "Ask the analyst"); alerts and forecast cards on the Overview; Evidence tab and a chart-to-table link on answers; the context chip bar with remove, re-run and clear; security and multi-turn sections on Benchmark; retrieval, anomaly and forecast settings.
- **Validation fix from user feedback:** "what is the max revenue" used to return totals. It now asks which level to compare (month, day, product, customer, country, or largest order), and the largest-order answer flags later cancellations. Cancelled-value labels now state their scope (all lines vs product lines).

### Verified (commands actually run)
- `python -m pytest -q` → **98 passed**.
- `python -m scripts.run_benchmark` (offline planner) → 20/20 cases, 15/15 security probes.
- `npx tsc -b` → no errors; `npm run build` → success.
- BGE-large + FAISS retrieval was loaded and queried locally: 1024-dim vectors, about 0.7 s per query. A first-start download is needed.
- Playwright with Edge at 390, 768 and 1440 px: Overview, Anomalies, Settings, the investigation flow, an anomaly-seeded analyst conversation, the follow-up chain, and chip removal with re-run. No console errors and no horizontal overflow.

### Not verified
- Live DeepSeek and Anthropic calls (no API keys). Both are tested against local mock servers only.
- A Docker image build.

## 2026-10-22 — v1.2: Dataset Manager, Saved Queries, result cache

### Audit (before coding)
| Requested | Found | Evidence |
|---|---|---|
| Saved Queries library | Missing | Only Query History (`app/history.py`, `HistoryPage.tsx`) |
| Save generated SQL | Partial | SQL tab, Copy SQL and a "Validated" chip in `AnswerCard.tsx`; no save; the caption called validated-but-failed SQL "executed" |
| Dataset Manager / multiple datasets | Missing | One built-in `retail.duckdb`; allowlist hard-coded in `schema_catalog.py`; single connection in `connection.py` |
| Active dataset selector | Missing | |
| Query-result cache | Missing | Only process-level caching of fixed dashboard, anomaly and forecast aggregates |
| Authentication | None | No per-user isolation possible; documented |

### Added
- **Connection layer:** `connection.run_query(..., db_path=)` keeps one locked-down read-only instance per file. `validate_sql(sql, allowed_tables, allowed_columns)` takes per-dataset allowlists; the defaults are unchanged.
- **`app/datasets/`:**
  - `registry.py`: SQLite registry, built-in dataset entry, active-dataset setting.
  - `importer.py`: streaming upload, content checks, XLSX→CSV, header mapping, column profiling, temp-then-rename build.
  - `execution.py`: validate against the dataset schema, then run with the cache.
- **`app/library/`:**
  - `store.py`: saved-query CRUD, typed parameters, compatibility checks.
  - `recommended.py`: curated queries for the built-in dataset, schema-derived queries for imports.
  - `runner.py`: execution and response building.
- **`app/cache.py`:** a bounded TTL cache keyed by SQL, dataset version, parameters and rules version.
- **`app/agent/generic.py`:** prompt, offline planner and flow for imported datasets. `answer_question` dispatches by dataset, binds conversations to a dataset (409 on mismatch), and routes built-in execution through the cache.
- **API (`app/api/workspace_routes.py`):**
  - `/api/datasets`: GET/POST, `/active` GET/PUT, `/{id}` GET/PATCH/DELETE, `/{id}/preview`, `/{id}/reimport`.
  - `/api/saved-queries`: GET/POST, `/{id}` GET/PATCH/DELETE, `/{id}/duplicate`, `/{id}/run`.
  - `/api/recommended-queries/{id}/run`.
  - `/api/cache`: GET/DELETE.
  - `dataset_id` on `/api/agent/query`.
  - An optional `error.details` on errors.
  - `dataset_id`/`dataset_name` columns on history (additive migration).
- **UI:**
  - Datasets page: upload with progress, list, schema, preview, findings, set active, rename, re-import, delete with confirmation.
  - Saved Queries page: recommended and saved queries, search and filters, run with parameters, compatibility, other-dataset confirmation, adapt, edit (update or copy), duplicate, delete.
  - Analyst: dataset selector with a confirmed switch, Save query dialog, `?ask=` prefill.
  - Answer card: dataset chip, cache chip, SQL stages Proposed → Validated → Executed, Save query button, CSV filename includes the dataset.
  - Header: active-dataset chip. History: dataset name.

### Bugs found while building
- DuckDB `TRY_CAST('120.50' AS BIGINT)` returns 121 (rounding), so a decimal column would have been typed as integer and changed. Integer detection now uses a strict digit regex; covered by a test.
- DuckDB's keyword list includes unreserved words (`name`, `day`), so ordinary columns were being renamed. Only reserved keywords are renamed now.
- Doubled braces in recommended-query templates rendered as DuckDB struct literals. Templates are fixed, and leftover braces are now rejected.

### Verified (commands actually run)
- `python -m pytest -q` → **130 passed**: 98 previous + 32 new in `tests/test_workspace.py`.
- `python -m scripts.run_benchmark` (offline planner) → 20/20 cases, 15/15 security probes.
- `npx tsc -b` → no errors; `npm run build` → success.
- Playwright with Edge at 1440 px and 390 px against the running app:
  - upload a CSV, then view findings and preview, then set it active;
  - ask a question, then save the query;
  - run it twice (second run shown "From cache");
  - switch to the built-in dataset (query shown incompatible), then run a parameterised recommended query (3 rows);
  - delete the dataset (dialog mentions affected saved queries).
  - No console errors and no horizontal overflow.

### Not verified / limitations
- No authentication, so all state is shared application-wide.
- No frontend unit-test framework; the UI was verified with Playwright scripts that are not committed.
- Live LLM providers were still not exercised (no keys).
- Docker image not built.
