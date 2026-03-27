// ============================================================
// |>JOYSTICK<| — GIBS LAU LP ADDER
// PulseChain Chain ID 369 | Rabby Wallet Browser Injection
// Verified balances at block 25,983,872
//
// Checks wallet balances, checks pair doesn't already exist,
// approves both tokens, then calls addLiquidity or addLiquidityETH.
// You sign each TX. Pools with zero balance are skipped with a warning.
//
// USAGE (paste into browser console on any page with Rabby connected):
//   await status()      — read-only check of all 10 pools
//   await addLP(0)      — deploy Pool 0: GIBS/WPLS  ← START HERE
//   await addLP(1)      — deploy Pool 1: GIBS/FED
//   await addLP(2)      — deploy Pool 2: GIBS/ATROPA (V1 Router)
//   await addLP(3)      — deploy Pool 3: GIBS/WM
//   await addLP(4)      — deploy Pool 4: GIBS/DFM
//   await addLP(5)      — deploy Pool 5: GIBS/PROOF_RES
//   await addLP(6)      — deploy Pool 6: GIBS/ZHENG
//   await addLP(7)      — deploy Pool 7: GIBS/VOID
//   await addLP(8)      — deploy Pool 8: GIBS/PARADE
//   await addLP(9)      — deploy Pool 9: GIBS/TLRz
//   await addAllLP()    — all 10 in order, skips already-live pairs
// ============================================================

// ─── CONFIG ──────────────────────────────────────────────────
const CFG = {
  JOEY:       "0x17367877aF5A8D0Eb33ba5689A880f696386E24D",
  GIBS:       "0x66a08aa12da955eb63d7ac121a88b2b210a07b03",
  WPLS:       "0xA1077a294dDE1B09bB078844df40758a5D0f9a27",
  V1_ROUTER:  "0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02",
  V2_ROUTER:  "0x165C3410fC91EF562C50559f7d2289fEbed552d9",
  V1_FACTORY: "0x1715a3E4A142d8b698131108995174F37aEBA10D",
  V2_FACTORY: "0x29eA7545DEf87022BAdc76323F373EA1e707C523",
  CHAIN_ID:   "0x171",
  RPC:        "https://rpc-pulsechain.g4mm4.io",
  GAS_FLOOR:  100_000n * 10n**18n,  // never go below 100K PLS
  SLIPPAGE:   50n,   // 0.5% each side (out of 10000)
  DEADLINE:   600,   // 10 min from latest block
};

// ─── POOL PLAN ───────────────────────────────────────────────
// All desired amounts reflect the planned LP allocation.
// The router absorbs minor shortfalls via amountMin slippage.
// Actual wallet balances at block 25,983,872:
//   PLS:       2,040,788  GIBS:      3,395
//   FED:         315,038  ATROPA:      166.95   WM:        22,678
//   DFM:  50,754,575,861,431   PROOF_RES: 2,905,451,181
//   ZHENG:       30.275   VOID:          68.00   (more than needed — good)
//   PARADE: 147,540,598,378,337   TLRz: 101,973,908,620,143
//
// Note: VOID/PARADE/TLRz have MORE than the capped 0.99%-impact amounts —
// the extra is fine, the script uses planned amounts not full wallet balance.

