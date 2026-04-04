// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

/*
 * ╔═══════════════════════════════════════════════════════════════════════╗
 * ║                  SPINE MODULE — V2 Autonomous Ammo Chain              ║
 * ║            |>JOYSTICK<| · Atropa/Dysnomia · PulseChain               ║
 * ╠═══════════════════════════════════════════════════════════════════════╣
 * ║  Delegatecall module for JoystickHub.                                 ║
 * ║  V2 Federal mint → sell → claim cycle (FDIC spine pattern).           ║
 * ║  Ammo (JAMMO) rebuild via JBASE intermediate.                         ║
 * ╚═══════════════════════════════════════════════════════════════════════╝
 */


// ═════════════════════════════════════════════════════════════════════════
//  INTERFACES
// ═════════════════════════════════════════════════════════════════════════

interface IERC20 {
    function balanceOf(address) external view returns (uint256);
    function approve(address, uint256) external returns (bool);
    function transfer(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
    function allowance(address, address) external view returns (uint256);
}

interface ITreasuryToken is IERC20 {
    function mint(uint256 amount) external;
    function Claim(address Contract, uint256 Amount) external;
    function Parent() external view returns (address);
    function Debenture() external view returns (bool);
}

interface IUniswapV2Router {
    function swapExactTokensForTokens(
        uint256 amountIn, uint256 amountOutMin,
        address[] calldata path, address to, uint256 deadline
    ) external returns (uint256[] memory amounts);
}


// ═════════════════════════════════════════════════════════════════════════
//  SHARED STORAGE LAYOUT (must match JoystickHub exactly)
// ═════════════════════════════════════════════════════════════════════════

/// @dev All modules inherit this. NEVER reorder slots. NEVER insert between.
///      New state MUST go into _config mapping or be APPENDED after existing slots.
abstract contract HubStorage {
    // ── Slot 0 ── Owner
    address internal _owner;

    // ── Slot 1 ── Reentrancy guard (1=unlocked, 2=locked)
    uint256 internal _reentrancy;

    // ── Slot 2 ── Paused flag
    bool internal _paused;

    // ── Slot 3 ── Module registry: selector → implementation
    mapping(bytes4 => address) internal _modules;

    // ── Slot 4 ── Auth mapping
    mapping(address => bool) internal _authorized;

    // ── Slot 5 ── Immutable external refs (set in constructor)
    address internal _wpls;
    address internal _routerV1;
    address internal _routerV2;
    address internal _factoryV1;
    address internal _factoryV2;

    // ── Slot 6 ── Extensible config mapping (namespaced keys)
    mapping(bytes32 => uint256) internal _config;

    // ── Slot 7 ── Operation nonce
    uint256 internal _opNonce;

    // ═══ APPEND NEW SLOTS BELOW THIS LINE ONLY ═══
}


// ═════════════════════════════════════════════════════════════════════════
//  SPINE MODULE
// ═════════════════════════════════════════════════════════════════════════

contract SpineModule is HubStorage {

    // ── Events ──────────────────────────────────────────────────────────
    event SpineCycle(
        address indexed target,
        address indexed ammo,
        uint256 iters,
        uint256 wplsOut,
        uint256 opNonce
    );

    event SpineReload(
        address indexed jbase,
        address indexed jammo,
        uint256 fedSpent,
        uint256 jammoMinted,
        uint256 opNonce
    );

    // ── Modifiers (must match Hub exactly) ──────────────────────────────
    modifier onlyAuth() {
        require(msg.sender == _owner || _authorized[msg.sender], "hub:unauthorized");
        _;
    }

    modifier nonReentrant() {
        require(_reentrancy == 1, "hub:reentrant");
        _reentrancy = 2;
        _;
        _reentrancy = 1;
    }

    modifier whenNotPaused() {
        require(!_paused, "hub:paused");
        _;
    }

    // ── SafeERC20 internals ─────────────────────────────────────────────
    function _approve(address token, address spender, uint256 amount) internal {
        // Zero-first pattern for USDT-style tokens
        (bool z,) = token.call(abi.encodeWithSelector(IERC20.approve.selector, spender, 0));
        // Always approve max — V4 tokens charge 2x via transferFrom
        (bool ok,) = token.call(
            abi.encodeWithSelector(IERC20.approve.selector, spender, type(uint256).max)
        );
        require(ok, "spine:approve failed");
    }

    // ── Core: spineRun ──────────────────────────────────────────────────
    /// @notice Execute N iterations of: mint target → sell on DEX → claim parent back via ammo.
    /// @param target  V2 Federal treasury token (e.g. FDIC)
    /// @param ammo    Debenture=true spend token (e.g. JAMMO)
    /// @param amount  Amount per mint/claim iteration (in token wei)
    /// @param iters   Number of mint-sell-claim iterations
    /// @param minWplsOut  Minimum WPLS received from selling all minted target tokens
    /// @param sellDex 0 = PulseX V1, 1 = PulseX V2
    /// @return wplsOut Total WPLS received from sells
    function spineRun(
        address target,
        address ammo,
        uint256 amount,
        uint256 iters,
        uint256 minWplsOut,
        uint8 sellDex
    ) external onlyAuth whenNotPaused nonReentrant returns (uint256 wplsOut) {
        require(iters > 0 && iters <= 50, "spine:iters 1-50");
        require(amount > 0, "spine:zero amount");

        address parent = ITreasuryToken(target).Parent();
        require(parent != address(0), "spine:no parent");

        // ── Phase 1: Mint target tokens ─────────────────────────────────
        _approve(parent, target, type(uint256).max);

        uint256 targetBalBefore = IERC20(target).balanceOf(address(this));
        for (uint256 i = 0; i < iters; i++) {
            ITreasuryToken(target).mint(amount);
        }
        uint256 targetMinted = IERC20(target).balanceOf(address(this)) - targetBalBefore;
        require(targetMinted > 0, "spine:no tokens minted");

        // ── Phase 2: Sell all minted target tokens on DEX → WPLS ────────
        address router = sellDex == 0 ? _routerV1 : _routerV2;
        _approve(target, router, type(uint256).max);

        address[] memory path = new address[](2);
        path[0] = target;
        path[1] = _wpls;

        uint256 wplsBefore = IERC20(_wpls).balanceOf(address(this));
        IUniswapV2Router(router).swapExactTokensForTokens(
            targetMinted,
            minWplsOut,
            path,
            address(this),
            block.timestamp + 300
        );
        wplsOut = IERC20(_wpls).balanceOf(address(this)) - wplsBefore;

        // ── Phase 3: Claim parent back using ammo ───────────────────────
        _approve(ammo, target, type(uint256).max);

        for (uint256 i = 0; i < iters; i++) {
            ITreasuryToken(target).Claim(ammo, amount);
        }

        _opNonce++;
        emit SpineCycle(target, ammo, iters, wplsOut, _opNonce);
    }

    // ── Core: spineReload ───────────────────────────────────────────────
    /// @notice Rebuild ammo: FED → JBASE → JAMMO.
    /// @param jbase  Intermediate token (minted from FED)
    /// @param jammo  Ammo token (minted from JBASE)
    /// @param amount Amount of FED to spend
    /// @return jammoMinted Amount of JAMMO produced
    function spineReload(
        address jbase,
        address jammo,
        uint256 amount
    ) external onlyAuth whenNotPaused nonReentrant returns (uint256 jammoMinted) {
        require(amount > 0, "spine:zero amount");

        address fed = ITreasuryToken(jbase).Parent();
        require(fed != address(0), "spine:jbase no parent");

        // ── Step 1: FED → JBASE ─────────────────────────────────────────
        _approve(fed, jbase, type(uint256).max);

        uint256 jbaseBalBefore = IERC20(jbase).balanceOf(address(this));
        ITreasuryToken(jbase).mint(amount);
        uint256 jbaseMinted = IERC20(jbase).balanceOf(address(this)) - jbaseBalBefore;
        require(jbaseMinted > 0, "spine:no jbase minted");

        // ── Step 2: JBASE → JAMMO ───────────────────────────────────────
        _approve(jbase, jammo, type(uint256).max);

        uint256 jammoBalBefore = IERC20(jammo).balanceOf(address(this));
        ITreasuryToken(jammo).mint(jbaseMinted);
        jammoMinted = IERC20(jammo).balanceOf(address(this)) - jammoBalBefore;
        require(jammoMinted > 0, "spine:no jammo minted");

        _opNonce++;
        emit SpineReload(jbase, jammo, amount, jammoMinted, _opNonce);
    }

    // ── View: spineStatus ───────────────────────────────────────────────
    /// @notice Check ammo balance and whether a reload is needed.
    /// @param ammo      Ammo token address
    /// @param threshold Minimum acceptable balance before reload
    /// @return balance      Current ammo balance held by the hub
    /// @return needsReload  True if balance < threshold
    function spineStatus(
        address ammo,
        uint256 threshold
    ) external view returns (uint256 balance, bool needsReload) {
        balance = IERC20(ammo).balanceOf(address(this));
        needsReload = balance < threshold;
    }
}
