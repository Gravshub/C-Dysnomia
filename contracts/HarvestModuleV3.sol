// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

/*
 * ╔═══════════════════════════════════════════════════════════════════════╗
 * ║              HARVEST MODULE V3 — Atomic Prime + Sell                  ║
 * ║            |>JOYSTICK<| · Atropa/Dysnomia · PulseChain               ║
 * ╠═══════════════════════════════════════════════════════════════════════╣
 * ║  Fixes the sniper exploit: a dedicated bot (0x65930aa7...) monitors   ║
 * ║  GIBS LAU self-balance. When primeGibs(17) deposits 17 GIBS, the     ║
 * ║  sniper calls Purchase(GIBS_LAU, 17) and extracts them before our     ║
 * ║  mintLPAndSell can execute. This module combines prime + extract +    ║
 * ║  sell into ONE atomic TX — no gap for snipers.                        ║
 * ║                                                                       ║
 * ║  Inherits HubStorage from JoystickHub.sol (same storage layout).     ║
 * ║  Deployed separately and registered via hub.batchRegisterModule().    ║
 * ╚═══════════════════════════════════════════════════════════════════════╝
 */


// ── Interfaces (same as JoystickHub.sol) ────────────────────────────────

interface IERC20 {
    function balanceOf(address) external view returns (uint256);
    function approve(address, uint256) external returns (bool);
    function transfer(address, uint256) external returns (bool);
    function transferFrom(address, address, uint256) external returns (bool);
    function allowance(address, address) external view returns (uint256);
}

interface IWPLS is IERC20 {
    function deposit() external payable;
    function withdraw(uint256 wad) external;
}

interface IPulseXRouter {
    function swapExactTokensForTokens(
        uint256 amountIn, uint256 amountOutMin,
        address[] calldata path, address to, uint256 deadline
    ) external returns (uint256[] memory amounts);

    function getAmountsOut(uint256 amountIn, address[] calldata path)
        external view returns (uint256[] memory amounts);
}

/// @dev Dysnomia token interface — Purchase and mintToCap
interface IDysnomiaToken is IERC20 {
    function Purchase(address _t, uint256 _a) external;
    function Generate() external returns (uint64);
    function mintToCap() external;
}


// ── HubStorage (must match JoystickHub.sol exactly) ─────────────────────

abstract contract HubStorage {
    address internal _owner;
    uint256 internal _reentrancy;
    bool internal _paused;
    mapping(bytes4 => address) internal _modules;
    mapping(address => bool) internal _authorized;
    address internal _wpls;
    address internal _routerV1;
    address internal _routerV2;
    address internal _factoryV1;
    address internal _factoryV2;
    mapping(bytes32 => uint256) internal _config;
    uint256 internal _opNonce;
    // ═══ APPEND NEW SLOTS BELOW THIS LINE ONLY ═══
}


// ═════════════════════════════════════════════════════════════════════════
//  HARVEST MODULE V3 — Atomic Prime + Sell (Anti-Sniper)
// ═════════════════════════════════════════════════════════════════════════

