export type Hex = `0x${string}`;

export interface TokenMeta {
  address: Hex;
  name: string;
  symbol: string;
  decimals: number;
  totalSupply: string; // decimal string, human-scaled
}

export type DexName =
  | 'pulsex-v1'
  | 'pulsex-v2'
  | '9inch-v2'
  | '9mm-v2';

export interface PairReserves {
  pair: Hex;
  token0: Hex;
  token1: Hex;
  reserve0: string; // raw wei-like decimal string
  reserve1: string;
  blockTimestampLast: number;
}

export interface PairInfo extends PairReserves {
  dex: DexName;
  tokenSide: 0 | 1;       // which side is the target token
  quoteSide: 0 | 1;       // which side is the quote (other) token
  tokenSymbol: string;
  quoteSymbol: string;
  quoteAddress: Hex;
  decimalsToken: number;
  decimalsQuote: number;
  priceTokenInQuote: number; // quote per 1 token, float
  priceUsd: number;          // USD per 1 token, float
  tvlUsd: number;
  tvlPls: number;
  pctOfTotal: number;        // 0..1 — filled after all pairs collected
  wplsForOnePercentMove: number;
  deployBlock: number | null;
}

export interface SwapEvent {
  txHash: Hex;
  block: number;
  timestamp: number;
  dex: DexName;
  pair: Hex;
  direction: 'buy' | 'sell';
  amountToken: string;  // human-scaled decimal string
  amountQuote: string;
  usdValue: number;
  actor: Hex;
  actorLabel: string | null;
  priceAfter: number;
}

export interface LpHolder {
  address: Hex;
  label: string | null;
  lpBalance: string;   // raw decimal string
  pctOfPool: number;   // 0..1
  usdValue: number;
}
