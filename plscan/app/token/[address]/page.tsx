import { getAddress } from 'ethers';
import { redirect, notFound } from 'next/navigation';
import { detectLpPair } from '@/lib/discovery/lp-detect';
import { TokenHeader } from '@/components/TokenHeader';
import { SummaryMetrics } from '@/components/SummaryMetrics';
import { PairTable } from '@/components/PairTable';
import { LiquidityDonut } from '@/components/LiquidityDonut';
import { DepthChart } from '@/components/DepthChart';
import { SwapFeed } from '@/components/SwapFeed';
import { HolderTable } from '@/components/HolderTable';

export const dynamic = 'force-dynamic';

async function fetchJson(url: string) {
  const r = await fetch(url, { cache: 'no-store' });
  return r.ok ? r.json() : null;
}

function parseAddr(s: string): string {
  try { return getAddress(s); } catch { notFound(); }
  throw new Error('unreachable');
}

export default async function TokenPage({ params }: { params: { address: string } }) {
  const addr = parseAddr(params.address);

  // If user pasted an LP contract, redirect to /lp/
  const det = await detectLpPair(addr);
  if (det.isPair) redirect(`/lp/${addr}`);

  const base = process.env.NEXT_PUBLIC_BASE_URL ?? 'http://localhost:3000';
  const [meta, pairs] = await Promise.all([
    fetchJson(`${base}/api/token/${addr}/metadata`),
    fetchJson(`${base}/api/token/${addr}/pairs`)
  ]);

  if (!meta || !pairs) {
    return <main className="p-10"><p className="text-sell">Failed to load token data.</p></main>;
  }

  const topPair = pairs.pairs?.[0];

  return (
    <main className="max-w-7xl mx-auto px-4 py-8 md:px-8 md:py-12 space-y-6">
      <TokenHeader token={meta.token} logoUrl={meta.logoUrl} label={meta.label} />
      <SummaryMetrics summary={pairs.summary} />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2"><PairTable pairs={pairs.pairs} /></div>
        <LiquidityDonut pairs={pairs.pairs.slice(0, 12)} />
      </div>
      <DepthChart
        topPairDepth={pairs.topPairDepth}
        quoteSymbol={topPair?.quoteSymbol ?? 'WPLS'}
      />
      <SwapFeed tokenAddress={addr} />
      {topPair && <HolderTable pairAddress={topPair.pair} />}
    </main>
  );
}
