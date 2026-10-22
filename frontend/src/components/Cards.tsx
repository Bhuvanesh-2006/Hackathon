import { Box, Card, CardContent, Stack, Typography } from '@mui/material';
import type { ReactNode } from 'react';
import { tokens } from '../theme/theme';

export function KpiCard({ label, value, caption, icon, accent = tokens.primary }: {
  label: string;
  value: string;
  caption?: ReactNode;
  icon: ReactNode;
  accent?: string;
}) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}>
        <Stack direction="row" alignItems="center" spacing={2}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="caption" color="text.secondary" fontWeight={600} noWrap component="div">
              {label}
            </Typography>
            <Typography variant="h5" sx={{ mt: 0.25, fontVariantNumeric: 'tabular-nums' }} noWrap>
              {value}
            </Typography>
            {caption && (
              <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.25 }}>
                {caption}
              </Typography>
            )}
          </Box>
          <Box
            sx={{
              width: 44, height: 44, borderRadius: 3, flexShrink: 0, display: 'grid', placeItems: 'center',
              bgcolor: accent, color: '#fff', '& svg': { fontSize: 22 },
            }}
          >
            {icon}
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}

export function SectionCard({ title, subtitle, action, children, sx, contentSx }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  sx?: object;
  contentSx?: object;
}) {
  return (
    <Card sx={{ height: '100%', ...sx }}>
      <CardContent sx={{ p: { xs: 2, sm: 2.5 }, '&:last-child': { pb: { xs: 2, sm: 2.5 } }, height: '100%', display: 'flex', flexDirection: 'column', ...contentSx }}>
        {(title || action) && (
          <Stack direction="row" alignItems="flex-start" justifyContent="space-between" spacing={1} sx={{ mb: 2 }}>
            <Box sx={{ minWidth: 0 }}>
              {title && <Typography variant="h6">{title}</Typography>}
              {subtitle && <Typography variant="body2" color="text.secondary">{subtitle}</Typography>}
            </Box>
            {action}
          </Stack>
        )}
        <Box sx={{ flex: 1, minWidth: 0 }}>{children}</Box>
      </CardContent>
    </Card>
  );
}
