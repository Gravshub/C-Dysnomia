import { describe, it, expect } from 'vitest';
import { GET } from '@/app/api/token/[address]/pairs/route';
import { WPLS } from '@/lib/chain/addresses';

describe('api /token/[address]/pairs', () => {
  it('returns a summary + sorted pair list for WPLS', async () => {
    const res = await GET(new Request(`http://x/token/${WPLS}/pairs`), {
      params: { address: WPLS }
    });
    expect(res.status).toBe(200);
    const body = await res.json();

    // Summary metrics
    expect(body.summary.pairCount).toBeGreaterThan(3);
    expect(body.summary.dexCount).toBeGreaterThanOrEqual(2);
    expect(body.summary.totalTvlUsd).toBeGreaterThan(0);
    expect(body.summary.priceUsd).toBeGreaterThan(0);
    expect(body.summary.deepestPairTvlUsd).toBeGreaterThan(0);

    // Pairs array
    expect(Array.isArray(body.pairs)).toBe(true);
    expect(body.pairs[0].tvlUsd).toBeGreaterThanOrEqual(body.pairs[body.pairs.length - 1].tvlUsd);
    const p = body.pairs[0];
    expect(p.priceUsd).toBeGreaterThan(0);
    expect(p.wplsForOnePercentMove).toBeGreaterThan(0);
    expect(['pulsex-v1', 'pulsex-v2', '9mm-v2']).toContain(p.dex);

    // Top-pair depth curve for Card D
    expect(body.topPairDepth.pair).toBe(body.pairs[0].pair);
    expect(body.topPairDepth.points).toHaveLength(5); // 0.5, 1, 2, 5, 10%
  }, 60000);
});
