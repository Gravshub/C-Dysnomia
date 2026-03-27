// ============================================================
// |>JOYSTICK<| — GIBS LAU LP Partner Token Buyer
// PulseChain Chain ID 369 | Rabby Wallet Browser Injection
//
// Purchases 9 tokens needed to seed GIBS LAU liquidity pools.
// Each token is bought individually — you sign each TX.
// Routes selected for <1% price impact per on-chain analysis
// at block 25,982,422.
//
// IMPORTANT: Run ONE token at a time. Call buyToken(N) where
// N is the index from the PURCHASE_PLAN below (0-8).
// Or call buyAll() to step through them sequentially.
//
// Usage (browser console, Rabby connected to PulseChain):
//   buyToken(0)   // buy FED
//   buyToken(1)   // buy ATROPA
//   buyToken(2)   // buy WM
//   ... etc
//   buyAll()      // run all 9 in sequence (you sign each one)
//
// RPC reads via g4mm4.io. TX submitted via window.ethereum (Rabby).
// ============================================================

// ─── ADDRESSES ───────────────────────────────────────────────
const ADDR = {
  JOEY:       "0x17367877aF5A8D0Eb33ba5689A880f696386E24D",
  WPLS:       "0xA1077a294dDE1B09bB078844df40758a5D0f9a27",
  pDAI:       "0x6B175474E89094C44Da98b954EEdeAC495271D0f",  // bridge for ATROPA
  V2_ROUTER:  "0x165C3410fC91EF562C50559f7d2289fEbed552d9",
  CHAIN_ID:   "0x171",  // 369 decimal
  RPC_READ:   "https://rpc-pulsechain.g4mm4.io",
};

