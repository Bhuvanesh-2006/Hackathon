const MONEY_COL = /(gbp|revenue|amount|value|sales|price|spend)/i;
const COUNT_COL = /(units|count|lines|invoices|orders|quantity)/i;

export function formatGBP(value: number | null | undefined, compact = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('en-GB', {
    style: 'currency',
    currency: 'GBP',
    notation: compact ? 'compact' : 'standard',
    maximumFractionDigits: compact ? 2 : 2,
  }).format(value);
}

export function formatNumber(value: number | null | undefined, compact = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('en-GB', {
    notation: compact ? 'compact' : 'standard',
    maximumFractionDigits: 2,
  }).format(value);
}

export function isMoneyColumn(col: string): boolean {
  return MONEY_COL.test(col) && !COUNT_COL.test(col);
}

export function formatCell(col: string, value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') return isMoneyColumn(col) ? formatGBP(value) : formatNumber(value);
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
}

export function humanize(col: string): string {
  return col.replace(/_/g, ' ').replace(/\bgbp\b/i, '(£)').replace(/^\w/, (c) => c.toUpperCase());
}

export function toCsv(columns: string[], rows: unknown[][]): string {
  const esc = (v: unknown) => {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map(esc).join(','), ...rows.map((r) => r.map(esc).join(','))].join('\r\n');
}

export function downloadText(filename: string, text: string, mime = 'text/csv;charset=utf-8') {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
