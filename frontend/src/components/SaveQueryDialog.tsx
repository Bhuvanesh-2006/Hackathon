import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, MenuItem, Stack, TextField, Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { ApiError } from '../services/api';
import { workspaceApi } from '../services/workspaceApi';
import type { QueryParameter, SavedQuery } from '../types/workspace';
import { useToast } from './Toast';

export const CATEGORIES = ['Products', 'Revenue', 'Customers', 'Trends', 'Geography', 'Returns', 'General'];

export interface SaveDraft {
  title: string;
  question: string;
  sql: string;
  description: string;
  category: string;
  tags: string[];
  parameters: QueryParameter[];
  dataset_id: string;
  dataset_name: string;
}

/**
 * Create a saved query, or edit an existing one. When editing, the user chooses explicitly between
 * updating the original and saving a new copy, so an original is never overwritten by accident.
 */
export function SaveQueryDialog({ open, draft, existing, onClose, onSaved }: {
  open: boolean;
  draft: SaveDraft | null;
  existing?: SavedQuery | null;
  onClose: () => void;
  onSaved: (q: SavedQuery) => void;
}) {
  const notify = useToast();
  const [form, setForm] = useState<SaveDraft | null>(draft);
  const [tagText, setTagText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setForm(draft);
    setTagText(draft?.tags.join(', ') ?? '');
    setError(null);
  }, [draft, open]);

  if (!form) return null;
  const set = <K extends keyof SaveDraft>(k: K, v: SaveDraft[K]) => setForm({ ...form, [k]: v });
  const placeholders = Array.from(new Set(Array.from(form.sql.matchAll(/\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}/g)).map((m) => m[1])));

  const payload = () => ({
    title: form.title.trim(), question: form.question || null, sql: form.sql, description: form.description || null,
    category: form.category, tags: tagText.split(',').map((t) => t.trim()).filter(Boolean), parameters: form.parameters,
    dataset_id: form.dataset_id,
  });

  const save = async (mode: 'create' | 'update' | 'copy') => {
    if (!form.title.trim()) {
      setError('Give the query a title.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      let q: SavedQuery;
      if (mode === 'update' && existing) {
        const { dataset_id: _ignored, ...changes } = payload();
        void _ignored;
        q = await workspaceApi.updateSavedQuery(existing.id, changes);
        notify(`Updated “${q.title}”`);
      } else {
        q = await workspaceApi.createSavedQuery(payload());
        notify(mode === 'copy' ? `Saved a new copy “${q.title}”` : `Saved “${q.title}” to Saved Queries`);
      }
      onSaved(q);
      onClose();
    } catch (e) {
      const err = e as ApiError;
      setError(err.code === 'duplicate_title' ? `${err.message} Choose another title.` : err.message);
    } finally {
      setBusy(false);
    }
  };

  const updateParam = (i: number, patch: Partial<QueryParameter>) =>
    set('parameters', form.parameters.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} maxWidth="md" fullWidth>
      <DialogTitle>{existing ? 'Edit saved query' : 'Save query'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Chip size="small" color="primary" variant="outlined" label={`Dataset: ${form.dataset_name}`} />
            <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
              The SQL is validated against this dataset when you save and again every time it runs. Results are not stored.
            </Typography>
          </Stack>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField id="sq-title" label="Title" value={form.title} onChange={(e) => set('title', e.target.value.slice(0, 120))} required autoFocus />
          <TextField id="sq-question" label="Question" value={form.question} onChange={(e) => set('question', e.target.value.slice(0, 500))} />
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField id="sq-category" select label="Category" value={form.category} onChange={(e) => set('category', e.target.value)} sx={{ minWidth: 180 }}>
              {CATEGORIES.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}
            </TextField>
            <TextField id="sq-tags" label="Tags (comma separated)" value={tagText} onChange={(e) => setTagText(e.target.value.slice(0, 200))} fullWidth />
          </Stack>
          <TextField id="sq-description" label="Description" value={form.description} onChange={(e) => set('description', e.target.value.slice(0, 1000))} multiline minRows={2} />
          <TextField id="sq-sql" label="SQL" value={form.sql} onChange={(e) => set('sql', e.target.value)} multiline minRows={5}
            InputProps={{ sx: { fontFamily: 'JetBrains Mono, monospace', fontSize: 13 } }}
            helperText="Use {{name}} placeholders for parameters, e.g. WHERE country = {{country}}. Edited SQL is revalidated before saving." />
          <Box>
            <Stack direction="row" alignItems="center" justifyContent="space-between">
              <Typography variant="subtitle2">Parameters</Typography>
              <Button size="small" startIcon={<AddIcon />}
                onClick={() => set('parameters', [...form.parameters, { name: placeholders.find((p) => !form.parameters.some((x) => x.name === p)) ?? 'param', type: 'text', default: '', description: '' }])}>
                Add parameter
              </Button>
            </Stack>
            {placeholders.length > 0 && (
              <Typography variant="caption" color="text.secondary">Placeholders in the SQL: {placeholders.join(', ')}</Typography>
            )}
            <Stack spacing={1} sx={{ mt: 1 }}>
              {form.parameters.map((p, i) => (
                <Stack key={i} direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ sm: 'center' }}>
                  <TextField size="small" label="Name" value={p.name} onChange={(e) => updateParam(i, { name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '') })} />
                  <TextField size="small" select label="Type" value={p.type} onChange={(e) => updateParam(i, { type: e.target.value as QueryParameter['type'] })} sx={{ minWidth: 120 }}>
                    {['text', 'integer', 'number', 'date'].map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
                  </TextField>
                  <TextField size="small" label="Default" value={p.default ?? ''} onChange={(e) => updateParam(i, { default: e.target.value })} />
                  <TextField size="small" label="Description" value={p.description ?? ''} onChange={(e) => updateParam(i, { description: e.target.value })} sx={{ flex: 1 }} />
                  <IconButton aria-label={`Remove parameter ${p.name}`} onClick={() => set('parameters', form.parameters.filter((_, j) => j !== i))}><DeleteOutlineIcon /></IconButton>
                </Stack>
              ))}
            </Stack>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ flexWrap: 'wrap', gap: 1 }}>
        <Button onClick={onClose} disabled={busy}>Cancel</Button>
        {existing ? (
          <>
            <Button variant="outlined" onClick={() => save('copy')} disabled={busy}>Save as new copy</Button>
            <Button variant="contained" onClick={() => save('update')} disabled={busy}>Update original</Button>
          </>
        ) : (
          <Button variant="contained" onClick={() => save('create')} disabled={busy}>Save query</Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
