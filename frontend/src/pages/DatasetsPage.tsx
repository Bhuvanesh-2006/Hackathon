import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CloudUploadOutlinedIcon from '@mui/icons-material/CloudUploadOutlined';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import ReplayIcon from '@mui/icons-material/Replay';
import {
  Alert, Box, Button, Card, CardActionArea, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Grid2 as Grid,
  LinearProgress, Stack, Tab, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tabs, TextField, Typography,
} from '@mui/material';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { SectionCard } from '../components/Cards';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { CardSkeleton, EmptyState, ErrorState } from '../components/Feedback';
import { ResultGrid } from '../components/ResultGrid';
import { useToast } from '../components/Toast';
import { useAsync } from '../hooks/useAsync';
import { useDatasets } from '../hooks/DatasetContext';
import { formatDateTime, formatNumber } from '../services/format';
import { workspaceApi } from '../services/workspaceApi';
import type { Dataset } from '../types/workspace';

const STATUS_COLOR: Record<string, 'success' | 'error' | 'warning' | 'default'> = {
  ready: 'success', failed: 'error', importing: 'warning', not_loaded: 'warning',
};

export default function DatasetsPage() {
  const { datasets, activeId, setActive, refresh, loading, error, maxUploadMb } = useDatasets();
  const [params, setParams] = useSearchParams();
  const selected = datasets.find((d) => d.id === params.get('id')) ?? datasets.find((d) => d.id === activeId) ?? datasets[0];
  const notify = useToast();
  const navigate = useNavigate();

  if (error) return <ErrorState error={error} onRetry={refresh} />;
  if (loading) return <CardSkeleton height={400} />;

  const activate = async (d: Dataset) => {
    try {
      await setActive(d.id);
      notify(`“${d.name}” is now the active dataset`);
    } catch (e) {
      notify((e as Error).message, 'error');
    }
  };

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5">Datasets</Typography>
        <Typography variant="body2" color="text.secondary">
          Import CSV or XLSX files (up to {maxUploadMb} MB). Each dataset is stored separately, validated before use, and queried only when you select it.
        </Typography>
      </Box>
      <Alert severity="info">
        RetailPilot has no user accounts: datasets, the active-dataset choice and saved queries are shared by everyone who can reach this server. Do not expose it publicly with sensitive data.
      </Alert>

      <UploadCard maxUploadMb={maxUploadMb} onImported={async (d) => { await refresh(); if (d) setParams({ id: d.id }, { replace: true }); }} />

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Stack spacing={1}>
            {datasets.map((d) => (
              <Card key={d.id} sx={{ flexShrink: 0, borderColor: selected?.id === d.id ? 'primary.main' : undefined }}>
                <CardActionArea onClick={() => setParams({ id: d.id }, { replace: true })} sx={{ p: 1.75 }}>
                  <Stack spacing={0.5}>
                    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                      <Typography fontWeight={700} sx={{ wordBreak: 'break-word' }}>{d.name}</Typography>
                      {d.id === activeId && <Chip size="small" color="primary" icon={<CheckCircleIcon />} label="Active" />}
                    </Stack>
                    <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
                      <Chip size="small" variant="outlined" label={d.kind === 'builtin' ? 'Built-in demo' : 'Imported'} />
                      <Chip size="small" variant="outlined" color={STATUS_COLOR[d.status]} label={d.status} />
                    </Stack>
                    <Typography variant="caption" color="text.secondary">
                      {d.status === 'ready' ? `${formatNumber(d.row_count)} rows · ${d.column_count} columns · v${d.version}` : d.errors[0] ?? 'No data'}
                    </Typography>
                  </Stack>
                </CardActionArea>
              </Card>
            ))}
          </Stack>
        </Grid>
        <Grid size={{ xs: 12, md: 8 }}>
          {selected ? (
            <DatasetDetail key={selected.id + selected.version} ds={selected} active={selected.id === activeId} onActivate={() => activate(selected)}
              onChanged={refresh} onDeleted={async () => { await refresh(); setParams({}, { replace: true }); }}
              onAsk={() => { void activate(selected).then(() => navigate('/analyst')); }} maxUploadMb={maxUploadMb} />
          ) : <Card><EmptyState title="No datasets yet" /></Card>}
        </Grid>
      </Grid>
    </Stack>
  );
}

