# RetailPilot — An AI Sales Analyst You Can Trust

RetailPilot answers sales questions in plain English from the real transaction data of the **UCI Online Retail II** dataset. Every answer shows the evidence behind it. RetailPilot also finds unusual weeks on its own and helps investigate where each change is concentrated.

**What it does**
- **Answers questions with validated SQL.** An LLM (DeepSeek or Anthropic) proposes a structured plan. RetailPilot then validates the SQL with SQLGlot and runs it on a read-only DuckDB connection with a timeout and a row cap. A failed query gets at most one regeneration, and that SQL is validated again.
- **Asks back instead of guessing.** Questions like "best customers", "max revenue", "the product's best date", "compare with the previous month" (when no month is set) and "those products" (when there is no previous result) get a clarifying question.
- **Keeps conversation context.** Filters, comparison periods and "those products" carry across turns. Active filters are read from the executed SQL and shown as chips you can remove.
- **Shows evidence for every answer.** Filters, date range, grouping, source rows scanned, metric definitions, data limitations, the executed SQL, the result table, and a clear note that a query running successfully does not mean its interpretation is verified.
- **Detects anomalies proactively.** A weekly robust z-score flags unusual net revenue, units, orders and cancelled value, with documented severity rules and a seasonal check.
- **Investigates anomalies.** Contribution analysis breaks a change down by product, country, customer or weekday. The contributions add up exactly to the total change, and the results are labelled descriptive, not causal.
- **Forecasts monthly net revenue (experimental).** A seasonal-naive baseline, evaluated on a time-based holdout against naive alternatives.
- **Imports your own datasets.** CSV and XLSX files are validated, profiled and stored in isolation, and you choose which dataset to query.
- **Saves queries.** Save any executed answer, or start from the recommended queries generated for each dataset. Saved queries are revalidated every time they run.
- **Measures its own reliability.** A benchmark of 20 trap questions (including multi-turn conversations) and 15 security probes, scored against independent hand-written SQL.

```
frontend/  React + TypeScript + Vite + MUI + Recharts + MUI X DataGrid
backend/   FastAPI + Pydantic + DuckDB + pandas + SQLGlot + pytest
  app/agent/       workflow, prompts, providers (DeepSeek, Anthropic, offline), retrieval (BGE + FAISS),
                   verified example library, conversation context, evidence, ambiguity guard, charts
  app/insights/    anomalies.py, contribution.py, forecast.py
  app/datasets/    registry.py (dataset registry), importer.py (CSV/XLSX import), execution.py (validated + cached execution)
  app/library/     store.py (saved queries), recommended.py, runner.py
  app/cache.py     bounded TTL result cache
  app/security/    SQL AST validator
  app/database/    read-only connection, schema allowlist, business rules (single source of truth)
  app/benchmarks/  trap questions, reference SQL, comparison, security probes, runner
  app/api/         HTTP routes, dashboard/explorer queries, error handling
  scripts/         prepare_data.py, init_db.py, run_benchmark.py
  tests/           pytest suite (130 tests)
docs/      API.md, DEVLOG.md, DEMO_QUESTIONS.md, build_report.html
```

---

## 1. Setup

Prerequisites: **Python 3.11+**, **Node.js 20+**.

1. **Dataset.** Download *Online Retail II* from <https://archive.ics.uci.edu/dataset/502/online+retail+ii> (CC BY 4.0) and unzip `online_retail_II.xlsx` to `online+retail+ii/` at the repository root, or pass `--excel PATH`.
2. **Backend.**
   ```bash
   cd backend
   python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   pip install -r requirements-retrieval.txt              # optional: BGE-large + FAISS (~2 GB with PyTorch)
   cp .env.example .env                                   # set DEEPSEEK_API_KEY (or ANTHROPIC_API_KEY)
   python -m scripts.prepare_data                         # ~1 min
   python -m scripts.init_db
   uvicorn app.main:app --reload --port 8000
   ```
3. **Frontend.**
   ```bash
   cd frontend && npm install && npm run dev               # http://localhost:5173, proxies /api to :8000
   ```
4. **Tests and benchmark.**
   ```bash
   cd backend
   python -m pytest -q                  # always uses the offline planner and mock servers; no API cost
   python -m scripts.run_benchmark      # 20 cases + 15 security probes with the configured provider
   ```

