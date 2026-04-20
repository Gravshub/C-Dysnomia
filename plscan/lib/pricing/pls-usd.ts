import { discoverV2Pairs } from '../discovery/v2-pairs';
import { WPLS, QUOTE_TOKENS } from '../chain/addresses';
import { rawToHuman } from '../format';

const STABLE_LOWER = new Set(
  QUOTE_TOKENS.filter(q => q.isStableUsd).map(q => q.address.toLowerCase())
);

// PulseChain mirrors: pDAI is 18 decimals; pUSDC / pUSDT mirrors are 6.
const STABLE_DECIMALS: Record<string, number> = Object.fromEntries(
  QUOTE_TOKENS.filter(q => q.isStableUsd).map(q => {
    const d = q.symbol === 'pDAI' ? 18 : 6;
    return [q.address.toLowerCase(), d];
  })
);

let cached: { value: number; at: number } | null = null;
const TTL_MS = 30_000;

export async function getPlsUsd(): Promise<number> {
  const now = Date.now();
  if (cached && now - cached.at < TTL_MS) return cached.value;

  const pairs = await discoverV2Pairs(WPLS);
  // Filter to WPLS <> stable pairs and pick deepest (by WPLS reserve).
  const stablePairs = pairs.filter(p => STABLE_LOWER.has(p.quoteAddress.toLowerCase()));
  if (stablePairs.length === 0) throw new Error('No WPLS/stable pair discovered');

  const ranked = stablePairs
    .map(p => {
      const wplsIsToken0 = p.token0.toLowerCase() === WPLS.toLowerCase();
      const wplsReserve = rawToHuman(wplsIsToken0 ? p.reserve0 : p.reserve1, 18);
      const stableReserve = rawToHuman(
        wplsIsToken0 ? p.reserve1 : p.reserve0,
        STABLE_DECIMALS[p.quoteAddress.toLowerCase()] ?? 18
      );
      return { p, wplsReserve, stableReserve };
    })
    .sort((a, b) => b.wplsReserve - a.wplsReserve);

  const top = ranked[0];
  const rate = top.stableReserve / top.wplsReserve;
  cached = { value: rate, at: now };
  return rate;
}
