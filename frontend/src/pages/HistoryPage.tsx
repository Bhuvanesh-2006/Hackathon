import DeleteSweepOutlinedIcon from '@mui/icons-material/DeleteSweepOutlined';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import SearchIcon from '@mui/icons-material/Search';
import {
  Box, Button, Card, CardContent, Collapse, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, InputAdornment,
  LinearProgress, MenuItem, Stack, TablePagination, TextField, Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { EmptyState, ErrorState, StatusChip } from '../components/Feedback';
import { SqlViewer } from '../components/SqlViewer';
import { useToast } from '../components/Toast';
import { useAsync } from '../hooks/useAsync';
import { api } from '../services/api';
import { formatDateTime, formatDuration } from '../services/format';

const STATUSES = ['success', 'empty', 'clarification', 'unsupported', 'rejected', 'error'];

export default function HistoryPage() {
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(20);
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const navigate = useNavigate();
  const notify = useToast();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => setPage(0), [status, debounced, pageSize]);

  const { data, error, loading, reload } = useAsync(
    () => api.history({ limit: pageSize, offset: page * pageSize, status, search: debounced }),
    [page, pageSize, status, debounced],
  );

  const clearAll = async () => {
    setConfirm(false);
    try {
      const r = await api.clearHistory();
      notify(`Deleted ${r.deleted} history entries`);
      reload();
    } catch (e) {
      notify((e as Error).message, 'error');
    }
  };

  if (error) return <ErrorState error={error} onRetry={reload} />;

  return (
    <Stack spacing={3}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'center' }}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h5">Query history</Typography>
          <Typography variant="body2" color="text.secondary">Questions, generated SQL, status and timings. No credentials are stored.</Typography>
        </Box>
        <Button color="error" variant="outlined" startIcon={<DeleteSweepOutlinedIcon />} onClick={() => setConfirm(true)} disabled={!data?.total}>
          Clear history
        </Button>
      </Stack>

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
        <TextField size="small" placeholder="Search questions" value={search} onChange={(e) => setSearch(e.target.value.slice(0, 100))} sx={{ flex: 1 }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
        <TextField select size="small" label="Status" value={status} onChange={(e) => setStatus(e.target.value)} sx={{ minWidth: 200 }}>
          <MenuItem value="">All statuses</MenuItem>
          {STATUSES.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
        </TextField>
      </Stack>

      {loading && <LinearProgress sx={{ borderRadius: 2 }} />}
      {data && data.items.length === 0 && (
        <Card><EmptyState title="No queries found" description={status || debounced ? 'Try a different filter.' : 'Questions you ask the AI Sales Analyst appear here.'}
          action={!status && !debounced ? <Button variant="contained" onClick={() => navigate('/analyst')}>Ask a question</Button> : undefined} /></Card>
      )}

      <Stack spacing={1.5}>
        {data?.items.map((h) => (
          <Card key={h.id}>
            <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} alignItems={{ md: 'center' }}>
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography fontWeight={700} sx={{ wordBreak: 'break-word' }}>
                    {h.question}{h.clarification && <Typography component="span" color="secondary.light" fontWeight={600}> → {h.clarification}</Typography>}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {formatDateTime(h.created_at)} · {h.dataset_name ? `${h.dataset_name} · ` : ''}{formatDuration(h.duration_ms)} · {h.row_count ?? 0} rows · {h.provider === 'offline' ? 'offline rule-based' : h.provider}
                  </Typography>
                  {h.summary && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{h.summary}</Typography>}
                </Box>
                <Stack direction="row" spacing={1} alignItems="center" flexShrink={0}>
                  <StatusChip status={h.status} />
                  {h.sql && <Button size="small" onClick={() => setOpen(open === h.id ? null : h.id)}>{open === h.id ? 'Hide SQL' : 'Show SQL'}</Button>}
                  <Button size="small" variant="outlined" startIcon={<OpenInNewIcon />} onClick={() => navigate(`/analyst?query=${h.id}`)}>Reopen</Button>
                </Stack>
              </Stack>
              <Collapse in={open === h.id} unmountOnExit>
                {h.sql && <Box sx={{ mt: 1.5 }}><SqlViewer sql={h.sql} maxHeight={280} /></Box>}
              </Collapse>
            </CardContent>
          </Card>
        ))}
      </Stack>

      {data && data.total > 0 && (
        <TablePagination component="div" count={data.total} page={page} onPageChange={(_, p) => setPage(p)} rowsPerPage={pageSize}
          onRowsPerPageChange={(e) => setPageSize(Number(e.target.value))} rowsPerPageOptions={[10, 20, 50]} />
      )}

      <Dialog open={confirm} onClose={() => setConfirm(false)}>
        <DialogTitle>Clear query history?</DialogTitle>
        <DialogContent><DialogContentText>This permanently deletes all {data?.total ?? 0} stored queries.</DialogContentText></DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirm(false)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={clearAll}>Delete all</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
