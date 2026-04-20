import { describe, it, expect } from 'vitest';
import { GET } from '@/app/api/token/[address]/swaps/route';
import { WPLS } from '@/lib/chain/addresses';

describe('api /token/[address]/swaps', () => {
  it('returns swap events for WPLS', async () => {
    const res = await GET(new Request(`http://x/token/${WPLS}/swaps`), {
      params: { address: WPLS }
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.events)).toBe(true);
    expect(body.events.length).toBeGreaterThan(0);
    const e = body.events[0];
    expect(['buy', 'sell']).toContain(e.direction);
    expect(e.txHash.startsWith('0x')).toBe(true);
    expect(typeof e.block).toBe('number');
  }, 40000);
});
