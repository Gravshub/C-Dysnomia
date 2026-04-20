'use client';
import { useEffect, useState } from 'react';
import { Card } from './Card';
import { AddressBadge } from './AddressBadge';
import { formatNumber } from '@/lib/format';

interface Holder { address: string; label: string | null; lpBalance: string; }

export function HolderTable({ pairAddress }: { pairAddress: string }) {
  const [holders, setHolders] = useState<Holder[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/pair/${pairAddress}/holders`)
      .then(r => r.json())
      .then(j => j.holders ? setHolders(j.holders) : setError(j.error ?? 'no data'))
      .catch(e => setError(String(e)));
  }, [pairAddress]);

  if (error) return <Card title="Top LP holders">Error: {error}</Card>;
  if (!holders) return <Card title="Top LP holders">Loading…</Card>;
  if (holders.length === 0) return <Card title="Top LP holders">No holder data available.</Card>;

  const total = holders.reduce((s, h) => s + Number(h.lpBalance), 0);

  return (
    <Card title="Top LP holders (top pair)">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-xs uppercase text-text-tertiary">
            <th className="text-left px-3 py-2 font-normal">Holder</th>
            <th className="text-left px-3 py-2 font-normal">LP balance</th>
            <th className="text-left px-3 py-2 font-normal">Share</th>
          </tr>
        </thead>
        <tbody>
          {holders.map(h => {
            const bal = Number(h.lpBalance);
            const pct = total > 0 ? bal / total : 0;
            return (
              <tr key={h.address} className="border-b border-border/50 hover:bg-bg-tertiary/40">
                <td className="px-3 py-2"><AddressBadge address={h.address} /></td>
                <td className="px-3 py-2 font-mono">{formatNumber(bal)}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 rounded bg-bg-tertiary w-20 overflow-hidden">
                      <div className="h-full bg-accent-tertiary" style={{ width: `${pct * 100}%` }} />
                    </div>
                    <span>{(pct * 100).toFixed(1)}%</span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}
