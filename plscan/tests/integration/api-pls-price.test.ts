import { describe, it, expect } from 'vitest';
import { GET } from '@/app/api/pls-price/route';

describe('api /pls-price', () => {
  it('returns a positive price', async () => {
    const res = await GET();
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.plsUsd).toBeGreaterThan(0);
    expect(body.cachedAt).toBeGreaterThan(0);
  }, 30000);
});
