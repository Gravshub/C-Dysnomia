import { describe, it, expect } from 'vitest';
import { formatUsd, formatNumber, formatAddress, formatPercent, rawToHuman } from '@/lib/format';

describe('format', () => {
  it('formatUsd small', () => {
    expect(formatUsd(0.0000071)).toBe('$7.10e-6');
    expect(formatUsd(1234.56)).toBe('$1.23K');
    expect(formatUsd(12345678)).toBe('$12.35M');
    expect(formatUsd(0)).toBe('$0');
  });

  it('formatNumber scales to K/M/B/T', () => {
    expect(formatNumber(999)).toBe('999');
    expect(formatNumber(1500)).toBe('1.50K');
    expect(formatNumber(2_500_000)).toBe('2.50M');
    expect(formatNumber(3_400_000_000)).toBe('3.40B');
  });

  it('formatAddress truncates', () => {
    expect(formatAddress('0x17367877aF5A8D0Eb33ba5689A880f696386E24D')).toBe('0x1736…E24D');
  });

  it('formatPercent', () => {
    expect(formatPercent(0.0125)).toBe('1.25%');
    expect(formatPercent(0.5)).toBe('50.00%');
  });

  it('rawToHuman', () => {
    expect(rawToHuman('1000000000000000000', 18)).toBeCloseTo(1, 9);
    expect(rawToHuman('1500000', 6)).toBeCloseTo(1.5, 6);
  });
});
