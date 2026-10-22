import type { CacheInfo, Compatibility } from './workspace';

export type QueryStatus = 'success' | 'empty' | 'clarification' | 'unsupported' | 'rejected' | 'error';

export interface ColumnInfo {
  name: string;
  type: string;
}

export interface ChartConfig {
  type: 'bar' | 'line' | 'pie';
  x: string;
  y: string[];
  title?: string | null;
}

export interface BusinessRule {
  id: string;
  name: string;
  definition: string;
  sql?: string;
}

export interface LlmStatus {
  provider: string;
  model: string;
  is_llm: boolean;
  configured: boolean;
  note?: string;
}

export interface AgentResponse {
  query_id: string;
  conversation_id: string;
  created_at: string;
  question: string;
  clarification_response?: string;
  status: QueryStatus;
  answer: string;
  explanation: string | null;
  sql: string | null;
  columns: ColumnInfo[];
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  stored_rows_truncated?: boolean;
  chart: ChartConfig | null;
  clarification: { question: string; options: string[]; source: string } | null;
  business_rules: BusinessRule[];
  error: { code: string; message: string; retryable: boolean } | null;
  evidence?: Evidence | null;
  context?: ConversationContext | null;
  rerun?: boolean;
  dataset?: { id: string; name: string; version: number; kind: string };
  saved_query?: { id: string | null; title: string; builtin: boolean; parameters: Record<string, unknown>; compatibility?: Compatibility };
  execution: {
    provider: string;
    model: string;
    is_llm: boolean;
    attempts: number;
    validated: boolean;
    db_ms: number | null;
    total_ms: number | null;
    regenerated: boolean;
    max_rows: number;
    timeout_s: number;
    cache?: CacheInfo;
  };
}

export interface HistoryItem {
  id: string;
  conversation_id: string;
  created_at: string;
  question: string;
  clarification: string | null;
  status: QueryStatus;
  duration_ms: number | null;
  sql: string | null;
  summary: string | null;
  row_count: number | null;
  provider: string | null;
  dataset_id?: string | null;
  dataset_name?: string | null;
}

export interface Health {
  status: string;
  version: string;
  database: { loaded: boolean; read_only: boolean; status: string; row_count?: number; prepared_at?: string };
  llm: LlmStatus;
}

export interface Kpis {
  gross_revenue: number | null;
  net_revenue: number | null;
  cancelled_value: number | null;
  product_cancelled_value: number | null;
  orders: number;
  units_sold: number | null;
  cancellation_invoices: number;
  returned_units: number | null;
  customers: number;
  unattributed_net_revenue: number | null;
  lines: number;
}

export interface DatasetMetadata {
  name: string;
  source: string;
  source_page: string;
  license: string;
  description: string;
  currency: string;
  source_file?: string;
  prepared_at?: string;
  row_count?: number;
  min_invoice_date?: string;
  max_invoice_date?: string;
  overlap_rows_removed?: number;
  overlap_window_start?: string;
  overlap_window_end?: string;
  source_rows_total?: number;
  exact_duplicate_rows_retained?: number;
}

export interface DashboardSummary {
  filters: { year: number | null; country: string | null };
  kpis: Kpis;
  revenue_trend: { month: string; gross_revenue: number; net_revenue: number; cancelled_value: number | null; orders: number }[];
  top_products: { stock_code: string; description: string; net_revenue: number; units_sold: number }[];
  sales_by_country: { country: string; net_revenue: number; orders: number }[];
  line_types: { line_type: string; lines: number; amount: number }[];
  currency: string;
  dataset: DatasetMetadata;
  recent_queries: HistoryItem[];
  filter_options: { years: number[]; countries: string[] };
}

export interface SchemaColumn {
  name: string;
  type: string;
  description: string;
  missing: number;
  missing_pct: number;
  approx_distinct: number;
}

export interface DatasetSchema {
  metadata: DatasetMetadata;
  dataset: DatasetMetadata;
  row_count: number;
  columns: SchemaColumn[];
  line_types: { line_type: string; lines: number; invoices: number; quantity: number; amount: number }[];
  item_types: { item_type: string; lines: number; amount: number; codes: string | null }[];
  quality: Record<string, number>;
  business_rules: BusinessRule[];
  line_type_definitions: Record<string, string>;
  item_type_definitions: Record<string, string>;
  table: string;
}

export interface DatasetPreview {
  columns: string[];
  rows: unknown[][];
  total: number;
  limit: number;
  offset: number;
}

export interface BenchmarkCase {
  id: string;
  question: string;
  category: string;
  expect: 'answer' | 'clarification' | 'unsupported' | 'empty';
  description: string;
  reference_sql: string | null;
  setup?: string[];
  clarification?: string | null;
}

export interface BenchmarkResult extends BenchmarkCase {
  passed: boolean;
  executed: boolean;
  reason: string;
  expected_display?: string;
  agent_status?: QueryStatus | 'not_run';
  agent_sql?: string | null;
  agent_answer?: string;
  agent_columns?: string[];
  agent_rows?: unknown[][];
  agent_row_count?: number;
  sql_validated?: boolean;
  attempts?: number;
  duration_ms?: number;
}

export interface Rate {
  passed: number;
  total: number;
  rate: number | null;
}

