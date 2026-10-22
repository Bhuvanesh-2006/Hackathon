import { CssBaseline, ThemeProvider } from '@mui/material';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { ToastProvider } from './components/Toast';
import { DatasetProvider } from './hooks/DatasetContext';
import { theme } from './theme/theme';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <ToastProvider>
        <DatasetProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </DatasetProvider>
      </ToastProvider>
    </ThemeProvider>
  </StrictMode>,
);
