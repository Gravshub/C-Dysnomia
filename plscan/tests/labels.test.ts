import { describe, it, expect } from 'vitest';
import { getAddress } from 'ethers';
import { FACTORIES, QUOTE_TOKENS, MULTICALL3, WPLS, PDAI } from '@/lib/chain/addresses';

const isAddr = (s: string) => /^0x[0-9a-fA-F]{40}$/.test(s);

describe('chain/addresses', () => {
  it('MULTICALL3 is a valid address', () => {
    expect(isAddr(MULTICALL3)).toBe(true);
  });

  it('all factory addresses are valid', () => {
    for (const f of FACTORIES) expect(isAddr(f.address)).toBe(true);
    expect(new Set(FACTORIES.map(f => f.dex)).size).toBe(FACTORIES.length);
  });

  it('all quote tokens are valid and unique', () => {
    const lower = QUOTE_TOKENS.map(q => q.address.toLowerCase());
    expect(new Set(lower).size).toBe(QUOTE_TOKENS.length);
    for (const q of QUOTE_TOKENS) expect(isAddr(q.address)).toBe(true);
  });

  it('stable USD quotes are defined', () => {
    const stables = QUOTE_TOKENS.filter(q => q.isStableUsd).map(q => q.symbol);
    expect(stables).toEqual(expect.arrayContaining(['pDAI', 'pUSDC', 'pUSDT']));
  });

  it('WPLS and pDAI are in the quote set', () => {
    const addrs = QUOTE_TOKENS.map(q => q.address);
    expect(addrs).toContain(WPLS);
    expect(addrs).toContain(PDAI);
  });
});

describe('chain/addresses EIP-55 checksum', () => {
  it('all factory addresses are canonical EIP-55 checksum', () => {
    for (const f of FACTORIES) {
      expect(() => getAddress(f.address)).not.toThrow();
      expect(getAddress(f.address)).toBe(f.address);
    }
  });

  it('MULTICALL3 is canonical EIP-55 checksum', () => {
    expect(getAddress(MULTICALL3)).toBe(MULTICALL3);
  });

  it('all quote token addresses are canonical EIP-55 checksum', () => {
    for (const q of QUOTE_TOKENS) {
      expect(() => getAddress(q.address)).not.toThrow();
      expect(getAddress(q.address)).toBe(q.address);
    }
  });
});
