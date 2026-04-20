'use client';
import { useEffect, useState } from 'react';
import { Card } from './Card';
import { DEXBadge } from './DEXBadge';
import { AddressBadge } from './AddressBadge';
import { formatUsd, formatNumber, formatAddress } from '@/lib/format';

interface SwapEvent {
  txHash: string; block: number; timestamp: number; pair: string;
  dex: string; direction: 'buy'|'sell'; amountToken: string; usdValue: number;
  actor: string; actorLabel: string | null;
}

export function SwapFeed({ tokenAddress }: { tokenAddress: string }) {
  const [events, setEvents] = useState<SwapEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/token/${tokenAddress}/swaps`)
      .then(r => r.json())
      .then(j => j.events ? setEvents(j.events) : setError(j.error ?? 'no data'))
      .catch(e => setError(String(e)));
  }, [tokenAddress]);

  if (error) return <Card title="Recent swaps">Error: {error}</Card>;
  if (!events) return <Card title="Recent swaps">Loading…</Card>;

  return (
    <Card title={`Recent swaps (${events.length})`}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase text-text-tertiary">
              <th className="text-left px-3 py-2 font-normal">Block</th>
              <th className="text-left px-3 py-2 font-normal">DEX</th>
              <th className="text-left px-3 py-2 font-normal">Side</th>
              <th className="text-left px-3 py-2 font-normal">Amount</th>
              <th className="text-left px-3 py-2 font-normal">USD</th>
              <th className="text-left px-3 py-2 font-normal">Actor</th>
              <th className="text-left px-3 py-2 font-normal">Tx</th>
            </tr>
          </thead>
          <tbody>
            {events.map(e => (
              <tr key={e.txHash + e.pair} className="border-b border-border/50 hover:bg-bg-tertiary/40">
                <td className="px-3 py-2 font-mono text-xs">{e.block}</td>
                <td className="px-3 py-2"><DEXBadge dex={e.dex} /></td>
                <td className={`px-3 py-2 font-bold ${e.direction === 'buy' ? 'text-buy' : 'text-sell'}`}>
                  {e.direction.toUpperCase()}
                </td>
                <td className="px-3 py-2 font-mono">{formatNumber(Number(e.amountToken))}</td>
                <td className="px-3 py-2">{formatUsd(e.usdValue)}</td>
                <td className="px-3 py-2"><AddressBadge address={e.actor} /></td>
                <td className="px-3 py-2">
                  <a href={`https://scan.pulsechain.com/tx/${e.txHash}`} target="_blank"
                     rel="noreferrer" className="text-xs text-text-tertiary hover:text-accent-secondary">
                    {formatAddress(e.txHash)}
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
