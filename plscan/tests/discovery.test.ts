import { describe, it, expect } from 'vitest';
import { discoverV2Pairs } from '@/lib/discovery/v2-pairs';
import { WPLS } from '@/lib/chain/addresses';

describe('discovery/v2-pairs', () => {
  it('finds WPLS paired across multiple DEXes (WPLS/pDAI, WPLS/HEX, etc.)', async () => {
    const pairs = await discoverV2Pairs(WPLS);
    expect(pairs.length).toBeGreaterThan(8);
    // Expect at least two distinct DEXes
    const dexes = new Set(pairs.map(p => p.dex));
    expect(dexes.size).toBeGreaterThanOrEqual(3);  // pulsex-v1, pulsex-v2, 9mm-v2
    // Every pair must be non-zero
    for (const p of pairs) {
      expect(p.pair).not.toBe('0x0000000000000000000000000000000000000000');
      expect(Number(p.reserve0)).toBeGreaterThan(0);
      expect(Number(p.reserve1)).toBeGreaterThan(0);
    }
  }, 30000);
});
