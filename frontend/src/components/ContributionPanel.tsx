import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Chip, LinearProgress, Stack, ToggleButton, ToggleButtonGroup, Typography,
} from '@mui/material';
import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useAsync } from '../hooks/useAsync';
import { api } from '../services/api';
import { downloadText, toCsv } from '../services/format';
import { tokens } from '../theme/theme';
import type { Anomaly } from '../types/api';
import { formatMetric } from './AnomalyViews';
import { ErrorState } from './Feedback';
import { ChartTooltip } from './ResultChart';
import { ResultGrid } from './ResultGrid';
import { SqlViewer } from './SqlViewer';
import { useToast } from './Toast';

const DIMENSIONS = [
  { id: 'product', label: 'Product' },
  { id: 'country', label: 'Country' },
  { id: 'customer', label: 'Customer' },
  { id: 'weekday', label: 'Weekday' },
];

/** Descriptive contribution analysis for one anomaly. Every number comes from the API response. */
export function ContributionPanel({ anomaly }: { anomaly: Anomaly }) {
  const [dimension, setDimension] = useState('product');
  const notify = useToast();
  const { data, error, loading, reload } = useAsync(
    () => api.contribution({ anomaly_id: anomaly.id, dimension, top_n: 10 }),
    [anomaly.id, dimension],
  );
  const unit = anomaly.unit;
  const fmt = (v: number) => formatMetric(unit, v, true);
  const chartRows = (data?.rows ?? []).map((r) => ({
    label: r.name && r.name !== r.category ? `${r.category} · ${r.name}` : r.category,
    change: r.change,
  }));

  const exportCsv = () => {
    if (!data) return;
    const cols = ['category', 'name', 'current_value', 'comparison_value', 'change', 'share_of_change_pct', 'only_in'];
    downloadText(`contribution_${anomaly.id}_${dimension}.csv`, toCsv(cols, data.rows.map((r) => cols.map((c) => r[c as keyof typeof r]))));
    notify(`Exported ${data.rows.length} rows`);
  };

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }}>
        <Typography variant="subtitle2" sx={{ flex: 1 }}>Break the change down by</Typography>
        <ToggleButtonGroup size="small" exclusive value={dimension} onChange={(_, v) => v && setDimension(v)} aria-label="Breakdown dimension">
          {DIMENSIONS.map((d) => (
            <ToggleButton key={d.id} value={d.id} disabled={anomaly.metric === 'orders' && d.id === 'product'} sx={{ px: 1.5 }}>{d.label}</ToggleButton>
          ))}
        </ToggleButtonGroup>
      </Stack>

      {loading && <LinearProgress sx={{ borderRadius: 2 }} />}
      {error && <ErrorState error={error} onRetry={reload} />}
      {data && !error && (
        <Box sx={{ opacity: loading ? 0.6 : 1 }}>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mb: 1.5 }}>
            <Chip size="small" label={`Current: ${data.current_window.start} to ${data.current_window.end_exclusive} (${data.current_window.trading_days} trading days)`} />
            <Chip size="small" label={`Comparison: ${data.comparison_windows.length} baseline weeks (${data.comparison_trading_days} trading days, scaled ×${data.scale})`} />
            <Chip size="small" color={data.reconciled ? 'success' : 'error'} variant="outlined"
              label={data.reconciled ? 'Contributions add up to the total change' : 'Contributions do not reconcile'} />
          </Stack>
          <Typography variant="body2" sx={{ mb: 1, fontVariantNumeric: 'tabular-nums' }}>
            {data.metric_label}: {formatMetric(unit, data.totals.current)} this week vs {formatMetric(unit, data.totals.comparison)} comparison
            → change <b>{formatMetric(unit, data.totals.change)}</b>. {data.positive_contributors.toLocaleString('en-GB')} categories increased,{' '}
            {data.negative_contributors.toLocaleString('en-GB')} decreased.
          </Typography>

          <ResponsiveContainer width="100%" height={Math.max(260, chartRows.length * 32 + 40)}>
            <BarChart data={chartRows} layout="vertical" margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
              <CartesianGrid stroke={tokens.grid} horizontal={false} />
              <XAxis type="number" stroke={tokens.textMuted} tick={{ fill: tokens.textSecondary, fontSize: 12 }} tickFormatter={fmt} />
              <YAxis type="category" dataKey="label" width={170} interval={0} stroke={tokens.textMuted}
                tick={{ fill: tokens.textSecondary, fontSize: 11 }} tickFormatter={(v: string) => (v.length > 26 ? `${v.slice(0, 25)}…` : v)} />
              <ReferenceLine x={0} stroke={tokens.textMuted} />
              <Tooltip content={<ChartTooltip xKey={dimension} />} cursor={{ fill: 'rgba(160,174,192,0.08)' }} />
              <Bar dataKey="change" name={`change_${unit === 'GBP' ? 'gbp' : unit}`} maxBarSize={22} isAnimationActive={false}>
                {chartRows.map((r) => <Cell key={r.label} fill={r.change >= 0 ? tokens.series[0] : tokens.series[1]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <Stack direction="row" spacing={2} sx={{ px: 1, mb: 1.5 }}>
            <Typography variant="caption" color="text.secondary"><Box component="span" sx={{ display: 'inline-block', width: 10, height: 10, borderRadius: '3px', bgcolor: tokens.series[0], mr: 0.75 }} />Increase</Typography>
            <Typography variant="caption" color="text.secondary"><Box component="span" sx={{ display: 'inline-block', width: 10, height: 10, borderRadius: '3px', bgcolor: tokens.series[1], mr: 0.75 }} />Decrease</Typography>
          </Stack>

          <Stack direction="row" justifyContent="flex-end" sx={{ mb: 1 }}>
            <Button size="small" onClick={exportCsv}>Export CSV</Button>
          </Stack>
          <ResultGrid
            columns={[{ name: 'category', type: 'VARCHAR' }, { name: 'name', type: 'VARCHAR' }, { name: `current_${unit === 'GBP' ? 'gbp' : unit}`, type: 'DOUBLE' },
              { name: `comparison_${unit === 'GBP' ? 'gbp' : unit}`, type: 'DOUBLE' }, { name: `change_${unit === 'GBP' ? 'gbp' : unit}`, type: 'DOUBLE' },
              { name: 'share_of_change_pct', type: 'DOUBLE' }, { name: 'only_in', type: 'VARCHAR' }]}
            rows={data.rows.map((r) => [r.category, r.name, r.current_value, r.comparison_value, r.change, r.share_of_change_pct, r.only_in])}
            height={Math.min(470, 110 + data.rows.length * 37)} />

          <Alert severity="warning" sx={{ mt: 2 }}>{data.disclaimer}</Alert>
          <Accordion disableGutters sx={{ mt: 1.5, border: 1, borderColor: 'divider', borderRadius: '12px !important' }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}><Typography variant="body2" fontWeight={600}>Calculation and SQL</Typography></AccordionSummary>
            <AccordionDetails>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>{data.calculation}</Typography>
              <SqlViewer sql={data.sql} maxHeight={320} />
            </AccordionDetails>
          </Accordion>
        </Box>
      )}
    </Stack>
  );
}