export interface BenchmarkRun {
  run_id: string;
  status: 'running' | 'completed' | 'failed';
  started_at: string;
  finished_at: string | null;
  provider: string;
  model: string;
  is_llm: boolean;
  progress: { done: number; total: number; current: string | null };
  results: BenchmarkResult[];
  summary: {
    overall: Rate;
    result_match: Rate;
    sql_execution: Rate;
    clarification: Rate;
    unsupported_and_empty: Rate;
    multi_turn?: Rate;
    security?: Rate;
  } | null;
  security?: SecurityProbe[];
  error?: string;
}

export interface SecurityProbe {
  id: string;
  name: string;
  kind: 'sql' | 'question';
  sql?: string;
  question?: string;
  passed: boolean;
  status: string;
  reason: string;
}

export interface ActiveFilter {
  field: 'country' | 'year' | 'date_range' | 'stock_codes' | 'customer_id';
  label: string;
}

export interface ComparisonPeriod {
  current: [string, string];
  previous: [string, string];
  label: string;
}

export interface ConversationContext {
  filters: ActiveFilter[];
  removed: string[];
  comparison: ComparisonPeriod | null;
  previous_result: { column: string; count: number } | null;
  root_question: string | null;
  topic: { type: string; anomaly_id: string; summary: string } | null;
}

export interface Evidence {
  filters: ActiveFilter[];
  date_range: { from: string; to: string; source: string };
  comparison: ComparisonPeriod | null;
  grouping: string[];
  source_row_count: number | null;
  source_row_note: string | null;
  result_rows: number;
  metric_definitions: BusinessRule[];
  limitations: string[];
  verification: { validated: boolean; executed: boolean; independently_verified: boolean; note: string };
  retrieval: { backend: string; examples: { id: string; question: string; score: number }[]; notes: { id: string; text: string; score: number }[] } | null;
}

export interface Anomaly {
  id: string;
  metric: string;
  metric_label: string;
  unit: 'GBP' | 'units' | 'orders';
  kind: 'spike' | 'drop';
  severity: 'high' | 'medium';
  period_start: string;
  period_end: string;
  trading_days: number;
  observed: number;
  expected: number;
  deviation: number;
  deviation_pct: number | null;
  robust_z: number;
  baseline_weeks: string[];
  baseline_per_day: number | null;
  seasonal: { last_year_week: string; last_year_observed: number; last_year_robust_z: number; recurring: boolean } | null;
  evidence: { week_start: string; trading_days: number; value: number; per_day: number; role: 'baseline' | 'observed' }[];
  notes: string[];
}

export interface AnomalyResponse {
  config: Record<string, number>;
  method: string;
  metrics: Record<string, { label: string; unit: string; directions: string[] }>;
  anomalies: Anomaly[];
  skipped_weeks: { week_start: string; reason: string }[];
  weeks_analysed: number;
  series: Record<string, { week_start: string; trading_days: number; value: number | null }[]>;
  sql: string;
  disclaimer: string;
}

export interface ContributionRow {
  category: string;
  name: string | null;
  current_value: number;
  comparison_value: number;
  change: number;
  share_of_change_pct: number | null;
  only_in: 'current' | 'comparison' | null;
}

export interface ContributionResult {
  metric: string;
  metric_label: string;
  unit: string;
  dimension: string;
  dimension_label: string;
  current_window: { start: string; end_exclusive: string; trading_days: number };
  comparison_windows: { start: string; end_exclusive: string }[];
  comparison_trading_days: number;
  scale: number;
  totals: { current: number; comparison: number; change: number };
  rows: ContributionRow[];
  categories_compared: number;
  positive_contributors: number;
  negative_contributors: number;
  reconciled: boolean;
  calculation: string;
  sql: string;
  disclaimer: string;
}

export interface ForecastResponse {
  available: boolean;
  reason?: string;
  metric: string;
  history: { month: string; actual: number }[];
  partial_month: { month: string; net_revenue_to_date: number; through: string } | null;
  train_period: [string, string];
  holdout_period: [string, string];
  evaluation: { method: string; description: string; mae: number; mape_pct: number; max_ape_pct: number; holdout: { month: string; actual: number; predicted: number }[] }[];
  selected_method: string;
  selected_description: string;
  improvement_vs_naive_pct: number | null;
  forecast: { month: string; forecast: number; low: number; high: number }[];
  range_note: string;
  limitations: string[];
  sql: string;
}

export interface KnowledgeStatus {
  retrieval: { backend: string | null; state: string; note?: string | null; model?: string | null; dim?: number; documents?: number; load_seconds?: number };
  configured_backend: string;
  embedding_model: string;
  examples: number;
  notes: number;
  used_by: string;
}

export interface BenchmarkState {
  cases: BenchmarkCase[];
  dataset_loaded: boolean;
  llm: LlmStatus;
  current: BenchmarkRun | null;
  last_completed: BenchmarkRun | null;
}

export interface AppSettings {
  dataset: DatasetMetadata & { excel_path_configured: string; database_file: string; loaded: boolean };
  database: { engine: string; mode: string };
  llm: LlmStatus;
  query_limits: { timeout_seconds: number; max_result_rows: number; max_question_length: number; max_regenerations: number };
  benchmark: { case_count: number; numeric_relative_tolerance: number; numeric_absolute_tolerance: number; comparison: string };
  business_rules: BusinessRule[];
  demo: { offline_provider_available: boolean; how_to_enable: string; sample_questions: string[] };
  anomaly_detection: Record<string, number | string>;
  forecast: { holdout_months: number; horizon_months: number; methods: Record<string, string> };
  retrieval: { configured_backend: string; embedding_model: string };
}