// ─── PURCHASE PLAN ───────────────────────────────────────────
// All amounts in wei (BigInt). Routes verified on-chain.
// Impact figures based on live reserves at block 25,982,422.
// Thin token (DFM/PARADE/TLRz/PROOF_RES/ZHENG/VOID) amounts
// are capped at 0.99% of their WPLS reserve — the maximum
// purchaseable under 1% impact. GIBS LP allocations will be
// adjusted to match these reduced partner quantities.
const PURCHASE_PLAN = [
  {
    index:    0,
    symbol:   "FED",
    address:  "0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff",
    // Route: V2 WPLS → FED (direct, 0.04% impact)
    path:     [ADDR.WPLS, "0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff"],
    // 492,611 PLS = $5.00
    amountInPLS: 492611n * 10n**18n,
    // 1% slippage on $5 buys — fine for deep pools
    slippagePct: 1,
    // Approximate out for display only (not used in TX)
    approxOut: "~316,070 FED",
    impact:   "0.04%",
    note:     "Deep V2 pool, $5 single TX, no problem.",
  },
  {
    index:    1,
    symbol:   "ATROPA",
    address:  "0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6",
    // Route: V2 WPLS → pDAI → ATROPA (2-hop, 0.004% impact)
    // pDAI is the lowest-impact bridge. WPLS/pDAI is massive.
    // pDAI/ATROPA pair also has deep TVL on V2.
    path:     [ADDR.WPLS, ADDR.pDAI, "0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6"],
    amountInPLS: 492611n * 10n**18n,
    slippagePct: 1,
    approxOut: "~169.6 ATROPA",
    impact:   "0.004%",
    note:     "2-hop via pDAI. Ultra-low impact on both legs.",
  },
  {
    index:    2,
    symbol:   "WM",
    address:  "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",
    // Route: V2 WPLS → WM (direct, 0.12% impact)
    path:     [ADDR.WPLS, "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29"],
    amountInPLS: 492611n * 10n**18n,
    slippagePct: 1,
    approxOut: "~22,415 WM",
    impact:   "0.12%",
    note:     "Deep V2 pool ~$8M TVL. $5 is nothing.",
  },
  {
    index:    3,
    symbol:   "DFM",
    address:  "0x51160F352ED148C89d48dfe6384Edd07aFA24E0E",
    // Route: V2 WPLS → DFM (direct)
    // DFM pool has UINT112_MAX tokens seeded (near-infinite token side).
    // WPLS reserve: 1,990,469 PLS. Max safe buy = 0.99% = 19,706 PLS.
    // Do NOT increase this amount — it will spike past 1% impact.
    path:     [ADDR.WPLS, "0x51160F352ED148C89d48dfe6384Edd07aFA24E0E"],
    amountInPLS: 19706n * 10n**18n,  // 0.99% of WPLS reserve
    slippagePct: 2,  // slightly wider for thin token, still safe
    approxOut: "~50,748,623,543,832 DFM",
    impact:   "0.99%",
    note:     "⚠️  Thin pool. Amount capped at 0.99% WPLS reserve ($0.20). GIBS LP ratio adjusted.",
  },
  {
    index:    4,
    symbol:   "PROOF_RES",
    address:  "0xaA1505C928fd85E10a550CfDe9e8F464c3574D8a",
    // Route: V2 WPLS → PROOF_RES (direct)
    // WPLS reserve: 6,156,773 PLS. Max safe = 60,952 PLS = $0.619
    path:     [ADDR.WPLS, "0xaA1505C928fd85E10a550CfDe9e8F464c3574D8a"],
    amountInPLS: 60952n * 10n**18n,
    slippagePct: 2,
    approxOut: "~2,945,763,053 PROOF_RES",
    impact:   "0.99%",
    note:     "⚠️  Capped at $0.62. GIBS LP ratio adjusted.",
  },
  {
    index:    5,
    symbol:   "ZHENG",
    address:  "0x24e62c39e34d7fe2b7df1162e1344eb6eb3b3e15",
    // Route: V2 WPLS → ZHENG (direct)
    // WPLS reserve: 3,014,487 PLS. Max safe = 29,843 PLS = $0.303
    // ZHENG has only ~3,097 total tokens in pool — extremely thin float.
    path:     [ADDR.WPLS, "0x24e62c39e34d7fe2b7df1162e1344eb6eb3b3e15"],
    amountInPLS: 29843n * 10n**18n,
    slippagePct: 2,
    approxOut: "~30.27 ZHENG",
    impact:   "0.99%",
    note:     "⚠️  Only ~3,097 ZHENG total in pool. Capped at $0.30.",
  },
  {
    index:    6,
    symbol:   "VOID",
    address:  "0x965B0d74591bF30327075A247C47dBf487dCff08",
    // Route: V2 WPLS → VOID (direct)
    // WPLS reserve: 1,564,538 PLS. Max safe = 15,489 PLS = $0.157
    // VOID has only ~1,717 total tokens in pool.
    path:     [ADDR.WPLS, "0x965B0d74591bF30327075A247C47dBf487dCff08"],
    amountInPLS: 15489n * 10n**18n,
    slippagePct: 2,
    approxOut: "~16.79 VOID",
    impact:   "0.99%",
    note:     "⚠️  Only ~1,717 VOID total in pool. Capped at $0.16.",
  },
  {
    index:    7,
    symbol:   "PARADE",
    address:  "0xE37ACc54711562510FaFC45d8199Ee329ebBceDd",
    // Route: V2 WPLS → PARADE (direct)
    // WPLS reserve: 159,603 PLS. Max safe = 1,580 PLS = $0.016
    path:     [ADDR.WPLS, "0xE37ACc54711562510FaFC45d8199Ee329ebBceDd"],
    amountInPLS: 1580n * 10n**18n,
    slippagePct: 3,
    approxOut: "~50,748,623,543,832 PARADE",
    impact:   "0.99%",
    note:     "⚠️  Very thin pool. Capped at $0.016. Tiny PLS cost.",
  },
  {
    index:    8,
    symbol:   "TLRz",
    address:  "0xC7145e1290B1d1221Aba5Ae48d4aCE17c6BE088F",
    // Route: V2 WPLS → TLRz (direct)
    // WPLS reserve: 49,194 PLS. Max safe = 487 PLS = $0.005
    path:     [ADDR.WPLS, "0xC7145e1290B1d1221Aba5Ae48d4aCE17c6BE088F"],
    amountInPLS: 487n * 10n**18n,
    slippagePct: 3,
    approxOut: "~50,748,623,543,832 TLRz",
    impact:   "0.99%",
    note:     "⚠️  Thinnest pool. Capped at $0.005. Costs pennies.",
  },
];

