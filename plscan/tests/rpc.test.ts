import { describe, it, expect } from 'vitest';
import { getProvider, callWithFallback } from '@/lib/chain/rpc';

describe('rpc', () => {
  it('getProvider returns a JsonRpcProvider wired to PulseChain', async () => {
    const p = getProvider();
    const net = await p.getNetwork();
    expect(Number(net.chainId)).toBe(369);
  }, 15000);

  it('callWithFallback returns the result from the first healthy URL', async () => {
    const block = await callWithFallback(async (p) => p.getBlockNumber());
    expect(block).toBeGreaterThan(25_000_000);
  }, 15000);

  it('callWithFallback skips a broken URL and succeeds on the next', async () => {
    const urls = ['https://this-does-not-resolve.invalid', 'https://rpc-pulsechain.g4mm4.io'];
    const block = await callWithFallback(async (p) => p.getBlockNumber(), urls);
    expect(block).toBeGreaterThan(25_000_000);
  }, 20000);
});
