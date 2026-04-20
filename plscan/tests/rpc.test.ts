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

  it('callWithFallback throws AggregateError when all URLs fail', async () => {
    const urls = ['http://127.0.0.1:1', 'http://127.0.0.1:2'];
    await expect(callWithFallback(async (p) => p.getBlockNumber(), urls))
      .rejects.toThrow(/All 2 RPC URLs failed/);
  }, 20000);
});
