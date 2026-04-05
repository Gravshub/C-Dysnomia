// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

// ============================================================
//  FloorHarvestModule  —  JoystickHub delegatecall module
//  Atomic: prime GIBS → LP (direct pair.mint) → sell (direct pair.swap)
//  No router. One TX. Optional LP burn.
// ============================================================
//
//  Config keys (set via hub.batchSetConfig):
//    floor.gibsLau        → address  GIBS LAU contract
//    floor.affection      → address  AFFECTION token
//    floor.gibsWplsPair   → address  GIBS/WPLS UniV2 pair
//    floor.gibsIsToken0   → uint256  1 = GIBS is token0, 0 = token1
//                          (GIBS 0x66a0... < WPLS 0xa107... → gibsIsToken0 = 1)
//    floor.burnAddr       → address  Where to send LP if burnLp=true
//                          (default: 0x0000000000000000000000000000000000000369)
//
//  GIBS/WPLS pair: 0x7bca1c997c475eac9c0b5fbd70f8f92ea8476593
//  gibsIsToken0 = 1  (GIBS 0x66... < WPLS 0xa1... by UniV2 address sort)
// ============================================================

// --- Interfaces -----------------------------------------------

interface IERC20 {
    function balanceOf(address) external view returns (uint256);
    function transfer(address, uint256) external returns (bool);
    function approve(address, uint256) external returns (bool);
    function allowance(address, address) external view returns (uint256);
}

interface IDysnomiaToken is IERC20 {
    // mintToCap() mints 1 token to address(this) per call until totalSupply == maxSupply
    // NOTE: Generate() reverts on LAU tokens due to crypto state prerequisites.
    //       Hub:Harvest V1 had the same bug — V2 switched to mintToCap(). See CLAUDE.md.
    function mintToCap() external;
    // Purchase(paymentToken, amount) → pulls amount*rate of paymentToken from msg.sender,
    //   transfers amount of this token to msg.sender
    function Purchase(address paymentToken, uint256 amount) external;
}

interface IUniV2Pair {
    function token0() external view returns (address);
    function token1() external view returns (address);
    function getReserves() external view returns (uint112 r0, uint112 r1, uint32 ts);
    // Direct swap: caller sends tokens to pair first, then calls swap()
    // amounts are what you want OUT. Exactly one of amount0Out/amount1Out must be 0.
    function swap(uint256 amount0Out, uint256 amount1Out, address to, bytes calldata data) external;
    // Direct LP mint: caller sends both tokens to pair first, then calls mint()
    // pair credits LP proportional to current reserves
    // NOTE: PulseX V2 pairs use mint(address,address) — 2nd arg is feeTo.
    //       Standard UniV2 mint(address) does NOT exist on PulseX V2.
    function mint(address to, address feeTo) external returns (uint256 liquidity);
    function totalSupply() external view returns (uint256);
}

// --- HubStorage (MUST match JoystickHub layout exactly) -------
// Never reorder. Append-only.

abstract contract HubStorage {
    address internal _owner;                            // slot 0
    uint256 internal _reentrancy;                       // slot 1  (1=unlocked, 2=locked)
    bool    internal _paused;                           // slot 2
    mapping(bytes4  => address) internal _modules;     // slot 3
    mapping(address => bool)    internal _authorized;  // slot 4
    address internal _wpls;                             // slot 5+
    address internal _routerV1;
    address internal _routerV2;
    address internal _factoryV1;
    address internal _factoryV2;
    mapping(bytes32 => uint256) internal _config;      // slot 6
    uint256 internal _opNonce;                          // slot 7
}

// --- FloorHarvestModule ---------------------------------------

