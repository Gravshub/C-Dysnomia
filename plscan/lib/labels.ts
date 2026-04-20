export const KNOWN_LABELS: Record<string, string> = Object.fromEntries(Object.entries({
  '0x0000000000000000000000000000000000000000': 'Null',
  '0x000000000000000000000000000000000000dead': 'Burn',
  // PulseX routers
  '0x98bf93ebf5c380c0e6ae8e192a7e2ae08edacc02': 'PulseX V1 Router',
  '0x165c3410fc91ef562c50559f7d2289febed552d9': 'PulseX V2 Router',
  // Multicall3
  '0xca11bde05977b3631167028862be2a173976ca11': 'Multicall3',
  // Dysnomia anchors
  '0x24f0154c1dce548adf15da2098fdd8b8a3b8151d': 'AFFECTION',
  '0xa1bee1dae9af77dac73aa0459ed63b4d93fc6d29': 'WM',
  '0xc7bdac3e6bb5ec37041a11328723e9927ccf430b': 'V1 Treasury Minter',
  '0xc15c5f699daf5e1135732139f05d2c05b3ef4354': 'V2 Federal Minter',
  '0x0c4f73328dfcecfbecf235c9f78a4494a7ec5ddc': 'V3 Index Minter',
  '0x394c3d5990cefc7be36b82fdb07a7251ace61cc7': 'V4 Personal Minter'
}).map(([k, v]) => [k.toLowerCase(), v]));

export function labelFor(addr: string | null | undefined): string | null {
  if (!addr) return null;
  return KNOWN_LABELS[addr.toLowerCase()] ?? null;
}
