import { describe, it, expect } from 'vitest';
import { getPlsUsd } from '@/lib/pricing/pls-usd';
import { priceTokenUsd } from '@/lib/pricing/token-usd';
import { discoverV2Pairs } from '@/lib/discovery/v2-pairs';
import { readTokenMetaBatch } from '@/lib/chain/token-meta';
import { WPLS, PDAI } from '@/lib/chain/addresses';

describe('pricing', () => {
  it('getPlsUsd returns a reasonable PLS/USD rate', async () => {
    const p = await getPlsUsd();
    // PulseChain PLS typically trades $1e-8..$1e-4
    expect(p).toBeGreaterThan(1e-8);
    expect(p).toBeLessThan(1);
  }, 30000);

  it('priceTokenUsd for WPLS equals getPlsUsd', async () => {
    const plsUsd = await getPlsUsd();
    const pairs = await discoverV2Pairs(WPLS);
    const metas = await readTokenMetaBatch([WPLS, ...pairs.map(p => p.quoteAddress)]);
    const wplsMeta = metas[0];
    const quoteMetas = Object.fromEntries(metas.slice(1).map(m => [m.address.toLowerCase(), m]));
    const price = priceTokenUsd(WPLS, wplsMeta, pairs, quoteMetas, plsUsd);
    expect(price).toBeCloseTo(plsUsd, Math.max(1, -Math.floor(Math.log10(plsUsd)) - 3));
  }, 30000);
});