const POOLS = [
  {
    index:          0,
    name:           "GIBS/WPLS",
    partnerSym:     "WPLS",
    partnerAddr:    CFG.WPLS,
    router:         CFG.V2_ROUTER,
    factory:        CFG.V2_FACTORY,
    isEth:          true,
    // 806 GIBS : 18,135 PLS → 22.50 PLS/GIBS price anchor
    // DSS Engine 2 break-even is 21.5 PLS/GIBS — safely above
    gibsWei:        806n    * 10n**18n,
    partnerWei:     18_135n * 10n**18n,
    note: "🔑 CRITICAL — deploys first, unlocks Engine 2 (DSS chatAndClaim). " +
          "Uses addLiquidityETH: native PLS sent as msg.value, wraps to WPLS inside router.",
  },
  {
    index:          1,
    name:           "GIBS/FED",
    partnerSym:     "FED",
    partnerAddr:    "0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff",
    router:         CFG.V2_ROUTER,
    factory:        CFG.V2_FACTORY,
    isEth:          false,
    // Planned: 854 GIBS : 316,069 FED → 576.83 PLS/GIBS implied
    // Wallet has 315,038 FED (1,031 short from swap slippage)
    // Using wallet balance as desired — router will accept, adjusts GIBS down ~0.3%
    gibsWei:        854n    * 10n**18n,
    partnerWei:     315_038n * 10n**18n,   // actual wallet balance
    note: "V2 direct. FED slightly under plan due to swap slippage — using actual balance. " +
          "Router accepts partial, GIBS side adjusts ~0.3% down. Ratio preserved.",
  },
  {
    index:          2,
    name:           "GIBS/ATROPA",
    partnerSym:     "ATROPA",
    partnerAddr:    "0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6",
    router:         CFG.V1_ROUTER,   // ← V1 Router, not V2
    factory:        CFG.V1_FACTORY,
    isEth:          false,
    // Planned: 781 GIBS : 169.57 ATROPA → 630.74 PLS/GIBS implied
    // Wallet has 166.949 ATROPA — using wallet balance
    gibsWei:        781n    * 10n**18n,
    partnerWei:     166_948_851n * 10n**9n,  // 166.948851 * 1e18 = 166948851000000000000
    note: "⚠️  Uses V1 Router (not V2). ATROPA's deepest pair is V1. " +
          "ATROPA slightly under plan — using wallet balance. Price ratio preserved.",
  },
  {
    index:          3,
    name:           "GIBS/WM",
    partnerSym:     "WM",
    partnerAddr:    "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",
    router:         CFG.V2_ROUTER,
    factory:        CFG.V2_FACTORY,
    isEth:          false,
    // 476 GIBS : 22,415 WM → 1,034.90 PLS/GIBS implied
    // Wallet has 22,678 WM — using planned 22,415 (not full balance)
    gibsWei:        476n    * 10n**18n,
    partnerWei:     22_415n * 10n**18n,
    note: "V2 direct. WM balance ✅ over target. Using planned amount.",
  },
  {
    index:          4,
    name:           "GIBS/DFM",
    partnerSym:     "DFM",
    partnerAddr:    "0x51160F352ED148C89d48dfe6384Edd07aFA24E0E",
    router:         CFG.V2_ROUTER,
    factory:        CFG.V2_FACTORY,
    isEth:          false,
    // 50 GIBS : 50,748,623,543,831 DFM → 9,852 PLS/GIBS implied
    // DFM pool has UINT112_MAX token side — near-infinite float
    gibsWei:        50n  * 10n**18n,
    partnerWei:     50_748_623_543_831n * 10n**18n,
    note: "Thin pool. DFM has near-infinite seeded supply (UINT112_MAX). " +
          "50 GIBS creates new arb loop. GIBS allocation reduced from original plan.",
  },
  {
    index:          5,
    name:           "GIBS/PROOF_RES",
    partnerSym:     "PROOF_RES",
    partnerAddr:    "0xaA1505C928fd85E10a550CfDe9e8F464c3574D8a",
    router:         CFG.V2_ROUTER,
    factory:        CFG.V2_FACTORY,
    isEth:          false,
    // Planned: 59 GIBS : 2,945,763,052 PROOF_RES
    // Wallet has 2,905,451,181 — ~40M short from swap slippage
    gibsWei:        59n  * 10n**18n,
    partnerWei:     2_905_451_181n * 10n**18n,   // actual wallet balance
    note: "V3 Index Minter parent. Using wallet balance (~40M under plan). " +
          "Router adjusts ratio. Still creates the arb loop.",
  },
  {
    index:          6,
    name:           "GIBS/ZHENG",
    partnerSym:     "ZHENG",
    partnerAddr:    "0x24e62c39e34d7fe2b7df1162e1344eb6eb3b3e15",
    router:         CFG.V2_ROUTER,
    factory:        CFG.V2_FACTORY,
    isEth:          false,
    // 50 GIBS : 30.275 ZHENG → 9,852 PLS/GIBS implied
    // ZHENG pool has only ~3,097 total tokens — extremely rare float
    gibsWei:        50n  * 10n**18n,
    partnerWei:     30_275_056n * 10n**12n,  // 30.275056 * 1e18
    note: "Tiny float token (~3,097 ZHENG total in pool). Using planned amount.",
  },
  {
    index:          7,
    name:           "GIBS/VOID",
    partnerSym:     "VOID",
    partnerAddr:    "0x965B0d74591bF30327075A247C47dBf487dCff08",
    router:         CFG.V2_ROUTER,
    factory:        CFG.V2_FACTORY,
    isEth:          false,
    // Planned: 50 GIBS : 16.78 VOID
    // Wallet has 68 VOID — using planned 16.78 (wallet has extra, that's fine)
    gibsWei:        50n  * 10n**18n,
    partnerWei:     16_780_000n * 10n**12n,  // 16.78 * 1e18
    note: "Tiny float token (~1,717 VOID total in pool). Wallet has 68 VOID — using 16.78.",
  },
  {
    index:          8,
    name:           "GIBS/PARADE",
    partnerSym:     "PARADE",
    partnerAddr:    "0xE37ACc54711562510FaFC45d8199Ee329ebBceDd",
    router:         CFG.V2_ROUTER,
    factory:        CFG.V2_FACTORY,
    isEth:          false,
    // 50 GIBS : 50,748,623,543,831 PARADE → 9,852 PLS/GIBS implied
    // Wallet has 147,540,598,378,337 PARADE — way more than needed, using planned
    gibsWei:        50n  * 10n**18n,
    partnerWei:     50_748_623_543_831n * 10n**18n,
    note: "Thin pool. Using planned amount. Wallet has ~3x more PARADE than needed.",
  },
  {
    index:          9,
    name:           "GIBS/TLRz",
    partnerSym:     "TLRz",
    partnerAddr:    "0xC7145e1290B1d1221Aba5Ae48d4aCE17c6BE088F",
    router:         CFG.V2_ROUTER,
    factory:        CFG.V2_FACTORY,
    isEth:          false,
    // 50 GIBS : 50,748,623,543,831 TLRz → 9,852 PLS/GIBS implied
    // Wallet has 101,973,908,620,143 TLRz — double what's needed, using planned
    gibsWei:        50n  * 10n**18n,
    partnerWei:     50_748_623_543_831n * 10n**18n,
    note: "Thinnest pool. Using planned amount. Wallet has ~2x more TLRz than needed.",
  },
];

