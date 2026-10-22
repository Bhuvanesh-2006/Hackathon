# RetailPilot API

Base path `/api`. All responses are JSON. Errors use this shape:

```json
{ "error": { "code": "invalid_question", "message": "Please enter a question." } }
```

Status codes: `400` invalid input, `404` not found, `422` request validation failed, `503` dataset not loaded, `500` unexpected (no stack trace). Interactive docs are served at `/docs` (Swagger UI).

---

## GET /api/health
Database and LLM status. Never includes credentials.
```json
{ "status": "ok", "version": "1.0.0",
  "database": { "loaded": true, "read_only": true, "status": "connected", "row_count": 1044848, "prepared_at": "..." },
  "llm": { "provider": "anthropic", "model": "claude-opus-5-5", "is_llm": true, "configured": true } }
```

## GET /api/dashboard/summary?year=2011&country=Germany
Both parameters are optional; `year` is 2009–2011. Returns `kpis` (gross_revenue, net_revenue, cancelled_value, orders, units_sold, cancellation_invoices, returned_units, customers, unattributed_net_revenue, lines), `revenue_trend[]`, `top_products[]`, `sales_by_country[]`, `line_types[]`, `dataset` metadata, `recent_queries[]` and `filter_options`. All values come from trusted hand-written SQL.

## GET /api/dataset/schema
Returns the column list with types, descriptions, missing counts and approximate distinct counts, plus line/item-type breakdowns, cancellation and missing-customer statistics, business rules and metadata.

## GET /api/dataset/preview
Query parameters: `limit` (1–200), `offset`, `line_type`, `item_type`, `country`, `search`. All are parameterised.
```json
{ "columns": ["invoice", "..."], "rows": [["489434", "..."]], "total": 19165, "limit": 25, "offset": 0 }
```

## POST /api/agent/query
Request:
```json
{ "question": "Who are our best customers?", "conversation_id": null, "clarification_response": null }
```
To answer a clarifying question, send `clarification_response` with the same `conversation_id`. The `question` may be empty; the original question is recovered from the conversation. Follow-up questions such as "now only for Germany" reuse the conversation context.

Response:
```json
{
  "query_id": "…", "conversation_id": "…", "created_at": "…", "question": "…",
  "status": "success | empty | clarification | unsupported | rejected | error",
  "answer": "Returned 10 rows. First row: 18102 with net revenue £578,408.64. …",
  "explanation": "Top 10 customers by net revenue. Lines without a customer ID are excluded…",
  "sql": "SELECT … (exact validated SQL that was executed)",
  "columns": [{ "name": "customer_id", "type": "VARCHAR" }, { "name": "net_revenue_gbp", "type": "DOUBLE" }],
  "rows": [["18102", 578408.64]], "row_count": 10, "truncated": false,
  "chart": { "type": "bar", "x": "customer_id", "y": ["net_revenue_gbp"] },
  "clarification": null,
  "business_rules": [{ "id": "net_revenue", "name": "…", "definition": "…" }],
  "error": null,
  "execution": { "provider": "anthropic", "model": "claude-opus-5-5", "is_llm": true, "attempts": 1,
                 "validated": true, "regenerated": false, "db_ms": 28.1, "total_ms": 2140.5,
                 "max_rows": 1000, "timeout_s": 10 }
}
```
When `status = "clarification"`, `clarification` is `{ "question": "...", "options": ["..."], "source": "ambiguity_rules | model" }`.
`rejected` means the generated SQL failed validation twice and was not executed. `error.code` is one of `llm_error`, `sql_rejected`, `execution_error`, `timeout`, `dataset_unavailable`.

## GET /api/history?limit=50&offset=0&status=success&search=revenue
`{ "items": [{ "id", "conversation_id", "created_at", "question", "clarification", "status", "duration_ms", "sql", "summary", "row_count", "provider" }], "total": 12 }`

## GET /api/history/{query_id}
Returns the stored full response, in the same shape as POST /api/agent/query, with up to 200 rows.

