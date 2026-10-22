import ForumOutlinedIcon from '@mui/icons-material/ForumOutlined';
import {
  Alert, Box, Button, Card, CardActionArea, Chip, Grid2 as Grid, MenuItem, Stack, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, TextField, Typography,
} from '@mui/material';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { AnomalyChart, AnomalySummary, formatMetric } from '../components/AnomalyViews';
import { SectionCard } from '../components/Cards';
import { ContributionPanel } from '../components/ContributionPanel';
import { CardSkeleton, EmptyState, ErrorState } from '../components/Feedback';
import { useToast } from '../components/Toast';
import { useAsync } from '../hooks/useAsync';
import { api } from '../services/api';
import type { Anomaly } from '../types/api';

export default function AnomaliesPage() {
  const { data, error, loading, reload } = useAsync(() => api.anomalies(), []);
  const [params, setParams] = useSearchParams();
  const [metric, setMetric] = useState('');
  const [severity, setSeverity] = useState('');
  const [starting, setStarting] = useState(false);
  const detailRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const notify = useToast();

  const list = useMemo(
    () => (data?.anomalies ?? []).filter((a) => (!metric || a.metric === metric) && (!severity || a.severity === severity)),
    [data, metric, severity],
  );
  const selectedId = params.get('id');
  const selected: Anomaly | null = list.find((a) => a.id === selectedId) ?? data?.anomalies.find((a) => a.id === selectedId) ?? list[0] ?? null;

  useEffect(() => {
    if (selectedId && detailRef.current && window.innerWidth < 900) detailRef.current.scrollIntoView({ behavior: 'smooth' });
  }, [selectedId]);

  const select = (id: string) => setParams({ id }, { replace: true });

  const askAnalyst = async (a: Anomaly) => {
    setStarting(true);
    try {
      const r = await api.createConversation(a.id);
      navigate(`/analyst?conversation=${r.conversation_id}`);
    } catch (e) {
      notify((e as Error).message, 'error');
    } finally {
      setStarting(false);
    }
  };

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (loading || !data) return <CardSkeleton height={420} />;

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5">Anomalies & investigation</Typography>
        <Typography variant="body2" color="text.secondary">{data.method} {data.weeks_analysed} weeks analysed; {data.skipped_weeks.length} weeks skipped for low coverage or short history.</Typography>
      </Box>
      <Alert severity="info">{data.disclaimer} Severity rule: medium when |z| ≥ {data.config.z_medium} and the change is at least {Math.round(Number(data.config.min_relative_change) * 100)}%; high when |z| ≥ {data.config.z_high}.</Alert>

      <Grid container spacing={2.5}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Stack spacing={1.5}>
            <Stack direction="row" spacing={1.5}>
              <TextField select size="small" label="Metric" value={metric} onChange={(e) => setMetric(e.target.value)} sx={{ flex: 1 }}>
                <MenuItem value="">All metrics</MenuItem>
                {Object.entries(data.metrics).map(([k, m]) => <MenuItem key={k} value={k}>{m.label}</MenuItem>)}
              </TextField>
              <TextField select size="small" label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)} sx={{ flex: 1 }}>
                <MenuItem value="">All</MenuItem>
                <MenuItem value="high">High</MenuItem>
                <MenuItem value="medium">Medium</MenuItem>
              </TextField>
            </Stack>
            <Typography variant="caption" color="text.secondary">{list.length} alerts</Typography>
            {list.length === 0 && <Card><EmptyState title="No alerts match these filters" /></Card>}
            <Stack spacing={1} sx={{ maxHeight: { md: 900 }, overflowY: { md: 'auto' }, pr: { md: 0.5 } }}>
              {list.map((a) => (
                <Card key={a.id} sx={{ flexShrink: 0, borderColor: selected?.id === a.id ? 'primary.main' : undefined }}>
                  <CardActionArea onClick={() => select(a.id)} sx={{ p: 1.75 }}>
                    <AnomalySummary a={a} compact />
                  </CardActionArea>
                </Card>
              ))}
            </Stack>
          </Stack>
        </Grid>

        <Grid size={{ xs: 12, md: 8 }} ref={detailRef}>
          {!selected ? <Card><EmptyState title="Select an alert to investigate" /></Card> : (
            <Stack spacing={2.5}>
              <SectionCard title={`${selected.metric_label} ${selected.kind}: week of ${selected.period_start}`}
                subtitle={`${selected.period_start} to ${selected.period_end} · ${selected.trading_days} trading days`}
                action={<Button variant="contained" startIcon={<ForumOutlinedIcon />} onClick={() => askAnalyst(selected)} disabled={starting}>Ask the analyst</Button>}>
                <Grid container spacing={1.5} sx={{ mb: 2 }}>
                  {[
                    ['Observed', formatMetric(selected.unit, selected.observed)],
                    ['Expected (median baseline)', formatMetric(selected.unit, selected.expected)],
                    ['Deviation', `${formatMetric(selected.unit, selected.deviation)} (${selected.deviation_pct}%)`],
                    ['Robust z-score', String(selected.robust_z)],
                  ].map(([k, v]) => (
                    <Grid key={k} size={{ xs: 6, sm: 3 }}>
                      <Box sx={{ p: 1.5, border: 1, borderColor: 'divider', borderRadius: 2, height: '100%' }}>
                        <Typography variant="caption" color="text.secondary">{k}</Typography>
                        <Typography fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>{v}</Typography>
                      </Box>
                    </Grid>
                  ))}
                </Grid>
                <AnomalyChart data={data} metric={selected.metric} selected={selected} />
                {selected.notes.length > 0 && (
                  <Stack component="ul" spacing={0.5} sx={{ mt: 2, mb: 0, pl: 2.5 }}>
                    {selected.notes.map((n) => <Typography component="li" variant="body2" key={n}>{n}</Typography>)}
                  </Stack>
                )}
                {selected.seasonal && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    Same week last year ({selected.seasonal.last_year_week}): {formatMetric(selected.unit, selected.seasonal.last_year_observed)}, z {selected.seasonal.last_year_robust_z}.
                  </Typography>
                )}
              </SectionCard>

              <SectionCard title="Investigate: what accounts for the change?" subtitle="Contribution analysis against the same baseline weeks, scaled to equal trading days">
                <ContributionPanel anomaly={selected} />
              </SectionCard>

              <SectionCard title="Evidence: baseline weeks">
                <TableContainer sx={{ overflowX: 'auto' }}>
                  <Table size="small" sx={{ minWidth: 460 }}>
                    <TableHead><TableRow><TableCell>Week</TableCell><TableCell align="right">Trading days</TableCell><TableCell align="right">Value</TableCell><TableCell align="right">Per day</TableCell><TableCell /></TableRow></TableHead>
                    <TableBody>
                      {selected.evidence.map((e) => (
                        <TableRow key={e.week_start} selected={e.role === 'observed'}>
                          <TableCell>{e.week_start}</TableCell>
                          <TableCell align="right">{e.trading_days}</TableCell>
                          <TableCell align="right">{formatMetric(selected.unit, e.value)}</TableCell>
                          <TableCell align="right">{formatMetric(selected.unit, e.per_day)}</TableCell>
                          <TableCell>{e.role === 'observed' ? <Chip size="small" label="Observed" color="primary" variant="outlined" /> : 'Baseline'}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </SectionCard>
            </Stack>
          )}
        </Grid>
      </Grid>
    </Stack>
  );
}