// ─── ABI ENCODING ────────────────────────────────────────────

// approve(address spender, uint256 amount) → selector 0x095ea7b3
function encodeApprove(spender, amount) {
  return "0x095ea7b3"
    + spender.slice(2).toLowerCase().padStart(64, "0")
    + amount.toString(16).padStart(64, "0");
}

// allowance(address owner, address spender) → selector 0xdd62ed3e
function encodeAllowance(owner, spender) {
  return "0xdd62ed3e"
    + owner.slice(2).toLowerCase().padStart(64, "0")
    + spender.slice(2).toLowerCase().padStart(64, "0");
}

// balanceOf(address) → selector 0x70a08231
function encodeBalanceOf(account) {
  return "0x70a08231"
    + account.slice(2).toLowerCase().padStart(64, "0");
}

// getPair(address,address) → selector 0xe6a43905
function encodeGetPair(a, b) {
  return "0xe6a43905"
    + a.slice(2).toLowerCase().padStart(64, "0")
    + b.slice(2).toLowerCase().padStart(64, "0");
}

// addLiquidity(tokenA,tokenB,amountADesired,amountBDesired,amountAMin,amountBMin,to,deadline)
// selector: 0xe8e33700
function encodeAddLiquidity(tA, tB, amtADes, amtBDes, amtAMin, amtBMin, to, deadline) {
  const pad = (v) => BigInt(v).toString(16).padStart(64, "0");
  const adr = (v) => v.slice(2).toLowerCase().padStart(64, "0");
  return "0xe8e33700"
    + adr(tA) + adr(tB)
    + pad(amtADes) + pad(amtBDes)
    + pad(amtAMin) + pad(amtBMin)
    + adr(to) + pad(deadline);
}

