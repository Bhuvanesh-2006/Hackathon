import { Alert, Box, Chip, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { formatGBP } from '../services/format';
import { tokens } from '../theme/theme';
import type { ForecastResponse } from '../types/api';

export function ForecastView({ f }: { f: ForecastResponse }) {
  if (!f.available) return <Alert severity="info">Forecast unavailable: {f.reason}</Alert>;
  const data = [
    ...f.history.map((h) => ({ month: h.month, actual: h.actual })),
    ...f.forecast.map((p, i) => ({
      month: p.month, forecast: p.forecast, range: [p.low, p.high] as [number, number],
      ...(i === 0 ? {} : {}),
    })),
  ];
  // Join the forecast line to the last actual point.
  const lastIdx = f.history.length - 1;
  if (lastIdx >= 0) Object.assign(data[lastIdx], { forecast: f.history[lastIdx].actual });
  const best = f.evaluation.find((e) => e.method === f.selected_method);
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
        <Chip size="small" color="warning" variant="outlined" label="Estimate, not actual results" />
        <Chip size="small" label={`Method: ${f.selected_description}`} />
        {best && <Chip size="small" label={`Holdout error ${best.mape_pct}% (MAPE)`} />}
        {f.improvement_vs_naive_pct !== null && <Chip size="small" label={`${f.improvement_vs_naive_pct}% lower MAE than naive`} />}
      </Stack>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
          <CartesianGrid stroke={tokens.grid} vertical={false} />
          <XAxis dataKey="month" stroke={tokens.textMuted} tick={{ fill: tokens.textSecondary, fontSize: 12 }} tickLine={false} minTickGap={24} />
          <YAxis stroke={tokens.textMuted} tick={{ fill: tokens.textSecondary, fontSize: 12 }} tickLine={false} tickFormatter={(v: number) => formatGBP(v, true)} width={64} />
          <Tooltip formatter={(v: number | number[], name: string) => [Array.isArray(v) ? `${formatGBP(v[0], true)} – ${formatGBP(v[1], true)}` : formatGBP(v), name]}
            contentStyle={{ background: '#0b1437', border: `1px solid ${tokens.border}`, borderRadius: 8 }} labelStyle={{ color: tokens.textSecondary }} />
          <Area dataKey="range" name="Rough range" stroke="none" fill={tokens.series[2]} fillOpacity={0.18} isAnimationActive={false} />
          <Line dataKey="actual" name="Actual net revenue" stroke={tokens.series[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="forecast" name="Forecast" stroke={tokens.series[2]} strokeWidth={2} strokeDasharray="5 4" dot={{ r: 3 }} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <Stack direction="row" spacing={2} flexWrap="wrap" useFlexGap sx={{ px: 1 }}>
        <Typography variant="caption" color="text.secondary"><Box component="span" sx={{ display: 'inline-block', width: 16, height: 2, bgcolor: tokens.series[0], mr: 0.75, verticalAlign: 'middle' }} />Actual</Typography>
        <Typography variant="caption" color="text.secondary"><Box component="span" sx={{ display: 'inline-block', width: 16, height: 2, bgcolor: tokens.series[2], mr: 0.75, verticalAlign: 'middle' }} />Forecast</Typography>
        <Typography variant="caption" color="text.secondary"><Box component="span" sx={{ display: 'inline-block', width: 10, height: 10, bgcolor: tokens.series[2], opacity: 0.3, mr: 0.75, verticalAlign: 'middle' }} />Rough range</Typography>
      </Stack>
      <Box sx={{ overflowX: 'auto' }}>
        <Table size="small" sx={{ minWidth: 360 }}>
          <TableHead><TableRow><TableCell>Month</TableCell><TableCell align="right">Forecast</TableCell><TableCell align="right">Rough range</TableCell></TableRow></TableHead>
          <TableBody>
            {f.forecast.map((p) => (
              <TableRow key={p.month}>
                <TableCell>{p.month}{f.partial_month?.month === p.month ? ' *' : ''}</TableCell>
                <TableCell align="right">{formatGBP(p.forecast)}</TableCell>
                <TableCell align="right">{formatGBP(p.low, true)} – {formatGBP(p.high, true)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Box>
      {f.partial_month && (
        <Typography variant="caption" color="text.secondary">
          * Actual to date for {f.partial_month.month}: {formatGBP(f.partial_month.net_revenue_to_date)} through {f.partial_month.through} (partial month, excluded from fitting).
        </Typography>
      )}
      <Typography variant="caption" color="text.secondary">
        Trained on {f.train_period[0]}–{f.train_period[1]}, evaluated on {f.holdout_period[0]}–{f.holdout_period[1]} against{' '}
        {f.evaluation.map((e) => `${e.method} (MAPE ${e.mape_pct}%)`).join(', ')}. {f.range_note} {f.limitations.join(' ')}
      </Typography>
    </Stack>
  );
}
