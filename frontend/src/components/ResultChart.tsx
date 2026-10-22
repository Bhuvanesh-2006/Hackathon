import { Box, Stack, Typography } from '@mui/material';
import { useMemo } from 'react';
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { formatCell, formatGBP, formatNumber, humanize, isMoneyColumn } from '../services/format';
import { tokens } from '../theme/theme';
import type { ChartConfig } from '../types/api';

const axisProps = {
  stroke: tokens.textMuted,
  tick: { fill: tokens.textSecondary, fontSize: 12 },
  tickLine: false,
  axisLine: { stroke: tokens.grid },
};

export function ChartTooltip({ active, payload, label, xKey }: {
  active?: boolean;
  payload?: { name: string; value: number; color: string; dataKey: string }[];
  label?: string;
  xKey?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <Box sx={{ bgcolor: '#0b1437', border: `1px solid ${tokens.border}`, borderRadius: 2, px: 1.5, py: 1, boxShadow: 6, maxWidth: 280 }}>
      <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 0.5 }}>
        {xKey ? `${humanize(xKey)}: ` : ''}{label}
      </Typography>
      {payload.map((p) => (
        <Stack key={p.dataKey} direction="row" spacing={1} alignItems="center">
          <Box sx={{ width: 10, height: 10, borderRadius: '3px', bgcolor: p.color, flexShrink: 0 }} />
          <Typography variant="body2" color="text.secondary">{humanize(p.name)}</Typography>
          <Typography variant="body2" fontWeight={700} sx={{ ml: 'auto', pl: 1 }}>{formatCell(p.dataKey, p.value)}</Typography>
        </Stack>
      ))}
    </Box>
  );
}

function axisFormatter(col: string) {
  return (v: number) => (isMoneyColumn(col) ? formatGBP(v, true) : formatNumber(v, true));
}

function truncate(s: string, n = 22) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** Renders the chart chosen by the backend from the rows the query actually returned. */
export function ResultChart({ config, columns, rows, height = 320 }: {
  config: ChartConfig;
  columns: string[];
  rows: unknown[][];
  height?: number;
}) {
  const data = useMemo(
    () => rows.map((r) => Object.fromEntries(columns.map((c, i) => [c, r[i] === null ? null : r[i]]))),
    [columns, rows],
  );
  // One value axis only: a second series is plotted only when it shares the first one's unit.
  const candidates = config.y.filter((y) => columns.includes(y));
  const ys = candidates.slice(0, 1).concat(
    candidates.slice(1, 2).filter((y) => isMoneyColumn(y) === isMoneyColumn(candidates[0])),
  );
  if (!columns.includes(config.x) || ys.length === 0) return null;
  const labelsLong = data.some((d) => String(d[config.x] ?? '').length > 10);

  if (config.type === 'line') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
          <CartesianGrid stroke={tokens.grid} vertical={false} />
          <XAxis dataKey={config.x} {...axisProps} minTickGap={24} />
          <YAxis {...axisProps} tickFormatter={axisFormatter(ys[0])} width={72} />
          <Tooltip content={<ChartTooltip xKey={config.x} />} cursor={{ stroke: tokens.textMuted, strokeDasharray: '3 3' }} />
          {ys.length > 1 && <Legend formatter={(v: string) => humanize(v)} wrapperStyle={{ fontSize: 12 }} />}
          {ys.map((y, i) => (
            <Line key={y} type="monotone" dataKey={y} name={y} stroke={tokens.series[i]} strokeWidth={2}
              dot={data.length <= 30 ? { r: 3, strokeWidth: 0, fill: tokens.series[i] } : false}
              activeDot={{ r: 5, stroke: tokens.card, strokeWidth: 2 }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (config.type === 'pie' && data.length <= 6) {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Tooltip content={<ChartTooltip xKey={config.x} />} />
          <Legend formatter={(v: string) => v} wrapperStyle={{ fontSize: 12 }} />
          <Pie data={data} dataKey={ys[0]} nameKey={config.x} innerRadius="55%" outerRadius="80%" paddingAngle={2} stroke={tokens.card} strokeWidth={2}>
            {data.map((_, i) => (
              <Cell key={i} fill={tokens.series[i % tokens.series.length]} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    );
  }

  // Bar: horizontal for rankings with long labels or many categories (labels stay legible on
  // phones); vertical for short category sets.
  const horizontal = labelsLong || (data.length > 6 && data.length <= 30);
  const h = horizontal ? Math.max(height, data.length * 34 + 40) : height;
  return (
    <ResponsiveContainer width="100%" height={h}>
      <BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: 8, right: 16, left: 4, bottom: 4 }} barCategoryGap="22%">
        <CartesianGrid stroke={tokens.grid} horizontal={!horizontal} vertical={horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" {...axisProps} tickFormatter={axisFormatter(ys[0])} />
            <YAxis type="category" dataKey={config.x} {...axisProps} width={150} tickFormatter={(v: string) => truncate(String(v))} interval={0} />
          </>
        ) : (
          <>
            <XAxis dataKey={config.x} {...axisProps} interval={data.length > 12 ? 'preserveStartEnd' : 0} tickFormatter={(v: string) => truncate(String(v), 12)} />
            <YAxis {...axisProps} tickFormatter={axisFormatter(ys[0])} width={72} />
          </>
        )}
        <Tooltip content={<ChartTooltip xKey={config.x} />} cursor={{ fill: 'rgba(160,174,192,0.08)' }} />
        {ys.length > 1 && <Legend formatter={(v: string) => humanize(v)} wrapperStyle={{ fontSize: 12 }} />}
        {ys.map((y, i) => (
          <Bar key={y} dataKey={y} name={y} fill={tokens.series[i]} radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={28} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
