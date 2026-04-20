import { describe, it, expect } from 'vitest';
import { amountOut, priceImpact, amountInForImpact } from '@/lib/analytics/depth';

describe('depth', () => {
  it('amountOut with 0 input is 0', () => {
    expect(amountOut(0, 1_000_000, 1_000_000)).toBe(0);
  });

  it('amountOut preserves xy=k within 0.3% fee bounds', () => {
    const out = amountOut(1000, 1_000_000, 1_000_000);
    // With 0.3% fee, ~997 tokens out, slightly less due to slippage
    expect(out).toBeGreaterThan(990);
    expect(out).toBeLessThan(997);
  });

  it('priceImpact for trivial trade is near 0', () => {
    const pi = priceImpact(1, 1_000_000, 1_000_000);
    expect(pi).toBeGreaterThan(0);
    expect(pi).toBeLessThan(0.001);
  });

  it('amountInForImpact finds input that causes ~1% impact', () => {
    const a = amountInForImpact(1_000_000, 1_000_000, 0.01);
    const pi = priceImpact(a, 1_000_000, 1_000_000);
    expect(pi).toBeGreaterThan(0.0095);
    expect(pi).toBeLessThan(0.0105);
  });
});