## DELETE /api/history
Clears the history. Returns `{ "deleted": 12 }`.

## GET /api/benchmarks
Returns `{ cases[], dataset_loaded, llm, current, last_completed }`. A run contains `status`, `progress {done,total,current}`, `results[]` (per case: `passed`, `executed`, `reason`, `expected_display`, `reference_sql`, `agent_sql`, `agent_status`, `agent_rows`) and `summary { overall, result_match, sql_execution, clarification, unsupported_and_empty }`. Each summary entry has the form `{passed,total,rate}`.

## POST /api/benchmarks/run
Starts a background run and returns `202 { "run_id", "status": "running", "progress" }`. Poll `GET /api/benchmarks` for progress. Returns `503` if the dataset is not loaded.

## GET /api/settings
Non-secret configuration: dataset and source, database mode, LLM provider and model, query limits, benchmark tolerances, business rules and demo questions.

---

## v1.1 additions

### POST /api/agent/query (new fields)
The request also accepts `"rerun": true` (with `conversation_id` and an empty question): it re-runs the conversation's base question with the current filters.
The response also contains:
- `context`: `{ filters: [{field, label}], removed: [...], comparison: {current, previous, label} | null, previous_result: {column, count} | null, root_question, topic }`. These are the filters actually applied, extracted from the executed SQL.
- `evidence`: `{ filters, date_range: {from, to, source}, comparison, grouping: [...], source_row_count, source_row_note, result_rows, metric_definitions, limitations: [...], verification: {validated, executed, independently_verified: false, note}, retrieval: {backend, examples, notes} | null }`.
- `rerun`: boolean.

### Conversations
- `POST /api/conversations` `{ "anomaly_id": "net_revenue-2011-09-19" }` → `201 { conversation_id, context }`. Starts a conversation scoped to the anomaly week.
- `GET /api/conversations/{id}` → `{ conversation_id, context }`.
- `PATCH /api/conversations/{id}` `{ "remove": ["country" | "year" | "date_range" | "stock_codes" | "customer_id"], "clear_filters": false, "clear_comparison": false }` → `{ conversation_id, context }`.

### Insights
- `GET /api/insights/anomalies?metric=net_revenue&severity=high` → `{ config, method, metrics, anomalies: [Anomaly], skipped_weeks, weeks_analysed, series: {metric: [{week_start, trading_days, value}]}, sql, disclaimer }`.
  An `Anomaly` contains `id, metric, metric_label, unit, kind (spike|drop), severity (high|medium), period_start, period_end, trading_days, observed, expected, deviation, deviation_pct, robust_z, baseline_weeks, baseline_per_day, seasonal {last_year_week, last_year_observed, last_year_robust_z, recurring} | null, evidence [{week_start, trading_days, value, per_day, role}], notes`.
- `GET /api/insights/anomalies/{id}` → one anomaly, or `404`.
- `POST /api/insights/contribution` `{ "anomaly_id": "...", "dimension": "product|country|customer|weekday", "top_n": 10 }`, or `{ "metric", "dimension", "current": {start, end}, "comparison": [{start, end}] }` (end dates exclusive). Returns `{ totals {current, comparison, change}, rows [{category, name, current_value, comparison_value, change, share_of_change_pct, only_in}], current_window, comparison_windows, comparison_trading_days, scale, reconciled, positive_contributors, negative_contributors, calculation, sql, disclaimer }`. A non-additive metric/dimension pair returns `400 invalid_analysis`.
- `GET /api/insights/forecast` → `{ available, history, partial_month, train_period, holdout_period, evaluation [{method, mae, mape_pct, max_ape_pct, holdout}], selected_method, improvement_vs_naive_pct, forecast [{month, forecast, low, high}], range_note, limitations, sql }`.

### Knowledge / retrieval
- `GET /api/knowledge/status` → retrieval backend, state, model, vector dimension, document counts.
- `GET /api/knowledge/search?q=...` → `{ backend, examples: [{id, question, sql, score}], notes: [{id, text, score}] }`.

