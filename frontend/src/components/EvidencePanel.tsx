import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { Alert, Box, Chip, Grid2 as Grid, Stack, Typography } from '@mui/material';
import { formatNumber } from '../services/format';
import type { Evidence } from '../types/api';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={{ xs: 0.25, sm: 2 }} sx={{ py: 0.75, borderBottom: 1, borderColor: 'divider' }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 170, flexShrink: 0 }}>{label}</Typography>
      <Box sx={{ minWidth: 0, fontSize: 14 }}>{children}</Box>
    </Stack>
  );
}

/** Evidence derived from the executed SQL and its result: nothing here is model-generated. */
export function EvidencePanel({ evidence }: { evidence: Evidence }) {
  const v = evidence.verification;
  return (
    <Stack spacing={2}>
      <Alert severity="info" icon={<InfoOutlinedIcon />} sx={{ alignItems: 'center' }}>
        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
          <Chip size="small" icon={<CheckCircleOutlineIcon />} color="success" variant="outlined" label="Validated" />
          <Chip size="small" icon={<CheckCircleOutlineIcon />} color="success" variant="outlined" label="Executed on dataset" />
          <Chip size="small" color="warning" variant="outlined" label="Interpretation not independently verified" />
        </Stack>
        <Typography variant="body2" sx={{ mt: 1 }}>{v.note}</Typography>
      </Alert>

      <Box>
        <Row label="Active filters">
          {evidence.filters.length ? (
            <Stack direction="row" spacing={0.75} flexWrap="wrap" useFlexGap>
              {evidence.filters.map((f) => <Chip key={f.field} size="small" label={f.label} />)}
            </Stack>
          ) : 'None (beyond the metric definitions)'}
        </Row>
        <Row label="Date range">
          {evidence.date_range.from} to {evidence.date_range.to} <Typography component="span" variant="caption" color="text.secondary">({evidence.date_range.source})</Typography>
        </Row>
        {evidence.comparison && (
          <Row label="Comparison">
            Current {evidence.comparison.current[0]} to {evidence.comparison.current[1]} vs previous {evidence.comparison.previous[0]} to {evidence.comparison.previous[1]} (end dates exclusive)
          </Row>
        )}
        <Row label="Grouped by">{evidence.grouping.length ? evidence.grouping.map((g) => <code key={g} style={{ marginRight: 8 }}>{g}</code>) : 'No grouping (single total)'}</Row>
        <Row label="Source rows scanned">
          {evidence.source_row_count !== null ? `${formatNumber(evidence.source_row_count)} transaction lines matched the query's filter` : evidence.source_row_note}
        </Row>
        <Row label="Rows returned">{formatNumber(evidence.result_rows)}</Row>
      </Box>

      {evidence.limitations.length > 0 && (
        <Box>
          <Typography variant="overline" color="text.secondary">Data limitations</Typography>
          <Stack component="ul" spacing={0.5} sx={{ m: 0, pl: 2.5 }}>
            {evidence.limitations.map((l) => <Typography component="li" variant="body2" key={l}>{l}</Typography>)}
          </Stack>
        </Box>
      )}

      {evidence.metric_definitions.length > 0 && (
        <Box>
          <Typography variant="overline" color="text.secondary">Metric definitions applied</Typography>
          <Grid container spacing={1.5}>
            {evidence.metric_definitions.map((r) => (
              <Grid key={r.id} size={{ xs: 12, md: 6 }}>
                <Box sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2, height: '100%' }}>
                  <Typography variant="body2" fontWeight={700}>{r.name}</Typography>
                  <Typography variant="body2" color="text.secondary">{r.definition}</Typography>
                </Box>
              </Grid>
            ))}
          </Grid>
        </Box>
      )}

      {evidence.retrieval && (evidence.retrieval.examples.length > 0 || evidence.retrieval.notes.length > 0) && (
        <Box>
          <Typography variant="overline" color="text.secondary">Retrieved for the model ({evidence.retrieval.backend})</Typography>
          <Stack spacing={0.5}>
            {evidence.retrieval.examples.map((e) => (
              <Typography key={e.id} variant="body2">Verified example: “{e.question}” <Typography component="span" variant="caption" color="text.secondary">similarity {e.score}</Typography></Typography>
            ))}
            {evidence.retrieval.notes.map((n) => (
              <Typography key={n.id} variant="body2" color="text.secondary">Note: {n.text}</Typography>
            ))}
          </Stack>
        </Box>
      )}
    </Stack>
  );
}
