import { Card } from './Card';
import { formatUsd, formatNumber } from '@/lib/format';

interface Summary {
  pairCount: number;
  dexCount: number;
  totalTvlUsd: number;
  deepestPairTvlUsd: number;
  priceUsd: number;
  priceChange24h: number | null;
  totalTokenLiquidity: number;
  plsUsd: number;
}

const Stat = ({ label, value }: { label: string; value: string }) => (
  <div>
    <div className="text-xs uppercase tracking-wider text-text-tertiary">{label}</div>
    <div className="text-xl font-bold mt-1">{value}</div>
  </div>
);

export function SummaryMetrics({ summary }: { summary: Summary }) {
  const tvlPls = summary.plsUsd > 0 ? summary.totalTvlUsd / summary.plsUsd : 0;
  return (
    <Card title="Summary">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-5">
        <Stat label="Price" value={formatUsd(summary.priceUsd)} />
        <Stat label="Total TVL (USD)" value={formatUsd(summary.totalTvlUsd)} />
        <Stat label="Total TVL (PLS)" value={formatNumber(tvlPls)} />
        <Stat label="Deepest pair"  value={formatUsd(summary.deepestPairTvlUsd)} />
        <Stat label="Pairs"   value={String(summary.pairCount)} />
        <Stat label="DEXes"   value={String(summary.dexCount)} />
        <Stat label="Token liquidity" value={formatNumber(summary.totalTokenLiquidity)} />
        <Stat label="24h change" value={summary.priceChange24h == null ? '—' : `${(summary.priceChange24h*100).toFixed(2)}%`} />
      </div>
    </Card>
  );
}
