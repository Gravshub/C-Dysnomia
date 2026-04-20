import { Interface, getAddress } from 'ethers';
import { ABI_PAIR_V2 } from '../chain/abi';
import { multicallBatch } from '../chain/multicall';
import type { Hex } from '../types';

const pair = new Interface(ABI_PAIR_V2);

export type LpDetection =
  | { isPair: false }
  | {
      isPair: true;
      address: Hex;
      token0: Hex;
      token1: Hex;
      reserve0: string;
      reserve1: string;
      blockTimestampLast: number;
    };

export async function detectLpPair(rawAddr: string): Promise<LpDetection> {
  let addr: Hex;
  try {
    addr = getAddress(rawAddr) as Hex;
  } catch {
    return { isPair: false };
  }

  const calls = [
    { target: addr, allowFailure: true, callData: pair.encodeFunctionData('token0', []) },
    { target: addr, allowFailure: true, callData: pair.encodeFunctionData('token1', []) },
    { target: addr, allowFailure: true, callData: pair.encodeFunctionData('getReserves', []) }
  ];

  const [r0, r1, r2] = await multicallBatch(calls);
  if (!r0.success || !r1.success || !r2.success) return { isPair: false };

  try {
    const token0 = pair.decodeFunctionResult('token0', r0.returnData)[0] as string;
    const token1 = pair.decodeFunctionResult('token1', r1.returnData)[0] as string;
    const res = pair.decodeFunctionResult('getReserves', r2.returnData);
    return {
      isPair: true,
      address: addr,
      token0: getAddress(token0) as Hex,
      token1: getAddress(token1) as Hex,
      reserve0: (res[0] as bigint).toString(),
      reserve1: (res[1] as bigint).toString(),
      blockTimestampLast: Number(res[2])
    };
  } catch {
    return { isPair: false };
  }
}
