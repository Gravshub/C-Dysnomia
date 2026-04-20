import { Interface, getAddress } from 'ethers';
import { ABI_FACTORY_V2, ABI_PAIR_V2 } from '../chain/abi';
import { FACTORIES, QUOTE_TOKENS } from '../chain/addresses';
import { multicallBatch } from '../chain/multicall';
import type { DexName, Hex, PairReserves } from '../types';

const factoryIface = new Interface(ABI_FACTORY_V2);
const pairIface = new Interface(ABI_PAIR_V2);

const ZERO = '0x0000000000000000000000000000000000000000';

export interface DiscoveredPair extends PairReserves {
  dex: DexName;
  quoteAddress: Hex;
}

export async function discoverV2Pairs(token: string): Promise<DiscoveredPair[]> {
  const tokenAddr = getAddress(token);

  // Phase 1: getPair(token, quote) across every factory × quote token.
  const getPairCalls = FACTORIES.flatMap((f) =>
    QUOTE_TOKENS
      .filter(q => q.address.toLowerCase() !== tokenAddr.toLowerCase())
      .map((q) => ({
        dex: f.dex,
        quote: q.address,
        factory: f.address,
        target: f.address,
        allowFailure: true,
        callData: factoryIface.encodeFunctionData('getPair', [tokenAddr, q.address])
      }))
  );

  const pairResults = await multicallBatch(
    getPairCalls.map(c => ({ target: c.target, allowFailure: c.allowFailure, callData: c.callData }))
  );

  interface Found { dex: DexName; quote: Hex; pair: Hex; }
  const found: Found[] = [];
  pairResults.forEach((r, i) => {
    if (!r.success) return;
    try {
      const addr = factoryIface.decodeFunctionResult('getPair', r.returnData)[0] as string;
      if (addr && addr !== ZERO) {
        found.push({
          dex: getPairCalls[i].dex,
          quote: getPairCalls[i].quote as Hex,
          pair: getAddress(addr) as Hex
        });
      }
    } catch { /* skip */ }
  });

  if (found.length === 0) return [];

  // Phase 2: For each discovered pair, batch fetch token0, token1, getReserves.
  const metaCalls = found.flatMap(f => [
    { target: f.pair, allowFailure: true, callData: pairIface.encodeFunctionData('token0', []) },
    { target: f.pair, allowFailure: true, callData: pairIface.encodeFunctionData('token1', []) },
    { target: f.pair, allowFailure: true, callData: pairIface.encodeFunctionData('getReserves', []) }
  ]);

  const metaResults = await multicallBatch(metaCalls);

  const out: DiscoveredPair[] = [];
  for (let i = 0; i < found.length; i++) {
    const base = i * 3;
    const r0 = metaResults[base];
    const r1 = metaResults[base + 1];
    const r2 = metaResults[base + 2];
    if (!r0.success || !r1.success || !r2.success) continue;
    try {
      const token0 = pairIface.decodeFunctionResult('token0', r0.returnData)[0] as string;
      const token1 = pairIface.decodeFunctionResult('token1', r1.returnData)[0] as string;
      const res = pairIface.decodeFunctionResult('getReserves', r2.returnData);
      const reserve0 = (res[0] as bigint).toString();
      const reserve1 = (res[1] as bigint).toString();
      // Filter dead / drained pairs
      if (reserve0 === '0' || reserve1 === '0') continue;
      out.push({
        dex: found[i].dex,
        quoteAddress: found[i].quote,
        pair: found[i].pair,
        token0: getAddress(token0) as Hex,
        token1: getAddress(token1) as Hex,
        reserve0,
        reserve1,
        blockTimestampLast: Number(res[2])
      });
    } catch { /* skip */ }
  }
  return out;
}
