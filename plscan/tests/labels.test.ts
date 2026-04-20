import { describe, it, expect } from 'vitest';
import { getAddress } from 'ethers';
import { FACTORIES, QUOTE_TOKENS, MULTICALL3, WPLS, PDAI } from '@/lib/chain/addresses';
import { callWithFallback } from '@/lib/chain/rpc';
import { labelFor, KNOWN_LABELS } from '@/lib/labels';

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

describe('labels', () => {
  it('labels known PulseX routers', () => {
    expect(labelFor('0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02')).toBe('PulseX V1 Router');
    expect(labelFor('0x165C3410fC91EF562C50559f7d2289fEbed552d9')).toBe('PulseX V2 Router');
  });
  it('labels burn addresses', () => {
    expect(labelFor('0x0000000000000000000000000000000000000000')).toBe('Null');
    expect(labelFor('0x000000000000000000000000000000000000dEaD')).toBe('Burn');
  });
  it('returns null for unknown addresses', () => {
    expect(labelFor('0x17367877aF5A8D0Eb33ba5689A880f696386E24D')).toBeNull();
  });
  it('is case-insensitive', () => {
    expect(labelFor('0x165c3410fc91ef562c50559f7d2289febed552d9')).toBe('PulseX V2 Router');
  });
});

describe('chain/addresses liveness', () => {
  it('all factory addresses have bytecode on PulseChain', async () => {
    for (const f of FACTORIES) {
      const code = await callWithFallback(async (p) => p.getCode(f.address));
      expect(code.length, `${f.dex} at ${f.address} has no code`).toBeGreaterThan(2);
    }
  }, 30000);

  it('MULTICALL3 has bytecode', async () => {
    const code = await callWithFallback(async (p) => p.getCode(MULTICALL3));
    expect(code.length).toBeGreaterThan(2);
  }, 15000);
});