### Environment variables (backend only; never sent to the browser)
| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `auto` picks DeepSeek if `DEEPSEEK_API_KEY` is set, else Anthropic if `ANTHROPIC_API_KEY` is set, else the offline planner. Other values: `deepseek`, `anthropic`, `offline` |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` / `DEEPSEEK_BASE_URL` | – / `deepseek-chat` / `https://api.deepseek.com` | DeepSeek chat-completions in JSON mode |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` / `ANTHROPIC_EFFORT` | – / `claude-opus-5-5` / `low` | Anthropic structured outputs, with server-side refusal fallback |
| `RETRIEVAL_BACKEND` | `bge-faiss` | `bge-faiss`, `keyword` or `none`. Falls back to `keyword` if the packages or the model are missing |
| `EMBEDDING_MODEL` | `BAAI/bge-large-en-v1.5` | downloaded (~1.3 GB) on first use |
| `QUERY_TIMEOUT_SECONDS` / `MAX_RESULT_ROWS` | `10` / `1000` | execution limits |

**The offline planner is not an LLM.** It maps a fixed set of question patterns to SQL templates so the app can be demoed and tested without a key. It is labelled in the header, on Settings, on the Benchmark page and in History, and its SQL goes through the same validator and executor as LLM SQL.

---

## 2. Data rules (verified against the imported data)

All definitions live in `backend/app/database/business_rules.py`. The prompt, the dashboard, the benchmark and the UI all use them.

| Topic | Rule |
|---|---|
| Currency | GBP. `line_amount = quantity × unit_price`. **Revenue is sales value, not profit**: the data has no costs, so profit and margin questions are declined. |
| Period | 2009-12-01 → 2011-12-09. December 2011 is partial. |
| Worksheet overlap | Both worksheets contain 2010-12-01 → 12-09 (22,523 identical rows). The second copy is removed after an exact-match check: 1,067,371 source rows → **1,044,848 loaded**. |
| Line types | `SALE` (qty > 0, price > 0), `CANCELLATION` (invoice starts with C), `STOCK_ADJUSTMENT` (qty ≤ 0 on a non-C invoice), `ZERO_PRICE`, `BAD_DEBT_ADJUSTMENT` (A invoices). |
| Net revenue (default "revenue") | SALE + CANCELLATION lines of PRODUCT items. Gross revenue = SALE lines only. |
| Cancellations and returns | C invoices mix cancellations and returns, so they are reported together. **A C line is not always the return of a sale in this data:** 2,061 of 18,446 customer-linked cancellation lines (11%) have no earlier sale of that product to that customer, and one manual-adjustment C line has a positive quantity. Stock write-offs (3,393 negative-quantity lines) are never counted as returns. |
| Cancelled value scope | All lines: £1,465,303.66 (includes Amazon fees and manual adjustments). Product lines only: £719,692.94. The UI labels which one it shows. |
| Returned units vs return transactions | −Σ quantity on product C lines vs distinct C invoices. The two are never mixed. |
| Quantity | Signed units per line; never summed across line types without saying so. |
| Orders | Distinct invoices with at least one SALE line. |
| Customer count | Distinct non-NULL `customer_id` with a SALE line. |
| Missing customer IDs | 235,287 lines (22.5%). Kept in totals, excluded from customer rankings, and stated in answers. |
| Non-product codes | POST/DOT/C2, fees, manual adjustments, discounts, samples, tests and gift vouchers are excluded from product figures. |
| Largest orders | 5 of the 10 largest orders were later cancelled (the largest, 581483 at £168,469.60, 12 minutes later). The "largest order" answer flags this from the data. |

---

