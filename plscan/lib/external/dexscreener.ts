/**
 * DexScreener helper URLs.
 *
 * DexScreener hosts token logos on a predictable CDN path; we build the URL
 * from (chain, address) rather than hitting their API. If the logo is
 * missing the CDN returns 404 — callers should render a fallback.
 */

export function logoUrl(address: string, chain: string = 'pulsechain'): string {
  return `https://dd.dexscreener.com/ds-data/tokens/${chain}/${address.toLowerCase()}.png`;
}

export function dexscreenerTokenUrl(address: string, chain: string = 'pulsechain'): string {
  return `https://dexscreener.com/${chain}/${address.toLowerCase()}`;
}
