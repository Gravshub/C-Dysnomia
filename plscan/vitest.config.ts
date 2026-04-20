import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    environment: 'node',
    testTimeout: 30000,
    include: ['tests/**/*.test.ts'],
    passWithNoTests: true
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, '.') }
  }
});