## 3. Question answering pipeline
1. Validate the input and load the conversation state (SQLite).
2. Deterministic guards: known ambiguous phrasings; comparisons without a current period; "those …" without a previous result.
3. **Retrieval** (LLM providers only): BGE-large-en-v1.5 embeddings in a FAISS inner-product index over 18 verified SQL examples and 8 notes. The top examples and notes are added as reference data. The full schema and every rule are always in the system prompt, so retrieval can never drop a safety rule. The example questions are checked by a test to differ from all benchmark questions, so the benchmark is not contaminated.
4. Structured plan from the model: intent, SQL, explanation, rules, chart.
5. **SQLGlot validation**: one statement; SELECT or a set operation only; only `transactions` and its columns; no file, system or settings functions. The validated AST is re-rendered, and that text is what runs and what is shown.
6. Execution on a single **read-only** DuckDB instance with external access off and settings locked. 10 s timeout and 1,000-row cap.
7. At most **one** regeneration on a validation or database error, and the new SQL goes through the same validator.
8. **Evidence and state.** The summary comes from the returned rows. Active filters and grouping come from the executed SQL's syntax tree. The source row count comes from a `COUNT(*)` with the same WHERE clause. Limitations are triggered by rules. The conversation state is updated from what was executed.

**Conversation context.** Filters persist across turns and show as chips. Removing a chip re-runs the conversation's base question without that filter. "Compare with the previous month" uses the active month or date range; if there is none, it asks. "Those products / customers / countries" resolves to the keys of the previous result. None of this bypasses validation: context only reaches SQL through the planner, and values are escaped and still validated (tested with injected values).

---

## 4. Insights

### Anomaly detection (`app/insights/anomalies.py`)
- **Metrics:** weekly net revenue, units sold, orders and cancelled value. Cancelled value is checked for increases only. The cancellation rate is reported as supporting evidence rather than as a separate alert.
- **Coverage:** values are divided by **trading days** (the shop never trades on Saturdays and closes over Christmas). Weeks with fewer than 4 trading days are skipped.
- **Baseline:** the median and MAD of the previous 8 eligible weeks (at least 6, looking back at most 12 weeks). The robust z-score is (observed − median) / (1.4826 × MAD).
- **Severity:** **medium** when |z| ≥ 3.5 **and** the change is ≥ 25%; **high** when |z| ≥ 5. The thresholds are in `AnomalyConfig` and shown in the UI.
- **Seasonal check:** the same week one year earlier is scored the same way and labelled "Also last year" when it deviated in the same direction.
- **Isolation Forest is not used.** With about 100 weekly points per metric it cannot be validated meaningfully, and its scores are not interpretable.
- **Current output:** 35 alerts (18 high) in 104 weeks; 7 weeks skipped. All are labelled potential issues, not causes.

### Contribution analysis (`app/insights/contribution.py`)
- **Formula:** change(category) = current − comparison × (current trading days / comparison trading days). For an anomaly, the comparison is its own baseline weeks.
- **Edge cases:** a category missing from one window counts as 0 there. Missing customers get their own bucket. Negative contributors are kept, and an "All other" row makes the total reconcile exactly. Non-additive breakdowns, such as orders by product, are refused with the reason.
- **Shown to the user:** the comparison windows, the calculation, the SQL, the result table, CSV export, and a statement that the analysis is descriptive, not causal.
- **Median vs total:** the anomaly's "expected" uses the median baseline week, which is robust but not additive. The breakdown uses the scaled baseline total, which is additive. The UI explains why they can differ slightly.

### Forecast (`app/insights/forecast.py`, experimental)
- **Data:** monthly net revenue over full months only (24). December 2011 is partial and excluded from fitting.
- **Candidates:** naive, seasonal-naive, and seasonal-naive with year-over-year drift.
- **Evaluation:** time-based holdout over the last 6 months (2011-06…11). Measured MAPE: naive 20.2%, seasonal-naive **6.9%**, seasonal drift 11.6%. Seasonal-naive is selected, with 74% lower MAE than naive.
- **Range:** ± the largest holdout percentage error. This is labelled a rough range, not a prediction interval, and the UI calls the figures estimates.

---

## 5. Reliability benchmark
- **Cases:** 20 cases with independent reference SQL written on raw columns: 13 with an exact result, 4 that must clarify, 2 that must decline, and 1 that must report no data. 4 of the cases are multi-turn (a follow-up filter, "those products", and period comparisons with and without a set period).
- **Security probes:** 15 probes, run through the real pipeline. 12 malicious SQL plans come from a stub model (DROP, DELETE, stacked statements, `read_csv`, `getenv`, catalogs, ATTACH, COPY, SET, UNION with internal tables, `duckdb_settings`), plus 3 prompt-injection questions.
- **Reported separately:** exact result match, SQL execution success (*not* proof of correctness), clarification, multi-turn, unsupported/empty handling, and security rejection.
- **Measured here (offline planner):** 20/20 cases, 15/15 probes. This verifies the pipeline and reference SQL; it says **nothing about LLM accuracy**, because the planner's templates target these question types. **The DeepSeek and Anthropic paths have not been run against their live APIs in this environment** (no keys). They are tested only against local mock servers. Run the benchmark with a key to measure them.