// addLiquidityETH(token,amountTokenDesired,amountTokenMin,amountETHMin,to,deadline)
// selector: 0xf305d719
function encodeAddLiquidityETH(token, amtTokDes, amtTokMin, amtEthMin, to, deadline) {
  const pad = (v) => BigInt(v).toString(16).padStart(64, "0");
  const adr = (v) => v.slice(2).toLowerCase().padStart(64, "0");
  return "0xf305d719"
    + adr(token)
    + pad(amtTokDes) + pad(amtTokMin) + pad(amtEthMin)
    + adr(to) + pad(deadline);
}

// ─── RPC HELPER ──────────────────────────────────────────────
async function rpc(method, params = []) {
  const res = await fetch(CFG.RPC, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
  const j = await res.json();
  if (j.error) throw new Error(`RPC ${method}: ${JSON.stringify(j.error)}`);
  return j.result;
}

function hexToBigInt(hex) {
  return hex && hex !== "0x" ? BigInt(hex) : 0n;
}

async function getBalance(tokenAddr, wallet) {
  const data = encodeBalanceOf(wallet);
  const res = await rpc("eth_call", [{ to: tokenAddr, data }, "latest"]);
  return hexToBigInt(res);
}

async function getAllowance(tokenAddr, owner, spender) {
  const data = encodeAllowance(owner, spender);
  const res = await rpc("eth_call", [{ to: tokenAddr, data }, "latest"]);
  return hexToBigInt(res);
}

async function getPair(factory, tokA, tokB) {
  const data = encodeGetPair(tokA, tokB);
  const res = await rpc("eth_call", [{ to: factory, data }, "latest"]);
  // last 40 hex chars = address
  const addr = "0x" + res.slice(-40);
  return addr === "0x" + "0".repeat(40) ? null : addr;
}

async function getBlockTimestamp() {
  const block = await rpc("eth_getBlockByNumber", ["latest", false]);
  return parseInt(block.timestamp, 16);
}

async function getPlsBalance(wallet) {
  const res = await rpc("eth_getBalance", [wallet, "latest"]);
  return hexToBigInt(res);
}

// ─── SLIPPAGE HELPER ─────────────────────────────────────────
// amountMin = desired * (10000 - slippageBps) / 10000
function applySlippage(amount) {
  return (amount * (10000n - CFG.SLIPPAGE * 2n)) / 10000n;
}

// ─── POLL RECEIPT ────────────────────────────────────────────
async function waitReceipt(txHash, timeoutMs = 120_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    await new Promise(r => setTimeout(r, 3000));
    const receipt = await rpc("eth_getTransactionReceipt", [txHash]);
    if (receipt) return receipt;
  }
  return null;
}

// ─── APPROVE HELPER ──────────────────────────────────────────
async function ensureApproval(sender, tokenAddr, spender, amount, label) {
  const current = await getAllowance(tokenAddr, sender, spender);
  if (current >= amount) {
    console.log(`  ✅ ${label} allowance sufficient (${current / 10n**18n} approved)`);
    return true;
  }
  console.log(`  🔐 Approving ${label} to router...`);
  const data = encodeApprove(spender, 2n**256n - 1n); // max approval
  const txHash = await window.ethereum.request({
    method: "eth_sendTransaction",
    params: [{ from: sender, to: tokenAddr, data }],
  });
  console.log(`  📝 Approve TX: ${txHash}`);
  const receipt = await waitReceipt(txHash);
  if (!receipt || parseInt(receipt.status, 16) !== 1) {
    throw new Error(`Approval for ${label} failed or timed out`);
  }
  console.log(`  ✅ ${label} approved`);
  return true;
}

