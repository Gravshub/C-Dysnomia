import { describe, it, expect } from 'vitest';
import { GET } from '@/app/api/token/[address]/metadata/route';
import { WPLS } from '@/lib/chain/addresses';

describe('api /token/[address]/metadata', () => {
  it('returns WPLS metadata', async () => {
    const res = await GET(new Request(`http://x/token/${WPLS}/metadata`), {
      params: { address: WPLS }
    });
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.token.symbol).toBe('WPLS');
    expect(body.token.decimals).toBe(18);
    expect(body.label).toBeNull();
  }, 20000);

  it('returns 400 for a malformed address', async () => {
    const res = await GET(new Request(`http://x/token/nope/metadata`), {
      params: { address: 'nope' }
    });
    expect(res.status).toBe(400);
  });
});
