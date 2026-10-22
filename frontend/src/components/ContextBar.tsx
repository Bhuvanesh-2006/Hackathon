import CompareArrowsIcon from '@mui/icons-material/CompareArrows';
import FilterAltOutlinedIcon from '@mui/icons-material/FilterAltOutlined';
import HistoryToggleOffIcon from '@mui/icons-material/HistoryToggleOff';
import TroubleshootIcon from '@mui/icons-material/Troubleshoot';
import { Button, Chip, Stack, Tooltip, Typography } from '@mui/material';
import { tokens } from '../theme/theme';
import type { ConversationContext } from '../types/api';

/** Conversation context the next question will use. Every chip reflects state the server holds. */
export function ContextBar({ context, disabled, onRemove, onClearComparison, onClearAll }: {
  context: ConversationContext;
  disabled: boolean;
  onRemove: (field: string, label: string) => void;
  onClearComparison: () => void;
  onClearAll: () => void;
}) {
  const hasAnything = context.filters.length > 0 || context.comparison || context.previous_result || context.topic;
  if (!hasAnything) return null;
  return (
    <Stack direction="row" spacing={0.75} alignItems="center" flexWrap="wrap" useFlexGap aria-label="Active conversation context"
      sx={{ mb: 1, px: 1.25, py: 1, bgcolor: tokens.bgAlt, border: 1, borderColor: 'divider', borderRadius: 3 }}>
      <Typography variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>Applies to next question:</Typography>
      {context.topic && (
        <Tooltip title={context.topic.summary}>
          <Chip size="small" icon={<TroubleshootIcon />} color="secondary" label="Investigating anomaly" />
        </Tooltip>
      )}
      {context.filters.map((f) => (
        <Chip key={f.field} size="small" icon={<FilterAltOutlinedIcon />} label={f.label} color="primary" variant="outlined"
          onDelete={disabled ? undefined : () => onRemove(f.field, f.label)} />
      ))}
      {context.comparison && (
        <Chip size="small" icon={<CompareArrowsIcon />} label={context.comparison.label} color="primary" variant="outlined"
          onDelete={disabled ? undefined : onClearComparison} />
      )}
      {context.previous_result && (
        <Tooltip title="Say “those products” (or customers / countries) to refer to them">
          <Chip size="small" icon={<HistoryToggleOffIcon />} variant="outlined"
            label={`Previous result: ${context.previous_result.count} ${context.previous_result.column.replace('_', ' ')}s`} />
        </Tooltip>
      )}
      {(context.filters.length > 0 || context.comparison) && (
        <Button size="small" onClick={onClearAll} disabled={disabled} sx={{ minHeight: 28 }}>Clear filters</Button>
      )}
    </Stack>
  );
}
