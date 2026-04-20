import { describe, it, expect } from 'vitest';
import { readTokenMeta, readTokenMetaBatch } from '@/lib/chain/token-meta';
import { WPLS, PDAI } from '@/lib/chain/addresses';

describe('token-meta', () => {
  it('reads WPLS metadata', async () => {
    const m = await readTokenMeta(WPLS);
    expect(m.symbol).toBe('WPLS');
    expect(m.decimals).toBe(18);
    expect(Number(m.totalSupply)).toBeGreaterThan(0);
  }, 20000);

  it('batch reads multiple tokens', async () => {
    const ms = await readTokenMetaBatch([WPLS, PDAI]);
    expect(ms).toHaveLength(2);
    expect(ms[0].symbol).toBe('WPLS');
    expect(ms[1].symbol).toMatch(/DAI/i);
  }, 20000);
});
