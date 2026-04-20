import { NextResponse } from 'next/server';
import { getAddress } from 'ethers';
import { fetchTokenTransfers } from '@/lib/external/blockscout';
import { discoverV2Pairs } from '@/lib/discovery/v2-pairs';
import { readTokenMeta, readTokenMetaBatch } from '@/lib/chain/token-meta';
import { getPlsUsd } from '@/lib/pricing/pls-usd';
import { priceTokenUsd } from '@/lib/pricing/token-usd';
import { labelFor } from '@/lib/labels';
import { rawToHuman } from '@/lib/format';
import { cacheGetSet } from '@/lib/cache/kv';

export const dynamic = 'force-dynamic';

export async function GET(_req: Request, ctx: { params: { address: string } }) {
  let addr: string;
  try { addr = getAddress(ctx.params.address); }
  catch { return NextResponse.json({ error: 'invalid address' }, { status: 400 }); }

  try {
    const payload = await cacheGetSet(`swaps:${addr.toLowerCase()}`, 20, async () => {
      const [transfers, pairs, tokenMeta, plsUsd] = await Promise.all([
        fetchTokenTransfers(addr, { offset: 50 }),
        discoverV2Pairs(addr),
        readTokenMeta(addr),
        getPlsUsd()
      ]);

      const pairSet = new Set(pairs.map(p => p.pair.toLowerCase()));
      const pairToDex = new Map(pairs.map(p => [p.pair.toLowerCase(), p.dex]));

      const quoteMetas = Object.fromEntries(
        (await readTokenMetaBatch(pairs.map(p => p.quoteAddress)))
          .map(m => [m.address.toLowerCase(), m])
      );
      const priceUsd = priceTokenUsd(addr, tokenMeta, pairs, quoteMetas, plsUsd);

      const events = transfers
        .filter(t => pairSet.has(t.from.toLowerCase()) || pairSet.has(t.to.toLowerCase()))
        .map(t => {
          const fromIsPair = pairSet.has(t.from.toLowerCase());
          const pairAddr = fromIsPair ? t.from : t.to;
          const actor = fromIsPair ? t.to : t.from;
          const direction: 'buy' | 'sell' = fromIsPair ? 'buy' : 'sell';
          const amountToken = rawToHuman(t.value, Number(t.tokenDecimal || tokenMeta.decimals));
          return {
            txHash: t.hash,
            block: Number(t.blockNumber),
            timestamp: Number(t.timeStamp),
            pair: pairAddr,
            dex: pairToDex.get(pairAddr.toLowerCase()) ?? 'unknown',
            direction,
            amountToken: amountToken.toString(),
            amountQuote: '',
            usdValue: amountToken * priceUsd,
            actor,
            actorLabel: labelFor(actor)
          };
        });

      return { events, priceUsd, plsUsd };
    });

    return NextResponse.json(payload, {
      headers: { 'Cache-Control': 'public, s-maxage=20, stale-while-revalidate=40' }
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 503 });
  }
}
