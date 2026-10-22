import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import CrisisAlertIcon from '@mui/icons-material/CrisisAlert';
import BookmarksOutlinedIcon from '@mui/icons-material/BookmarksOutlined';
import StorageOutlinedIcon from '@mui/icons-material/StorageOutlined';
import ChevronLeftIcon from '@mui/icons-material/ChevronLeft';
import ChevronRightIcon from '@mui/icons-material/ChevronRight';
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined';
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined';
import HistoryIcon from '@mui/icons-material/History';
import MenuIcon from '@mui/icons-material/Menu';
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined';
import TableChartOutlinedIcon from '@mui/icons-material/TableChartOutlined';
import {
  AppBar, Box, Breadcrumbs, Chip, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, Stack,
  Toolbar, Tooltip, Typography, useMediaQuery, useTheme,
} from '@mui/material';
import { useEffect, useState, type ReactNode } from 'react';
import { Link as RouterLink, NavLink, useLocation } from 'react-router-dom';
import { useDatasets } from '../hooks/DatasetContext';
import { api } from '../services/api';
import { tokens } from '../theme/theme';
import type { Health } from '../types/api';

export const NAV = [
  { to: '/', label: 'Overview', icon: <DashboardOutlinedIcon /> },
  { to: '/analyst', label: 'AI Sales Analyst', icon: <AutoAwesomeIcon /> },
  { to: '/anomalies', label: 'Anomalies', icon: <CrisisAlertIcon /> },
  { to: '/saved-queries', label: 'Saved Queries', icon: <BookmarksOutlinedIcon /> },
  { to: '/datasets', label: 'Datasets', icon: <StorageOutlinedIcon /> },
  { to: '/data', label: 'Data Explorer', icon: <TableChartOutlinedIcon /> },
  { to: '/benchmark', label: 'Reliability Benchmark', icon: <FactCheckOutlinedIcon /> },
  { to: '/history', label: 'Query History', icon: <HistoryIcon /> },
  { to: '/settings', label: 'Settings & Data Rules', icon: <SettingsOutlinedIcon /> },
];

const FULL = 264;
const RAIL = 84;

function Brand({ compact }: { compact: boolean }) {
  return (
    <Stack direction="row" alignItems="center" spacing={1.25} sx={{ px: compact ? 0 : 1, justifyContent: compact ? 'center' : 'flex-start' }}>
      <Box sx={{ width: 36, height: 36, borderRadius: 2.5, bgcolor: tokens.primary, display: 'grid', placeItems: 'center', flexShrink: 0 }}>
        <svg width="20" height="20" viewBox="0 0 32 32" aria-hidden><path d="M7 23l6-7 5 3 7-10" stroke="#fff" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </Box>
      {!compact && (
        <Box>
          <Typography fontWeight={700} letterSpacing="0.06em" fontSize={14}>RETAILPILOT</Typography>
          <Typography variant="caption" color="text.secondary">Sales Intelligence Agent</Typography>
        </Box>
      )}
    </Stack>
  );
}

function NavList({ compact, onNavigate }: { compact: boolean; onNavigate?: () => void }) {
  return (
    <List sx={{ px: 1.5 }}>
      {NAV.map((item) => (
        <Tooltip key={item.to} title={compact ? item.label : ''} placement="right">
          <ListItemButton
            component={NavLink}
            to={item.to}
            end={item.to === '/'}
            onClick={onNavigate}
            sx={{
              borderRadius: 3.5, mb: 0.5, minHeight: 48, px: compact ? 0 : 1.5, justifyContent: compact ? 'center' : 'flex-start',
              color: 'text.secondary',
              '& .nav-icon': { width: 32, height: 32, borderRadius: 2.5, display: 'grid', placeItems: 'center', bgcolor: '#1a1f37', color: tokens.primary, '& svg': { fontSize: 18 } },
              '&.active': { bgcolor: '#1a1f37', color: 'text.primary', '& .nav-icon': { bgcolor: tokens.primary, color: '#fff' } },
            }}
          >
            <ListItemIcon sx={{ minWidth: compact ? 0 : 44 }}><span className="nav-icon">{item.icon}</span></ListItemIcon>
            {!compact && <ListItemText primary={item.label} primaryTypographyProps={{ fontSize: 14, fontWeight: 600 }} />}
          </ListItemButton>
        </Tooltip>
      ))}
    </List>
  );
}

