import { alpha, createTheme } from '@mui/material/styles';

// Vision UI-inspired dark palette: deep navy canvas, translucent navy cards, blue/purple accents.
export const tokens = {
  bg: '#060b26',
  bgAlt: '#0b1437',
  card: '#111c44',
  cardGradient: 'linear-gradient(127deg, rgba(17,28,68,0.96) 20%, rgba(10,14,35,0.82) 78%)',
  sidebar: 'linear-gradient(160deg, rgba(6,11,40,0.97) 0%, rgba(10,14,35,0.94) 100%)',
  border: 'rgba(226,232,240,0.10)',
  textPrimary: '#ffffff',
  textSecondary: '#a0aec0',
  textMuted: '#718096',
  primary: '#0075ff',
  purple: '#7551ff',
  success: '#01b574',
  warning: '#ffb547',
  error: '#e31a1a',
  // Chart series (validated for CVD separation and >=3:1 contrast on the card surface).
  series: ['#3987e5', '#d95926', '#9085e9'],
  grid: 'rgba(160,174,192,0.14)',
};

export const theme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: tokens.primary },
    secondary: { main: tokens.purple },
    success: { main: tokens.success },
    warning: { main: tokens.warning },
    error: { main: '#ff5b5b' },
    info: { main: '#21d4fd' },
    background: { default: tokens.bg, paper: tokens.card },
    text: { primary: tokens.textPrimary, secondary: tokens.textSecondary },
    divider: tokens.border,
  },
  shape: { borderRadius: 14 },
  typography: {
    fontFamily: '"Plus Jakarta Sans", "Helvetica Neue", Arial, sans-serif',
    h4: { fontWeight: 700, fontSize: '1.6rem' },
    h5: { fontWeight: 700, fontSize: '1.25rem' },
    h6: { fontWeight: 700, fontSize: '1.05rem' },
    subtitle2: { fontWeight: 600 },
    button: { textTransform: 'none', fontWeight: 600 },
    overline: { fontWeight: 700, letterSpacing: '0.08em' },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          background: `radial-gradient(1200px 600px at 85% -10%, ${alpha(tokens.purple, 0.16)}, transparent 60%), ${tokens.bg}`,
          backgroundAttachment: 'fixed',
          minHeight: '100vh',
        },
        '*::-webkit-scrollbar': { width: 8, height: 8 },
        '*::-webkit-scrollbar-thumb': { background: 'rgba(160,174,192,0.25)', borderRadius: 8 },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: { backgroundImage: 'none' },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          background: tokens.cardGradient,
          border: `1px solid ${tokens.border}`,
          borderRadius: 20,
          boxShadow: '0 12px 32px rgba(0,0,0,0.25)',
          backdropFilter: 'blur(42px)',
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 12, minHeight: 40 },
        containedPrimary: { background: tokens.primary },
      },
    },
    MuiIconButton: { styleOverrides: { root: { minWidth: 40, minHeight: 40 } } },
    MuiChip: { styleOverrides: { root: { fontWeight: 600, borderRadius: 8 } } },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 14,
          background: alpha(tokens.bg, 0.6),
          '& fieldset': { borderColor: tokens.border },
        },
      },
    },
    MuiTooltip: {
      styleOverrides: { tooltip: { background: '#1a2456', border: `1px solid ${tokens.border}`, fontSize: 12 } },
    },
    MuiTableCell: { styleOverrides: { root: { borderColor: tokens.border } } },
    MuiAccordion: {
      styleOverrides: {
        root: { background: 'transparent', boxShadow: 'none', '&:before': { display: 'none' } },
      },
    },
  },
});
