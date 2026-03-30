// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

/*
 * ╔═══════════════════════════════════════════════════════════════════════╗
 * ║                     JOYSTICK HUB — Modular Proxy                     ║
 * ║            |>JOYSTICK<| · Atropa/Dysnomia · PulseChain               ║
 * ╠═══════════════════════════════════════════════════════════════════════╣
 * ║  Single-file deploy: Hub + HarvestModule + AffectionModule +          ║
 * ║  PurchaseModule. No OpenZeppelin. Everything inlined.                 ║
 * ║                                                                       ║
 * ║  Hub routes calls to modules via selector→impl delegatecall.          ║
 * ║  Modules share storage layout via HubStorage.                         ║
 * ║  Hot-swappable: re-register selectors to upgrade any module.          ║
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
    function totalSupply() external view returns (uint256);
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

    function swapExactETHForTokens(
        uint256 amountOutMin,
        address[] calldata path, address to, uint256 deadline
    ) external payable returns (uint256[] memory amounts);

    function swapExactTokensForETH(
        uint256 amountIn, uint256 amountOutMin,
        address[] calldata path, address to, uint256 deadline
    ) external returns (uint256[] memory amounts);

    function addLiquidity(
        address tokenA, address tokenB,
        uint256 amountADesired, uint256 amountBDesired,
        uint256 amountAMin, uint256 amountBMin,
        address to, uint256 deadline
    ) external returns (uint256 amountA, uint256 amountB, uint256 liquidity);

    function getAmountsOut(uint256 amountIn, address[] calldata path)
        external view returns (uint256[] memory amounts);

    function WETH() external view returns (address);
}

interface IPulseXFactory {
    function getPair(address tokenA, address tokenB) external view returns (address pair);
}

interface IUniswapV2Pair {
    function getReserves() external view returns (uint112 r0, uint112 r1, uint32 ts);
    function token0() external view returns (address);
    function totalSupply() external view returns (uint256);
}

/// @dev Dysnomia token interface — Purchase, Generate, mintToCap, and Claim
interface IDysnomiaToken is IERC20 {
    function Purchase(address _t, uint256 _a) external;
    function Generate() external returns (uint64);
    function mintToCap() external;
    function Claim(address Contract, uint256 Amount) external;
    function Parent() external view returns (address);
    function Debenture() external view returns (bool);
}


// ═════════════════════════════════════════════════════════════════════════
//  SHARED STORAGE LAYOUT
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
//  JOYSTICK HUB — Proxy + Admin
// ═════════════════════════════════════════════════════════════════════════

contract JoystickHub is HubStorage {

    // ── Events ──────────────────────────────────────────────────────────
    event AuthSet(address indexed who, bool enabled);
    event ModuleRegistered(bytes4 indexed selector, address indexed impl);
    event ModuleBatchRegistered(bytes4[] selectors, address indexed impl);
    event ConfigSet(bytes32 indexed key, uint256 value);
    event Deposited(address indexed token, address indexed from, uint256 amount);
    event Withdrawn(address indexed token, address indexed to, uint256 amount);
    event WithdrawnPLS(address indexed to, uint256 amount);
    event EmergencyERC20(address indexed token, address indexed to, uint256 amount);
    event EmergencyNative(address indexed to, uint256 amount);
    event OwnershipTransferred(address indexed prev, address indexed next);

    // ── Modifiers ───────────────────────────────────────────────────────
    modifier onlyOwner() {
        require(msg.sender == _owner, "hub:not owner");
        _;
    }

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
        require(ok, "hub:approve failed");
    }

    function _safeTransfer(address token, address to, uint256 amount) internal {
        (bool ok, bytes memory data) = token.call(
            abi.encodeWithSelector(IERC20.transfer.selector, to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "hub:transfer");
    }

    function _safeTransferFrom(address token, address from, address to, uint256 amount) internal {
        (bool ok, bytes memory data) = token.call(
            abi.encodeWithSelector(IERC20.transferFrom.selector, from, to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "hub:transferFrom");
    }

    // ── Constructor ─────────────────────────────────────────────────────
    constructor(
        address wpls_,
        address routerV1_,
        address routerV2_,
        address factoryV1_,
        address factoryV2_
    ) {
        _owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);

        _authorized[msg.sender] = true;
        emit AuthSet(msg.sender, true);

        _reentrancy = 1;

        _wpls      = wpls_;
        _routerV1  = routerV1_;
        _routerV2  = routerV2_;
        _factoryV1 = factoryV1_;
        _factoryV2 = factoryV2_;
    }

    // ── Admin (onlyOwner) ───────────────────────────────────────────────
    function setAuth(address who, bool on) external onlyOwner {
        _authorized[who] = on;
        emit AuthSet(who, on);
    }

    function pause() external onlyOwner {
        _paused = true;
    }

    function unpause() external onlyOwner {
        _paused = false;
    }

    function setConfig(bytes32 key, uint256 val) external onlyOwner {
        _config[key] = val;
        emit ConfigSet(key, val);
    }

    function batchSetConfig(bytes32[] calldata keys, uint256[] calldata vals) external onlyOwner {
        require(keys.length == vals.length, "hub:length mismatch");
        for (uint256 i; i < keys.length; ++i) {
            _config[keys[i]] = vals[i];
            emit ConfigSet(keys[i], vals[i]);
        }
    }

    function registerModule(bytes4 selector, address impl) external onlyOwner {
        _modules[selector] = impl;
        emit ModuleRegistered(selector, impl);
    }

    function batchRegisterModule(bytes4[] calldata selectors, address impl) external onlyOwner {
        for (uint256 i; i < selectors.length; ++i) {
            _modules[selectors[i]] = impl;
        }
        emit ModuleBatchRegistered(selectors, impl);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "hub:zero owner");
        emit OwnershipTransferred(_owner, newOwner);
        _owner = newOwner;
    }

    // ── Operations (onlyAuth) ───────────────────────────────────────────
    function deposit(address token, uint256 amount) external onlyAuth {
        _safeTransferFrom(token, msg.sender, address(this), amount);
        emit Deposited(token, msg.sender, amount);
    }

    function withdraw(address token, uint256 amount) external onlyAuth {
        _safeTransfer(token, msg.sender, amount);
        emit Withdrawn(token, msg.sender, amount);
    }

    function withdrawPLS(uint256 amount) external onlyAuth {
        require(address(this).balance >= amount, "hub:insufficient PLS");
        (bool ok,) = payable(msg.sender).call{value: amount}("");
        require(ok, "hub:PLS send failed");
        emit WithdrawnPLS(msg.sender, amount);
    }

    function approveExternal(address token, address spender, uint256 amount) external onlyAuth {
        _approve(token, spender, amount);
    }

    // ── Emergency (onlyOwner) ───────────────────────────────────────────
    function emergencyWithdrawERC20(address token, address to, uint256 amt) external onlyOwner {
        _safeTransfer(token, to, amt);
        emit EmergencyERC20(token, to, amt);
    }

    function emergencyWithdrawNative(address payable to) external onlyOwner {
        uint256 bal = address(this).balance;
        (bool ok,) = to.call{value: bal}("");
        require(ok, "hub:emergency PLS failed");
        emit EmergencyNative(to, bal);
    }

    // ── Views ───────────────────────────────────────────────────────────
    function owner() external view returns (address) { return _owner; }
    function isPaused() external view returns (bool) { return _paused; }
    function isAuthorized(address who) external view returns (bool) { return _authorized[who]; }
    function module(bytes4 selector) external view returns (address) { return _modules[selector]; }
    function config(bytes32 key) external view returns (uint256) { return _config[key]; }
    function bal(address token) external view returns (uint256) {
        return IERC20(token).balanceOf(address(this));
    }
    function nativeBal() external view returns (uint256) { return address(this).balance; }

    // ── Proxy: fallback + receive ───────────────────────────────────────
    fallback() external payable {
        address impl = _modules[msg.sig];
        require(impl != address(0), "hub:no module");

        assembly {
            calldatacopy(0, 0, calldatasize())
            let result := delegatecall(gas(), impl, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            switch result
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }

    receive() external payable {}
}


// ═════════════════════════════════════════════════════════════════════════
//  HARVEST MODULE
// ═════════════════════════════════════════════════════════════════════════

contract HarvestModule is HubStorage {

    // ── Events ──────────────────────────────────────────────────────────
    event HarvestExecuted(uint256 gibsMinted, uint256 lpMinted, uint256 plsReceived, uint256 lpBurned);
    event GibsPrimed(uint256 count);
    event PairsReseeded(uint256 count, uint256 totalGibs);

    // ── Modifiers (must be duplicated — delegatecall context) ───────────
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
    function _approve(address token, address spender, uint256) internal {
        token.call(abi.encodeWithSelector(IERC20.approve.selector, spender, 0));
        (bool ok,) = token.call(
            abi.encodeWithSelector(IERC20.approve.selector, spender, type(uint256).max)
        );
        require(ok, "harv:approve failed");
    }

    function _safeTransfer(address token, address to, uint256 amount) internal {
        (bool ok, bytes memory data) = token.call(
            abi.encodeWithSelector(IERC20.transfer.selector, to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "harv:transfer");
    }

    /// @notice Prime active LAU self-balance by calling mintToCap() N times.
    ///         Config key "harvest.gibsLau" = address of the active LAU token.
    ///         Requires Hub to be in the LAU's MultiOwnable owner mapping.
    function primeGibs(uint256 count) external onlyAuth whenNotPaused {
        address gibsLau = address(uint160(_config[keccak256("harvest.gibsLau")]));
        require(gibsLau != address(0), "harv:gibsLau not set");

        for (uint256 i; i < count; ++i) {
            IDysnomiaToken(gibsLau).mintToCap();
        }
        emit GibsPrimed(count);
    }

    /// @notice Atomic GIBS harvest: mint → LP-first → sell-second → optional burn.
    function mintLPAndSell(
        uint256 mintCount,
        uint256 lpBps,
        uint256 burnBps,
        uint8 lpDex,
        uint256 minSellOut,
        address[] calldata sellPath,
        uint8 sellDex
    )
        external payable onlyAuth whenNotPaused nonReentrant
        returns (uint256 gibsMinted, uint256 lpMinted, uint256 plsReceived)
    {
        address gibsLau   = address(uint160(_config[keccak256("harvest.gibsLau")]));
        address affection = address(uint160(_config[keccak256("harvest.affection")]));
        require(gibsLau != address(0), "harv:gibsLau not set");
        require(affection != address(0), "harv:affection not set");

        // Step 1 — Wrap PLS
        if (msg.value > 0) {
            IWPLS(_wpls).deposit{value: msg.value}();
        }

        // Step 2 — safeMint: Purchase GIBS using AFF
        uint256 affBal = IERC20(affection).balanceOf(address(this));
        uint256 affNeeded = mintCount * 1e18;
        require(affBal >= affNeeded, "harv:insufficient AFF");

        _approve(affection, gibsLau, affNeeded);
        uint256 gibsBefore = IERC20(gibsLau).balanceOf(address(this));
        IDysnomiaToken(gibsLau).Purchase(affection, affNeeded);
        gibsMinted = IERC20(gibsLau).balanceOf(address(this)) - gibsBefore;
        require(gibsMinted > 0, "harv:mint got zero - did you primeGibs?");

        uint256 gibsForLP;
        uint256 lpBurned;

        // Step 3 — LP First (only if lpBps > 0)
        if (lpBps > 0) {
            gibsForLP = gibsMinted * lpBps / 10000;

            // Compute proportional WPLS from pair reserves
            IPulseXFactory factory = IPulseXFactory(lpDex == 0 ? _factoryV1 : _factoryV2);
            address pair = factory.getPair(gibsLau, _wpls);
            require(pair != address(0), "harv:no LP pair");

            (uint112 r0, uint112 r1,) = IUniswapV2Pair(pair).getReserves();
            address token0 = IUniswapV2Pair(pair).token0();

            uint256 reserveGibs;
            uint256 reserveWpls;
            if (token0 == gibsLau) {
                reserveGibs = uint256(r0);
                reserveWpls = uint256(r1);
            } else {
                reserveGibs = uint256(r1);
                reserveWpls = uint256(r0);
            }

            uint256 wplsForLP = (gibsForLP * reserveWpls) / reserveGibs;
            require(IERC20(_wpls).balanceOf(address(this)) >= wplsForLP, "harv:insufficient WPLS for LP");

            IPulseXRouter router = IPulseXRouter(lpDex == 0 ? _routerV1 : _routerV2);
            _approve(gibsLau, address(router), gibsForLP);
            _approve(_wpls, address(router), wplsForLP);

            (,, lpMinted) = router.addLiquidity(
                gibsLau, _wpls,
                gibsForLP, wplsForLP,
                gibsForLP * 9500 / 10000,   // 5% slip on GIBS side
                wplsForLP * 9500 / 10000,   // 5% slip on WPLS side
                address(this),
                block.timestamp
            );

            // Step 5 — Optional LP Burn (only if burnBps > 0 AND lpMinted > 0)
            if (burnBps > 0 && lpMinted > 0) {
                lpBurned = lpMinted * burnBps / 10000;
                if (lpBurned > 0) {
                    _safeTransfer(pair, 0x000000000000000000000000000000000000dEaD, lpBurned);
                }
            }
        }

        // Step 4 — Sell Second (only if remaining GIBS > 0 and sellPath valid)
        uint256 gibsToSell = gibsMinted - gibsForLP;
        if (gibsToSell > 0 && sellPath.length >= 2) {
            require(sellPath[0] == gibsLau, "harv:sellPath[0] != gibsLau");

            IPulseXRouter sellRouter = IPulseXRouter(sellDex == 0 ? _routerV1 : _routerV2);
            _approve(gibsLau, address(sellRouter), gibsToSell);

            uint256[] memory amounts = sellRouter.swapExactTokensForTokens(
                gibsToSell,
                minSellOut,
                sellPath,
                address(this),
                block.timestamp
            );
            plsReceived = amounts[amounts.length - 1];
        }

        _opNonce++;
        emit HarvestExecuted(gibsMinted, lpMinted, plsReceived, lpBurned);
    }

    /// @notice Batch-reseed drained LP pairs with GIBS from hub working balance.
    function batchReseed(
        address[] calldata pairs,
        uint256[] calldata amounts
    ) external onlyAuth whenNotPaused nonReentrant {
        require(pairs.length == amounts.length, "harv:length mismatch");
        address gibsLau = address(uint160(_config[keccak256("harvest.gibsLau")]));
        require(gibsLau != address(0), "harv:gibsLau not set");

        uint256 totalGibs;
        for (uint256 i; i < pairs.length; ++i) {
            _safeTransfer(gibsLau, pairs[i], amounts[i]);
            totalGibs += amounts[i];
        }
        emit PairsReseeded(pairs.length, totalGibs);
    }

    /// @notice LP + sell GIBS already deposited in the Hub (skip Purchase).
    ///         Use with DSS.mintToSelf(N) → Joey deposits GIBS → harvestPreloaded.
    function harvestPreloaded(
        uint256 lpBps,
        uint256 burnBps,
        uint8   lpDex,
        uint256 minSellOut,
        address[] calldata sellPath,
        uint8   sellDex
    )
        external payable onlyAuth whenNotPaused nonReentrant
        returns (uint256 lpMinted, uint256 plsReceived)
    {
        address gibsLau = address(uint160(_config[keccak256("harvest.gibsLau")]));
        require(gibsLau != address(0), "harv:gibsLau not set");

        // Step 1 — Wrap PLS for LP
        if (msg.value > 0) {
            IWPLS(_wpls).deposit{value: msg.value}();
        }

        // Step 2 — Use GIBS already in Hub (no Purchase)
        uint256 gibsTotal = IERC20(gibsLau).balanceOf(address(this));
        require(gibsTotal > 0, "harv:no GIBS in hub");

        uint256 gibsForLP;
        uint256 lpBurned;

        // Step 3 — LP First
        if (lpBps > 0) {
            gibsForLP = gibsTotal * lpBps / 10000;

            IPulseXFactory factory = IPulseXFactory(lpDex == 0 ? _factoryV1 : _factoryV2);
            address pair = factory.getPair(gibsLau, _wpls);
            require(pair != address(0), "harv:no LP pair");

            (uint112 r0, uint112 r1,) = IUniswapV2Pair(pair).getReserves();
            address token0 = IUniswapV2Pair(pair).token0();

            uint256 reserveGibs;
            uint256 reserveWpls;
            if (token0 == gibsLau) {
                reserveGibs = uint256(r0);
                reserveWpls = uint256(r1);
            } else {
                reserveGibs = uint256(r1);
                reserveWpls = uint256(r0);
            }

            uint256 wplsForLP = (gibsForLP * reserveWpls) / reserveGibs;
            require(IERC20(_wpls).balanceOf(address(this)) >= wplsForLP, "harv:insufficient WPLS for LP");

            IPulseXRouter router = IPulseXRouter(lpDex == 0 ? _routerV1 : _routerV2);
            _approve(gibsLau, address(router), gibsForLP);
            _approve(_wpls, address(router), wplsForLP);

            (,, lpMinted) = router.addLiquidity(
                gibsLau, _wpls,
                gibsForLP, wplsForLP,
                gibsForLP * 9500 / 10000,
                wplsForLP * 9500 / 10000,
                address(this),
                block.timestamp
            );

            // Optional LP Burn
            if (burnBps > 0 && lpMinted > 0) {
                lpBurned = lpMinted * burnBps / 10000;
                if (lpBurned > 0) {
                    _safeTransfer(pair, 0x000000000000000000000000000000000000dEaD, lpBurned);
                }
            }
        }

        // Step 4 — Sell Second
        uint256 gibsToSell = gibsTotal - gibsForLP;
        if (gibsToSell > 0 && sellPath.length >= 2) {
            require(sellPath[0] == gibsLau, "harv:sellPath[0] != gibsLau");

            IPulseXRouter sellRouter = IPulseXRouter(sellDex == 0 ? _routerV1 : _routerV2);
            _approve(gibsLau, address(sellRouter), gibsToSell);

            uint256[] memory amounts = sellRouter.swapExactTokensForTokens(
                gibsToSell,
                minSellOut,
                sellPath,
                address(this),
                block.timestamp
            );
            plsReceived = amounts[amounts.length - 1];
        }

        // Step 5 — Sweep
        _sweepToken(gibsLau);
        _sweepToken(_wpls);
        if (lpMinted > lpBurned) {
            IPulseXFactory factory = IPulseXFactory(lpDex == 0 ? _factoryV1 : _factoryV2);
            address pair = factory.getPair(gibsLau, _wpls);
            _sweepToken(pair);
        }

        _opNonce++;
        emit HarvestExecuted(gibsTotal, lpMinted, plsReceived, lpBurned);
    }

    function _sweepToken(address token) internal {
        uint256 bal = IERC20(token).balanceOf(address(this));
        if (bal > 0) {
            _safeTransfer(token, _owner, bal);
        }
    }

    /// @notice View: read current harvest config.
    function harvestConfig() external view returns (
        address gibsLau,
        address affection,
        uint256 primeCount
    ) {
        gibsLau   = address(uint160(_config[keccak256("harvest.gibsLau")]));
        affection = address(uint160(_config[keccak256("harvest.affection")]));
        primeCount = _config[keccak256("harvest.primeCount")];
    }
}


// ═════════════════════════════════════════════════════════════════════════
//  AFFECTION MODULE
// ═════════════════════════════════════════════════════════════════════════

contract AffectionModule is HubStorage {

    // ── Events ──────────────────────────────────────────────────────────
    event AffectionBought(address indexed paymentToken, uint256 loops, uint256 affReceived, uint256 plsOut);

    // ── Modifiers ───────────────────────────────────────────────────────
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
    function _approve(address token, address spender, uint256) internal {
        token.call(abi.encodeWithSelector(IERC20.approve.selector, spender, 0));
        (bool ok,) = token.call(
            abi.encodeWithSelector(IERC20.approve.selector, spender, type(uint256).max)
        );
        require(ok, "aff:approve failed");
    }

    /// @notice Atomic AFF acquisition: PLS → payment token → BuyWith → AFF in hub.
    function buyAffection(
        address paymentToken,
        bytes4 buySelector,
        uint256 loops,
        uint256 minAffOut,
        uint8 dex
    )
        external payable onlyAuth whenNotPaused nonReentrant
        returns (uint256 affReceived, uint256 plsOut)
    {
        address affection = address(uint160(_config[keccak256("affection.token")]));
        require(affection != address(0), "aff:token not set");

        uint256 maxLoops = _config[keccak256("affection.maxLoops")];
        if (maxLoops > 0) {
            require(loops <= maxLoops, "aff:exceeds maxLoops");
        }

        // Step 1 — Wrap PLS
        uint256 swapAmount;
        if (msg.value > 0) {
            IWPLS(_wpls).deposit{value: msg.value}();
            swapAmount = msg.value;
        } else {
            swapAmount = IERC20(_wpls).balanceOf(address(this));
        }
        require(swapAmount > 0, "aff:no PLS to swap");

        // Step 2 — Swap WPLS → paymentToken
        IPulseXRouter router = IPulseXRouter(dex == 0 ? _routerV1 : _routerV2);
        _approve(_wpls, address(router), swapAmount);

        address[] memory path = new address[](2);
        path[0] = _wpls;
        path[1] = paymentToken;

        uint256[] memory amounts = router.swapExactTokensForTokens(
            swapAmount, 1, path, address(this), block.timestamp
        );
        uint256 paymentReceived = amounts[1];

        // Step 3 — BuyWith on AFFECTION
        _approve(paymentToken, affection, type(uint256).max);
        uint256 affBefore = IERC20(affection).balanceOf(address(this));

        (bool ok,) = affection.call(
            abi.encodeWithSelector(buySelector, loops * 1e18)
        );
        require(ok, "aff:buyWith failed");

        affReceived = IERC20(affection).balanceOf(address(this)) - affBefore;
        require(affReceived >= minAffOut, "aff:slippage");

        // Step 4 — Optional auto-sell
        if (_config[keccak256("affection.autoSell")] == 1 && affReceived > 0) {
            IPulseXRouter sellRouter = IPulseXRouter(_routerV2);
            _approve(affection, address(sellRouter), affReceived);

            address[] memory sellPath = new address[](2);
            sellPath[0] = affection;
            sellPath[1] = _wpls;

            uint256[] memory sellAmounts = sellRouter.swapExactTokensForTokens(
                affReceived, 1, sellPath, address(this), block.timestamp
            );
            plsOut = sellAmounts[1];

            // Unwrap WPLS → PLS stays in hub
            IWPLS(_wpls).withdraw(plsOut);
        }

        _opNonce++;
        emit AffectionBought(paymentToken, loops, affReceived, plsOut);
    }

    /// @notice View: estimate output for a buyAffection call.
    function quoteBuyAffection(
        address paymentToken,
        uint256 plsAmount,
        uint256 loops,
        uint8 dex
    ) external view returns (uint256 estPaymentTokens, uint256 estAff) {
        IPulseXRouter router = IPulseXRouter(dex == 0 ? _routerV1 : _routerV2);

        address[] memory path = new address[](2);
        path[0] = _wpls;
        path[1] = paymentToken;

        try router.getAmountsOut(plsAmount, path) returns (uint256[] memory amounts) {
            estPaymentTokens = amounts[1];
        } catch {
            return (0, 0);
        }

        // AFF output depends on BuyWith rate (approximately 1:1 for most routes)
        // This is a rough estimate — actual output depends on the specific BuyWith function
        estAff = loops * 1e18;
    }
}


// ═════════════════════════════════════════════════════════════════════════
//  PURCHASE MODULE
// ═════════════════════════════════════════════════════════════════════════

contract PurchaseModule is HubStorage {

    // ── Events ──────────────────────────────────────────────────────────
    event PurchaseProfit(address indexed targetToken, uint256 affSpent, uint256 tokensReceived, uint256 plsReceived);

    // ── Modifiers ───────────────────────────────────────────────────────
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
    function _approve(address token, address spender, uint256) internal {
        token.call(abi.encodeWithSelector(IERC20.approve.selector, spender, 0));
        (bool ok,) = token.call(
            abi.encodeWithSelector(IERC20.approve.selector, spender, type(uint256).max)
        );
        require(ok, "pur:approve failed");
    }

    function _safeTransfer(address token, address to, uint256 amount) internal {
        (bool ok, bytes memory data) = token.call(
            abi.encodeWithSelector(IERC20.transfer.selector, to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "pur:transfer");
    }

    /// @notice Atomic Purchase arb: spend AFF → receive targetToken → sell on DEX → PLS.
    function purchaseAndSell(
        address targetToken,
        uint256 affAmount,
        address[] calldata sellPath,
        uint8 dex,
        uint256 minPLSOut
    )
        external onlyAuth whenNotPaused nonReentrant
        returns (uint256 tokensReceived, uint256 plsReceived)
    {
        address affection = address(uint160(_config[keccak256("purchase.affection")]));
        require(affection != address(0), "pur:aff not set");
        require(IERC20(affection).balanceOf(address(this)) >= affAmount, "pur:insufficient AFF");
        require(sellPath.length >= 2, "pur:sell path too short");
        require(sellPath[0] == targetToken, "pur:path[0] != target");

        // Step 1 — Purchase
        _approve(affection, targetToken, affAmount);
        uint256 targetBefore = IERC20(targetToken).balanceOf(address(this));
        IDysnomiaToken(targetToken).Purchase(affection, affAmount);
        tokensReceived = IERC20(targetToken).balanceOf(address(this)) - targetBefore;
        require(tokensReceived > 0, "pur:purchase got zero");

        // Step 2 — Sell on DEX
        IPulseXRouter router = IPulseXRouter(dex == 0 ? _routerV1 : _routerV2);
        _approve(targetToken, address(router), tokensReceived);

        uint256[] memory amounts = router.swapExactTokensForTokens(
            tokensReceived,
            minPLSOut,
            sellPath,
            address(this),
            block.timestamp
        );
        plsReceived = amounts[amounts.length - 1];

        _opNonce++;
        emit PurchaseProfit(targetToken, affAmount, tokensReceived, plsReceived);
    }

    /// @notice Batch purchase across multiple targets. Each is independent (try/catch).
    function batchPurchaseAndSell(
        address[] calldata targets,
        uint256[] calldata affAmounts,
        address[][] calldata sellPaths,
        uint8[] calldata dexes,
        uint256[] calldata minOuts
    )
        external onlyAuth whenNotPaused nonReentrant
        returns (uint256[] memory profits)
    {
        require(
            targets.length == affAmounts.length &&
            targets.length == sellPaths.length &&
            targets.length == dexes.length &&
            targets.length == minOuts.length,
            "pur:length mismatch"
        );

        address affection = address(uint160(_config[keccak256("purchase.affection")]));
        require(affection != address(0), "pur:aff not set");

        profits = new uint256[](targets.length);

        for (uint256 i; i < targets.length; ++i) {
            try this._executeSinglePurchase(
                affection, targets[i], affAmounts[i], sellPaths[i], dexes[i], minOuts[i]
            ) returns (uint256 profit) {
                profits[i] = profit;
            } catch {
                profits[i] = 0;
            }
        }
    }

    /// @dev Internal function called via this.call for try/catch in batch.
    ///      Must be external for try/catch but only callable by self.
    function _executeSinglePurchase(
        address affection,
        address targetToken,
        uint256 affAmount,
        address[] calldata sellPath,
        uint8 dex,
        uint256 minPLSOut
    ) external returns (uint256 plsReceived) {
        require(msg.sender == address(this), "pur:internal only");
        require(IERC20(affection).balanceOf(address(this)) >= affAmount, "pur:insufficient AFF");
        require(sellPath.length >= 2 && sellPath[0] == targetToken, "pur:bad path");

        _approve(affection, targetToken, affAmount);
        uint256 targetBefore = IERC20(targetToken).balanceOf(address(this));
        IDysnomiaToken(targetToken).Purchase(affection, affAmount);
        uint256 tokensReceived = IERC20(targetToken).balanceOf(address(this)) - targetBefore;
        require(tokensReceived > 0, "pur:purchase got zero");

        IPulseXRouter router = IPulseXRouter(dex == 0 ? _routerV1 : _routerV2);
        _approve(targetToken, address(router), tokensReceived);

        uint256[] memory amounts = router.swapExactTokensForTokens(
            tokensReceived, minPLSOut, sellPath, address(this), block.timestamp
        );
        plsReceived = amounts[amounts.length - 1];

        _opNonce++;
        emit PurchaseProfit(targetToken, affAmount, tokensReceived, plsReceived);
    }

    /// @notice View: check if a Purchase route is profitable.
    function quotePurchase(
        address targetToken,
        uint256 affAmount,
        address[] calldata sellPath,
        uint8 dex
    ) external view returns (bool profitable, uint256 spreadBps, uint256 estPLSOut) {
        require(sellPath.length >= 2, "pur:sell path too short");

        address affection = address(uint160(_config[keccak256("purchase.affection")]));
        IPulseXRouter router = IPulseXRouter(dex == 0 ? _routerV1 : _routerV2);

        // Estimate sell output for purchased tokens (Purchase is ~1:1 at market rate)
        try router.getAmountsOut(affAmount, sellPath) returns (uint256[] memory amounts) {
            estPLSOut = amounts[amounts.length - 1];
        } catch {
            return (false, 0, 0);
        }

        // AFF cost in PLS terms
        address[] memory affPath = new address[](2);
        affPath[0] = affection;
        affPath[1] = _wpls;

        try router.getAmountsOut(affAmount, affPath) returns (uint256[] memory affAmts) {
            uint256 affCostPLS = affAmts[1];
            if (estPLSOut > affCostPLS && affCostPLS > 0) {
                spreadBps = (estPLSOut - affCostPLS) * 10000 / affCostPLS;
                uint256 minSpread = _config[keccak256("purchase.minSpreadBps")];
                profitable = spreadBps >= minSpread;
            }
        } catch {
            // Can't price AFF, return what we have
            return (false, 0, estPLSOut);
        }
    }
}