function StatusChips({ health }: { health: Health | null }) {
  const { active } = useDatasets();
  if (!health) return null;
  const db = health.database;
  const llm = health.llm;
  return (
    <Stack direction="row" spacing={1} sx={{ display: { xs: 'none', sm: 'flex' } }}>
      {active && (
        <Tooltip title="Active dataset (change it in Datasets or the AI Sales Analyst)">
          <Chip size="small" variant="outlined" color="secondary" component={RouterLink} to="/datasets" clickable label={`Dataset: ${active.name}`} sx={{ maxWidth: 260 }} />
        </Tooltip>
      )}
      <Tooltip title={db.loaded ? `${db.row_count?.toLocaleString('en-GB')} rows, read-only DuckDB` : 'Dataset not loaded'}>
        <Chip size="small" variant="outlined" color={db.loaded ? 'success' : 'warning'} label={db.loaded ? 'Data: connected' : 'Data: not loaded'} />
      </Tooltip>
      <Tooltip title={llm.is_llm ? `${llm.provider} · ${llm.model}` : llm.note ?? 'Offline rule-based planner (no LLM)'}>
        <Chip size="small" variant="outlined" color={llm.is_llm ? 'primary' : 'warning'} label={llm.is_llm ? `LLM: ${llm.model}` : 'Offline demo mode'} />
      </Tooltip>
    </Stack>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up('md'));
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => localStorageGet('rp.sidebarCollapsed') === '1');
  const [health, setHealth] = useState<Health | null>(null);
  const location = useLocation();
  const current = NAV.find((n) => (n.to === '/' ? location.pathname === '/' : location.pathname.startsWith(n.to))) ?? NAV[0];

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, [location.pathname]);

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      localStorageSet('rp.sidebarCollapsed', c ? '0' : '1');
      return !c;
    });
  };

  const width = collapsed ? RAIL : FULL;
  const drawerContent = (compact: boolean) => (
    <Stack sx={{ height: '100%', py: 2.5 }}>
      <Box sx={{ px: 2, pb: 2 }}><Brand compact={compact} /></Box>
      <Box sx={{ mx: 2, mb: 2, height: '1px', background: 'linear-gradient(90deg, transparent, rgba(224,225,226,0.35), transparent)' }} />
      <NavList compact={compact} onNavigate={() => setMobileOpen(false)} />
      <Box sx={{ flex: 1 }} />
      {!compact && (
        <Box sx={{ mx: 2, p: 2, borderRadius: 4, background: `linear-gradient(135deg, ${tokens.primary} 0%, ${tokens.purple} 100%)` }}>
          <Typography fontWeight={700} fontSize={14}>Ask your data</Typography>
          <Typography variant="caption" sx={{ opacity: 0.85 }} component="div">Plain-English questions, validated SQL, real answers in GBP.</Typography>
          <Chip component={RouterLink} to="/analyst" clickable label="Open analyst" size="small" onClick={() => setMobileOpen(false)} sx={{ mt: 1.25, bgcolor: 'rgba(255,255,255,0.2)', color: '#fff' }} />
        </Box>
      )}
      {isDesktop && (
        <Box sx={{ px: 2, pt: 1.5, display: 'flex', justifyContent: compact ? 'center' : 'flex-end' }}>
          <Tooltip title={compact ? 'Expand sidebar' : 'Collapse sidebar'}>
            <IconButton aria-label={compact ? 'Expand sidebar' : 'Collapse sidebar'} onClick={toggleCollapsed} sx={{ color: 'text.secondary' }}>
              {compact ? <ChevronRightIcon /> : <ChevronLeftIcon />}
            </IconButton>
          </Tooltip>
        </Box>
      )}
    </Stack>
  );

  const paperSx = { background: tokens.sidebar, borderRight: `1px solid ${tokens.border}`, color: 'text.primary' };

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      {isDesktop ? (
        <Drawer variant="permanent" sx={{ width, flexShrink: 0, transition: 'width 200ms', '& .MuiDrawer-paper': { width, transition: 'width 200ms', overflowX: 'hidden', ...paperSx } }}>
          {drawerContent(collapsed)}
        </Drawer>
      ) : (
        <Drawer variant="temporary" open={mobileOpen} onClose={() => setMobileOpen(false)} ModalProps={{ keepMounted: true }}
          sx={{ '& .MuiDrawer-paper': { width: FULL, ...paperSx } }}>
          {drawerContent(false)}
        </Drawer>
      )}
      <Box component="main" sx={{ flex: 1, minWidth: 0, px: { xs: 2, sm: 3, lg: 4 }, pb: 4 }}>
        <AppBar position="sticky" elevation={0} sx={{ background: 'rgba(6,11,38,0.72)', backdropFilter: 'blur(14px)', mx: { xs: -2, sm: -3, lg: -4 }, width: 'auto', borderBottom: `1px solid ${tokens.border}` }}>
          <Toolbar sx={{ gap: 1.5, px: { xs: 2, sm: 3, lg: 4 }, minHeight: { xs: 64 } }}>
            {!isDesktop && (
              <IconButton aria-label="Open navigation" edge="start" onClick={() => setMobileOpen(true)}><MenuIcon /></IconButton>
            )}
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Breadcrumbs sx={{ fontSize: 12, '& .MuiBreadcrumbs-separator': { mx: 0.5 } }}>
                <Typography component={RouterLink} to="/" variant="caption" color="text.secondary" sx={{ textDecoration: 'none' }}>RetailPilot</Typography>
                <Typography variant="caption" color="text.primary">{current.label}</Typography>
              </Breadcrumbs>
              <Typography variant="h6" noWrap>{current.label}</Typography>
            </Box>
            <StatusChips health={health} />
          </Toolbar>
        </AppBar>
        <Box sx={{ pt: { xs: 2, sm: 3 } }}>{children}</Box>
      </Box>
    </Box>
  );
}

function localStorageGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function localStorageSet(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: preference is not remembered */
  }
}
