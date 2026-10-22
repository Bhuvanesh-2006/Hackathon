import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { CardSkeleton } from './components/Feedback';
import { Layout } from './components/Layout';

const OverviewPage = lazy(() => import('./pages/OverviewPage'));
const AnalystPage = lazy(() => import('./pages/AnalystPage'));
const AnomaliesPage = lazy(() => import('./pages/AnomaliesPage'));
const SavedQueriesPage = lazy(() => import('./pages/SavedQueriesPage'));
const DatasetsPage = lazy(() => import('./pages/DatasetsPage'));
const DataExplorerPage = lazy(() => import('./pages/DataExplorerPage'));
const BenchmarkPage = lazy(() => import('./pages/BenchmarkPage'));
const HistoryPage = lazy(() => import('./pages/HistoryPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));

export default function App() {
  return (
    <Layout>
      <Suspense fallback={<CardSkeleton height={360} />}>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/analyst" element={<AnalystPage />} />
          <Route path="/anomalies" element={<AnomaliesPage />} />
          <Route path="/saved-queries" element={<SavedQueriesPage />} />
          <Route path="/datasets" element={<DatasetsPage />} />
          <Route path="/data" element={<DataExplorerPage />} />
          <Route path="/benchmark" element={<BenchmarkPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}
