import BookmarkAddOutlinedIcon from '@mui/icons-material/BookmarkAddOutlined';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import FileCopyOutlinedIcon from '@mui/icons-material/FileCopyOutlined';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import SearchIcon from '@mui/icons-material/Search';
import {
  Alert, Box, Button, Card, CardContent, Chip, Collapse, Dialog, DialogActions, DialogContent, DialogTitle, Grid2 as Grid,
  InputAdornment, LinearProgress, MenuItem, Stack, TextField, Tooltip, Typography,
} from '@mui/material';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AnswerCard } from '../components/AnswerCard';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { CardSkeleton, EmptyState, ErrorState } from '../components/Feedback';
import { CATEGORIES, SaveQueryDialog, type SaveDraft } from '../components/SaveQueryDialog';
import { SqlViewer } from '../components/SqlViewer';
import { useToast } from '../components/Toast';
import { useAsync } from '../hooks/useAsync';
import { useDatasets } from '../hooks/DatasetContext';
import { ApiError } from '../services/api';
import { formatDateTime } from '../services/format';
import { workspaceApi } from '../services/workspaceApi';
import type { AgentResponse } from '../types/api';
import type { Compatibility, QueryParameter, RecommendedQuery, SavedQuery } from '../types/workspace';

const COMPAT: Record<Compatibility['status'], { label: string; color: 'success' | 'warning' | 'error' | 'default' }> = {
  compatible: { label: 'Compatible', color: 'success' },
  other_dataset: { label: 'Other dataset · needs confirmation', color: 'warning' },
  incompatible: { label: 'Incompatible with this dataset', color: 'error' },
  unavailable: { label: 'Unavailable', color: 'default' },
};

type RunTarget = { kind: 'saved'; q: SavedQuery } | { kind: 'recommended'; q: RecommendedQuery };

