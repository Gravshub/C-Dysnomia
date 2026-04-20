import { WPLS } from '../chain/addresses';
import { rawToHuman } from '../format';
import type { DexName, Hex, TokenMeta } from '../types';

interface PriceablePair {
  pair: Hex;
  dex: DexName;
  token0: Hex;
  token1: Hex;
  reserve0: string;
  reserve1: string;
  quoteAddress: Hex;
}

// Covers both the PulseChain mirror convention (pDAI/pUSDC/pUSDT) and the
// underlying on-chain symbol() strings, which for the mirror tokens return
// "DAI"/"USDC"/"USDT" rather than the p-prefixed names. Without the unprefixed
// variants, stable quotes routed through these mirrors would be mis-classified.
const STABLE_SYMBOLS = new Set(['pDAI', 'DAI', 'pUSDC', 'USDC', 'pUSDT', 'USDT']);

export function priceTokenUsd(
  tokenAddr: string,
  tokenMeta: TokenMeta,
  pairs: PriceablePair[],
  quoteMetas: Record<string, TokenMeta>,
  plsUsd: number
): number {
  if (pairs.length === 0) return 0;
  const lowerToken = tokenAddr.toLowerCase();

  // Compute price + USD depth for every pair; pick deepest.
  let best: { priceUsd: number; tvlUsd: number } | null = null;

  for (const p of pairs) {
    const quoteMeta = quoteMetas[p.quoteAddress.toLowerCase()];
    if (!quoteMeta) continue;

    const tokenIsToken0 = p.token0.toLowerCase() === lowerToken;
    const tokenRes = rawToHuman(tokenIsToken0 ? p.reserve0 : p.reserve1, tokenMeta.decimals);
    const quoteRes = rawToHuman(tokenIsToken0 ? p.reserve1 : p.reserve0, quoteMeta.decimals);
    if (tokenRes <= 0 || quoteRes <= 0) continue;

    const priceInQuote = quoteRes / tokenRes; // quote per 1 token
    const quoteIsStable = STABLE_SYMBOLS.has(quoteMeta.symbol);
    const quoteIsWpls = p.quoteAddress.toLowerCase() === WPLS.toLowerCase();

    let priceUsd: number;
    let quoteUsdPerOne: number;
    if (quoteIsStable) {
      priceUsd = priceInQuote;
      quoteUsdPerOne = 1;
    } else if (quoteIsWpls) {
      priceUsd = priceInQuote * plsUsd;
      quoteUsdPerOne = plsUsd;
    } else {
      // Non-stable, non-WPLS quote — skip (we can't price without a second hop in MVP)
      continue;
    }

    const tvlUsd = quoteRes * quoteUsdPerOne * 2; // both sides have equal USD value in a V2 pool
    if (!best || tvlUsd > best.tvlUsd) best = { priceUsd, tvlUsd };
  }

  return best?.priceUsd ?? 0;
}