contract HarvestModuleV3 is HubStorage {

    // ── Events ──────────────────────────────────────────────────────────
    event PrimeAndSell(uint256 count, uint256 plsOut);
    event GibsPrimed(uint256 count);
    event HarvestExecuted(uint256 gibsMinted, uint256 lpMinted, uint256 plsReceived, uint256 lpBurned);

    // ── Modifiers (duplicated — delegatecall context) ───────────────────
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
    function _approve(address token, address spender) internal {
        // Zero-first pattern for USDT-style tokens
        token.call(abi.encodeWithSelector(IERC20.approve.selector, spender, 0));
        (bool ok,) = token.call(
            abi.encodeWithSelector(IERC20.approve.selector, spender, type(uint256).max)
        );
        require(ok, "harv3:approve failed");
    }

    function _safeTransfer(address token, address to, uint256 amount) internal {
        (bool ok, bytes memory data) = token.call(
            abi.encodeWithSelector(IERC20.transfer.selector, to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "harv3:transfer");
    }

    // ═════════════════════════════════════════════════════════════════════
    //  primeAndSell — THE ANTI-SNIPER FUNCTION
    // ═════════════════════════════════════════════════════════════════════

    /// @notice Atomic: prime GIBS LAU self-balance → Purchase to extract →
    ///         sell on DEX. All in one TX — no gap for snipers.
    /// @param count       Number of GIBS to mint (calls mintToCap N times)
    /// @param minPLSOut   Minimum PLS output from sell (slippage guard)
    /// @param dex         0=V1, 1=V2 router for sell
    /// @param sellPath    Token path for sell (e.g. [GIBS, WPLS])
    function primeAndSell(
        uint256 count,
        uint256 minPLSOut,
        uint8 dex,
        address[] calldata sellPath
    )
        external payable onlyAuth whenNotPaused nonReentrant
        returns (uint256 plsReceived)
    {
        address gibsLau   = address(uint160(_config[keccak256("harvest.gibsLau")]));
        address affection = address(uint160(_config[keccak256("harvest.affection")]));
        require(gibsLau != address(0), "harv3:gibsLau not set");
        require(affection != address(0), "harv3:affection not set");
        require(count > 0, "harv3:count zero");
        require(sellPath.length >= 2, "harv3:sellPath too short");
        require(sellPath[0] == gibsLau, "harv3:sellPath[0] != gibsLau");

        // Step 1 — Prime: call mintToCap() N times on GIBS LAU
        // This deposits GIBS into GIBS LAU's self-balance (address(gibsLau))
        for (uint256 i; i < count; ++i) {
            IDysnomiaToken(gibsLau).mintToCap();
        }

        // Step 2 — Extract: Purchase GIBS from LAU using AFFECTION
        // Purchase(affection, N) spends N AFF and transfers N GIBS to msg.sender
        // In delegatecall context, msg.sender = Hub, so GIBS land in Hub
        uint256 affNeeded = count * 1e18;
        uint256 affBal = IERC20(affection).balanceOf(address(this));
        require(affBal >= affNeeded, "harv3:insufficient AFF");

        _approve(affection, gibsLau);
        uint256 gibsBefore = IERC20(gibsLau).balanceOf(address(this));
        IDysnomiaToken(gibsLau).Purchase(affection, affNeeded);
        uint256 gibsReceived = IERC20(gibsLau).balanceOf(address(this)) - gibsBefore;
        require(gibsReceived > 0, "harv3:purchase got zero GIBS");

        // Step 3 — Sell: swap GIBS → PLS via DEX
        IPulseXRouter router = IPulseXRouter(dex == 0 ? _routerV1 : _routerV2);
        _approve(gibsLau, address(router));

        uint256[] memory amounts = router.swapExactTokensForTokens(
            gibsReceived,
            minPLSOut,
            sellPath,
            address(this),
            block.timestamp
        );
        plsReceived = amounts[amounts.length - 1];

        // Step 4 — Verify slippage guard
        require(plsReceived >= minPLSOut, "harv3:slippage");

        _opNonce++;
        emit PrimeAndSell(count, plsReceived);
    }

    // ═════════════════════════════════════════════════════════════════════
    //  primeGibs — Backward compat (same as V2, registered to same selector)
    // ═════════════════════════════════════════════════════════════════════

    /// @notice Prime active LAU self-balance by calling mintToCap() N times.
    ///         Kept for backward compatibility — old V2 selector still works.
    function primeGibs(uint256 count) external onlyAuth whenNotPaused {
        address gibsLau = address(uint160(_config[keccak256("harvest.gibsLau")]));
        require(gibsLau != address(0), "harv3:gibsLau not set");

        for (uint256 i; i < count; ++i) {
            IDysnomiaToken(gibsLau).mintToCap();
        }
        emit GibsPrimed(count);
    }
}