function UploadCard({ maxUploadMb, onImported }: { maxUploadMb: number; onImported: (d: Dataset | null) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const notify = useToast();

  const pick = (f: File | null) => {
    setError(null);
    if (!f) return;
    const ext = f.name.toLowerCase().split('.').pop();
    if (ext !== 'csv' && ext !== 'xlsx') {
      setError('Only .csv and .xlsx files are supported.');
      return;
    }
    if (f.size > maxUploadMb * 1024 * 1024) {
      setError(`The file is ${(f.size / 1024 / 1024).toFixed(1)} MB; the limit is ${maxUploadMb} MB.`);
      return;
    }
    setFile(f);
    if (!name) setName(f.name.replace(/\.(csv|xlsx)$/i, '').slice(0, 80));
  };

  const submit = async () => {
    if (!file || !name.trim()) return;
    const form = new FormData();
    form.append('file', file);
    form.append('name', name.trim());
    if (description.trim()) form.append('description', description.trim());
    setProgress(0);
    setError(null);
    try {
      const d = await workspaceApi.uploadDataset(form, setProgress);
      notify(`Imported “${d.name}”: ${formatNumber(d.row_count)} rows, ${d.column_count} columns`);
      setFile(null);
      setName('');
      setDescription('');
      if (inputRef.current) inputRef.current.value = '';
      onImported(d);
    } catch (e) {
      setError((e as Error).message);
      onImported(null); // a failed import is listed with its errors
    } finally {
      setProgress(null);
    }
  };

  return (
    <SectionCard title="Import a dataset" subtitle="CSV (comma, semicolon, tab or pipe separated) or XLSX (first worksheet with data). Macros are rejected.">
      <Stack spacing={2}>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'center' }}>
          <Button component="label" variant="outlined" startIcon={<CloudUploadOutlinedIcon />} sx={{ flexShrink: 0 }}>
            {file ? 'Change file' : 'Choose file'}
            <input ref={inputRef} type="file" hidden accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(e) => pick(e.target.files?.[0] ?? null)} />
          </Button>
          <Typography variant="body2" color="text.secondary" sx={{ minWidth: 0, wordBreak: 'break-all' }}>
            {file ? `${file.name} · ${(file.size / 1024).toFixed(0)} KB` : 'No file selected'}
          </Typography>
        </Stack>
        <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
          <TextField id="ds-name" size="small" label="Dataset name" value={name} onChange={(e) => setName(e.target.value.slice(0, 80))} required sx={{ flex: 1 }} />
          <TextField id="ds-description" size="small" label="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value.slice(0, 500))} sx={{ flex: 2 }} />
          <Button variant="contained" onClick={submit} disabled={!file || !name.trim() || progress !== null}>Import</Button>
        </Stack>
        {progress !== null && (
          <Box>
            <LinearProgress variant={progress < 100 ? 'determinate' : 'indeterminate'} value={progress} sx={{ height: 6, borderRadius: 3 }} />
            <Typography variant="caption" color="text.secondary">{progress < 100 ? `Uploading ${progress}%` : 'Validating and importing…'}</Typography>
          </Box>
        )}
        {error && <Alert severity="error">{error}</Alert>}
      </Stack>
    </SectionCard>
  );
}