// ─── ABI ENCODERS ─────────────────────────────────────────────
// swapExactETHForTokens(uint256 amountOutMin, address[] path, address to, uint256 deadline)
// selector: 0x7ff36ab5
function encodeSwapExactETHForTokens(amountOutMin, path, to, deadline) {
  const sel = "7ff36ab5";
  // ABI encode: (uint256, address[], address, uint256)
  // amountOutMin: pad to 32 bytes
  const p1 = amountOutMin.toString(16).padStart(64, "0");
  // offset to path array: 4 params * 32 = 128 = 0x80
  const p2 = "0000000000000000000000000000000000000000000000000000000000000080";
  // to: pad address to 32 bytes
  const p3 = to.slice(2).toLowerCase().padStart(64, "0");
  // deadline: pad to 32 bytes
  const p4 = deadline.toString(16).padStart(64, "0");
  // path array: length + elements
  const pathLen = path.length.toString(16).padStart(64, "0");
  const pathElems = path.map(a => a.slice(2).toLowerCase().padStart(64, "0")).join("");
  return "0x" + sel + p1 + p2 + p3 + p4 + pathLen + pathElems;
}

// getAmountsOut(uint256 amountIn, address[] path) view
// selector: 0xd06ca61f
function encodeGetAmountsOut(amountIn, path) {
  const sel = "d06ca61f";
  const p1 = amountIn.toString(16).padStart(64, "0");
  const offset = "0000000000000000000000000000000000000000000000000000000000000040";
  const pathLen = path.length.toString(16).padStart(64, "0");
  const pathElems = path.map(a => a.slice(2).toLowerCase().padStart(64, "0")).join("");
  return "0x" + sel + p1 + offset + pathLen + pathElems;
}

