import Image from 'next/image';
import { AddressBadge } from './AddressBadge';

interface Props {
  token: { address: string; name: string; symbol: string; decimals: number; totalSupply: string };
  logoUrl: string;
  label: string | null;
}

export function TokenHeader({ token, logoUrl, label }: Props) {
  return (
    <header className="flex items-center gap-4 mb-6">
      <Image src={logoUrl} alt={token.symbol} width={56} height={56}
             className="rounded-full bg-bg-secondary" unoptimized />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-bold truncate">{token.name}</h1>
          <span className="text-text-secondary font-mono">{token.symbol}</span>
          {label && <span className="text-xs px-2 py-0.5 rounded bg-accent-primary/30 text-accent-secondary">{label}</span>}
          <span className="text-xs px-2 py-0.5 rounded border border-border text-text-tertiary">
            PulseChain
          </span>
        </div>
        <div className="mt-1 text-text-secondary">
          <AddressBadge address={token.address} />
        </div>
      </div>
    </header>
  );
}
