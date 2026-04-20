'use client';
import { Card } from './Card';
import { formatUsd, formatNumber } from '@/lib/format';

interface DepthPoint { impact: number; amountIn: number; amountInUsd: number; }
interface TopPairDepth { pair: string; dex: string; dexLabel: string; points: DepthPoint[]; }

export function DepthChart({
  topPairDepth,
  quoteSymbol = 'WPLS'
}: { topPairDepth: TopPairDepth | null; quoteSymbol?: string }) {

  if (!topPairDepth) return <Card title="Depth">No pair data available.</Card>;

  const W = 720, H = 240, M = 36;
  const pts = topPairDepth.points;
  const maxAmount = pts[pts.length - 1].amountIn || 1;
  const xAt = (x: number) => M + (x / maxAmount) * (W - M * 2);
  const yAt = (impact: number) => H - M - (impact / 0.10) * (H - M * 2);

  // Smooth curve through (0,0) → each impact point
  const allPts = [{ impact: 0, amountIn: 0, amountInUsd: 0 }, ...pts];
  const pathD = allPts.map((p, i) =>
    `${i === 0 ? 'M' : 'L'} ${xAt(p.amountIn).toFixed(1)} ${yAt(p.impact).toFixed(1)}`
  ).join(' ');

  return (
    <Card title={`Depth — ${topPairDepth.dexLabel}`}>
      <p className="text-text-secondary text-sm mb-3">
        {quoteSymbol} input required to move the price by N%. Top pair only.
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {/* grid */}
        {[0.005, 0.01, 0.02, 0.05, 0.10].map(imp => (
          <line key={imp} x1={M} y1={yAt(imp)} x2={W - M} y2={yAt(imp)}
                stroke="#5A5A80" strokeOpacity="0.25" strokeDasharray="2 4" />
        ))}
        {/* curve */}
        <path d={pathD} fill="none" stroke="#B44FFF" strokeWidth={2} />
        {/* marker points */}
        {pts.map(p => (
          <g key={p.impact}>
            <circle cx={xAt(p.amountIn)} cy={yAt(p.impact)} r={4} fill="#FF2D9D" />
            <text x={xAt(p.amountIn)} y={yAt(p.impact) - 8}
                  fontSize={10} fill="#A0A0C0" textAnchor="middle">
              {(p.impact * 100).toFixed(p.impact < 0.01 ? 1 : 0)}%
            </text>
          </g>
        ))}
        {/* axes labels */}
        <text x={M} y={H - 8} fontSize={10} fill="#5A5A80">0 {quoteSymbol}</text>
        <text x={W - M} y={H - 8} fontSize={10} fill="#5A5A80" textAnchor="end">
          {formatNumber(maxAmount)} {quoteSymbol}
        </text>
        <text x={4} y={yAt(0.10) + 4} fontSize={10} fill="#5A5A80">10%</text>
        <text x={4} y={yAt(0.005) + 4} fontSize={10} fill="#5A5A80">0.5%</text>
      </svg>
      <div className="grid grid-cols-5 gap-2 mt-4 text-center text-xs">
        {pts.map(p => (
          <div key={p.impact} className="card-surface p-2">
            <div className="text-text-tertiary">{(p.impact * 100).toFixed(p.impact < 0.01 ? 1 : 0)}%</div>
            <div className="font-mono mt-1">{formatNumber(p.amountIn)}</div>
            <div className="text-text-secondary text-[11px]">{formatUsd(p.amountInUsd)}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}
