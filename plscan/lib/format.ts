export function rawToHuman(raw: string | bigint, decimals: number): number {
  const s = typeof raw === 'bigint' ? raw.toString() : raw;
  if (s === '0') return 0;
  if (decimals === 0) return Number(s);
  const neg = s.startsWith('-');
  const abs = neg ? s.slice(1) : s;
  const pad = abs.padStart(decimals + 1, '0');
  const whole = pad.slice(0, pad.length - decimals);
  const frac = pad.slice(pad.length - decimals).slice(0, 18);
  const n = Number(`${whole}.${frac}`);
  return neg ? -n : n;
}

export function formatNumber(n: number): string {
  if (!isFinite(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9)  return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6)  return `${(n / 1e6).toFixed(2)}M`;
  if (abs >= 1e3)  return `${(n / 1e3).toFixed(2)}K`;
  if (abs >= 1)    return n.toFixed(0);
  if (abs === 0)   return '0';
  if (abs < 1e-4)  return n.toExponential(2);
  return n.toFixed(4);
}

export function formatUsd(n: number): string {
  if (!isFinite(n)) return '—';
  if (n === 0) return '$0';
  const abs = Math.abs(n);
  if (abs < 1e-4) return `$${n.toExponential(2)}`;
  if (abs < 1)    return `$${n.toFixed(4)}`;
  return `$${formatNumber(n)}`;
}

export function formatPercent(frac: number): string {
  if (!isFinite(frac)) return '—';
  return `${(frac * 100).toFixed(2)}%`;
}

export function formatAddress(addr: string): string {
  if (!addr || addr.length < 10) return addr;
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

export function formatDex(d: string): string {
  switch (d) {
    case 'pulsex-v1': return 'PulseX V1';
    case 'pulsex-v2': return 'PulseX V2';
    case '9mm-v2':    return '9mm V2';
    default:          return d;
  }
}