// ─── RPC HELPER ───────────────────────────────────────────────
async function rpcCall(method, params) {
  const resp = await fetch(ADDR.RPC_READ, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
  const json = await resp.json();
  if (json.error) throw new Error(`RPC error: ${JSON.stringify(json.error)}`);
  return json.result;
}

// Decode uint256 array from getAmountsOut returndata
function decodeUint256Array(hex) {
  const data = hex.startsWith("0x") ? hex.slice(2) : hex;
  // first 32 bytes = offset to array, next 32 = length
  const length = parseInt(data.slice(64, 128), 16);
  const result = [];
  for (let i = 0; i < length; i++) {
    result.push(BigInt("0x" + data.slice(128 + i * 64, 128 + (i + 1) * 64)));
  }
  return result;
}

// ─── PRE-FLIGHT SIMULATION ────────────────────────────────────
async function simulate(plan) {
  console.log(`  🔍 Simulating ${plan.symbol}...`);
  const data = encodeGetAmountsOut(plan.amountInPLS, plan.path);
  const result = await rpcCall("eth_call", [
    { to: ADDR.V2_ROUTER, data },
    "latest",
  ]);
  const amounts = decodeUint256Array(result);
  const amountOut = amounts[amounts.length - 1];
  console.log(`  📊 Simulated out: ${amountOut} wei`);
  // amountOutMin = amountOut * (1 - slippage)
  const slipFactor = BigInt(Math.floor((1 - plan.slippagePct / 100) * 10000));
  const amountOutMin = (amountOut * slipFactor) / 10000n;
  return { amountOut, amountOutMin };
}

// ─── SINGLE TOKEN BUYER ───────────────────────────────────────
async function buyToken(indexOrSymbol) {
  let plan;
  if (typeof indexOrSymbol === "number") {
    plan = PURCHASE_PLAN[indexOrSymbol];
  } else {
    plan = PURCHASE_PLAN.find(p => p.symbol === indexOrSymbol);
  }
  if (!plan) {
    console.error(`❌ Unknown token: ${indexOrSymbol}`);
    return null;
  }

  console.log(`\n${"=".repeat(60)}`);
  console.log(`|>JOYSTICK<| BUYING: ${plan.symbol}`);
  console.log(`${"=".repeat(60)}`);
  console.log(`  Route:   ${plan.path.map((a,i) => i===0 ? "WPLS" : i===plan.path.length-1 ? plan.symbol : "pDAI").join(" → ")}`);
  console.log(`  Spend:   ${(Number(plan.amountInPLS) / 1e18).toLocaleString()} PLS`);
  console.log(`  Impact:  ${plan.impact}`);
  console.log(`  Expect:  ${plan.approxOut}`);
  console.log(`  Note:    ${plan.note}`);

  // 1. Check wallet
  if (typeof window.ethereum === "undefined") {
    throw new Error("No wallet. Install Rabby.");
  }

  const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
  const sender = accounts[0];
  console.log(`  Wallet: ${sender}`);

  // 2. Chain check
  const chainId = await window.ethereum.request({ method: "eth_chainId" });
  if (chainId.toLowerCase() !== ADDR.CHAIN_ID.toLowerCase()) {
    throw new Error(`Wrong chain: ${chainId}. Need 0x171 (PulseChain 369). Switch in Rabby.`);
  }
  console.log(`  ✅ PulseChain confirmed`);

  // 3. Balance check via RPC
  const balHex = await rpcCall("eth_getBalance", [sender, "latest"]);
  const balWei = BigInt(balHex);
  const balPLS = Number(balWei) / 1e18;
  console.log(`  PLS balance: ${balPLS.toLocaleString(undefined, {maximumFractionDigits: 2})} PLS`);

  // Gas floor check — never drop below 100K PLS
  const GAS_FLOOR = 100_000n * 10n**18n;
  const needed = plan.amountInPLS + 5000n * 10n**18n;  // spend + 5K PLS gas buffer
  if (balWei < needed + GAS_FLOOR) {
    const shortfall = Number(needed + GAS_FLOOR - balWei) / 1e18;
    throw new Error(`⛽ GAS FLOOR VIOLATION: Need ${shortfall.toLocaleString()} more PLS to stay above 100K gas floor.`);
  }

  // 4. Simulate to get amountOutMin
  let amountOutMin;
  try {
    const sim = await simulate(plan);
    amountOutMin = sim.amountOutMin;
    console.log(`  amountOutMin: ${amountOutMin}`);
  } catch (e) {
    throw new Error(`Simulation failed for ${plan.symbol}: ${e.message}`);
  }

  // 5. Build deadline
  const blockHex = await rpcCall("eth_getBlockByNumber", ["latest", false]);
  const blockTs = parseInt(blockHex.timestamp, 16);
  const deadline = BigInt(blockTs + 600);  // 10 minutes

  // 6. Encode calldata
  const calldata = encodeSwapExactETHForTokens(
    amountOutMin,
    plan.path,
    sender,   // tokens go to Joey's wallet
    deadline
  );

  console.log(`  Sending TX to V2 Router...`);
  console.log(`  Value: ${(Number(plan.amountInPLS)/1e18).toLocaleString()} PLS`);

  // 7. Send — Rabby pops for signature
  const txHash = await window.ethereum.request({
    method: "eth_sendTransaction",
    params: [{
      from: sender,
      to: ADDR.V2_ROUTER,
      value: "0x" + plan.amountInPLS.toString(16),
      data: calldata,
      // No gas — let Rabby estimate (it's good at this)
    }],
  });

  console.log(`  ✅ TX submitted: ${txHash}`);
  console.log(`  🔗 https://scan.pulsechain.com/tx/${txHash}`);

  // 8. Poll for receipt
  console.log(`  ⏳ Waiting for confirmation...`);
  let receipt = null;
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 3000));
    const raw = await rpcCall("eth_getTransactionReceipt", [txHash]);
    if (raw) { receipt = raw; break; }
  }

  if (!receipt) {
    console.warn(`  ⚠️  Receipt timeout. TX may still be pending: ${txHash}`);
    return txHash;
  }

  if (parseInt(receipt.status, 16) === 1) {
    console.log(`  ✅ CONFIRMED in block ${parseInt(receipt.blockNumber, 16).toLocaleString()}`);
    console.log(`  Gas used: ${parseInt(receipt.gasUsed, 16).toLocaleString()}`);
  } else {
    console.error(`  ❌ REVERTED. TX hash: ${txHash}`);
    console.error(`  Check: https://scan.pulsechain.com/tx/${txHash}`);
    throw new Error(`TX reverted for ${plan.symbol}`);
  }

  return txHash;
}

