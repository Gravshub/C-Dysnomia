import type { DexName, Hex } from '../types';

export const MULTICALL3: Hex = '0xcA11bde05977b3631167028862bE2a173976CA11';

export const PULSE_CHAIN_ID = 369;

export const WPLS: Hex   = '0xA1077a294dDE1B09bB078844df40758a5D0f9a27';
export const PDAI: Hex   = '0x6B175474E89094C44Da98b954EedeAC495271d0F';
export const PUSDC: Hex  = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48';
export const PUSDT: Hex  = '0xdAC17F958D2ee523a2206206994597C13D831ec7';

export interface Factory {
  dex: DexName;
  address: Hex;
  initCodeHash: Hex | null;
}

// NOTE: 9inch V2 and 9mm V2 factory addresses must be verified against
// each project's docs/deployed contracts before first deploy.
// Values below are the current mainnet (PulseChain) deployments.
export const FACTORIES: Factory[] = [
  { dex: 'pulsex-v1', address: '0x1715a3E4A142d8b698131108995174F37aEBA10D', initCodeHash: null },
  { dex: 'pulsex-v2', address: '0x29eA7545DEf87022BAdc76323F373EA1e707C523', initCodeHash: null },
  { dex: '9inch-v2',  address: '0xe5dCDc13B628C2df813dB1080367e929c1507CA0', initCodeHash: null },
  { dex: '9mm-v2',    address: '0x3a0Fa7884dD93f3cd234bBE2A0958Ef04b05E13b', initCodeHash: null }
];

// Curated quote-token universe for discovery.
// Each token address is lowercased for comparison; checksum is only required
// when sending. The keys become query set for getPair against every factory.
export const QUOTE_TOKENS: ReadonlyArray<{ address: Hex; symbol: string; isStableUsd: boolean }> = [
  { address: WPLS,                                             symbol: 'WPLS',     isStableUsd: false },
  { address: PDAI,                                             symbol: 'pDAI',     isStableUsd: true },
  { address: PUSDC,                                            symbol: 'pUSDC',    isStableUsd: true },
  { address: PUSDT,                                            symbol: 'pUSDT',    isStableUsd: true },
  { address: '0x2b591e99afe9f32eaa6214f7b7629768c40eeb39',    symbol: 'HEX',      isStableUsd: false },
  { address: '0x95b303987a60c71504d99aa1b13b4da07b0790ab',    symbol: 'PLSX',     isStableUsd: false },
  { address: '0x2fa878Ab3F87CC1C9737Fc071108F904c0B0C95d',    symbol: 'INC',      isStableUsd: false },
  { address: '0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6',    symbol: 'ATROPA',   isStableUsd: false },
  { address: '0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff',    symbol: 'FED',      isStableUsd: false },
  { address: '0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D',    symbol: 'AFFECTION',isStableUsd: false },
  { address: '0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29',    symbol: 'WM',       isStableUsd: false },
  { address: '0x02DcdD04e3F455D838cd1249292C58f3B79e3C3C',    symbol: 'WETH',     isStableUsd: false }
];