---

## 6. Datasets, saved queries and caching (v1.2)

### Dataset Manager (`/datasets`)
- **Formats:** CSV, comma/semicolon/tab/pipe separated (UTF-8; other encodings are decoded as Windows-1252 and reported), and XLSX (the first worksheet with data; other sheets are reported; macro workbooks are rejected). No other formats are accepted. The limit is 50 MB (`MAX_UPLOAD_MB`) and 200 columns.
- **Upload handling:** files are streamed to `backend/data/uploads/` under a random name, with SHA-256 and a size check. The extension must match the content: a CSV must be text, and an XLSX must be a ZIP containing an Excel workbook. Files are never executed, and their contents are treated as data only.
- **Storage:** each import gets an internal id (`ds_<hex>`) and its own DuckDB file, `backend/data/datasets/<id>/v<version>.duckdb`, with exactly one table, `data`. Queries open only that file, read-only with external access disabled, so other datasets are physically unreachable. The registry (name, description, status, version, fingerprint, row and column counts, schema, findings, errors) lives in `backend/data/app_state.sqlite3`.
- **Identifiers:** dataset names are display text only. Column headers are mapped to safe identifiers: lowercase, `[a-z0-9_]`, `c_` added before a leading digit, reserved words suffixed `_col`, duplicates numbered. The original header is kept and shown.
- **Validation and profiling:** empty files, header-only files, ragged rows (the DuckDB parse error is shown), binary data and fake XLSX files are rejected. Each column is profiled for missing values, approximate distinct count, and integer/decimal/boolean/date parse rates. A type is applied only if **every** non-empty value parses. Integers are checked with a strict digit pattern, because DuckDB's `TRY_CAST('120.50' AS BIGINT)` silently rounds to 121. Day/month-ambiguous dates, partly numeric columns, and numbers with leading zeros stay text and are reported. Duplicate headers, missing values and duplicate rows are reported, never silently fixed.
- **Re-import:** the new file is built as `v<n+1>.duckdb.tmp` and renamed only on success. The registry then points to it, the old file is deleted, and that dataset's cache entries are dropped. A failed re-import leaves the previous version in use (tested).
- **Delete:** removes only that dataset's own folder (derived from its id) and its cache entries. Associated saved queries stay in the library but are shown as unavailable, with the reason. The confirmation dialog says how many are affected.
- **Built-in dataset:** Online Retail II works as before (`retail.duckdb`, curated rules, anomalies, benchmark). It is labelled "built-in demo" and cannot be renamed, re-imported or deleted from the UI.
- **Active dataset:** chosen in the Dataset Manager, the AI Sales Analyst (selector) or Saved Queries, and shown in the header. Every query request names its dataset. A conversation is bound to the dataset it started on, so switching starts a new chat after a confirmation (a mismatched API request gets 409). The Overview, Data Explorer, Anomalies and Benchmark pages describe the built-in dataset only.

### Questions on imported datasets
- **What the model sees:** only the selected dataset's schema: safe names, original headers, types, example values and supported analyses. The retail rules, retail examples and retail guards are not used.
- **No invented metrics:** the prompt forbids inventing revenue, profit or returns unless a column contains them.
- **Validation and isolation:** SQL is validated against that dataset's own table and columns. Cross-dataset queries are rejected: other tables, `transactions`, `dataset_metadata` and file functions are all blocked (tested).
- **Without an LLM:** a small rule-based planner handles questions that name the dataset's columns (totals and averages, rankings, monthly trends, counts) and declines money questions that have no matching column.

