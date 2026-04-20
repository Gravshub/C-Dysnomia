// Constant-product AMM with 0.3% fee.
const FEE_NUM = 997n;
const FEE_DEN = 1000n;

export function amountOut(amountIn: number, reserveIn: number, reserveOut: number): number {
  if (amountIn <= 0 || reserveIn <= 0 || reserveOut <= 0) return 0;
  const inWithFee = amountIn * 0.997;
  return (reserveOut * inWithFee) / (reserveIn + inWithFee);
}

// Price impact on buy side: start price = reserveOut/reserveIn, after price = (reserveOut-out)/(reserveIn+in).
// Returns a fraction (0..1). Measures curve slippage only (fee-exclusive), matching the
// standard Uniswap UI definition where a trivial trade has ~0 impact.
export function priceImpact(amountIn: number, reserveIn: number, reserveOut: number): number {
  if (amountIn <= 0 || reserveIn <= 0 || reserveOut <= 0) return 0;
  // Fee-exclusive out amount: pure xy=k curve, no 0.3% fee applied.
  const outNoFee = (reserveOut * amountIn) / (reserveIn + amountIn);
  const priceBefore = reserveOut / reserveIn;
  const effectiveRate = outNoFee / amountIn;
  return 1 - effectiveRate / priceBefore;
}

// Binary-search the IN amount that causes target impact (fraction 0..1).
// Returns the smallest amountIn producing >= targetImpact.
export function amountInForImpact(
  reserveIn: number, reserveOut: number, targetImpact: number,
  maxIterations = 60
): number {
  if (targetImpact <= 0) return 0;
  let lo = 0;
  let hi = reserveIn * 100;
  for (let i = 0; i < maxIterations; i++) {
    const mid = (lo + hi) / 2;
    const pi = priceImpact(mid, reserveIn, reserveOut);
    if (pi < targetImpact) lo = mid; else hi = mid;
    if (Math.abs(hi - lo) / reserveIn < 1e-9) break;
  }
  return (lo + hi) / 2;
}

export interface DepthPoint {
  impact: number;   // input fraction (0.005 = 0.5%)
  amountIn: number; // quote-side units (e.g. WPLS)
  amountInUsd: number;
}

export function buildDepthCurve(
  reserveQuote: number,
  reserveToken: number,
  quoteUsdPerOne: number,
  impacts: number[] = [0.005, 0.01, 0.02, 0.05, 0.10]
): DepthPoint[] {
  return impacts.map(imp => {
    const amt = amountInForImpact(reserveQuote, reserveToken, imp);
    return { impact: imp, amountIn: amt, amountInUsd: amt * quoteUsdPerOne };
  });
}