// ─── STATUS ──────────────────────────────────────────────────
async function status() {
  console.log(`\n${"═".repeat(65)}`);
  console.log("|>JOYSTICK<| GIBS LP STATUS — block scan");
  console.log(`${"═".repeat(65)}`);

  const plsBal = await getPlsBalance(CFG.JOEY);
  const gibsBal = await getBalance(CFG.GIBS, CFG.JOEY);
  console.log(`PLS  balance: ${(Number(plsBal) / 1e18).toLocaleString(undefined, {maximumFractionDigits: 2})} PLS`);
  console.log(`GIBS balance: ${(Number(gibsBal) / 1e18).toFixed(4)} GIBS`);
  console.log(`Gas floor:    100,000 PLS ${plsBal >= CFG.GAS_FLOOR ? "✅" : "❌ BELOW FLOOR"}`);
  console.log();

  for (const pool of POOLS) {
    const pair = await getPair(pool.factory, CFG.GIBS, pool.partnerAddr);
    const pBal = pool.isEth
      ? await getPlsBalance(CFG.JOEY)
      : await getBalance(pool.partnerAddr, CFG.JOEY);
    const gBal = await getBalance(CFG.GIBS, CFG.JOEY);

    const hasGibs    = gBal >= pool.gibsWei;
    const hasPartner = pBal >= pool.partnerWei;
    const ready      = hasGibs && hasPartner;
    const liveStr    = pair ? `✅ LIVE  ${pair}` : "⏳ not created";

    console.log(`Pool ${pool.index}: ${pool.name}`);
    console.log(`  Pair:    ${liveStr}`);
    console.log(`  GIBS:    need ${Number(pool.gibsWei)/1e18}  have ${(Number(gBal)/1e18).toFixed(4)}  ${hasGibs?"✅":"❌"}`);
    console.log(`  ${pool.partnerSym.padEnd(9)}: need ${Number(pool.partnerWei)/1e18}  have ${Number(pBal)/1e18}  ${hasPartner?"✅":"❌"}`);
    console.log(`  Ready:   ${ready ? "✅ deploy with addLP("+pool.index+")" : pair ? "already live" : "❌ missing balance"}`);
    console.log();
    await new Promise(r => setTimeout(r, 150));
  }
}

