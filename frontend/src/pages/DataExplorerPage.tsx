import SearchIcon from '@mui/icons-material/Search';
import {
  Box, Chip, Grid2 as Grid, InputAdornment, LinearProgress, MenuItem, Stack, Table, TableBody, TableCell, TableContainer,
  TableHead, TableRow, TablePagination, TextField, Typography,
} from '@mui/material';
import { useEffect, useState } from 'react';
import { KpiCard, SectionCard } from '../components/Cards';
import { CardSkeleton, ErrorState } from '../components/Feedback';
import { ResultGrid } from '../components/ResultGrid';
import { useAsync } from '../hooks/useAsync';
import { api } from '../services/api';
import { formatCell, formatGBP, formatNumber } from '../services/format';
import { tokens } from '../theme/theme';
import StorageOutlinedIcon from '@mui/icons-material/StorageOutlined';
import EventOutlinedIcon from '@mui/icons-material/EventOutlined';
import PersonOffOutlinedIcon from '@mui/icons-material/PersonOffOutlined';
import UndoOutlinedIcon from '@mui/icons-material/UndoOutlined';

export default function DataExplorerPage() {
  const schema = useAsync(() => api.schema(), []);
  if (schema.error) return <ErrorState error={schema.error} onRetry={schema.reload} />;
  const s = schema.data;
  const q = s?.quality;

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5">Data Explorer</Typography>
        <Typography variant="body2" color="text.secondary">
          Table <code>transactions</code> in a local read-only DuckDB database, prepared from the UCI Online Retail II workbook.
        </Typography>
      </Box>

      <Grid container spacing={2.5}>
        {!s || !q ? [0, 1, 2, 3].map((i) => <Grid key={i} size={{ xs: 12, sm: 6, lg: 3 }}><CardSkeleton height={110} /></Grid>) : (
          <>
            <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
              <KpiCard label="Records loaded" value={formatNumber(s.row_count)} icon={<StorageOutlinedIcon />}
                caption={`${formatNumber(s.metadata.source_rows_total)} source rows − ${formatNumber(s.metadata.overlap_rows_removed)} overlap`} />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
              <KpiCard label="Reporting period" value={`${s.metadata.min_invoice_date?.slice(0, 7)} → ${s.metadata.max_invoice_date?.slice(0, 7)}`}
                icon={<EventOutlinedIcon />} caption={`${s.metadata.min_invoice_date?.slice(0, 10)} to ${s.metadata.max_invoice_date?.slice(0, 10)}`} />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
              <KpiCard label="Cancellation invoices" value={formatNumber(q.cancellation_invoices)} icon={<UndoOutlinedIcon />} accent={tokens.purple}
                caption={`${formatNumber(q.cancellation_lines)} lines · ${formatGBP(q.cancelled_value, true)}`} />
            </Grid>
            <Grid size={{ xs: 12, sm: 6, lg: 3 }}>
              <KpiCard label="Lines without customer ID" value={formatNumber(q.lines_missing_customer)} icon={<PersonOffOutlinedIcon />} accent="#475089"
                caption={`${((100 * q.lines_missing_customer) / s.row_count).toFixed(1)}% of lines · kept in totals`} />
            </Grid>
          </>
        )}
      </Grid>

      {!s ? <CardSkeleton height={400} /> : (
        <Grid container spacing={2.5}>
          <Grid size={{ xs: 12, lg: 7 }}>
            <SectionCard title="Columns & missing values" subtitle="Derived columns (line_type, item_type, has_customer…) are computed during preparation">
              <TableContainer sx={{ overflowX: 'auto' }}>
                <Table size="small" sx={{ minWidth: 560 }}>
                  <TableHead>
                    <TableRow>
                      <TableCell>Column</TableCell><TableCell>Type</TableCell><TableCell align="right">Missing</TableCell>
                      <TableCell sx={{ width: 120 }}>Missing %</TableCell><TableCell align="right">≈ Distinct</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {s.columns.map((c) => (
                      <TableRow key={c.name} hover>
                        <TableCell>
                          <Typography variant="body2" fontWeight={700} fontFamily="JetBrains Mono, monospace" fontSize={13}>{c.name}</Typography>
                          <Typography variant="caption" color="text.secondary">{c.description}</Typography>
                        </TableCell>
                        <TableCell><Chip size="small" label={c.type} variant="outlined" /></TableCell>
                        <TableCell align="right">{formatNumber(c.missing)}</TableCell>
                        <TableCell>
                          <Stack direction="row" spacing={1} alignItems="center">
                            <LinearProgress variant="determinate" value={Math.min(100, c.missing_pct)} sx={{ flex: 1, height: 6, borderRadius: 3 }} color={c.missing_pct > 5 ? 'warning' : 'primary'} />
                            <Typography variant="caption" sx={{ minWidth: 40 }}>{c.missing_pct}%</Typography>
                          </Stack>
                        </TableCell>
                        <TableCell align="right">{formatNumber(c.approx_distinct)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </SectionCard>
          </Grid>
          <Grid size={{ xs: 12, lg: 5 }}>
            <Stack spacing={2.5}>
              <SectionCard title="Cancellations, returns & negative quantities">
                <Stack spacing={1}>
                  {q && [
                    ['Lines with negative quantity', formatNumber(q.negative_quantity_lines)],
                    ['… on cancellation (C) invoices', formatNumber(q.negative_qty_cancellations)],
                    ['… stock adjustments (not returns)', formatNumber(q.negative_qty_stock_adjustments)],
                    ['Cancelled / returned units', formatNumber(q.cancelled_units)],
                    ['Cancelled value', formatGBP(q.cancelled_value)],
                    ['Invoices without customer ID', formatNumber(q.invoices_missing_customer)],
                    ['Net revenue without customer ID', formatGBP(q.net_revenue_missing_customer)],
                    ['Exact duplicate rows (retained)', formatNumber(s.metadata.exact_duplicate_rows_retained)],
                  ].map(([k, v]) => (
                    <Stack key={k} direction="row" justifyContent="space-between" spacing={2}>
                      <Typography variant="body2" color="text.secondary">{k}</Typography>
                      <Typography variant="body2" fontWeight={700}>{v}</Typography>
                    </Stack>
                  ))}
                </Stack>
              </SectionCard>
              <SectionCard title="Line types">
                <BreakdownTable rows={s.line_types.map((l) => [l.line_type, l.lines, l.amount, s.line_type_definitions[l.line_type]])} />
              </SectionCard>
            </Stack>
          </Grid>
          <Grid size={12}>
            <SectionCard title="Item types (non-product codes)" subtitle="Classified from stock codes; excluded from product revenue and rankings">
              <BreakdownTable rows={s.item_types.map((l) => [l.item_type, l.lines, l.amount, l.codes ? `Codes: ${l.codes.length > 160 ? l.codes.slice(0, 160) + '…' : l.codes}` : s.item_type_definitions[l.item_type]])} />
            </SectionCard>
          </Grid>
          <Grid size={12}>
            <SectionCard title="Business definitions" subtitle="The same definitions are given to the agent and used by the dashboard and benchmark">
              <Grid container spacing={2}>
                {s.business_rules.map((r) => (
                  <Grid key={r.id} size={{ xs: 12, md: 6 }}>
                    <Box sx={{ p: 2, borderRadius: 3, border: 1, borderColor: 'divider', height: '100%' }}>
                      <Typography variant="subtitle2">{r.name}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{r.definition}</Typography>
                      {r.sql && <Box component="code" sx={{ display: 'block', mt: 1, fontSize: 12, fontFamily: 'JetBrains Mono, monospace', color: '#9cdcfe', wordBreak: 'break-word' }}>{r.sql}</Box>}
                    </Box>
                  </Grid>
                ))}
              </Grid>
            </SectionCard>
          </Grid>
        </Grid>
      )}

      <SampleRows lineTypes={s ? Object.keys(s.line_type_definitions) : []} itemTypes={s ? Object.keys(s.item_type_definitions) : []} />
    </Stack>
  );
}

function BreakdownTable({ rows }: { rows: [string, number, number, string | undefined][] }) {
  return (
    <TableContainer sx={{ overflowX: 'auto' }}>
      <Table size="small" sx={{ minWidth: 420 }}>
        <TableHead>
          <TableRow><TableCell>Type</TableCell><TableCell align="right">Lines</TableCell><TableCell align="right">Amount</TableCell></TableRow>
        </TableHead>
        <TableBody>
          {rows.map(([name, lines, amount, desc]) => (
            <TableRow key={name}>
              <TableCell>
                <Typography variant="body2" fontWeight={700}>{name}</Typography>
                {desc && <Typography variant="caption" color="text.secondary">{desc}</Typography>}
              </TableCell>
              <TableCell align="right">{formatNumber(lines)}</TableCell>
              <TableCell align="right">{formatGBP(amount)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

function SampleRows({ lineTypes, itemTypes }: { lineTypes: string[]; itemTypes: string[] }) {
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const [lineType, setLineType] = useState('');
  const [itemType, setItemType] = useState('');
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);
  useEffect(() => setPage(0), [lineType, itemType, debounced, pageSize]);
  const { data, error, loading, reload } = useAsync(
    () => api.preview({ limit: pageSize, offset: page * pageSize, line_type: lineType, item_type: itemType, search: debounced }),
    [page, pageSize, lineType, itemType, debounced],
  );

  return (
    <SectionCard title="Sample transaction rows" subtitle="Filter to inspect cancellations, stock adjustments or non-product lines">
      <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} sx={{ mb: 2 }}>
        <TextField size="small" placeholder="Search invoice, stock code, description or customer ID" value={search} onChange={(e) => setSearch(e.target.value.slice(0, 60))}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} sx={{ flex: 1 }} />
        <TextField select size="small" label="Line type" value={lineType} onChange={(e) => setLineType(e.target.value)} sx={{ minWidth: 200 }}>
          <MenuItem value="">All line types</MenuItem>
          {lineTypes.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Item type" value={itemType} onChange={(e) => setItemType(e.target.value)} sx={{ minWidth: 200 }}>
          <MenuItem value="">All item types</MenuItem>
          {itemTypes.map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
        </TextField>
      </Stack>
      {error ? <ErrorState error={error} onRetry={reload} /> : (
        <>
          {loading && <LinearProgress sx={{ mb: 1, borderRadius: 2 }} />}
          {data && (
            <Box sx={{ opacity: loading ? 0.6 : 1 }}>
              <ResultGrid columns={data.columns.map((c) => ({ name: c }))} rows={data.rows} height={440} pageSize={100} hideFooter key={`${page}-${pageSize}-${data.rows.length}`} />
              <TablePagination component="div" count={data.total} page={page} onPageChange={(_, p) => setPage(p)} rowsPerPage={pageSize}
                onRowsPerPageChange={(e) => setPageSize(Number(e.target.value))} rowsPerPageOptions={[25, 50, 100]}
                labelDisplayedRows={({ from, to, count }) => `${formatCell('n', from)}–${formatCell('n', to)} of ${formatCell('n', count)} matching rows`} />
            </Box>
          )}
        </>
      )}
    </SectionCard>
  );
}
