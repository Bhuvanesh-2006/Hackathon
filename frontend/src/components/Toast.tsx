import { Alert, Snackbar } from '@mui/material';
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

type Severity = 'success' | 'info' | 'warning' | 'error';
interface ToastMsg {
  id: number;
  message: string;
  severity: Severity;
}

const ToastContext = createContext<(message: string, severity?: Severity) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastMsg | null>(null);
  const notify = useCallback((message: string, severity: Severity = 'success') => {
    setToast({ id: Date.now(), message, severity });
  }, []);
  return (
    <ToastContext.Provider value={notify}>
      {children}
      <Snackbar
        key={toast?.id}
        open={!!toast}
        autoHideDuration={3500}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        {toast ? (
          <Alert severity={toast.severity} variant="filled" onClose={() => setToast(null)} sx={{ borderRadius: 3 }}>
            {toast.message}
          </Alert>
        ) : undefined}
      </Snackbar>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
