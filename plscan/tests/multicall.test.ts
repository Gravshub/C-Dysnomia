import { describe, it, expect } from 'vitest';
import { Interface } from 'ethers';
import { multicallBatch } from '@/lib/chain/multicall';
import { ABI_ERC20 } from '@/lib/chain/abi';
import { WPLS, PDAI } from '@/lib/chain/addresses';

const erc20 = new Interface(ABI_ERC20);

describe('multicall', () => {
  it('batches ERC20 symbol() for WPLS and pDAI', async () => {
    const calls = [WPLS, PDAI].map(addr => ({
      target: addr,
      allowFailure: true,
      callData: erc20.encodeFunctionData('symbol', [])
    }));
    const results = await multicallBatch(calls);
    const symbols = results.map(r =>
      r.success ? (erc20.decodeFunctionResult('symbol', r.returnData)[0] as string) : null
    );
    expect(symbols[0]).toBe('WPLS');
    // pDAI mirror on PulseChain uses the source symbol "DAI"
    expect(symbols[1]).toMatch(/DAI/i);
  }, 20000);

  it('splits large batches into chunks and concatenates results', async () => {
    const calls = Array(1600).fill(null).map(() => ({
      target: WPLS,
      allowFailure: true,
      callData: erc20.encodeFunctionData('decimals', [])
    }));
    const results = await multicallBatch(calls, { chunkSize: 1000 });
    expect(results).toHaveLength(1600);
    expect(results.every(r => r.success)).toBe(true);
  }, 30000);

  it('throws on chunkSize 0 instead of looping forever', async () => {
    const calls = [{ target: WPLS, allowFailure: true, callData: erc20.encodeFunctionData('decimals', []) }];
    await expect(multicallBatch(calls, { chunkSize: 0 })).rejects.toThrow(/chunkSize must be > 0/);
  });

  it('throws when allowFailure=false and target reverts', async () => {
    const calls = [{
      target: WPLS,
      allowFailure: false,
      callData: '0xdeadbeef' // unknown selector — pair call reverts
    }];
    await expect(multicallBatch(calls)).rejects.toThrow();
  }, 20000);
});