### Saved Queries (`/saved-queries`)
- **What is stored:** title, question, SQL, description, category, tags, typed parameters, dataset id/name/version, required columns, created/updated/last-used times and use count, all in `app_state.sqlite3`. No API keys, prompts or result rows are stored, and saving never freezes a result.
- **Saving:** "Save query" appears only on answers whose SQL was validated **and** executed. The SQL panel shows Proposed → Validated/Rejected → Executed/Not executed. Titles are unique per dataset (409 otherwise). Editing offers an explicit **Update original** or **Save as new copy**. Duplicate, rename, delete (with confirmation), copy SQL, and search and filtering by category or tag are available.
- **Parameters:** `{{name}}` placeholders with types integer, number, text or date. Values become escaped literals, the rendered SQL is validated, and leftover braces are rejected.
- **Compatibility:** checked against the selected dataset every time a query is listed or run:
  - *compatible*: its own dataset, current schema;
  - *other dataset*: validates there, but needs explicit confirmation;
  - *incompatible*: shows the missing columns and offers "Adapt in Analyst", which pre-fills the question. It is not executed;
  - *unavailable*.
- **Recommended queries:** the built-in dataset has curated SQL that follows the documented rules: top products, monthly trend, best sellers by units, country, top customers, cancellations/returns, and a parameterised top-N-in-country. Imported datasets get queries generated from detected column roles, each validated before it is offered. Nothing is called revenue unless such a column exists, and return analyses exist only for the built-in dataset.

### Result cache (`app/cache.py`)
- **Key:** SHA-256 of {normalised validated SQL (filters are part of it), dataset id, dataset version and fingerprint, parameters, business-rule version, row limit}.
- **What is stored:** successful validated executions only; errors and rejected SQL never are. `CACHE_TTL_SECONDS` defaults to 600 and `CACHE_MAX_ENTRIES` to 256 (LRU).
- **Invalidation:** per dataset on re-import or delete. A new version also changes the key, so an old result can never match. `DELETE /api/cache` clears everything, or one dataset with `?dataset_id=`.
- **In the UI:** a cached answer shows "From cache · N min old" with the dataset version, and the SQL stage reads "Executed (result reused from cache)". The benchmark bypasses the cache.
- **Scope:** the cache is application-wide, because there are no user accounts.

## 7. Security
- **Read-only database:** external access is disabled and settings are locked, and a test proves even unvalidated SQL cannot write, read files or change settings.
- **AST validation and limits:** allowlists, timeout, row cap, and a single regeneration that goes through the same validator.
- **Untrusted LLM output:** model output is parsed into a schema, and malformed JSON becomes an error, never an execution. Retrieved text and conversation state are passed to the model as data and are never trusted to run.
- **Secrets:** API keys are read from the backend environment only and never returned by any endpoint (tested).

## 8. Deployment
- **One process:** `npm run build` in `frontend/`, then `uvicorn app.main:app --host 0.0.0.0 --port 8000` serves both the UI and the API.
- **Docker:** `docker build -t retailpilot .`, then `docker run -p 8000:8000 -e DEEPSEEK_API_KEY=... -v "$PWD/backend/data:/app/backend/data" retailpilot`. The image installs `requirements.txt` only, so retrieval falls back to keyword unless you add `requirements-retrieval.txt`. The Dockerfile has not been built in this environment.

## 9. Known limitations
- Live DeepSeek and Anthropic calls are unverified here; see the benchmark section.
- BGE-large retrieval takes about 0.7 s per question on CPU. The first start downloads the model (it took about 11 minutes here).
- Anomalies are weekly only. The seasonal check uses one prior year, so 2010 alerts have no seasonal context.
- Contribution analysis supports the product, country, customer and weekday dimensions.
- The forecast is based on two seasonal cycles. Treat it as an indicative baseline.
- The offline planner covers documented question families only. Other questions are reported as unsupported.
- **No authentication:** datasets, the active dataset, saved queries and the cache are shared by everyone who can reach the server. Do not expose it publicly with sensitive data.
- **Imports are synchronous** in the request, which is fine up to the 50 MB limit. XLSX imports read one worksheet. Encodings other than UTF-8 are decoded as Windows-1252.
- **Built-in-only pages:** anomaly detection, contribution analysis, the forecast and the benchmark are defined for the built-in retail dataset only.
- **No frontend test framework:** the UI flows were verified with Playwright scripts run against the app, but those scripts are not committed as a test suite.
