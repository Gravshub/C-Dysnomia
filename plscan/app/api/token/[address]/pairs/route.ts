import { NextResponse } from 'next/server';
import { getAddress } from 'ethers';
import { discoverV2Pairs } from '@/lib/discovery/v2-pairs';
import { readTokenMetaBatch } from '@/lib/chain/token-meta';
import { getPlsUsd } from '@/lib/pricing/pls-usd';
import { priceTokenUsd } from '@/lib/pricing/token-usd';
import { WPLS } from '@/lib/chain/addresses';
import { rawToHuman, formatDex } from '@/lib/format';
import { amountInForImpact, buildDepthCurve } from '@/lib/analytics/depth';
import { cacheGetSet } from '@/lib/cache/kv';
import type { PairInfo } from '@/lib/types';

export const dynamic = 'force-dynamic';

// Stable quote symbols — covers both PulseChain mirror naming (p-prefix) and
// the bare on-chain symbol() strings those mirrors return. Must match the set
// used in lib/pricing/token-usd.ts.
const STABLE_SYMBOLS = new Set(['pDAI', 'DAI', 'pUSDC', 'USDC', 'pUSDT', 'USDT']);

async function buildPayload(tokenAddr: string) {
  const [rawPairs, plsUsd] = await Promise.all([
    discoverV2Pairs(tokenAddr),
    getPlsUsd()
  ]);

  if (rawPairs.length === 0) {
    return {
      summary: {
        pairCount: 0, dexCount: 0, totalTvlUsd: 0, deepestPairTvlUsd: 0,
        priceUsd: 0, priceChange24h: null, totalTokenLiquidity: 0, plsUsd
      },
      pairs: [],
      topPairDepth: null
    };
  }

  const tokenLower = tokenAddr.toLowerCase();
  const uniqueTokens = new Set<string>([tokenAddr]);
  rawPairs.forEach(p => uniqueTokens.add(p.quoteAddress));
  const metas = await readTokenMetaBatch(Array.from(uniqueTokens));
  const tokenMeta = metas.find(m => m.address.toLowerCase() === tokenLower)!;
  const quoteMetas: Record<string, typeof metas[number]> = Object.fromEntries(
    metas.filter(m => m.address.toLowerCase() !== tokenLower).map(m => [m.address.toLowerCase(), m])
  );

  const priceUsd = priceTokenUsd(tokenAddr, tokenMeta, rawPairs, quoteMetas, plsUsd);

  // Build PairInfo for each discovered pair
  const pairs: PairInfo[] = [];
  for (const p of rawPairs) {
    const quoteMeta = quoteMetas[p.quoteAddress.toLowerCase()];
    if (!quoteMeta) continue;

    const tokenIsToken0 = p.token0.toLowerCase() === tokenLower;
    const tokenSide: 0 | 1 = tokenIsToken0 ? 0 : 1;
    const quoteSide: 0 | 1 = tokenIsToken0 ? 1 : 0;
    const tokenRes = rawToHuman(tokenIsToken0 ? p.reserve0 : p.reserve1, tokenMeta.decimals);
    const quoteRes = rawToHuman(tokenIsToken0 ? p.reserve1 : p.reserve0, quoteMeta.decimals);
    if (tokenRes <= 0 || quoteRes <= 0) continue;

    const priceTokenInQuote = quoteRes / tokenRes;

    // Price in USD via this pair (derived — not necessarily the weighted price above)
    let pairPriceUsd = 0;
    let tvlUsd = 0;
    let quoteUsdPerOne = 0;
    if (STABLE_SYMBOLS.has(quoteMeta.symbol)) {
      quoteUsdPerOne = 1;
    } else if (p.quoteAddress.toLowerCase() === WPLS.toLowerCase()) {
      quoteUsdPerOne = plsUsd;
    }
    if (quoteUsdPerOne > 0) {
      pairPriceUsd = priceTokenInQuote * quoteUsdPerOne;
      tvlUsd = quoteRes * quoteUsdPerOne * 2;
    }
    const tvlPls = plsUsd > 0 ? tvlUsd / plsUsd : 0;

    // WPLS needed for 1% move. Two cases:
    //   (a) Target token is WPLS itself → the "token side" IS the WPLS side,
    //       so push WPLS in against the quote reserve: amountIn(tokenRes, quoteRes, 1%).
    //   (b) Quote is WPLS (normal case) → push WPLS into quote reserve to move
    //       the target token's price: amountIn(quoteRes, tokenRes, 1%).
    //   Else → not a WPLS-involved pair, depth in WPLS units is not meaningful.
    const targetIsWpls = tokenLower === WPLS.toLowerCase();
    const quoteIsWpls = p.quoteAddress.toLowerCase() === WPLS.toLowerCase();
    let wplsForOnePercent = 0;
    if (targetIsWpls) {
      wplsForOnePercent = amountInForImpact(tokenRes, quoteRes, 0.01);
    } else if (quoteIsWpls) {
      wplsForOnePercent = amountInForImpact(quoteRes, tokenRes, 0.01);
    }

    pairs.push({
      pair: p.pair,
      dex: p.dex,
      token0: p.token0,
      token1: p.token1,
      reserve0: p.reserve0,
      reserve1: p.reserve1,
      blockTimestampLast: p.blockTimestampLast,
      tokenSide,
      quoteSide,
      tokenSymbol: tokenMeta.symbol,
      quoteSymbol: quoteMeta.symbol,
      quoteAddress: p.quoteAddress,
      decimalsToken: tokenMeta.decimals,
      decimalsQuote: quoteMeta.decimals,
      priceTokenInQuote,
      priceUsd: pairPriceUsd,
      tvlUsd,
      tvlPls,
      pctOfTotal: 0,
      wplsForOnePercentMove: wplsForOnePercent,
      deployBlock: null
    });
  }

  // Sort by TVL desc and assign pctOfTotal
  pairs.sort((a, b) => b.tvlUsd - a.tvlUsd);
  const totalTvlUsd = pairs.reduce((s, p) => s + p.tvlUsd, 0);
  pairs.forEach(p => { p.pctOfTotal = totalTvlUsd > 0 ? p.tvlUsd / totalTvlUsd : 0; });

  const top = pairs[0];
  let topPairDepth:
    | { pair: string; dex: string; dexLabel: string; points: unknown[] }
    | null = null;
  if (top) {
    const tokenIsToken0 = top.tokenSide === 0;
    const tokenRes = rawToHuman(tokenIsToken0 ? top.reserve0 : top.reserve1, tokenMeta.decimals);
    const quoteRes = rawToHuman(
      tokenIsToken0 ? top.reserve1 : top.reserve0,
      quoteMetas[top.quoteAddress.toLowerCase()].decimals
    );
    const quoteUsdPerOne = STABLE_SYMBOLS.has(top.quoteSymbol)
      ? 1
      : top.quoteAddress.toLowerCase() === WPLS.toLowerCase()
        ? plsUsd
        : 0;
    const curve = buildDepthCurve(quoteRes, tokenRes, quoteUsdPerOne);
    topPairDepth = { pair: top.pair, dex: top.dex, dexLabel: formatDex(top.dex), points: curve };
  }

  const totalTokenLiquidity = pairs.reduce((s, p) => {
    const r = p.tokenSide === 0 ? p.reserve0 : p.reserve1;
    return s + rawToHuman(r, tokenMeta.decimals);
  }, 0);

  return {
    summary: {
      pairCount: pairs.length,
      dexCount: new Set(pairs.map(p => p.dex)).size,
      totalTvlUsd,
      deepestPairTvlUsd: top?.tvlUsd ?? 0,
      priceUsd,
      priceChange24h: null, // MVP: populate in Phase 3
      totalTokenLiquidity,
      plsUsd
    },
    pairs,
    topPairDepth
  };
}

export async function GET(_req: Request, ctx: { params: { address: string } }) {
  let addr: string;
  try { addr = getAddress(ctx.params.address); }
  catch { return NextResponse.json({ error: 'invalid address' }, { status: 400 }); }

  try {
    const payload = await cacheGetSet(`pairs:${addr.toLowerCase()}`, 30, () => buildPayload(addr));
    return NextResponse.json(payload, {
      headers: { 'Cache-Control': 'public, s-maxage=30, stale-while-revalidate=60' }
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 503 });
  }
}
