import { NextResponse } from 'next/server';
import { getAddress } from 'ethers';
import { detectLpPair } from '@/lib/discovery/lp-detect';
import { readTokenMetaBatch } from '@/lib/chain/token-meta';
import { getPlsUsd } from '@/lib/pricing/pls-usd';
import { WPLS } from '@/lib/chain/addresses';
import { rawToHuman } from '@/lib/format';
import { buildDepthCurve } from '@/lib/analytics/depth';
import { cacheGetSet } from '@/lib/cache/kv';

export const dynamic = 'force-dynamic';

export async function GET(_req: Request, ctx: { params: { address: string } }) {
  let addr: string;
  try { addr = getAddress(ctx.params.address); }
  catch { return NextResponse.json({ error: 'invalid address' }, { status: 400 }); }

  try {
    const payload = await cacheGetSet(`pair:${addr.toLowerCase()}`, 30, async () => {
      const det = await detectLpPair(addr);
      if (!det.isPair) return { isPair: false };
      const [metas, plsUsd] = await Promise.all([
        readTokenMetaBatch([det.token0, det.token1]),
        getPlsUsd()
      ]);
      const m0 = metas[0];
      const m1 = metas[1];
      const r0 = rawToHuman(det.reserve0, m0.decimals);
      const r1 = rawToHuman(det.reserve1, m1.decimals);

      // Identify quote side by preference stable > WPLS > token1
      const stables = new Set(['pDAI', 'DAI', 'pUSDC', 'USDC', 'pUSDT', 'USDT']);
      let quoteIs = 1 as 0 | 1;
      if (stables.has(m0.symbol) && !stables.has(m1.symbol)) quoteIs = 0;
      else if (m0.address.toLowerCase() === WPLS.toLowerCase()) quoteIs = 0;

      const quoteMeta = quoteIs === 0 ? m0 : m1;
      const tokenMeta = quoteIs === 0 ? m1 : m0;
      const quoteRes = quoteIs === 0 ? r0 : r1;
      const tokenRes = quoteIs === 0 ? r1 : r0;

      const quoteUsdPerOne = stables.has(quoteMeta.symbol) ? 1
        : quoteMeta.address.toLowerCase() === WPLS.toLowerCase() ? plsUsd : 0;
      const priceUsd = tokenRes > 0 && quoteUsdPerOne > 0
        ? (quoteRes / tokenRes) * quoteUsdPerOne : 0;
      const tvlUsd = quoteRes * quoteUsdPerOne * 2;

      return {
        isPair: true,
        address: addr,
        token0: m0,
        token1: m1,
        reserve0: det.reserve0,
        reserve1: det.reserve1,
        quoteSide: quoteIs,
        priceUsd,
        tvlUsd,
        depth: {
          points: buildDepthCurve(quoteRes, tokenRes, quoteUsdPerOne)
        }
      };
    });
    return NextResponse.json(payload);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 503 });
  }
}