### Benchmarks
Runs now also include `security: [{id, name, kind (sql|question), passed, status, reason}]`. The summary adds `multi_turn` and `security` rates. Cases may carry `setup` (earlier turns) and `clarification`.

---

## v1.2 additions (datasets, saved queries, cache)

Errors may now include `error.details`; for example, a 409 from a saved-query run carries `details.compatibility`.

### Datasets
| Method & path | Purpose |
|---|---|
| `GET /api/datasets` | `{ items: [Dataset], active_id, limits: {max_upload_mb, formats} }`. The built-in dataset is always first (`kind: "builtin"`). |
| `POST /api/datasets` (multipart: `file`, `name`, optional `description`) | Import CSV/XLSX → `201 Dataset`. `409` duplicate name, `413` too large, `415` unsupported type, `422 import_failed` (the dataset is recorded with `status: "failed"` and its errors). |
| `GET /api/datasets/{id}` | One dataset. |
| `GET /api/datasets/{id}/preview?limit=50` | `{ columns, column_types, rows }` (max 200 rows). |
| `PATCH /api/datasets/{id}` `{name?, description?}` | Rename (not allowed for the built-in dataset → 403). |
| `POST /api/datasets/{id}/reimport` (multipart `file`) | Replace the data with a new version. A failed re-import → `422`, and the previous version stays active. |
| `DELETE /api/datasets/{id}` | `{ deleted, saved_queries_unavailable, cache_entries_dropped, active_id }`. |
| `GET /api/datasets/active`, `PUT /api/datasets/active {dataset_id}` | Read or set the application-wide active dataset (`409` if not ready). |

A `Dataset` has `id, name, description, kind, source_filename, file_format, status (ready|failed|importing|not_loaded), version, row_count, column_count, columns [{name, original_name, type, role, missing, missing_pct, approx_distinct, samples, notes}], findings, errors, support, table, created_at, imported_at, updated_at, file_size_bytes, saved_query_count`. No filesystem paths are returned.

### Querying a dataset
`POST /api/agent/query` accepts `dataset_id`. If it is omitted, the conversation's dataset is used, else the built-in one. Responses include `dataset {id, name, version, kind}` and `execution.cache {hit, cached_at, age_seconds, dataset_version, ttl_seconds}`. If a conversation started on another dataset, the request fails with `409 dataset_mismatch`.

### Saved queries
| Method & path | Purpose |
|---|---|
| `GET /api/saved-queries?dataset_id=&search=&category=&tag=&scope=all|dataset` | `{ dataset, recommended: [RecommendedQuery], items: [SavedQuery + compatibility], categories }`. Compatibility is evaluated against `dataset_id`. |
| `POST /api/saved-queries` | `{title, question?, sql, description?, category, tags[], parameters[{name, type, default, description}], dataset_id}` → `201`. `409 duplicate_title`, `422` invalid SQL or parameters. |
| `GET /api/saved-queries/{id}?dataset_id=` | One saved query with compatibility. |
| `PATCH /api/saved-queries/{id}` | Partial update (rename, edit SQL; SQL is revalidated). |
| `POST /api/saved-queries/{id}/duplicate {title?}` | Copy → `201`. |
| `DELETE /api/saved-queries/{id}` | Delete. |
| `POST /api/saved-queries/{id}/run {dataset_id, parameters{}, allow_other_dataset=false, use_cache=true}` | Revalidates and runs; returns an analyst-style response with `saved_query`. `409 incompatible_query` or `409 confirmation_required` (other dataset). |
| `POST /api/recommended-queries/{id}/run {dataset_id, parameters{}}` | Run a recommended query for that dataset. |

`compatibility.status` is one of `compatible`, `other_dataset`, `incompatible`, `unavailable`, plus `reason` and `missing_columns`.

### Cache
`GET /api/cache` → `{entries, max_entries, ttl_seconds, hits, misses, per_dataset, scope}`. `DELETE /api/cache?dataset_id=` clears everything, or one dataset.
