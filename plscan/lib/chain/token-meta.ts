import { Interface, getAddress } from 'ethers';
import { ABI_ERC20 } from './abi';
import { multicallBatch } from './multicall';
import { rawToHuman } from '../format';
import type { Hex, TokenMeta } from '../types';

const erc20 = new Interface(ABI_ERC20);

export async function readTokenMetaBatch(addrs: string[]): Promise<TokenMeta[]> {
  const checksummed = addrs.map(a => getAddress(a) as Hex);
  const calls = checksummed.flatMap(addr => [
    { target: addr, allowFailure: true, callData: erc20.encodeFunctionData('name', []) },
    { target: addr, allowFailure: true, callData: erc20.encodeFunctionData('symbol', []) },
    { target: addr, allowFailure: true, callData: erc20.encodeFunctionData('decimals', []) },
    { target: addr, allowFailure: true, callData: erc20.encodeFunctionData('totalSupply', []) }
  ]);
  const results = await multicallBatch(calls);

  const out: TokenMeta[] = [];
  for (let i = 0; i < checksummed.length; i++) {
    const base = i * 4;
    const decodeStr = (r: { success: boolean; returnData: string }, fn: string, fallback: string) => {
      if (!r.success) return fallback;
      try { return erc20.decodeFunctionResult(fn, r.returnData)[0] as string; }
      catch { return fallback; }
    };
    const decodeNum = (r: { success: boolean; returnData: string }, fn: string, fallback: number) => {
      if (!r.success) return fallback;
      try { return Number(erc20.decodeFunctionResult(fn, r.returnData)[0]); }
      catch { return fallback; }
    };
    const decodeBig = (r: { success: boolean; returnData: string }, fn: string) => {
      if (!r.success) return 0n;
      try { return erc20.decodeFunctionResult(fn, r.returnData)[0] as bigint; }
      catch { return 0n; }
    };

    const decimals = decodeNum(results[base + 2], 'decimals', 18);
    out.push({
      address: checksummed[i],
      name:    decodeStr(results[base + 0], 'name',   'Unknown'),
      symbol:  decodeStr(results[base + 1], 'symbol', '???'),
      decimals,
      totalSupply: rawToHuman(decodeBig(results[base + 3], 'totalSupply'), decimals).toString()
    });
  }
  return out;
}

export async function readTokenMeta(addr: string): Promise<TokenMeta> {
  const [m] = await readTokenMetaBatch([addr]);
  return m;
}
