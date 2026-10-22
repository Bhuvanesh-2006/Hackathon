import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline';
import InboxOutlinedIcon from '@mui/icons-material/InboxOutlined';
import StorageOutlinedIcon from '@mui/icons-material/StorageOutlined';
import { Box, Button, Card, CardContent, Chip, Skeleton, Stack, Typography } from '@mui/material';
import type { ReactNode } from 'react';
import type { QueryStatus } from '../types/api';
import { ApiError } from '../services/api';

export function EmptyState({ title, description, action, icon }: { title: string; description?: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <Stack alignItems="center" justifyContent="center" spacing={1.5} sx={{ py: 6, px: 2, textAlign: 'center' }}>
      <Box sx={{ color: 'text.secondary', '& svg': { fontSize: 40 } }}>{icon ?? <InboxOutlinedIcon />}</Box>
      <Typography variant="subtitle1" fontWeight={700}>{title}</Typography>
      {description && <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 460 }}>{description}</Typography>}
      {action}
    </Stack>
  );
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const isDataMissing = error instanceof ApiError && error.code === 'dataset_unavailable';
  if (isDataMissing) return <SetupState message={error.message} />;
  return (
    <Card>
      <EmptyState
        icon={<ErrorOutlineIcon color="error" />}
        title="Something went wrong"
        description={error.message}
        action={onRetry && <Button variant="outlined" onClick={onRetry}>Retry</Button>}
      />
    </Card>
  );
}

export function SetupState({ message }: { message?: string }) {
  return (
    <Card>
      <CardContent>
        <EmptyState
          icon={<StorageOutlinedIcon color="warning" />}
          title="Setup required: dataset not loaded"
          description={
            message ??
            'No live analytics are shown because the dataset has not been prepared. Download online_retail_II.xlsx from the UCI repository and run the preparation script.'
          }
          action={
            <Box component="code" sx={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 13, p: 1.5, borderRadius: 2, bgcolor: 'rgba(0,0,0,0.35)' }}>
              cd backend &amp;&amp; python -m scripts.prepare_data --excel path/to/online_retail_II.xlsx
            </Box>
          }
        />
      </CardContent>
    </Card>
  );
}

export function CardSkeleton({ height = 280 }: { height?: number }) {
  return (
    <Card>
      <CardContent>
        <Skeleton width="40%" height={28} />
        <Skeleton variant="rounded" height={height - 60} sx={{ mt: 2, borderRadius: 3 }} />
      </CardContent>
    </Card>
  );
}

const STATUS_META: Record<string, { label: string; color: 'success' | 'warning' | 'error' | 'info' | 'default' | 'secondary' }> = {
  success: { label: 'Success', color: 'success' },
  empty: { label: 'Empty result', color: 'info' },
  clarification: { label: 'Needs clarification', color: 'secondary' },
  unsupported: { label: 'Unsupported', color: 'warning' },
  rejected: { label: 'Rejected (unsafe)', color: 'error' },
  error: { label: 'Error', color: 'error' },
  running: { label: 'Running', color: 'info' },
  passed: { label: 'Pass', color: 'success' },
  failed: { label: 'Fail', color: 'error' },
  not_run: { label: 'Not run', color: 'default' },
};

export function StatusChip({ status, size = 'small' }: { status: QueryStatus | string; size?: 'small' | 'medium' }) {
  const meta = STATUS_META[status] ?? { label: status, color: 'default' as const };
  return <Chip size={size} label={meta.label} color={meta.color} variant="outlined" />;
}
