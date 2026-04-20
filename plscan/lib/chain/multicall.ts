import { Contract } from 'ethers';
import { MULTICALL3 } from './addresses';
import { ABI_MULTICALL3 } from './abi';
import { callWithFallback } from './rpc';

export interface Call3 {
  target: string;
  allowFailure: boolean;
  callData: string;
}
export interface Result3 {
  success: boolean;
  returnData: string;
}

export async function multicallBatch(
  calls: Call3[],
  opts: { chunkSize?: number } = {}
): Promise<Result3[]> {
  const chunkSize = opts.chunkSize ?? 1000;
  if (chunkSize <= 0) throw new Error(`chunkSize must be > 0, got ${chunkSize}`);

  const chunks: Call3[][] = [];
  for (let i = 0; i < calls.length; i += chunkSize) chunks.push(calls.slice(i, i + chunkSize));

  const runChunk = (chunk: Call3[]) =>
    callWithFallback(async (provider) => {
      const mc = new Contract(MULTICALL3, ABI_MULTICALL3, provider);
      const raw = await mc.aggregate3.staticCall(chunk);
      return (raw as Result3[]).map(r => ({ success: r.success, returnData: r.returnData }));
    });

  const results: Result3[] = [];
  for (let ci = 0; ci < chunks.length; ci++) {
    try {
      results.push(...await runChunk(chunks[ci]));
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      (e as Error & { chunkIndex?: number; chunkSize?: number }).chunkIndex = ci;
      (e as Error & { chunkIndex?: number; chunkSize?: number }).chunkSize = chunks[ci].length;
      throw e;
    }
  }
  return results;
}