function DatasetDetail({ ds, active, onActivate, onChanged, onDeleted, onAsk, maxUploadMb }: {
  ds: Dataset;
  active: boolean;
  onActivate: () => void;
  onChanged: () => Promise<void>;
  onDeleted: () => Promise<void>;
  onAsk: () => void;
  maxUploadMb: number;
}) {
  const [tab, setTab] = useState<'schema' | 'preview' | 'findings'>(ds.status === 'ready' ? 'schema' : 'findings');
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reimportPct, setReimportPct] = useState<number | null>(null);
  const [reimportError, setReimportError] = useState<string | null>(null);
  const notify = useToast();
  const builtin = ds.kind === 'builtin';

  const reimport = async (f: File | null) => {
    if (!f) return;
    if (f.size > maxUploadMb * 1024 * 1024) {
      setReimportError(`The file exceeds the ${maxUploadMb} MB limit.`);
      return;
    }
    const form = new FormData();
    form.append('file', f);
    setReimportPct(0);
    setReimportError(null);
    try {
      const d = await workspaceApi.reimportDataset(ds.id, form, setReimportPct);
      notify(`Re-imported “${d.name}” as version ${d.version}. Cached results for the old version were discarded.`);
      await onChanged();
    } catch (e) {
      setReimportError((e as Error).message);
      await onChanged();
    } finally {
      setReimportPct(null);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      const r = await workspaceApi.deleteDataset(ds.id);
      notify(`Deleted “${ds.name}”.${r.saved_queries_unavailable ? ` ${r.saved_queries_unavailable} saved queries are now unavailable until adapted to another dataset.` : ''}`);
      setDeleteOpen(false);
      await onDeleted();
    } catch (e) {
      notify((e as Error).message, 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionCard title={ds.name} subtitle={ds.description ?? undefined}
      action={
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap justifyContent="flex-end">
          {ds.status === 'ready' && !active && <Button variant="contained" size="small" onClick={onActivate}>Set active</Button>}
          {ds.status === 'ready' && <Button size="small" variant="outlined" onClick={onAsk}>Ask about it</Button>}
        </Stack>
      }>
      <Stack spacing={2}>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          <Chip size="small" variant="outlined" color={STATUS_COLOR[ds.status]} label={`Status: ${ds.status}`} />
          {active && <Chip size="small" color="primary" label="Active dataset" />}
          <Chip size="small" variant="outlined" label={builtin ? 'Built-in demo data' : 'Imported'} />
          {ds.source_filename && <Chip size="small" variant="outlined" label={`File: ${ds.source_filename}`} />}
          {ds.status === 'ready' && <Chip size="small" variant="outlined" label={`${formatNumber(ds.row_count)} rows · ${ds.column_count} columns`} />}
          <Chip size="small" variant="outlined" label={`Version ${ds.version}`} />
          <Chip size="small" variant="outlined" label={`Imported ${formatDateTime(ds.imported_at)}`} />
          <Chip size="small" variant="outlined" label={`${ds.saved_query_count} saved queries`} />
        </Stack>

        {ds.errors.length > 0 && (
          <Alert severity={ds.status === 'failed' ? 'error' : 'warning'}>
            {ds.status === 'failed' ? 'Import failed: ' : 'The last re-import failed; the previous version is still in use: '}{ds.errors[0]}
          </Alert>
        )}
        {ds.support.length > 0 && (
          <Box>
            <Typography variant="overline" color="text.secondary">What this dataset supports</Typography>
            <Stack component="ul" spacing={0.25} sx={{ m: 0, pl: 2.5 }}>
              {ds.support.map((s) => <Typography component="li" variant="body2" key={s}>{s}</Typography>)}
            </Stack>
          </Box>
        )}

        {!builtin && (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button size="small" startIcon={<EditOutlinedIcon />} onClick={() => setRenameOpen(true)}>Rename</Button>
            <Button size="small" component="label" startIcon={<ReplayIcon />} disabled={reimportPct !== null}>
              Re-import file
              <input type="file" hidden accept=".csv,.xlsx" onChange={(e) => { void reimport(e.target.files?.[0] ?? null); e.target.value = ''; }} />
            </Button>
            <Button size="small" color="error" startIcon={<DeleteOutlineIcon />} onClick={() => setDeleteOpen(true)}>Delete</Button>
          </Stack>
        )}
        {builtin && (
          <Typography variant="caption" color="text.secondary">The built-in demo dataset cannot be renamed, re-imported or deleted here; rebuild it with <code>python -m scripts.prepare_data</code>.</Typography>
        )}
        {reimportPct !== null && <LinearProgress variant={reimportPct < 100 ? 'determinate' : 'indeterminate'} value={reimportPct} />}
        {reimportError && <Alert severity="error">{reimportError}</Alert>}

        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" allowScrollButtonsMobile>
          <Tab value="schema" label={`Schema (${ds.columns.length})`} disabled={ds.columns.length === 0} />
          <Tab value="preview" label="Preview" disabled={ds.status !== 'ready'} />
          <Tab value="findings" label={`Findings (${ds.findings.length})`} />
        </Tabs>
        {tab === 'schema' && <SchemaTable ds={ds} />}
        {tab === 'preview' && ds.status === 'ready' && <Preview ds={ds} />}
        {tab === 'findings' && (
          ds.findings.length === 0 ? <Typography variant="body2" color="text.secondary">No data-quality findings were reported.</Typography> : (
            <Stack spacing={1}>
              {ds.findings.map((f) => <Alert key={f} severity="warning" variant="outlined">{f}</Alert>)}
              <Typography variant="caption" color="text.secondary">Findings are reported, not fixed: values are imported as they are, and only columns where every value parses get a numeric or date type.</Typography>
            </Stack>
          )
        )}
      </Stack>

      <RenameDialog open={renameOpen} ds={ds} onClose={() => setRenameOpen(false)} onSaved={onChanged} />
      <ConfirmDialog open={deleteOpen} danger busy={busy} title={`Delete “${ds.name}”?`} confirmLabel="Delete dataset"
        body={<>This permanently removes the imported data and its cached results. {ds.saved_query_count > 0
          ? <><b>{ds.saved_query_count} saved queries</b> are associated with it; they will stay in the library but be unavailable until adapted to another dataset.</>
          : 'No saved queries use it.'} Other datasets are not affected.</>}
        onClose={() => setDeleteOpen(false)} onConfirm={remove} />
    </SectionCard>
  );
}

function SchemaTable({ ds }: { ds: Dataset }) {
  return (
    <TableContainer sx={{ overflowX: 'auto' }}>
      <Table size="small" sx={{ minWidth: 620 }}>
        <TableHead>
          <TableRow><TableCell>Column (SQL name)</TableCell><TableCell>Original header</TableCell><TableCell>Type</TableCell><TableCell align="right">Missing</TableCell><TableCell>Notes / examples</TableCell></TableRow>
        </TableHead>
        <TableBody>
          {ds.columns.map((c) => (
            <TableRow key={c.name}>
              <TableCell><Typography variant="body2" fontFamily="JetBrains Mono, monospace" fontSize={13}>{c.name}</Typography></TableCell>
              <TableCell>{c.original_name}</TableCell>
              <TableCell><Chip size="small" variant="outlined" label={c.type} /></TableCell>
              <TableCell align="right">{c.missing !== undefined ? `${formatNumber(c.missing)} (${c.missing_pct}%)` : '—'}</TableCell>
              <TableCell sx={{ color: 'text.secondary', fontSize: 13 }}>
                {[...(c.notes ?? []), c.description, c.samples?.length ? `e.g. ${c.samples.join(', ')}` : null].filter(Boolean).join(' · ')}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function Preview({ ds }: { ds: Dataset }) {
  const { data, error, loading, reload } = useAsync(() => workspaceApi.preview(ds.id, 50), [ds.id, ds.version]);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !data) return <LinearProgress />;
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">First {data.rows.length} rows of {ds.name}</Typography>
      <ResultGrid columns={data.columns.map((c, i) => ({ name: c, type: data.column_types[i] }))} rows={data.rows} height={420} />
    </Box>
  );
}

function RenameDialog({ open, ds, onClose, onSaved }: { open: boolean; ds: Dataset; onClose: () => void; onSaved: () => Promise<void> }) {
  const [name, setName] = useState(ds.name);
  const [description, setDescription] = useState(ds.description ?? '');
  const [error, setError] = useState<string | null>(null);
  const notify = useToast();
  useEffect(() => {
    setName(ds.name);
    setDescription(ds.description ?? '');
    setError(null);
  }, [ds, open]);
  const save = async () => {
    try {
      await workspaceApi.updateDataset(ds.id, { name: name.trim(), description });
      notify('Dataset details saved');
      await onSaved();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Rename dataset</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField id="rename-name" label="Name" value={name} onChange={(e) => setName(e.target.value.slice(0, 80))} autoFocus />
          <TextField id="rename-description" label="Description" value={description} onChange={(e) => setDescription(e.target.value.slice(0, 500))} multiline minRows={2} />
          <Typography variant="caption" color="text.secondary">Names are display text only; they are never used in SQL.</Typography>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={!name.trim()}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}
