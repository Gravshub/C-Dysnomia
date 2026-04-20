import { describe, it, expect } from 'vitest';
import { fetchTokenTransfers, fetchTokenHolders } from '@/lib/external/blockscout';
import { WPLS } from '@/lib/chain/addresses';

describe('blockscout', () => {
  it('fetches recent token transfers for WPLS', async () => {
    const rows = await fetchTokenTransfers(WPLS, { page: 1, offset: 20 });
    expect(Array.isArray(rows)).toBe(true);
    expect(rows.length).toBeGreaterThan(0);
    const r = rows[0];
    expect(r.hash.startsWith('0x')).toBe(true);
    expect(Number(r.blockNumber)).toBeGreaterThan(0);
  }, 20000);

  it('fetches token holders', async () => {
    const holders = await fetchTokenHolders(WPLS, { offset: 20 });
    expect(holders.length).toBeGreaterThan(0);
    expect(Number(holders[0].value)).toBeGreaterThan(0);
  }, 20000);
});
