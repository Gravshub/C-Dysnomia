'use client';
import { Doughnut } from 'react-chartjs-2';
import { Chart, ArcElement, Tooltip, Legend } from 'chart.js';
import { Card } from './Card';
import { formatDex } from '@/lib/format';
import type { PairInfo } from '@/lib/types';

Chart.register(ArcElement, Tooltip, Legend);

const DEX_COLORS: Record<string, string> = {
  'pulsex-v1': '#8A2BE2',
  'pulsex-v2': '#B44FFF',
  '9mm-v2':    '#00E5A0'
};

export function LiquidityDonut({ pairs }: { pairs: PairInfo[] }) {
  const data = {
    labels: pairs.map(p => `${p.tokenSymbol}/${p.quoteSymbol} · ${formatDex(p.dex)}`),
    datasets: [{
      data: pairs.map(p => p.tvlUsd),
      backgroundColor: pairs.map(p => DEX_COLORS[p.dex] ?? '#5A5A80'),
      borderColor: '#0D0D1A',
      borderWidth: 2
    }]
  };
  return (
    <Card title="Liquidity distribution">
      <div className="max-w-md mx-auto">
        <Doughnut data={data} options={{
          plugins: {
            legend: { labels: { color: '#A0A0C0', font: { size: 11 } }, position: 'bottom' },
            tooltip: { callbacks: { label: (ctx) =>
              `${ctx.label}: $${Number(ctx.raw).toLocaleString(undefined, { maximumFractionDigits: 0 })}` } }
          },
          cutout: '65%',
          responsive: true
        }} />
      </div>
    </Card>
  );
}
