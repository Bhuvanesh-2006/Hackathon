import type { AgentResponse } from '../types/api';
import type { Dataset, DatasetList, SavedQuery, SavedQueryInput, SavedQueryList } from '../types/workspace';
import { ApiError, request, qs, API_BASE } from './api';

/** Multipart upload with progress (fetch cannot report upload progress). */
function upload<T>(path: string, form: FormData, onProgress?: (pct: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE}${path}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((100 * e.loaded) / e.total));
    };
    xhr.onerror = () => reject(new ApiError(0, 'network_error', 'Upload failed: cannot reach the RetailPilot API.'));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        body = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else {
        const err = (body as { error?: { code?: string; message?: string } } | null)?.error;
        reject(new ApiError(xhr.status, err?.code ?? 'http_error', err?.message ?? `Upload failed (${xhr.status})`));
      }
    };
    xhr.send(form);
  });
}

const enc = encodeURIComponent;

export const workspaceApi = {
  datasets: () => request<DatasetList>('/api/datasets'),
  dataset: (id: string) => request<Dataset>(`/api/datasets/${enc(id)}`),
  preview: (id: string, limit = 50) =>
    request<{ columns: string[]; column_types: string[]; rows: unknown[][] }>(`/api/datasets/${enc(id)}/preview?limit=${limit}`),
  setActive: (dataset_id: string) => request<{ active: Dataset }>('/api/datasets/active', { method: 'PUT', body: JSON.stringify({ dataset_id }) }),
  updateDataset: (id: string, body: { name?: string; description?: string }) =>
    request<Dataset>(`/api/datasets/${enc(id)}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteDataset: (id: string) =>
    request<{ deleted: string; saved_queries_unavailable: number; cache_entries_dropped: number; active_id: string }>(
      `/api/datasets/${enc(id)}`, { method: 'DELETE' }),
  uploadDataset: (form: FormData, onProgress?: (pct: number) => void) => upload<Dataset>('/api/datasets', form, onProgress),
  reimportDataset: (id: string, form: FormData, onProgress?: (pct: number) => void) =>
    upload<Dataset>(`/api/datasets/${enc(id)}/reimport`, form, onProgress),

  savedQueries: (p: { dataset_id: string; search?: string; category?: string; tag?: string; scope?: string }) =>
    request<SavedQueryList>(`/api/saved-queries${qs(p)}`),
  savedQuery: (id: string, dataset_id?: string) => request<SavedQuery>(`/api/saved-queries/${enc(id)}${qs({ dataset_id })}`),
  createSavedQuery: (body: SavedQueryInput) => request<SavedQuery>('/api/saved-queries', { method: 'POST', body: JSON.stringify(body) }),
  updateSavedQuery: (id: string, body: Partial<SavedQueryInput>) =>
    request<SavedQuery>(`/api/saved-queries/${enc(id)}`, { method: 'PATCH', body: JSON.stringify(body) }),
  duplicateSavedQuery: (id: string, title?: string) =>
    request<SavedQuery>(`/api/saved-queries/${enc(id)}/duplicate`, { method: 'POST', body: JSON.stringify(title ? { title } : {}) }),
  deleteSavedQuery: (id: string) => request<{ deleted: string }>(`/api/saved-queries/${enc(id)}`, { method: 'DELETE' }),
  runSavedQuery: (id: string, body: { dataset_id: string; parameters?: Record<string, unknown>; allow_other_dataset?: boolean }) =>
    request<AgentResponse>(`/api/saved-queries/${enc(id)}/run`, { method: 'POST', body: JSON.stringify(body) }),
  runRecommended: (id: string, body: { dataset_id: string; parameters?: Record<string, unknown> }) =>
    request<AgentResponse>(`/api/recommended-queries/${enc(id)}/run`, { method: 'POST', body: JSON.stringify(body) }),
  cacheStatus: () =>
    request<{ entries: number; max_entries: number; ttl_seconds: number; hits: number; misses: number; scope: string; per_dataset: Record<string, number> }>('/api/cache'),
  clearCache: (dataset_id?: string) => request<{ cleared: number }>(`/api/cache${qs({ dataset_id })}`, { method: 'DELETE' }),
};
