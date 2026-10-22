import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { workspaceApi } from '../services/workspaceApi';
import type { Dataset } from '../types/workspace';

interface DatasetState {
  datasets: Dataset[];
  activeId: string | null;
  active: Dataset | null;
  loading: boolean;
  error: Error | null;
  maxUploadMb: number;
  refresh: () => Promise<void>;
  setActive: (id: string) => Promise<void>;
}

const Ctx = createContext<DatasetState | null>(null);

/** Application-wide dataset selection. The server stores the active dataset (no per-user accounts). */
export function DatasetProvider({ children }: { children: ReactNode }) {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [maxUploadMb, setMaxUploadMb] = useState(50);

  const refresh = useCallback(async () => {
    try {
      const r = await workspaceApi.datasets();
      setDatasets(r.items);
      setActiveId(r.active_id);
      setMaxUploadMb(r.limits.max_upload_mb);
      setError(null);
    } catch (e) {
      setError(e as Error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setActive = useCallback(async (id: string) => {
    await workspaceApi.setActive(id);
    setActiveId(id);
  }, []);

  const active = datasets.find((d) => d.id === activeId) ?? null;
  return (
    <Ctx.Provider value={{ datasets, activeId, active, loading, error, maxUploadMb, refresh, setActive }}>
      {children}
    </Ctx.Provider>
  );
}

export function useDatasets(): DatasetState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useDatasets must be used inside DatasetProvider');
  return v;
}
