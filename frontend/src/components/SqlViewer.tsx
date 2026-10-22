import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import { Box, IconButton, Tooltip } from '@mui/material';
import { Highlight, themes } from 'prism-react-renderer';
import { useToast } from './Toast';

export function SqlViewer({ sql, maxHeight = 360 }: { sql: string; maxHeight?: number }) {
  const notify = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      notify('SQL copied to clipboard');
    } catch {
      notify('Could not access the clipboard', 'error');
    }
  };
  return (
    <Box sx={{ position: 'relative', borderRadius: 3, border: '1px solid rgba(226,232,240,0.10)', bgcolor: '#070d2a' }}>
      <Tooltip title="Copy SQL">
        <IconButton aria-label="Copy SQL" onClick={copy} size="small" sx={{ position: 'absolute', top: 6, right: 6, zIndex: 1, bgcolor: 'rgba(17,28,68,0.9)' }}>
          <ContentCopyIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Highlight theme={themes.vsDark} code={sql.trim()} language="sql">
        {({ style, tokens, getLineProps, getTokenProps }) => (
          <Box
            component="pre"
            sx={{
              ...style, background: 'transparent', m: 0, p: 2, pr: 6, overflow: 'auto', maxHeight,
              fontFamily: '"JetBrains Mono", Consolas, monospace', fontSize: 13, lineHeight: 1.6,
            }}
          >
            {tokens.map((line, i) => (
              <div key={i} {...getLineProps({ line })}>
                <Box component="span" sx={{ display: 'inline-block', width: 28, color: '#4a5578', userSelect: 'none' }}>{i + 1}</Box>
                {line.map((token, key) => (
                  <span key={key} {...getTokenProps({ token })} />
                ))}
              </div>
            ))}
          </Box>
        )}
      </Highlight>
    </Box>
  );
}
