import Link from 'next/link';
import { formatAddress } from '@/lib/format';
import { labelFor } from '@/lib/labels';
import { CopyButton } from './CopyButton';

interface Props { address: string; link?: boolean; showLabel?: boolean; }

export function AddressBadge({ address, link = true, showLabel = true }: Props) {
  const lbl = showLabel ? labelFor(address) : null;
  const text = lbl ?? formatAddress(address);
  const inner = <span className="font-mono text-sm">{text}</span>;
  return (
    <span className="inline-flex items-center gap-1.5">
      {link
        ? <Link href={`https://scan.pulsechain.com/address/${address}`} target="_blank"
                className="hover:text-accent-secondary">{inner}</Link>
        : inner}
      <CopyButton value={address} label="copy" />
    </span>
  );
}