export default function SavedQueriesPage() {
  const { datasets, activeId, active, setActive } = useDatasets();
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [category, setCategory] = useState('');
  const [tag, setTag] = useState('');
  const [scope, setScope] = useState<'all' | 'dataset'>('all');
  const [result, setResult] = useState<AgentResponse | null>(null);
  const [running, setRunning] = useState<string | null>(null);
  const [paramTarget, setParamTarget] = useState<RunTarget | null>(null);
  const [confirmOther, setConfirmOther] = useState<{ q: SavedQuery; values: Record<string, unknown> } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SavedQuery | null>(null);
  const [saveDraft, setSaveDraft] = useState<SaveDraft | null>(null);
  const [editing, setEditing] = useState<SavedQuery | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const notify = useToast();
  const navigate = useNavigate();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data, error, loading, reload } = useAsync(
    () => (activeId ? workspaceApi.savedQueries({ dataset_id: activeId, search: debounced, category, tag, scope }) : Promise.resolve(null)),
    [activeId, debounced, category, tag, scope],
  );

  const execute = async (target: RunTarget, values: Record<string, unknown>, allowOther = false) => {
    if (!activeId) return;
    setRunning(target.q.id);
    try {
      const r = target.kind === 'saved'
        ? await workspaceApi.runSavedQuery(target.q.id, { dataset_id: activeId, parameters: values, allow_other_dataset: allowOther })
        : await workspaceApi.runRecommended(target.q.id, { dataset_id: activeId, parameters: values });
      setResult(r);
      if (target.kind === 'saved') reload();
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
    } catch (e) {
      const err = e as ApiError;
      if (err.code === 'confirmation_required' && target.kind === 'saved') setConfirmOther({ q: target.q, values });
      else notify(err.message, 'error');
    } finally {
      setRunning(null);
    }
  };

  const run = (target: RunTarget) => {
    if (target.kind === 'saved' && target.q.compatibility?.status === 'incompatible') return;
    if (target.q.parameters.length) setParamTarget(target);
    else void execute(target, {});
  };

  const copy = async (sql: string) => {
    try {
      await navigator.clipboard.writeText(sql);
      notify('SQL copied to clipboard');
    } catch {
      notify('Could not access the clipboard', 'error');
    }
  };

  const duplicate = async (q: SavedQuery) => {
    try {
      const d = await workspaceApi.duplicateSavedQuery(q.id);
      notify(`Duplicated as “${d.title}”`);
      reload();
    } catch (e) {
      notify((e as Error).message, 'error');
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    try {
      await workspaceApi.deleteSavedQuery(deleteTarget.id);
      notify(`Deleted “${deleteTarget.title}”`);
      setDeleteTarget(null);
      reload();
    } catch (e) {
      notify((e as Error).message, 'error');
    }
  };

  const draftFrom = (q: RecommendedQuery | SavedQuery | AgentResponse, dsId: string): SaveDraft => {
    if ('answer' in q) {
      return { title: q.question.slice(0, 120), question: q.question, sql: q.sql ?? '', description: q.explanation ?? '', category: 'General',
        tags: [], parameters: [], dataset_id: dsId, dataset_name: q.dataset?.name ?? active?.name ?? dsId };
    }
    return { title: q.title, question: q.question ?? '', sql: q.sql, description: q.description ?? '', category: q.category,
      tags: q.tags, parameters: q.parameters, dataset_id: dsId, dataset_name: datasets.find((d) => d.id === dsId)?.name ?? dsId };
  };

  const allTags = Array.from(new Set((data?.items ?? []).flatMap((q) => q.tags))).sort();

  return (
    <Stack spacing={3}>
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'center' }}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h5">Saved Queries</Typography>
          <Typography variant="body2" color="text.secondary">
            Reusable questions and SQL. Every run is revalidated against the selected dataset; saving a query never stores its result.
          </Typography>
        </Box>
        <TextField select size="small" label="Run against dataset" value={activeId ?? ''} sx={{ minWidth: 280 }}
          onChange={(e) => { setResult(null); void setActive(e.target.value); }}>
          {datasets.filter((d) => d.status === 'ready').map((d) => <MenuItem key={d.id} value={d.id}>{d.name}</MenuItem>)}
        </TextField>
      </Stack>

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5}>
        <TextField size="small" placeholder="Search titles, questions and SQL" value={search} onChange={(e) => setSearch(e.target.value.slice(0, 100))} sx={{ flex: 1 }}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
        <TextField select size="small" label="Category" value={category} onChange={(e) => setCategory(e.target.value)} sx={{ minWidth: 160 }}>
          <MenuItem value="">All categories</MenuItem>
          {CATEGORIES.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Tag" value={tag} onChange={(e) => setTag(e.target.value)} sx={{ minWidth: 140 }} disabled={!allTags.length && !tag}>
          <MenuItem value="">All tags</MenuItem>
          {allTags.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Show saved" value={scope} onChange={(e) => setScope(e.target.value as 'all' | 'dataset')} sx={{ minWidth: 200 }}>
          <MenuItem value="all">From all datasets</MenuItem>
          <MenuItem value="dataset">For this dataset only</MenuItem>
        </TextField>
      </Stack>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <CardSkeleton height={300} />}

      {result && (
        <Box ref={resultRef}>
          <Stack direction="row" alignItems="center" sx={{ mb: 1 }}>
            <Typography variant="h6" sx={{ flex: 1 }}>Result</Typography>
            <Button size="small" onClick={() => setResult(null)}>Close</Button>
          </Stack>
          <AnswerCard response={result} onClarify={() => undefined} clarifyDisabled onRetry={() => undefined}
            onSave={(r) => setSaveDraft(draftFrom(r, r.dataset?.id ?? activeId ?? ''))} />
        </Box>
      )}

      {data && (
        <>
          <Box>
            <Typography variant="h6">My saved queries</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>Compatibility is checked against “{data.dataset.name}”.</Typography>
            {data.items.length === 0 ? (
              <Card><EmptyState title="No saved queries yet" description="Use “Save query” on an analyst answer, or save one of the recommended queries below."
                action={<Button variant="contained" onClick={() => navigate('/analyst')}>Open AI Sales Analyst</Button>} /></Card>
            ) : (
              <Grid container spacing={2}>
                {data.items.map((q) => (
                  <Grid key={q.id} size={{ xs: 12, lg: 6 }}>
                    <QueryCard title={q.title} description={q.description} question={q.question} sql={q.sql} category={q.category} tags={q.tags}
                      parameters={q.parameters} badge={<Chip size="small" label="Saved" color="secondary" variant="outlined" />}
                      datasetLabel={`Saved for ${q.dataset_name ?? q.dataset_id}`} compatibility={q.compatibility}
                      meta={`Updated ${formatDateTime(q.updated_at)} · ${q.use_count} runs${q.last_used_at ? ` · last ${formatDateTime(q.last_used_at)}` : ''}`}
                      running={running === q.id} onRun={() => run({ kind: 'saved', q })} onCopy={() => copy(q.sql)}
                      actions={
                        <>
                          <Button size="small" startIcon={<EditOutlinedIcon />} onClick={() => setEditing(q)}>Edit</Button>
                          <Button size="small" startIcon={<FileCopyOutlinedIcon />} onClick={() => duplicate(q)}>Duplicate</Button>
                          <Button size="small" color="error" startIcon={<DeleteOutlineIcon />} onClick={() => setDeleteTarget(q)}>Delete</Button>
                          {q.compatibility?.status === 'incompatible' && q.question && (
                            <Button size="small" variant="outlined" onClick={() => navigate(`/analyst?ask=${encodeURIComponent(q.question ?? '')}`)}>Adapt in Analyst</Button>
                          )}
                        </>
                      } />
                  </Grid>
                ))}
              </Grid>
            )}
          </Box>

          <Box>
            <Typography variant="h6">Recommended for “{data.dataset.name}”</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              Built-in queries generated from this dataset's actual columns and validated against its schema.
            </Typography>
            {data.recommended.length === 0 ? <Card><EmptyState title="No recommended queries for these filters" /></Card> : (
              <Grid container spacing={2}>
                {data.recommended.map((q) => (
                  <Grid key={q.id} size={{ xs: 12, lg: 6 }}>
                    <QueryCard title={q.title} description={q.description} question={q.question} sql={q.sql} category={q.category} tags={[]}
                      parameters={q.parameters} badge={<Chip size="small" label="Recommended" color="primary" variant="outlined" />}
                      datasetLabel={`For ${q.dataset_name}`} compatibility={q.compatibility} meta={null}
                      running={running === q.id} onRun={() => run({ kind: 'recommended', q })} onCopy={() => copy(q.sql)}
                      actions={<Button size="small" startIcon={<BookmarkAddOutlinedIcon />} onClick={() => setSaveDraft(draftFrom(q, q.dataset_id))}>Save to my queries</Button>} />
                  </Grid>
                ))}
              </Grid>
            )}
          </Box>
        </>
      )}

      <ParamDialog target={paramTarget} onClose={() => setParamTarget(null)}
        onRun={(values) => { const t = paramTarget; setParamTarget(null); if (t) void execute(t, values); }} />
      <ConfirmDialog open={confirmOther !== null} title="Run on a different dataset?" confirmLabel="Run on this dataset"
        body={<>“{confirmOther?.q.title}” was saved for <b>{confirmOther?.q.dataset_name}</b>. Its SQL also validates against <b>{active?.name}</b>,
          so the columns exist, but their meaning may differ. Run it against <b>{active?.name}</b>?</>}
        onClose={() => setConfirmOther(null)}
        onConfirm={() => { const c = confirmOther; setConfirmOther(null); if (c) void execute({ kind: 'saved', q: c.q }, c.values, true); }} />
      <ConfirmDialog open={deleteTarget !== null} danger title={`Delete “${deleteTarget?.title}”?`} confirmLabel="Delete"
        body="This removes the saved query permanently. Query history is not affected." onClose={() => setDeleteTarget(null)} onConfirm={remove} />
      <SaveQueryDialog open={saveDraft !== null} draft={saveDraft} onClose={() => setSaveDraft(null)} onSaved={() => reload()} />
      <SaveQueryDialog open={editing !== null} existing={editing} draft={editing ? draftFrom(editing, editing.dataset_id) : null}
        onClose={() => setEditing(null)} onSaved={() => reload()} />
    </Stack>
  );
}