// ─── SEQUENTIAL BUYER ─────────────────────────────────────────
async function buyAll() {
  console.log(`\n${"═".repeat(60)}`);
  console.log("|>JOYSTICK<| — GIBS LP TOKEN ACQUISITION");
  console.log(`${"═".repeat(60)}`);
  console.log("Will purchase 9 tokens. You sign each TX.\n");

  const results = {};

  for (const plan of PURCHASE_PLAN) {
    try {
      const hash = await buyToken(plan.index);
      results[plan.symbol] = { ok: true, hash };
    } catch (e) {
      console.error(`\n❌ FAILED on ${plan.symbol}: ${e.message}`);
      console.log("Stopping. Fix error before continuing.");
      results[plan.symbol] = { ok: false, error: e.message };
      break;
    }
    // Small pause between TXs — let Rabby settle nonce
    if (plan.index < PURCHASE_PLAN.length - 1) {
      console.log(`\n⏳ Pausing 5s before next token...\n`);
      await new Promise(r => setTimeout(r, 5000));
    }
  }

  console.log(`\n${"═".repeat(60)}`);
  console.log("ACQUISITION SUMMARY");
  console.log(`${"═".repeat(60)}`);
  for (const [sym, r] of Object.entries(results)) {
    console.log(`  ${r.ok ? "✅" : "❌"} ${sym.padEnd(12)} ${r.ok ? r.hash : r.error}`);
  }
}

// ─── STATUS CHECK ─────────────────────────────────────────────
async function status() {
  console.log(`\n${"═".repeat(60)}`);
  console.log("|>JOYSTICK<| — PURCHASE PLAN SUMMARY");
  console.log(`${"═".repeat(60)}`);
  console.log(`${"Token".padEnd(12)} ${"USD Spend".padStart(10)} ${"PLS Spend".padStart(15)} ${"Impact".padStart(8)}  Route`);
  console.log("─".repeat(75));

  const PLS_USD = 0.00001015;
  let totalPLS = 0n;

  for (const p of PURCHASE_PLAN) {
    const pls = Number(p.amountInPLS) / 1e18;
    const usd = pls * PLS_USD;
    totalPLS += p.amountInPLS;
    const route = p.path.length === 3
      ? `V2 WPLS→pDAI→${p.symbol}`
      : `V2 WPLS→${p.symbol}`;
    console.log(
      `${p.symbol.padEnd(12)} ${("$"+usd.toFixed(4)).padStart(10)} ${pls.toLocaleString(undefined,{maximumFractionDigits:0}).padStart(15)} ${p.impact.padStart(8)}  ${route}`
    );
  }

  const totalUSD = (Number(totalPLS) / 1e18) * PLS_USD;
  console.log("─".repeat(75));
  console.log(`${"TOTAL".padEnd(12)} ${("$"+totalUSD.toFixed(2)).padStart(10)} ${(Number(totalPLS)/1e18).toLocaleString(undefined,{maximumFractionDigits:0}).padStart(15)}`);
  console.log(`\n📝 Run buyToken(0) through buyToken(8), or buyAll()`);
  console.log(`   Index map:`);
  PURCHASE_PLAN.forEach(p => console.log(`     buyToken(${p.index})  →  ${p.symbol}  ${p.note.slice(0,50)}`));
}

// ─── PRINT PLAN ON LOAD ───────────────────────────────────────
status();

// ─── EXPORTS ──────────────────────────────────────────────────
// Available in console after pasting:
//   buyToken(N)   — buy single token by index
//   buyToken("FED") — buy by symbol
//   buyAll()      — buy all 9 in sequence
//   status()      — show plan
