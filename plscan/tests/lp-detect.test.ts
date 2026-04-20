import { describe, it, expect } from 'vitest';
import { detectLpPair } from '@/lib/discovery/lp-detect';

// GIBS/WPLS V2 pair (PulseX V2)
const GIBS_WPLS = '0x7BCa1c997C475Eac9c61417e88bED158ACA757F0';
// WPLS itself (an ERC20, not a pair)
const WPLS = '0xA1077a294dDE1B09bB078844df40758a5D0f9a27';

describe('lp-detect', () => {
  it('detects an LP pair and returns token sides', async () => {
    const info = await detectLpPair(GIBS_WPLS);
    expect(info.isPair).toBe(true);
    if (info.isPair) {
      expect(info.token0.toLowerCase().startsWith('0x')).toBe(true);
      expect(info.token1.toLowerCase().startsWith('0x')).toBe(true);
    }
  }, 20000);

  it('returns isPair=false for a plain ERC20', async () => {
    const info = await detectLpPair(WPLS);
    expect(info.isPair).toBe(false);
  }, 20000);
});
