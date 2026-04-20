import { describe, it, expect } from 'vitest';
import { cacheGetSet } from '@/lib/cache/kv';

describe('cache/kv', () => {
  it('caches a value for the given TTL', async () => {
    let calls = 0;
    const fn = async () => { calls++; return { n: 42 }; };
    const a = await cacheGetSet('test:k1', 60, fn);
    const b = await cacheGetSet('test:k1', 60, fn);
    expect(a).toEqual(b);
    expect(calls).toBe(1);
  });

  it('re-computes after TTL expires', async () => {
    let calls = 0;
    const fn = async () => { calls++; return { n: Math.random() }; };
    const a = await cacheGetSet('test:k2', 0.05, fn);
    await new Promise(r => setTimeout(r, 80));
    const b = await cacheGetSet('test:k2', 0.05, fn);
    expect(calls).toBe(2);
    expect(a).not.toEqual(b);
  });
});
