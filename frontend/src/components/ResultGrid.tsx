import { Box } from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useMemo } from 'react';
import { formatCell, humanize } from '../services/format';
import { tokens } from '../theme/theme';

const NUMERIC = /^(BIGINT|INTEGER|HUGEINT|SMALLINT|TINYINT|DOUBLE|FLOAT|REAL|DECIMAL)/i;

export function ResultGrid({ columns, rows, height = 420, pageSize = 10, hideFooter = false }: {
  columns: { name: string; type?: string }[];
  rows: unknown[][];
  height?: number;
  pageSize?: number;
  hideFooter?: boolean;
}) {
  const cols: GridColDef[] = useMemo(
    () =>
      columns.map((c, i) => {
        const numeric = c.type ? NUMERIC.test(c.type) : rows.some((r) => typeof r[i] === 'number');
        return {
          field: `c${i}`,
          headerName: humanize(c.name),
          description: c.name,
          minWidth: numeric ? 120 : 140,
          flex: numeric ? 0.7 : 1,
          type: numeric ? 'number' : 'string',
          valueFormatter: (value: unknown) => formatCell(c.name, value),
        } satisfies GridColDef;
      }),
    [columns, rows],
  );
  const gridRows = useMemo(
    () => rows.map((r, idx) => Object.fromEntries([['id', idx], ...r.map((v, i) => [`c${i}`, v])])),
    [rows],
  );
  return (
    <Box sx={{ height, width: '100%', minWidth: 0 }}>
      <DataGrid
        rows={gridRows}
        columns={cols}
        density="compact"
        disableRowSelectionOnClick
        hideFooter={hideFooter}
        pageSizeOptions={[10, 25, 50, 100]}
        initialState={{ pagination: { paginationModel: { pageSize } } }}
        sx={{
          border: `1px solid ${tokens.border}`,
          borderRadius: 3,
          bgcolor: 'rgba(6,11,38,0.55)',
          fontVariantNumeric: 'tabular-nums',
          '--DataGrid-containerBackground': '#0d1640',
          '& .MuiDataGrid-columnHeaderTitle': { fontWeight: 700, color: tokens.textSecondary, fontSize: 12 },
          '& .MuiDataGrid-cell': { borderColor: tokens.border },
          '& .MuiDataGrid-row:hover': { bgcolor: 'rgba(0,117,255,0.08)' },
        }}
      />
    </Box>
  );
}
