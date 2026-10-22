import BarChartIcon from '@mui/icons-material/BarChart';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import DownloadIcon from '@mui/icons-material/Download';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import GppBadOutlinedIcon from '@mui/icons-material/GppBadOutlined';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import RefreshIcon from '@mui/icons-material/Refresh';
import TableRowsOutlinedIcon from '@mui/icons-material/TableRowsOutlined';
import CodeIcon from '@mui/icons-material/Code';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import BoltIcon from '@mui/icons-material/Bolt';
import BookmarkAddOutlinedIcon from '@mui/icons-material/BookmarkAddOutlined';
import StorageOutlinedIcon from '@mui/icons-material/StorageOutlined';
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Card, CardContent, Chip, Stack, Tab, Tabs, Tooltip, Typography,
} from '@mui/material';
import { useState } from 'react';
import { downloadText, formatDuration, toCsv } from '../services/format';
import type { AgentResponse } from '../types/api';
import { StatusChip } from './Feedback';
import { ResultChart } from './ResultChart';
import { ResultGrid } from './ResultGrid';
import { EvidencePanel } from './EvidencePanel';
import { SqlViewer } from './SqlViewer';
import { useToast } from './Toast';

export function AnswerCard({ response, onClarify, onRetry, clarifyDisabled, onSave }: {
  response: AgentResponse;
  onClarify: (option: string) => void;
  onRetry: () => void;
  clarifyDisabled: boolean;
  onSave?: (response: AgentResponse) => void;
}) {
  const notify = useToast();
  const hasRows = response.columns.length > 0 && response.rows.length > 0;
  const [tab, setTab] = useState<'chart' | 'table' | 'sql' | 'evidence'>(response.chart && hasRows ? 'chart' : hasRows ? 'table' : 'sql');
  const ex = response.execution;
  const columns = response.columns.map((c) => c.name);
  const executed = ex.validated && (response.status === 'success' || response.status === 'empty');
  const sqlStage = !response.sql ? null : !ex.validated ? 'proposed' : executed ? 'executed' : 'validated';
  const cache = ex.cache;

  const exportCsv = () => {
    const safe = response.question.replace(/[^a-z0-9]+/gi, '_').slice(0, 40).toLowerCase() || 'result';
    const ds = (response.dataset?.name ?? 'dataset').replace(/[^a-z0-9]+/gi, '_').slice(0, 30).toLowerCase();
    downloadText(`retailpilot_${ds}_${safe}.csv`, toCsv(columns, response.rows));
    notify(`Exported ${response.rows.length} rows to CSV`);
  };
  const copySql = async () => {
    try {
      await navigator.clipboard.writeText(response.sql ?? '');
      notify('SQL copied to clipboard');
    } catch {
      notify('Could not access the clipboard', 'error');
    }
  };

  return (
    <Card sx={{ width: '100%' }}>
      <CardContent sx={{ p: { xs: 2, sm: 2.5 } }}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
          <StatusChip status={response.status} />
          {response.dataset && (
            <Tooltip title={`Dataset ${response.dataset.id}, version ${response.dataset.version}`}>
              <Chip size="small" icon={<StorageOutlinedIcon />} label={response.dataset.name} variant="outlined" />
            </Tooltip>
          )}
          {response.saved_query && <Chip size="small" label={`${response.saved_query.builtin ? 'Recommended' : 'Saved'} query: ${response.saved_query.title}`} variant="outlined" color="secondary" />}
          {cache?.hit && (
            <Tooltip title={`Reused a result computed ${Math.round(cache.age_seconds)} s ago on the same dataset version (${cache.dataset_version}), same SQL and parameters. Cache TTL ${cache.ttl_seconds} s.`}>
              <Chip size="small" icon={<BoltIcon />} label={`From cache · ${formatAge(cache.age_seconds)} old`} color="info" variant="outlined" />
            </Tooltip>
          )}
          {ex.validated && (
            <Tooltip title="SQL parsed with SQLGlot, read-only and allowlist checks passed before execution">
              <Chip size="small" icon={<CheckCircleOutlineIcon />} label="Validated SQL" variant="outlined" color="success" />
            </Tooltip>
          )}
          {response.status === 'rejected' && <Chip size="small" icon={<GppBadOutlinedIcon />} label="Blocked by validator" color="error" variant="outlined" />}
          {ex.regenerated && <Chip size="small" label="Regenerated once after error" variant="outlined" color="warning" />}
          {response.rerun && <Chip size="small" label="Re-run with updated filters" variant="outlined" color="info" />}
          <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto !important' }}>
            {ex.db_ms !== null && `DB ${formatDuration(ex.db_ms)} · `}Total {formatDuration(ex.total_ms)} · {ex.is_llm ? ex.model : 'offline rule-based'}
          </Typography>
        </Stack>

        <Typography variant="body1" sx={{ fontWeight: 600, whiteSpace: 'pre-wrap' }}>{response.answer}</Typography>
        {response.explanation && response.status !== 'clarification' && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>{response.explanation}</Typography>
        )}
        {response.truncated && (
          <Alert severity="info" sx={{ mt: 1.5 }}>Result limited to the first {ex.max_rows.toLocaleString('en-GB')} rows.</Alert>
        )}
        {response.stored_rows_truncated && (
          <Alert severity="info" sx={{ mt: 1.5 }}>Reopened from history: only the first 200 stored rows are shown. Ask again to re-run the query.</Alert>
        )}

        {response.status === 'clarification' && response.clarification && (
          <Box sx={{ mt: 2 }}>
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              <HelpOutlineIcon fontSize="small" color="secondary" />
              <Typography variant="body2" color="text.secondary">Choose a definition to continue this conversation:</Typography>
            </Stack>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap" useFlexGap>
              {response.clarification.options.map((o) => (
                <Button key={o} variant="outlined" color="secondary" disabled={clarifyDisabled} onClick={() => onClarify(o)} sx={{ justifyContent: 'flex-start' }}>
                  {o}
                </Button>
              ))}
            </Stack>
          </Box>
        )}

        {response.error && (
          <Alert severity={response.status === 'rejected' ? 'warning' : 'error'} sx={{ mt: 2 }}
            action={response.error.retryable ? <Button color="inherit" size="small" startIcon={<RefreshIcon />} onClick={onRetry}>Retry</Button> : undefined}>
            {response.error.message}
          </Alert>
        )}

        {(hasRows || response.sql) && (
          <Box sx={{ mt: 2 }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} alignItems={{ sm: 'center' }} spacing={1} sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
              <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" allowScrollButtonsMobile sx={{ flex: 1, minHeight: 44 }}>
                {response.chart && hasRows && <Tab value="chart" icon={<BarChartIcon fontSize="small" />} iconPosition="start" label="Chart" sx={{ minHeight: 44 }} />}
                {hasRows && <Tab value="table" icon={<TableRowsOutlinedIcon fontSize="small" />} iconPosition="start" label={`Table (${response.row_count})`} sx={{ minHeight: 44 }} />}
                {response.sql && <Tab value="sql" icon={<CodeIcon fontSize="small" />} iconPosition="start" label="SQL" sx={{ minHeight: 44 }} />}
                {response.evidence && <Tab value="evidence" icon={<FactCheckOutlinedIcon fontSize="small" />} iconPosition="start" label="Evidence" sx={{ minHeight: 44 }} />}
              </Tabs>
              <Stack direction="row" spacing={1} sx={{ pb: { xs: 1, sm: 0 } }}>
                {response.sql && <Button size="small" startIcon={<CodeIcon />} onClick={copySql}>Copy SQL</Button>}
                {onSave && executed && response.sql && (
                  <Button size="small" variant="contained" startIcon={<BookmarkAddOutlinedIcon />} onClick={() => onSave(response)}>Save query</Button>
                )}
                {hasRows && <Button size="small" startIcon={<DownloadIcon />} onClick={exportCsv}>Export CSV</Button>}
              </Stack>
            </Stack>
            {tab === 'chart' && response.chart && hasRows && (
              <>
                <ResultChart config={response.chart} columns={columns} rows={response.rows} />
                <Button size="small" startIcon={<TableRowsOutlinedIcon />} onClick={() => setTab('table')} sx={{ mt: 1 }}>
                  View the {response.row_count} rows behind this chart
                </Button>
              </>
            )}
            {tab === 'evidence' && response.evidence && <EvidencePanel evidence={response.evidence} />}
            {tab === 'table' && hasRows && <ResultGrid columns={response.columns} rows={response.rows} height={Math.min(460, 110 + Math.min(response.rows.length, 10) * 37)} />}
            {tab === 'sql' && response.sql && (
              <>
                <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap sx={{ mb: 1 }}>
                  <Chip size="small" label="1. Proposed" color="default" variant={sqlStage === 'proposed' ? 'filled' : 'outlined'} />
                  <Chip size="small" label={sqlStage === 'proposed' ? '2. Rejected by validator' : '2. Validated'} color={sqlStage === 'proposed' ? 'error' : 'success'} variant="outlined" />
                  <Chip size="small" label={executed ? (cache?.hit ? '3. Executed (result reused from cache)' : '3. Executed') : '3. Not executed'} color={executed ? 'success' : 'warning'} variant="outlined" />
                </Stack>
                <SqlViewer sql={response.sql} />
                <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 1 }}>
                  {sqlStage === 'proposed' && 'Proposed SQL: it failed validation and was NOT executed.'}
                  {sqlStage === 'validated' && 'Validated SQL, but execution did not succeed, so no result is shown as an answer.'}
                  {sqlStage === 'executed' && `This is the exact SQL that ran on the read-only connection for ${response.dataset?.name ?? 'the selected dataset'}.`}
                  {ex.timeout_s ? ` Limits: ${ex.timeout_s}s timeout, ${ex.max_rows.toLocaleString('en-GB')} rows.` : ''}
                </Typography>
              </>
            )}
          </Box>
        )}

        {response.business_rules.length > 0 && response.status !== 'clarification' && !response.evidence && (
          <Accordion disableGutters sx={{ mt: 1.5, border: 1, borderColor: 'divider', borderRadius: '12px !important' }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="body2" fontWeight={600}>Business rules applied ({response.business_rules.length})</Typography>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={1.25}>
                {response.business_rules.map((r) => (
                  <Box key={r.id}>
                    <Typography variant="body2" fontWeight={700}>{r.name}</Typography>
                    <Typography variant="body2" color="text.secondary">{r.definition}</Typography>
                  </Box>
                ))}
              </Stack>
            </AccordionDetails>
          </Accordion>
        )}
      </CardContent>
    </Card>
  );
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}