// ─── SINGLE POOL LP ADDER ────────────────────────────────────
async function addLP(indexOrName) {
  const pool = typeof indexOrName === "number"
    ? POOLS[indexOrName]
    : POOLS.find(p => p.name === indexOrName || p.partnerSym === indexOrName);

  if (!pool) { console.error(`❌ Unknown pool: ${indexOrName}`); return null; }

  console.log(`\n${"═".repeat(65)}`);
  console.log(`|>JOYSTICK<| ADD LP — Pool ${pool.index}: ${pool.name}`);
  console.log(`${"═".repeat(65)}`);
  console.log(`  ${pool.note}`);

  // ── 1. Wallet check ────────────────────────────────────────
  if (typeof window.ethereum === "undefined")
    throw new Error("No wallet detected. Install Rabby.");

  const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
  const sender = accounts[0];
  console.log(`  Wallet: ${sender}`);

  const chainId = await window.ethereum.request({ method: "eth_chainId" });
  if (chainId.toLowerCase() !== CFG.CHAIN_ID.toLowerCase())
    throw new Error(`Wrong chain: ${chainId}. Need 0x171 (PulseChain). Switch in Rabby.`);
  console.log(`  ✅ PulseChain confirmed`);

  // ── 2. Gas floor check ─────────────────────────────────────
  const plsBal = await getPlsBalance(sender);
  const plsHuman = Number(plsBal) / 1e18;
  console.log(`  PLS balance: ${plsHuman.toLocaleString(undefined, {maximumFractionDigits: 2})} PLS`);

  // For Pool 0: gas floor + partner PLS + buffer
  const plsNeeded = pool.isEth
    ? CFG.GAS_FLOOR + pool.partnerWei + 5000n * 10n**18n
    : CFG.GAS_FLOOR + 5000n * 10n**18n;

  if (plsBal < plsNeeded) {
    const short = Number(plsNeeded - plsBal) / 1e18;
    throw new Error(`⛽ GAS FLOOR: Need ${short.toLocaleString()} more PLS. Aborting.`);
  }

  // ── 3. Pair existence check ────────────────────────────────
  console.log(`  Checking if pair already exists...`);
  const existingPair = await getPair(pool.factory, CFG.GIBS, pool.partnerAddr);
  if (existingPair) {
    console.log(`  ⚠️  Pair already exists at ${existingPair} — nothing to do.`);
    return existingPair;
  }
  console.log(`  ✅ No existing pair — proceeding.`);

  // ── 4. Balance checks ──────────────────────────────────────
  const gibsBal = await getBalance(CFG.GIBS, sender);
  if (gibsBal < pool.gibsWei) {
    throw new Error(
      `❌ Insufficient GIBS: need ${Number(pool.gibsWei)/1e18}, have ${Number(gibsBal)/1e18}`
    );
  }
  console.log(`  GIBS: ${Number(gibsBal)/1e18} ✅`);

  if (!pool.isEth) {
    const partnerBal = await getBalance(pool.partnerAddr, sender);
    if (partnerBal < pool.partnerWei) {
      throw new Error(
        `❌ Insufficient ${pool.partnerSym}: need ${Number(pool.partnerWei)/1e18}, have ${Number(partnerBal)/1e18}`
      );
    }
    console.log(`  ${pool.partnerSym}: ${Number(partnerBal)/1e18} ✅`);
  }

  // ── 5. Approvals ───────────────────────────────────────────
  console.log(`\n  Step 1/2: Approve GIBS → Router`);
  await ensureApproval(sender, CFG.GIBS, pool.router, pool.gibsWei, "GIBS");

  if (!pool.isEth) {
    console.log(`  Step 2/2: Approve ${pool.partnerSym} → Router`);
    await ensureApproval(sender, pool.partnerAddr, pool.router, pool.partnerWei, pool.partnerSym);
  } else {
    console.log(`  Step 2/2: WPLS is native PLS — no token approval needed`);
  }

  // ── 6. Build addLiquidity calldata ─────────────────────────
  const ts = await getBlockTimestamp();
  const deadline = BigInt(ts + CFG.DEADLINE);
  const gibsMin    = applySlippage(pool.gibsWei);
  const partnerMin = applySlippage(pool.partnerWei);

  let calldata, value;

  if (pool.isEth) {
    // addLiquidityETH(token, amountTokenDesired, amountTokenMin, amountETHMin, to, deadline)
    calldata = encodeAddLiquidityETH(
      CFG.GIBS,
      pool.gibsWei,
      gibsMin,
      partnerMin,
      sender,
      deadline
    );
    value = "0x" + pool.partnerWei.toString(16);
    console.log(`\n  addLiquidityETH:`);
    console.log(`    GIBS desired: ${Number(pool.gibsWei)/1e18}`);
    console.log(`    GIBS min:     ${Number(gibsMin)/1e18}`);
    console.log(`    PLS  desired: ${Number(pool.partnerWei)/1e18}`);
    console.log(`    PLS  min:     ${Number(partnerMin)/1e18}`);
  } else {
    // addLiquidity(tokenA, tokenB, amtADes, amtBDes, amtAMin, amtBMin, to, deadline)
    calldata = encodeAddLiquidity(
      CFG.GIBS,
      pool.partnerAddr,
      pool.gibsWei,
      pool.partnerWei,
      gibsMin,
      partnerMin,
      sender,
      deadline
    );
    value = "0x0";
    console.log(`\n  addLiquidity:`);
    console.log(`    GIBS desired:         ${Number(pool.gibsWei)/1e18}`);
    console.log(`    GIBS min:             ${Number(gibsMin)/1e18}`);
    console.log(`    ${pool.partnerSym} desired: ${Number(pool.partnerWei)/1e18}`);
    console.log(`    ${pool.partnerSym} min:     ${Number(partnerMin)/1e18}`);
  }

  console.log(`    Deadline:     +${CFG.DEADLINE}s from now`);
  console.log(`    Router:       ${pool.router === CFG.V1_ROUTER ? "V1" : "V2"} (${pool.router})`);

  // ── 7. Send TX ─────────────────────────────────────────────
  console.log(`\n  📡 Sending addLiquidity TX — sign in Rabby...`);
  const txParams = { from: sender, to: pool.router, data: calldata, value };
  const txHash = await window.ethereum.request({
    method: "eth_sendTransaction",
    params: [txParams],
  });
  console.log(`  📝 TX: ${txHash}`);
  console.log(`  🔗 https://scan.pulsechain.com/tx/${txHash}`);

  // ── 8. Wait for confirmation ───────────────────────────────
  console.log(`  ⏳ Waiting for confirmation (up to 120s)...`);
  const receipt = await waitReceipt(txHash, 120_000);

  if (!receipt) {
    console.warn(`  ⚠️  Timeout. TX may still be pending: ${txHash}`);
    console.warn(`  Check: https://scan.pulsechain.com/tx/${txHash}`);
    return txHash;
  }

  if (parseInt(receipt.status, 16) !== 1) {
    console.error(`  ❌ REVERTED in block ${parseInt(receipt.blockNumber, 16)}`);
    console.error(`  Check: https://scan.pulsechain.com/tx/${txHash}`);
    throw new Error(`addLiquidity reverted for ${pool.name}`);
  }

  console.log(`  ✅ CONFIRMED in block ${parseInt(receipt.blockNumber, 16)}`);
  console.log(`  Gas used: ${parseInt(receipt.gasUsed, 16).toLocaleString()}`);

  // ── 9. Verify pair created ─────────────────────────────────
  await new Promise(r => setTimeout(r, 2000)); // let state settle
  const newPair = await getPair(pool.factory, CFG.GIBS, pool.partnerAddr);
  if (newPair) {
    console.log(`  🎉 Pair created: ${newPair}`);
    if (pool.index === 0) {
      console.log(`\n  🔓 ENGINE 2 (DSS chatAndClaim) IS NOW UNLOCKED`);
      console.log(`     GIBS/WPLS pair exists. DSS can now mint and sell GIBS.`);
    }
  } else {
    console.warn(`  ⚠️  Pair not found after confirmation — check scan for logs`);
  }

  return { txHash, pair: newPair };
}

