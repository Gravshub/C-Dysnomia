import { describe, it, expect } from 'vitest';
import { GET as getPair } from '@/app/api/pair/[address]/route';
import { GET as getHolders } from '@/app/api/pair/[address]/holders/route';

// WPLS/pDAI PulseX V2 pair — this was the top WPLS pair in Task 16's test:
const TEST_PAIR = '0xaE8429918FdBF9a5867e3243697637Dc56aa76A1';

describe('api /pair/[address]', () => {
  it('returns pair detail with reserves + depth curve', async () => {
    const res = await getPair(new Request(`http://x/pair/${TEST_PAIR}`), {
      params: { address: TEST_PAIR }
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.token0).toBeDefined();
    expect(body.token1).toBeDefined();
    expect(body.depth.points).toHaveLength(5);
  }, 30000);

  it('returns holders (or empty on BlockScout failure)', async () => {
    const res = await getHolders(new Request(`http://x/pair/${TEST_PAIR}/holders`), {
      params: { address: TEST_PAIR }
    });
    expect([200, 503]).toContain(res.status);
  }, 30000);
});
