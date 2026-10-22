import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import ReportProblemOutlinedIcon from '@mui/icons-material/ReportProblemOutlined';
import TrendingDownIcon from '@mui/icons-material/TrendingDown';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import { Box, Chip, Stack, Typography } from '@mui/material';
import { useMemo } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { formatGBP, formatNumber } from '../services/format';
import { tokens } from '../theme/theme';
import type { Anomaly, AnomalyResponse } from '../types/api';
import { ChartTooltip } from './ResultChart';

export const SEVERITY_COLOR = { high: '#ff5b5b', medium: tokens.warning } as const;

export function formatMetric(unit: string, v: number | null | undefined, compact = false): string {
  return unit === 'GBP' ? formatGBP(v ?? null, compact) : formatNumber(v ?? null, compact);
}

export function SeverityChip({ severity }: { severity: 'high' | 'medium' }) {
  return (
    <Chip size="small" variant="outlined" label={severity === 'high' ? 'High' : 'Medium'}
      icon={severity === 'high' ? <ErrorOutlineIcon /> : <ReportProblemOutlinedIcon />}
      sx={{ color: SEVERITY_COLOR[severity], borderColor: SEVERITY_COLOR[severity], '& .MuiChip-icon': { color: SEVERITY_COLOR[severity] } }} />
  );
}

export function AnomalySummary({ a, compact = false }: { a: Anomaly; compact?: boolean }) {
  const Icon = a.kind === 'spike' ? TrendingUpIcon : TrendingDownIcon;
  return (
    <Stack spacing={0.5} sx={{ minWidth: 0 }}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
        <SeverityChip severity={a.severity} />
        <Typography variant="body2" fontWeight={700}>{a.metric_label} {a.kind}</Typography>
        <Icon fontSize="small" sx={{ color: 'text.secondary' }} />
        {a.seasonal?.recurring && <Chip size="small" variant="outlined" label="Also last year" />}
      </Stack>
      <Typography variant="caption" color="text.secondary">Week of {a.period_start} · {a.trading_days} trading days</Typography>
      <Typography variant="body2" sx={{ fontVariantNumeric: 'tabular-nums' }}>
        {formatMetric(a.unit, a.observed, compact)} vs expected {formatMetric(a.unit, a.expected, compact)}
        <Box component="span" sx={{ color: 'text.secondary' }}> ({a.deviation_pct !== null && a.deviation_pct > 0 ? '+' : ''}{a.deviation_pct}% · z {a.robust_z})</Box>
      </Typography>
    </Stack>
  );
}

/** Weekly per-trading-day series with every alert of this metric marked; baseline window shaded. */
export function AnomalyChart({ data, metric, selected, height = 300 }: {
  data: AnomalyResponse;
  metric: string;
  selected?: Anomaly | null;
  height?: number;
}) {
  const unit = data.metrics[metric]?.unit ?? '';
  const series = useMemo(
    () => (data.series[metric] ?? []).map((w) => ({
      week: w.week_start,
      per_day: w.value === null || !w.trading_days ? null : Math.round((w.value / w.trading_days) * 100) / 100,
    })),
    [data, metric],
  );
  const alerts = data.anomalies.filter((a) => a.metric === metric);
  const fmt = (v: number) => formatMetric(unit, v, true);
  return (
    <Box>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={series} margin={{ top: 12, right: 16, left: 4, bottom: 4 }}>
          <CartesianGrid stroke={tokens.grid} vertical={false} />
          <XAxis dataKey="week" stroke={tokens.textMuted} tick={{ fill: tokens.textSecondary, fontSize: 12 }} tickLine={false} minTickGap={32} />
          <YAxis stroke={tokens.textMuted} tick={{ fill: tokens.textSecondary, fontSize: 12 }} tickLine={false} tickFormatter={fmt} width={64} />
          <Tooltip content={<ChartTooltip xKey="week_start" />} cursor={{ stroke: tokens.textMuted, strokeDasharray: '3 3' }} />
          {selected && selected.metric === metric && (
            <ReferenceArea x1={selected.baseline_weeks[0]} x2={selected.period_start} fill={tokens.series[0]} fillOpacity={0.08}
              ifOverflow="extendDomain" />
          )}
          <Line type="monotone" dataKey="per_day" name={`${data.metrics[metric]?.label} per trading day`} stroke={tokens.series[0]}
            strokeWidth={2} dot={false} activeDot={{ r: 4 }} connectNulls={false} isAnimationActive={false} />
          {alerts.map((a) => {
            const pt = series.find((s) => s.week === a.period_start);
            if (!pt || pt.per_day === null) return null;
            const isSel = selected?.id === a.id;
            return (
              <ReferenceDot key={a.id} x={a.period_start} y={pt.per_day} r={isSel ? 7 : 5} fill={SEVERITY_COLOR[a.severity]}
                stroke={tokens.card} strokeWidth={2} />
            );
          })}
        </LineChart>
      </ResponsiveContainer>
      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ px: 1 }}>
        <Legend color={tokens.series[0]} label="Per trading day" line />
        <Legend color={SEVERITY_COLOR.high} label="High alert" />
        <Legend color={SEVERITY_COLOR.medium} label="Medium alert" />
        {selected && <Legend color={tokens.series[0]} label="Baseline window" area />}
      </Stack>
    </Box>
  );
}

function Legend({ color, label, line = false, area = false }: { color: string; label: string; line?: boolean; area?: boolean }) {
  return (
    <Stack direction="row" spacing={0.75} alignItems="center">
      <Box sx={{
        width: line ? 16 : 10, height: line ? 2 : 10, borderRadius: line ? 1 : area ? '3px' : '50%',
        bgcolor: color, opacity: area ? 0.35 : 1,
      }} />
      <Typography variant="caption" color="text.secondary">{label}</Typography>
    </Stack>
  );
}