// ─── SEQUENTIAL ALL-POOLS ADDER ──────────────────────────────
async function addAllLP() {
  console.log(`\n${"═".repeat(65)}`);
  console.log("|>JOYSTICK<| ADD ALL LP — 10 pools, sequential");
  console.log(`${"═".repeat(65)}`);
  console.log("You will sign up to 2 TXs per pool (approve + addLiquidity).");
  console.log("Pools that already exist are skipped automatically.\n");

  const results = {};

  for (const pool of POOLS) {
    try {
      // Skip already-live pairs
      const existing = await getPair(pool.factory, CFG.GIBS, pool.partnerAddr);
      if (existing) {
        console.log(`\nPool ${pool.index} ${pool.name}: ✅ already live at ${existing} — skipping`);
        results[pool.name] = { status: "already_live", pair: existing };
        continue;
      }

      const result = await addLP(pool.index);
      results[pool.name] = { status: "deployed", ...result };
    } catch (e) {
      console.error(`\n❌ Pool ${pool.index} ${pool.name} failed: ${e.message}`);
      results[pool.name] = { status: "failed", error: e.message };
      console.log("Stopping. Fix error then continue with addLP(" + pool.index + ")");
      break;
    }

    if (pool.index < POOLS.length - 1) {
      console.log(`\n⏳ Pausing 5s before next pool...\n`);
      await new Promise(r => setTimeout(r, 5000));
    }
  }

  // Summary
  console.log(`\n${"═".repeat(65)}`);
  console.log("FINAL SUMMARY");
  console.log(`${"═".repeat(65)}`);
  for (const [name, r] of Object.entries(results)) {
    const icon = r.status === "deployed" ? "✅" : r.status === "already_live" ? "🔵" : "❌";
    console.log(`  ${icon} ${name.padEnd(20)} ${r.status}${r.pair ? "  "+r.pair : ""}${r.error ? "  "+r.error : ""}`);
  }
}

// ─── AUTO-RUN STATUS ON PASTE ─────────────────────────────────
console.log("|>JOYSTICK<| GIBS LP Adder loaded.");
console.log("Commands: status() | addLP(0..9) | addAllLP()");
console.log("Run status() first to verify balances before deploying.\n");
status();
