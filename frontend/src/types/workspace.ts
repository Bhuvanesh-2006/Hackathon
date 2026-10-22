export interface DatasetColumn {
  name: string;
  original_name?: string;
  type: string;
  role?: string;
  missing?: number;
  missing_pct?: number;
  approx_distinct?: number;
  samples?: string[];
  notes?: string[];
  description?: string;
}

export interface Dataset {
  id: string;
  name: string;
  description: string | null;
  kind: 'builtin' | 'imported';
  source_filename: string | null;
  file_format: string | null;
  status: 'ready' | 'failed' | 'importing' | 'not_loaded';
  version: number;
  row_count: number | null;
  column_count: number | null;
  columns: DatasetColumn[];
  findings: string[];
  errors: string[];
  support: string[];
  table: string;
  created_at: string | null;
  imported_at: string | null;
  updated_at: string | null;
  file_size_bytes: number | null;
  saved_query_count: number;
}

export interface DatasetList {
  items: Dataset[];
  active_id: string;
  limits: { max_upload_mb: number; formats: string[] };
}

export interface QueryParameter {
  name: string;
  type: 'integer' | 'number' | 'text' | 'date';
  default?: string | number | null;
  description?: string | null;
}

export interface Compatibility {
  status: 'compatible' | 'other_dataset' | 'incompatible' | 'unavailable';
  reason: string;
  missing_columns?: string[];
  same_dataset?: boolean;
  hint?: string;
}

export interface SavedQuery {
  id: string;
  title: string;
  question: string | null;
  sql: string;
  description: string | null;
  category: string;
  tags: string[];
  parameters: QueryParameter[];
  dataset_id: string;
  dataset_name: string | null;
  dataset_version: string | null;
  required_columns: string[];
  source: string;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  use_count: number;
  compatibility?: Compatibility;
}

export interface RecommendedQuery {
  id: string;
  title: string;
  question: string;
  sql: string;
  description: string;
  category: string;
  tags: string[];
  parameters: QueryParameter[];
  builtin: true;
  dataset_id: string;
  dataset_name: string;
  compatibility: Compatibility;
}

export interface SavedQueryList {
  dataset: { id: string; name: string };
  recommended: RecommendedQuery[];
  items: SavedQuery[];
  categories: string[];
}

export interface CacheInfo {
  hit: boolean;
  cached_at: number;
  age_seconds: number;
  dataset_version: string;
  ttl_seconds: number;
  stored?: boolean;
}

export interface SavedQueryInput {
  title: string;
  question?: string | null;
  sql: string;
  description?: string | null;
  category?: string;
  tags?: string[];
  parameters?: QueryParameter[];
  dataset_id: string;
}
