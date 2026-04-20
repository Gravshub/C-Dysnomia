import { formatDex } from '@/lib/format';

const COLORS: Record<string, string> = {
  'pulsex-v1': 'bg-accent-primary/20 text-accent-secondary border-accent-primary/40',
  'pulsex-v2': 'bg-accent-primary/30 text-accent-secondary border-accent-primary/60',
  '9mm-v2':    'bg-accent-tertiary/30 text-accent-tertiary border-accent-tertiary/60'
};

export function DEXBadge({ dex }: { dex: string }) {
  const cls = COLORS[dex] ?? 'bg-bg-tertiary text-text-secondary border-border';
  return (
    <span className={`inline-block px-2 py-0.5 text-xs font-mono rounded border ${cls}`}>
      {formatDex(dex)}
    </span>
  );
}
