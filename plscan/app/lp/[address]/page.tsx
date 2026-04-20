import { getAddress } from 'ethers';
import { notFound } from 'next/navigation';
import { Card } from '@/components/Card';
import { AddressBadge } from '@/components/AddressBadge';
import { DepthChart } from '@/components/DepthChart';
import { HolderTable } from '@/components/HolderTable';
import { formatUsd, formatNumber } from '@/lib/format';

export const dynamic = 'force-dynamic';

async function fetchJson(url: string) {
  const r = await fetch(url, { cache: 'no-store' });
  return r.ok ? r.json() : null;
}

function parseAddr(s: string): string {
  try { return getAddress(s); } catch { notFound(); }
  throw new Error('unreachable');
}

export default async function LpPage({ params }: { params: { address: string } }) {
  const addr = parseAddr(params.address);

  const base = process.env.NEXT_PUBLIC_BASE_URL ?? 'http://localhost:3000';
  const detail = await fetchJson(`${base}/api/pair/${addr}`);
  if (!detail || !detail.isPair) {
    return <main className="p-10">
      <p className="text-sell">That address isn't a V2 LP pair.</p>
    </main>;
  }

  return (
    <main className="max-w-6xl mx-auto px-4 py-8 md:px-8 md:py-12 space-y-6">
      <header>
        <h1 className="text-2xl font-bold">
          {detail.token0.symbol} / {detail.token1.symbol}
        </h1>
        <div className="mt-2 text-text-secondary text-sm">
          <AddressBadge address={detail.address} />
        </div>
      </header>

      <Card title="Pair summary">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-5">
          <div>
            <div className="text-xs uppercase text-text-tertiary">Price</div>
            <div className="text-xl font-bold mt-1">{formatUsd(detail.priceUsd)}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-text-tertiary">TVL</div>
            <div className="text-xl font-bold mt-1">{formatUsd(detail.tvlUsd)}</div>
          </div>
          <div>
            <div className="text-xs uppercase text-text-tertiary">{detail.token0.symbol}</div>
            <div className="text-xl font-bold mt-1">
              {formatNumber(Number(detail.reserve0) / 10 ** detail.token0.decimals)}
            </div>
          </div>
          <div>
            <div className="text-xs uppercase text-text-tertiary">{detail.token1.symbol}</div>
            <div className="text-xl font-bold mt-1">
              {formatNumber(Number(detail.reserve1) / 10 ** detail.token1.decimals)}
            </div>
          </div>
        </div>
      </Card>

      <DepthChart
        topPairDepth={{
          pair: detail.address,
          dex: 'pair',
          dexLabel: 'This pair',
          points: detail.depth.points
        }}
        quoteSymbol={detail.quoteSide === 0 ? detail.token0.symbol : detail.token1.symbol}
      />

      <HolderTable pairAddress={addr} />
    </main>
  );
}
