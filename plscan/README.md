# PLSCAN LP

Token-first liquidity intelligence for PulseChain. Paste any token address; get every LP pair across PulseX V1/V2 and 9mm V2 with TVL, prices, depth curve, swap feed, and LP holder breakdown.

## Local dev

```
cp .env.local.example .env.local
npm install
npm run dev
```

Visit http://localhost:3000.

## Tests

```
npm test
```

Integration tests hit real PulseChain RPC — they require network access.

## Deploy (Vercel)

1. Push to a Vercel-connected repo.
2. In Vercel project settings, set env vars from `.env.local.example` (required: none for MVP — defaults point to public RPC/BlockScout; optional: Vercel KV for cache).
3. Build command: `next build`. Output: automatic.

## Notes

- Chain: PulseChain (chain ID 369).
- Read-only — no wallet connection, no user state.
- MVP scope limited to V2 pools (PulseX V1/V2, 9mm V2). V3 support, historical price, and wallet scanner are in roadmap.
- **Known limitation:** USD values derive from WPLS/pDAI pair rate assuming pDAI=$1. Since pDAI trades at a discount to USD on PulseChain, absolute USD values are inflated. Relative rankings (% of pool, deepest pair) remain accurate.