function QueryCard({ title, description, question, sql, category, tags, parameters, badge, datasetLabel, compatibility, meta, running, onRun, onCopy, actions }: {
  title: string; description: string | null; question: string | null; sql: string; category: string; tags: string[];
  parameters: QueryParameter[]; badge: React.ReactNode; datasetLabel: string; compatibility?: Compatibility; meta: string | null;
  running: boolean; onRun: () => void; onCopy: () => void; actions: React.ReactNode;
}) {
  const [showSql, setShowSql] = useState(false);
  const compat = compatibility ? COMPAT[compatibility.status] : null;
  const blocked = compatibility?.status === 'incompatible' || compatibility?.status === 'unavailable';
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent sx={{ p: 2, '&:last-child': { pb: 2 } }}>
        <Stack spacing={1}>
          <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap alignItems="center">
            {badge}
            <Chip size="small" variant="outlined" label={category} />
            <Chip size="small" variant="outlined" label={datasetLabel} />
            {compat && (
              <Tooltip title={compatibility?.reason ?? ''}>
                <Chip size="small" variant="outlined" color={compat.color} label={compat.label} />
              </Tooltip>
            )}
          </Stack>
          <Typography fontWeight={700}>{title}</Typography>
          {question && question !== title && <Typography variant="body2">“{question}”</Typography>}
          {description && <Typography variant="body2" color="text.secondary">{description}</Typography>}
          {parameters.length > 0 && (
            <Typography variant="caption" color="text.secondary">
              Parameters: {parameters.map((p) => `${p.name} (${p.type}${p.default !== undefined && p.default !== null && p.default !== '' ? `, default ${p.default}` : ''})`).join(', ')}
            </Typography>
          )}
          {tags.length > 0 && (
            <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>{tags.map((t) => <Chip key={t} size="small" label={`#${t}`} />)}</Stack>
          )}
          {compatibility && blocked && (
            <Alert severity="error" sx={{ py: 0 }}>
              {compatibility.reason}{compatibility.missing_columns?.length ? ` Missing columns: ${compatibility.missing_columns.join(', ')}.` : ''} {compatibility.hint ?? ''}
            </Alert>
          )}
          {meta && <Typography variant="caption" color="text.secondary">{meta}</Typography>}
          {running && <LinearProgress />}
          <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
            <Button size="small" variant="contained" startIcon={<PlayArrowRoundedIcon />} onClick={onRun} disabled={blocked || running}>Run</Button>
            <Button size="small" onClick={() => setShowSql((v) => !v)}>{showSql ? 'Hide SQL' : 'View SQL'}</Button>
            <Button size="small" startIcon={<ContentCopyIcon />} onClick={onCopy}>Copy SQL</Button>
            {actions}
          </Stack>
          <Collapse in={showSql} unmountOnExit><SqlViewer sql={sql} maxHeight={280} /></Collapse>
        </Stack>
      </CardContent>
    </Card>
  );
}

function ParamDialog({ target, onClose, onRun }: { target: RunTarget | null; onClose: () => void; onRun: (v: Record<string, unknown>) => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  useEffect(() => {
    setValues(Object.fromEntries((target?.q.parameters ?? []).map((p) => [p.name, p.default === null || p.default === undefined ? '' : String(p.default)])));
  }, [target]);
  if (!target) return null;
  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Run “{target.q.title}”</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {target.q.parameters.map((p) => (
            <TextField key={p.name} id={`param-${p.name}`} label={`${p.name} (${p.type})`} helperText={p.description || undefined}
              type={p.type === 'integer' || p.type === 'number' ? 'number' : p.type === 'date' ? 'date' : 'text'}
              InputLabelProps={p.type === 'date' ? { shrink: true } : undefined}
              value={values[p.name] ?? ''} onChange={(e) => setValues({ ...values, [p.name]: e.target.value })} />
          ))}
          <Typography variant="caption" color="text.secondary">Values are inserted as typed literals and the SQL is validated before it runs.</Typography>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={() => onRun(values)}>Run</Button>
      </DialogActions>
    </Dialog>
  );
}
