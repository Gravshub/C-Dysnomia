'use client';
import { useState, useMemo } from 'react';
import { Card } from './Card';
import { DEXBadge } from './DEXBadge';
import { AddressBadge } from './AddressBadge';
import { formatUsd, formatNumber, formatPercent } from '@/lib/format';
import { dexscreenerTokenUrl } from '@/lib/external/dexscreener';
import type { PairInfo } from '@/lib/types';

type SortKey = 'tvlUsd' | 'priceUsd' | 'pctOfTotal' | 'wplsForOnePercentMove';

export function PairTable({ pairs }: { pairs: PairInfo[] }) {
  const [sort, setSort] = useState<SortKey>('tvlUsd');
  const [asc, setAsc] = useState(false);

  const sorted = useMemo(() => {
    const copy = [...pairs];
    copy.sort((a, b) => (a[sort] as number) - (b[sort] as number));
    return asc ? copy : copy.reverse();
  }, [pairs, sort, asc]);

  const click = (k: SortKey) => { if (sort === k) setAsc(!asc); else { setSort(k); setAsc(false); } };

  const header = (label: string, k: SortKey) => (
    <th className="text-left px-3 py-2 text-xs uppercase tracking-wider text-text-tertiary font-normal">
      <button onClick={() => click(k)} className="hover:text-accent-secondary">
        {label}{sort === k ? (asc ? ' ↑' : ' ↓') : ''}
      </button>
    </th>
  );

  return (
    <Card title={`Pairs (${pairs.length})`}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-3 py-2 text-xs uppercase tracking-wider text-text-tertiary font-normal">DEX</th>
              <th className="text-left px-3 py-2 text-xs uppercase tracking-wider text-text-tertiary font-normal">Pair</th>
              {header('TVL', 'tvlUsd')}
              {header('Price', 'priceUsd')}
              {header('% Pool', 'pctOfTotal')}
              {header('1% move', 'wplsForOnePercentMove')}
              <th className="text-left px-3 py-2 text-xs uppercase tracking-wider text-text-tertiary font-normal">LP</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(p => (
              <tr key={p.pair} className="border-b border-border/50 hover:bg-bg-tertiary/40">
                <td className="px-3 py-3"><DEXBadge dex={p.dex} /></td>
                <td className="px-3 py-3">
                  <span className="font-mono">{p.tokenSymbol} / {p.quoteSymbol}</span>
                </td>
                <td className="px-3 py-3">{formatUsd(p.tvlUsd)}</td>
                <td className="px-3 py-3">{formatUsd(p.priceUsd)}</td>
                <td className="px-3 py-3">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 rounded bg-bg-tertiary w-24 overflow-hidden">
                      <div className="h-full bg-accent-primary" style={{ width: `${p.pctOfTotal * 100}%` }} />
                    </div>
                    <span>{formatPercent(p.pctOfTotal)}</span>
                  </div>
                </td>
                <td className="px-3 py-3 font-mono">
                  {p.wplsForOnePercentMove > 0 ? `${formatNumber(p.wplsForOnePercentMove)} WPLS` : '—'}
                </td>
                <td className="px-3 py-3">
                  <AddressBadge address={p.pair} />
                  <a href={dexscreenerTokenUrl(p.pair)} target="_blank" rel="noreferrer"
                     className="ml-2 text-xs text-text-tertiary hover:text-accent-secondary">dex</a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