contract FloorHarvestModule is HubStorage {

    // ── Events ──────────────────────────────────────────────
    event FloorCycleComplete(
        uint256 indexed opNonce,
        uint256 primeCount,
        uint256 lpGibs,
        uint256 wplsCommitted,   // WPLS sent to pair for LP
        uint256 lpMinted,        // LP tokens received
        bool    lpBurned,
        uint256 sellGibs,
        uint256 wplsReceived     // WPLS from sell side
    );

    // ── Config key helpers ───────────────────────────────────
    bytes32 private constant K_GIBS_LAU      = keccak256("floor.gibsLau");
    bytes32 private constant K_AFFECTION     = keccak256("floor.affection");
    bytes32 private constant K_GIBS_WPLS     = keccak256("floor.gibsWplsPair");
    bytes32 private constant K_GIBS_IS_T0    = keccak256("floor.gibsIsToken0");
    bytes32 private constant K_BURN_ADDR     = keccak256("floor.burnAddr");

    // Default burn address when config key is 0
    address private constant DEFAULT_BURN = address(0x0000000000000000000000000000000000000369);

    // ── Guards ───────────────────────────────────────────────
    modifier onlyAuth() {
        require(_authorized[msg.sender] || msg.sender == _owner, "hub:auth");
        _;
    }
    modifier whenNotPaused() {
        require(!_paused, "hub:paused");
        _;
    }
    modifier nonReentrant() {
        require(_reentrancy == 1, "hub:reentrant");
        _reentrancy = 2;
        _;
        _reentrancy = 1;
    }

    // ── AMM math (UniV2, 0.3% fee) ───────────────────────────
    function _getAmountOut(uint256 amtIn, uint256 resIn, uint256 resOut)
        internal pure returns (uint256)
    {
        require(amtIn > 0 && resIn > 0 && resOut > 0, "floor:zero reserve");
        uint256 amtInFee = amtIn * 997;
        return (amtInFee * resOut) / (resIn * 1000 + amtInFee);
    }

    // ── Config readers ───────────────────────────────────────
    function _addr(bytes32 key) internal view returns (address) {
        return address(uint160(_config[key]));
    }
    function _gibsWplsPair() internal view returns (IUniV2Pair) {
        return IUniV2Pair(_addr(K_GIBS_WPLS));
    }
    function _gibsIsToken0() internal view returns (bool) {
        return _config[K_GIBS_IS_T0] == 1;
    }
    function _burnAddr() internal view returns (address) {
        address a = _addr(K_BURN_ADDR);
        return a == address(0) ? DEFAULT_BURN : a;
    }

    // ── Approve helper (reset-first pattern) ─────────────────
    function _approveMax(address token, address spender) internal {
        if (IERC20(token).allowance(address(this), spender) != type(uint256).max) {
            IERC20(token).approve(spender, 0);
            IERC20(token).approve(spender, type(uint256).max);
        }
    }

    // ============================================================
    //  floorAndHarvest
    //
    //  Flow:
    //    1. Generate() × primeCount  → GIBS minted into GIBS_LAU self-balance (free)
    //    2. Purchase(AFF, primeCount) → Hub receives primeCount GIBS (costs AFF)
    //    3. Split GIBS: lpGibs = primeCount * lpBps / 10000
    //                   sellGibs = primeCount - lpGibs
    //    4. LP side (direct pair.mint — no router):
    //         a. Read current pair reserves
    //         b. Calculate WPLS needed: wplsNeeded = lpGibs * rWpls / rGibs
    //         c. Require wplsNeeded <= wplsMax (slippage guard)
    //         d. Require Hub.WPLS >= wplsNeeded
    //         e. IERC20(GIBS).transfer(pair, lpGibs)
    //         f. IERC20(WPLS).transfer(pair, wplsNeeded)
    //         g. pair.mint(address(this)) → LP tokens arrive at Hub
    //         h. If burnLp: LP.transfer(burnAddr, lpMinted)
    //    5. Sell side (direct pair.swap — no router):
    //         a. Read post-mint reserves (fresh getReserves)
    //         b. Compute wplsOut = getAmountOut(sellGibs, rGibs_after, rWpls_after)
    //         c. Require wplsOut >= minWplsOut
    //         d. IERC20(GIBS).transfer(pair, sellGibs)
    //         e. pair.swap(amount0Out, amount1Out, Hub, "")
    //    6. Emit FloorCycleComplete
    //
    //  Result: Hub holds accumulated WPLS from sell. LP is either in Hub or burned.
    //          The sell step pushes GIBS price UP in the pair. Arb bots see the
    //          imbalance → buy GIBS from pair → push more WPLS in → consistent
    //          step-up price floor pattern (see image).
    // ============================================================
    function floorAndHarvest(
        uint256 primeCount,   // GIBS to generate (e.g. 17)
        uint256 lpBps,        // Fraction of GIBS to LP in basis points (e.g. 5000 = 50%)
        uint256 wplsMax,      // Max WPLS to commit to LP (slippage ceiling)
        bool    burnLp,       // true = burn LP to burnAddr after minting
        uint256 minWplsOut    // Min WPLS from sell side (slippage floor)
    )
        external
        onlyAuth
        whenNotPaused
        nonReentrant
        returns (uint256 wplsReceived)
    {
        // ── Validate params ──────────────────────────────────
        require(primeCount > 0,          "floor:prime=0");
        require(lpBps <= 9000,           "floor:lpBps>90%");  // never LP more than 90%
        require(lpBps > 0,               "floor:lpBps=0");

        address gibsLau   = _addr(K_GIBS_LAU);
        address affection = _addr(K_AFFECTION);
        require(gibsLau   != address(0), "floor:cfg gibsLau");
        require(affection != address(0), "floor:cfg affection");
        IUniV2Pair pair   = _gibsWplsPair();
        require(address(pair) != address(0), "floor:cfg pair");

        // ── Step 1: Prime — mintToCap() × primeCount ────────
        // Mints GIBS from zero into GIBS_LAU self-balance.
        // Cost: gas only. No tokens leave Hub.
        // NOTE: Generate() reverts on LAU due to crypto state prereqs.
        //       mintToCap() is the correct call (same as Hub:Harvest V2).
        IDysnomiaToken gibs = IDysnomiaToken(gibsLau);
        for (uint256 i = 0; i < primeCount; i++) {
            gibs.mintToCap();
        }

        // ── Step 2: Purchase — AFF → GIBS ───────────────────
        // Hub pays primeCount AFF (in wei), receives primeCount GIBS (in wei).
        // Purchase() operates in wei (1 token = 1e18), so scale primeCount.
        uint256 amount = primeCount * 1e18;
        require(IERC20(affection).balanceOf(address(this)) >= amount, "floor:aff low");
        _approveMax(affection, gibsLau);
        gibs.Purchase(affection, amount);

        // Verify Hub received GIBS
        uint256 gibsBal = gibs.balanceOf(address(this));
        require(gibsBal >= amount, "floor:gibs recv");

        // ── Compute split ────────────────────────────────────
        uint256 lpGibs   = (amount * lpBps) / 10000;
        uint256 sellGibs = amount - lpGibs;
        require(sellGibs > 0, "floor:sellGibs=0");
        require(lpGibs   > 0, "floor:lpGibs=0");

        bool git0 = _gibsIsToken0();   // GIBS = token0 → true  (0x66... < 0xa1...)

        // ── Step 4: LP mint (direct pair.mint, no router) ────
        uint256 lpMinted;
        uint256 wplsCommitted;
        {
            // Read current reserves
            (uint112 r0, uint112 r1,) = pair.getReserves();
            uint256 rGibs = git0 ? uint256(r0) : uint256(r1);
            uint256 rWpls = git0 ? uint256(r1) : uint256(r0);
            require(rGibs > 0 && rWpls > 0, "floor:pair empty");

            // Optimal WPLS for lpGibs at current price
            // UniV2 accepts min(x/r0, y/r1) ratio — must match reserves proportionally
            wplsCommitted = (lpGibs * rWpls) / rGibs;
            require(wplsCommitted <= wplsMax,                           "floor:wpls slippage");
            require(IERC20(_wpls).balanceOf(address(this)) >= wplsCommitted, "floor:wpls low");

            // Send both tokens directly to pair
            // UniV2 mint reads its own balances, computes deltas, mints LP
            require(gibs.transfer(address(pair), lpGibs),              "floor:gibs xfer LP");
            require(IERC20(_wpls).transfer(address(pair), wplsCommitted), "floor:wpls xfer");

            // pair.mint → LP tokens arrive at Hub (address(this) = Hub via delegatecall)
            // PulseX V2 uses mint(to, feeTo) — pass address(0) for feeTo
            lpMinted = pair.mint(address(this), address(0));
            require(lpMinted > 0, "floor:no LP");

            // Optional LP burn
            if (burnLp) {
                require(
                    IERC20(address(pair)).transfer(_burnAddr(), lpMinted),
                    "floor:burn xfer"
                );
            }
        }

        // ── Step 5: Sell (direct pair.swap, no router) ───────
        {
            // Re-read reserves AFTER mint (pair state has changed)
            (uint112 r0, uint112 r1,) = pair.getReserves();
            uint256 rGibs = git0 ? uint256(r0) : uint256(r1);
            uint256 rWpls = git0 ? uint256(r1) : uint256(r0);

            // Compute WPLS out for sellGibs at post-mint reserves
            wplsReceived = _getAmountOut(sellGibs, rGibs, rWpls);
            require(wplsReceived >= minWplsOut, "floor:wpls out low");

            // Send sellGibs directly to pair
            // UniV2 swap reads incoming token balance delta to determine amountIn
            require(gibs.transfer(address(pair), sellGibs), "floor:gibs xfer sell");

            // Call swap: tell pair how many of each token to send OUT
            // One of the two amounts must be 0. We're selling GIBS, getting WPLS.
            uint256 a0Out = git0 ? 0 : wplsReceived;  // if GIBS=token0: WPLS=token1, out1
            uint256 a1Out = git0 ? wplsReceived : 0;  // if GIBS=token1: WPLS=token0, out0
            pair.swap(a0Out, a1Out, address(this), bytes(""));

            // Verify WPLS arrived at Hub
            // (pair sends it directly to address(this))
        }

        // ── Increment op nonce + emit ─────────────────────────
        _opNonce++;
        emit FloorCycleComplete(
            _opNonce,
            primeCount,
            lpGibs,
            wplsCommitted,
            lpMinted,
            burnLp,
            sellGibs,
            wplsReceived
        );
    }

    // ============================================================
    //  quoteFloorCycle  (view — free simulation)
    //
    //  Returns expected outputs for given params at current reserves.
    //  Call via eth_call before sending. Bot uses this for simulate().
    // ============================================================
    function quoteFloorCycle(
        uint256 primeCount,
        uint256 lpBps,
        uint256 wplsAvailable  // Hub's current WPLS balance (pass in)
    )
        external
        view
        returns (
            bool    feasible,
            uint256 wplsNeeded,    // WPLS that will be committed to LP
            uint256 wplsFromSell,  // WPLS expected from sell side
            uint256 netWpls,       // wplsFromSell - wplsNeeded (net WPLS flow)
            uint256 lpGibs,
            uint256 sellGibs
        )
    {
        if (primeCount == 0 || lpBps == 0 || lpBps > 9000) return (false,0,0,0,0,0);

        IUniV2Pair pair = _gibsWplsPair();
        if (address(pair) == address(0)) return (false,0,0,0,0,0);

        (uint112 r0, uint112 r1,) = pair.getReserves();
        if (r0 == 0 || r1 == 0) return (false,0,0,0,0,0);

        bool git0 = _gibsIsToken0();
        uint256 rGibs = git0 ? uint256(r0) : uint256(r1);
        uint256 rWpls = git0 ? uint256(r1) : uint256(r0);

        // Scale primeCount to wei (1 token = 1e18) — matches floorAndHarvest
        uint256 amount = primeCount * 1e18;
        lpGibs   = (amount * lpBps) / 10000;
        sellGibs = amount - lpGibs;
        if (lpGibs == 0 || sellGibs == 0) return (false,0,0,0,lpGibs,sellGibs);

        wplsNeeded = (lpGibs * rWpls) / rGibs;
        if (wplsNeeded > wplsAvailable) return (false,wplsNeeded,0,0,lpGibs,sellGibs);

        // Simulate post-mint reserves
        uint256 rGibs_after = rGibs + lpGibs;
        uint256 rWpls_after = rWpls + wplsNeeded;

        wplsFromSell = _getAmountOut(sellGibs, rGibs_after, rWpls_after);
        netWpls      = wplsFromSell > wplsNeeded
                       ? wplsFromSell - wplsNeeded
                       : 0;
        feasible     = wplsFromSell > 0;
    }

    // ============================================================
    //  floorConfig  (view — human-readable config dump)
    // ============================================================
    function floorConfig()
        external
        view
        returns (
            address gibsLau,
            address affection,
            address gibsWplsPair,
            bool    gibsIsToken0,
            address burnAddr
        )
    {
        gibsLau      = _addr(K_GIBS_LAU);
        affection    = _addr(K_AFFECTION);
        gibsWplsPair = _addr(K_GIBS_WPLS);
        gibsIsToken0 = _gibsIsToken0();
        burnAddr     = _burnAddr();
    }
}
