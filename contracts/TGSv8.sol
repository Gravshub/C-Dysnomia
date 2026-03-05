// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

/*
 * ╔═══════════════════════════════════════════════════════════════════════╗
 * ║                    TREASURY GAME SHARK V8 (TGSv8)                     ║
 * ║          Agent-Operated Game Controller · Atropa/Dysnomia             ║
 * ╠═══════════════════════════════════════════════════════════════════════╣
 * ║  CHANGES FROM V6:                                                     ║
 * ║  · No OpenZeppelin — Ownable/Pausable/ReentrancyGuard/SafeERC20       ║
 * ║    all inlined. Self-contained single-file deploy.                    ║
 * ║  · Dual DEX: PulseX V1 + V2 with DEX{V1,V2,BEST} enum on all swaps    ║
 * ║  · getBestAmountsOut() — oracle pre-flight, queries both routers      ║
 * ║  · atomicArb() — buy V1/sell V2 (or vice versa) in one TX             ║
 * ║    Reverts atomically if profit < minProfit. Engine 1 substrate.      ║
 * ║  · Native PLS in/out — swapNativeForTokens, swapTokensForNative,      ║
 * ║    wrapPLS, unwrapPLS. No manual WPLS pre-wrap needed.                ║
 * ║  · Step.dex field in executeRoute — per-step DEX selection            ║
 * ║  · getReservesBoth() — reserves from V1 and V2 in one call            ║
 * ║  CHANGES FROM V7:                                                     ║
 * ║  · mintWM(count) — batch-mint WM via mv.RHO() loop, lands in working  ║
 * ║    balance. Replaces external TGSv5 dependency.                       ║
 * ╠═══════════════════════════════════════════════════════════════════════╣
 * ║  PulseChain Mainnet Addresses:                                        ║
 * ║    V4 Minter:        0x394c3D5990cEfC7Be36B82FDB07a7251ACe61cc7       ║
 * ║    V3 Minter:        0x0c4F73328dFCECfbecf235C9F78A4494a7EC5ddC       ║
 * ║    MV Token:         0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29       ║
 * ║    PulseX V1 Router: 0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02       ║
 * ║    PulseX V2 Router: 0x165C3410fC91EF562C50559f7d2289fEbed552d9       ║
 * ║    PulseX V1 Factory:0x1715a3E4A142d8b698131108995174F37aEBA10D       ║
 * ║    PulseX V2 Factory:0x29eA7545DEf87022BAdc76323F373EA1e707C523       ║
 * ║    WPLS:             0xA1077a294dDE1B09bB078844df40758a5D0f9a27       ║
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
    function decimals() external view returns (uint8);
    function name() external view returns (string memory);
    function symbol() external view returns (string memory);
}

/// @dev WPLS: ERC20 + deposit (wrap PLS) + withdraw (unwrap to PLS)
interface IWPLS is IERC20 {
    function deposit() external payable;
    function withdraw(uint256 wad) external;
}

/// @dev V4 Personal Minter — deploys a new treasury token
interface IV4Minter {
    function New(string calldata Name, string calldata Symbol,
                 uint256 InitialMint, address Parent) external returns (address);
}

/// @dev V3 Index Minter — same signature, universal multiplier
interface IV3Minter {
    function New(string calldata Name, string calldata Symbol,
                 uint256 InitialMint, address Parent) external returns (address);
}

/// @dev Treasury Token (TTv2 ABI)
interface ITreasuryToken is IERC20 {
    function Parent()       external view returns (address);
    function Debenture()    external view returns (bool);
    function _mintingKey()  external view returns (uint64);
    function mint(uint256 amount) external;
    function Claim(address Contract, uint256 Amount) external;
    function publish() external;
}

/// @dev PulseX V1/V2 Router (Uniswap V2 fork)
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

    function addLiquidityETH(
        address token, uint256 amountTokenDesired,
        uint256 amountTokenMin, uint256 amountETHMin,
        address to, uint256 deadline
    ) external payable returns (uint256 amountToken, uint256 amountETH, uint256 liquidity);

    function getAmountsOut(uint256 amountIn, address[] calldata path)
        external view returns (uint256[] memory amounts);

    function WETH() external view returns (address);
}

/// @dev PulseX V1/V2 Factory
interface IPulseXFactory {
    function getPair(address tokenA, address tokenB) external view returns (address pair);
}

/// @dev Uniswap V2 Pair
interface IUniswapV2Pair {
    function getReserves() external view returns (uint112 r0, uint112 r1, uint32 ts);
    function token0() external view returns (address);
    function totalSupply() external view returns (uint256);
}


// ═════════════════════════════════════════════════════════════════════════
//  MAIN CONTRACT
// ═════════════════════════════════════════════════════════════════════════

contract TreasurySharkV8 {

    // ── Inlined: Ownable ─────────────────────────────────────────────────
    address private _owner;
    event OwnershipTransferred(address indexed prev, address indexed next);
    modifier onlyOwner() { require(msg.sender == _owner, "v8:not owner"); _; }
    function owner() public view returns (address) { return _owner; }
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "v8:zero owner");
        emit OwnershipTransferred(_owner, newOwner);
        _owner = newOwner;
    }

    // ── Inlined: Pausable ─────────────────────────────────────────────────
    bool private _paused;
    event Paused(address account);
    event Unpaused(address account);
    modifier whenNotPaused() { require(!_paused, "v8:paused"); _; }
    function paused() public view returns (bool) { return _paused; }
    function _doPause()   internal { _paused = true;  emit Paused(msg.sender); }
    function _doUnpause() internal { _paused = false; emit Unpaused(msg.sender); }

    // ── Inlined: ReentrancyGuard ──────────────────────────────────────────
    uint256 private _reentrancy = 1;

    // ── WM minting ────────────────────────────────────────────────────────
    bytes4 private constant _RHO = 0xa4566950;

    modifier nonReentrant() {
        require(_reentrancy == 1, "v8:reentrant");
        _reentrancy = 2; _; _reentrancy = 1;
    }

    // ── Inlined: SafeERC20 helpers ────────────────────────────────────────

    /// @dev Approve with zero-first pattern for USDT-style tokens.
    function _approve(IERC20 token, address spender, uint256 amount) internal {
        // Attempt zero-first (silently ignore failure — not all tokens need it)
        address(token).call(abi.encodeWithSelector(token.approve.selector, spender, 0));
        // Always approve type(uint256).max — V4 tokens charge 2x mint amount via
        // transferFrom, so approving `amount` always falls short. TGSv8 only ever
        // approves to trusted contracts (minters, routers, child tokens) so MAX is safe.
        // `amount` parameter kept for ABI compatibility — callers unchanged.
        (bool ok,) = address(token).call(
            abi.encodeWithSelector(token.approve.selector, spender, type(uint256).max)
        );
        require(ok, "v8:approve failed");
    }

    function _safeTransfer(IERC20 token, address to, uint256 amount) internal {
        (bool ok, bytes memory data) = address(token).call(
            abi.encodeWithSelector(token.transfer.selector, to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "v8:transfer");
    }

    function _safeTransferFrom(IERC20 token, address from, address to, uint256 amount) internal {
        (bool ok, bytes memory data) = address(token).call(
            abi.encodeWithSelector(token.transferFrom.selector, from, to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "v8:transferFrom");
    }


    // ─────────────────────────────────────────────────────────────────────
    //  ENUMS & STRUCTS
    // ─────────────────────────────────────────────────────────────────────

    /// @notice Which DEX to use. BEST = auto-route to highest output.
    enum DEX { V1, V2, BEST }

    /// @notice Step types for executeRoute.
    enum StepType {
        MINT,            // 0: mint(amount) on target. tokenA=parent already deposited.
        CLAIM,           // 1: Claim(tokenA, amount) on target. tokenA=spending token.
        SWAP,            // 2: tokenA→tokenB via router selected by step.dex.
        ADD_LIQUIDITY,   // 3: LP tokenA+tokenB on step.dex router.
        TRANSFER_IN,     // 4: pull tokenA from msg.sender into contract.
        TRANSFER_OUT,    // 5: push tokenA from contract to msg.sender.
        APPROVE,         // 6: approve tokenA to target for amount.
        SWAP_MULTI,      // 7: 3-hop tokenA→target→tokenB via step.dex router.
        WRAP_PLS,        // 8: wrap contract's native PLS balance to WPLS (amount = how much).
        UNWRAP_WPLS      // 9: unwrap amount of WPLS to native PLS in contract.
    }

    struct Step {
        StepType action;
        address  target;    // child token, spender, or middle-hop for SWAP_MULTI
        address  tokenA;    // primary token
        address  tokenB;    // secondary token (swap out, LP pair)
        uint256  amount;    // primary amount
        uint256  amountB;   // secondary amount (minOut, LP amountB)
        uint256  slipBps;   // slippage basis points (100 = 1%)
        DEX      dex;       // which router to use for SWAP/ADD_LIQUIDITY steps
    }

    struct TokenMeta {
        address token;
        address parent;
        uint256 initialMint;
        uint256 createdAt;
        uint8   minterVersion;   // 3=V3, 4=V4, 0=imported
        bool    published;
    }


    // ─────────────────────────────────────────────────────────────────────
    //  STATE
    // ─────────────────────────────────────────────────────────────────────

    // ── External refs ─────────────────────────────────────────────────────
    IV4Minter       public minterV4;
    IV3Minter       public minterV3;
    IERC20          public mv;           // MV token (WM)
    IWPLS           public wpls;         // Wrapped PLS
    IPulseXRouter   public routerV1;     // PulseX V1 Router
    IPulseXRouter   public routerV2;     // PulseX V2 Router
    IPulseXFactory  public factoryV1;    // PulseX V1 Factory
    IPulseXFactory  public factoryV2;    // PulseX V2 Factory

    // ── Auth ──────────────────────────────────────────────────────────────
    mapping(address => bool) public authorized;

    // ── Token Registry ────────────────────────────────────────────────────
    mapping(address => TokenMeta)    public tokenMeta;
    address[]                        public registry;
    mapping(address => bool)         public imported;
    mapping(address => address[])    internal _children;
    mapping(address => address[])    internal _pairs;

    // ── Operations ────────────────────────────────────────────────────────
    uint256 public opNonce;
    uint256 public maxBatch = 20;


    // ─────────────────────────────────────────────────────────────────────
    //  EVENTS
    // ─────────────────────────────────────────────────────────────────────

    event AuthSet(address indexed who, bool enabled);
    event RefUpdated(string ref, address indexed addr);
    event Deposited(address indexed token, address indexed from, uint256 amount);
    event Withdrawn(address indexed token, address indexed to, uint256 amount);
    event TokenCreated(uint256 indexed op, address indexed token, address indexed parent, uint256 supply, uint8 version);
    event TokenImported(address indexed token, address indexed parent);
    event Minted(uint256 indexed op, address indexed child, uint256 parentSpent, uint256 childReceived);
    event Claimed(uint256 indexed op, address indexed child, address indexed spendToken, uint256 amount, uint256 parentBack);
    event MintAndClaimed(uint256 indexed op, address indexed child, address indexed spendToken, uint256 amount, uint256 childNet);
    event TreasuryClaimed(uint256 indexed op, address indexed treasury, address indexed backing, uint256 received);
    event Swapped(uint256 indexed op, address indexed tokenIn, address indexed tokenOut, uint256 amountIn, uint256 amountOut, DEX dex);
    event LiquidityAdded(uint256 indexed op, address indexed tokenA, address indexed tokenB, uint256 usedA, uint256 usedB, uint256 lp, DEX dex);
    event ArbExecuted(uint256 indexed op, address indexed tokenIn, address indexed tokenOut, uint256 amountIn, uint256 profit, DEX buyOn, DEX sellOn);
    event Wrapped(uint256 indexed op, uint256 amount);
    event Unwrapped(uint256 indexed op, uint256 amount);
    event RouteExecuted(uint256 indexed op, uint256 stepCount);
    event PairRegistered(address indexed a, address indexed b);
    event Published(address indexed token);
    event EmergencyERC20(address indexed token, address indexed to, uint256 amount);
    event EmergencyNative(address indexed to, uint256 amount);
    event WMMinted(uint256 indexed op, address indexed caller, uint256 count);


    // ─────────────────────────────────────────────────────────────────────
    //  MODIFIERS
    // ─────────────────────────────────────────────────────────────────────

    modifier onlyAuth() {
        require(msg.sender == _owner || authorized[msg.sender], "v8:unauthorized");
        _;
    }


    // ─────────────────────────────────────────────────────────────────────
    //  CONSTRUCTOR
    // ─────────────────────────────────────────────────────────────────────

    constructor(
        address _v4,
        address _v3,
        address _mv,
        address _wpls,
        address _routerV1,
        address _routerV2,
        address _factoryV1,
        address _factoryV2
    ) {
        _owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);

        authorized[msg.sender] = true;
        emit AuthSet(msg.sender, true);

        if (_v4       != address(0)) minterV4  = IV4Minter(_v4);
        if (_v3       != address(0)) minterV3  = IV3Minter(_v3);
        if (_mv       != address(0)) mv        = IERC20(_mv);
        if (_wpls     != address(0)) wpls      = IWPLS(_wpls);
        if (_routerV1 != address(0)) routerV1  = IPulseXRouter(_routerV1);
        if (_routerV2 != address(0)) routerV2  = IPulseXRouter(_routerV2);
        if (_factoryV1!= address(0)) factoryV1 = IPulseXFactory(_factoryV1);
        if (_factoryV2!= address(0)) factoryV2 = IPulseXFactory(_factoryV2);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T1: SAFETY & ADMIN
    // ═════════════════════════════════════════════════════════════════════

    function pause()   external onlyOwner { _doPause(); }
    function unpause() external onlyOwner { _doUnpause(); }

    function setAuth(address who, bool on) external onlyOwner {
        authorized[who] = on;
        emit AuthSet(who, on);
    }

    // ── Ref updates ───────────────────────────────────────────────────────
    function setMinterV4(address a)  external onlyOwner { minterV4  = IV4Minter(a);       emit RefUpdated("v4",       a); }
    function setMinterV3(address a)  external onlyOwner { minterV3  = IV3Minter(a);       emit RefUpdated("v3",       a); }
    function setMV(address a)        external onlyOwner { mv        = IERC20(a);           emit RefUpdated("mv",       a); }
    function setWPLS(address a)      external onlyOwner { wpls      = IWPLS(a);            emit RefUpdated("wpls",     a); }
    function setRouterV1(address a)  external onlyOwner { routerV1  = IPulseXRouter(a);   emit RefUpdated("routerV1", a); }
    function setRouterV2(address a)  external onlyOwner { routerV2  = IPulseXRouter(a);   emit RefUpdated("routerV2", a); }
    function setFactoryV1(address a) external onlyOwner { factoryV1 = IPulseXFactory(a);  emit RefUpdated("factV1",   a); }
    function setFactoryV2(address a) external onlyOwner { factoryV2 = IPulseXFactory(a);  emit RefUpdated("factV2",   a); }
    function setMaxBatch(uint256 n)  external onlyOwner { require(n > 0 && n <= 50, "v8:batch range"); maxBatch = n; }

    // ── Deposit / Withdraw ────────────────────────────────────────────────
    function deposit(address token, uint256 amount) external onlyAuth whenNotPaused {
        _safeTransferFrom(IERC20(token), msg.sender, address(this), amount);
        emit Deposited(token, msg.sender, amount);
    }

    function withdraw(address token, uint256 amount) external onlyAuth whenNotPaused {
        _safeTransfer(IERC20(token), msg.sender, amount);
        emit Withdrawn(token, msg.sender, amount);
    }

    // ── Approval helpers ──────────────────────────────────────────────────
    function approveMax(address token, address spender) external onlyAuth whenNotPaused {
        _approve(IERC20(token), spender, type(uint256).max);
    }

    function revokeApproval(address token, address spender) external onlyAuth whenNotPaused {
        _approve(IERC20(token), spender, 0);
    }

    // ── Emergency ─────────────────────────────────────────────────────────
    function emergencyWithdrawERC20(address token, address to, uint256 amt) external onlyOwner {
        _safeTransfer(IERC20(token), to, amt);
        emit EmergencyERC20(token, to, amt);
    }

    function emergencyWithdrawAll(address token, address to) external onlyOwner {
        uint256 b = IERC20(token).balanceOf(address(this));
        if (b > 0) { _safeTransfer(IERC20(token), to, b); emit EmergencyERC20(token, to, b); }
    }

    function emergencyWithdrawNative(address payable to) external onlyOwner {
        uint256 b = address(this).balance;
        require(b > 0, "v8:no native");
        (bool ok,) = to.call{value: b}("");
        require(ok, "v8:native send failed");
        emit EmergencyNative(to, b);
    }

    // ── WM Batch Minting ──────────────────────────────────────────────────

    /// @notice Batch-mint WM by calling mv.RHO() count times.
    ///         WM mints to tx.origin — caller must withdraw separately if needed.
    ///         Kept here so TGSv8 is fully self-contained (no TGSv5 dependency).
    function mintWM(uint256 count) external onlyAuth whenNotPaused nonReentrant {
        require(address(mv) != address(0), "v8:mv not set");
        require(count > 0 && count <= 100, "v8:wm count");
        for (uint256 i; i < count;) {
            (bool ok,) = address(mv).call(abi.encodeWithSelector(_RHO));
            require(ok, "v8:RHO failed");
            unchecked { ++i; }
        }
        emit WMMinted(_op(), msg.sender, count);
    }

    // ── Balance views ─────────────────────────────────────────────────────
    function bal(address token) external view returns (uint256) {
        return IERC20(token).balanceOf(address(this));
    }

    function nativeBal() external view returns (uint256) {
        return address(this).balance;
    }

    function batchBal(address[] calldata tokens) external view returns (uint256[] memory b) {
        b = new uint256[](tokens.length);
        for (uint256 i; i < tokens.length; ++i)
            b[i] = IERC20(tokens[i]).balanceOf(address(this));
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T2a: TOKEN CREATION
    // ═════════════════════════════════════════════════════════════════════

    function createV4(
        string calldata name_, string calldata symbol_,
        uint256 initialMint, address parent
    ) public onlyAuth whenNotPaused nonReentrant returns (address token) {
        require(address(minterV4) != address(0), "v8:v4 not set");
        require(initialMint > 0 && parent != address(0), "v8:bad params");
        _approve(mv, address(minterV4), initialMint);
        token = minterV4.New(name_, symbol_, initialMint, parent);
        require(token != address(0), "v8:deploy failed");
        _register(token, parent, initialMint, 4);
    }

    function createV3(
        string calldata name_, string calldata symbol_,
        uint256 initialMint, address parent
    ) public onlyAuth whenNotPaused nonReentrant returns (address token) {
        require(address(minterV3) != address(0), "v8:v3 not set");
        require(initialMint > 0 && parent != address(0), "v8:bad params");
        _approve(mv, address(minterV3), initialMint);
        token = minterV3.New(name_, symbol_, initialMint, parent);
        require(token != address(0), "v8:deploy failed");
        _register(token, parent, initialMint, 3);
    }

    function importToken(address token, uint8 version) external onlyAuth whenNotPaused {
        require(tokenMeta[token].token == address(0), "v8:exists");
        address par = _parent(token);
        uint256 sup;
        try ITreasuryToken(token).totalSupply() returns (uint256 s) { sup = s; } catch {}
        tokenMeta[token] = TokenMeta(token, par, sup, block.timestamp, version, false);
        registry.push(token);
        if (par != address(0)) _children[par].push(token);
        imported[token] = true;
        emit TokenImported(token, par);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T2b: MINT & CLAIM
    // ═════════════════════════════════════════════════════════════════════

    function mintTokens(address child, uint256 amount)
        public onlyAuth whenNotPaused nonReentrant returns (uint256 received)
    {
        address par = _parent(child);
        require(par != address(0), "v8:no parent");
        _approve(IERC20(par), child, amount);
        uint256 before = IERC20(child).balanceOf(address(this));
        _doMint(child, amount);
        received = IERC20(child).balanceOf(address(this)) - before;
        require(received > 0, "v8:mint got zero");
        emit Minted(_op(), child, amount, received);
    }

    function claimTokens(address child, address spendToken, uint256 amount)
        public onlyAuth whenNotPaused nonReentrant returns (uint256 parentBack)
    {
        address par = _parent(child);
        _approve(IERC20(spendToken), child, amount);
        uint256 before = IERC20(par).balanceOf(address(this));
        bool ok = _doClaim(child, spendToken, amount);
        require(ok, "v8:claim failed");
        parentBack = IERC20(par).balanceOf(address(this)) - before;
        emit Claimed(_op(), child, spendToken, amount, parentBack);
    }

    /// @notice Atomic mint-then-claim: the V2 infinite mint pattern.
    function mintAndClaim(address child, address spendToken, uint256 amount)
        public onlyAuth whenNotPaused nonReentrant returns (uint256 childNet)
    {
        address par = _parent(child);
        require(par != address(0), "v8:no parent");
        _approve(IERC20(par), child, amount);
        uint256 childBefore = IERC20(child).balanceOf(address(this));
        _doMint(child, amount);
        childNet = IERC20(child).balanceOf(address(this)) - childBefore;
        require(childNet > 0, "v8:mint got zero");
        _approve(IERC20(spendToken), child, amount);
        bool ok = _doClaim(child, spendToken, amount);
        require(ok, "v8:claim failed");
        emit MintAndClaimed(_op(), child, spendToken, amount, childNet);
    }

    function batchMintAndClaim(
        address[] calldata children_, address[] calldata spendTokens, uint256[] calldata amounts
    ) external onlyAuth whenNotPaused returns (uint256[] memory results) {
        uint256 len = children_.length;
        require(len == spendTokens.length && len == amounts.length, "v8:mismatch");
        require(len <= maxBatch, "v8:batch");
        results = new uint256[](len);
        for (uint256 i; i < len; ++i)
            results[i] = mintAndClaim(children_[i], spendTokens[i], amounts[i]);
    }

    function publishToken(address token) external onlyAuth whenNotPaused {
        ITreasuryToken(token).publish();
        if (tokenMeta[token].token != address(0)) tokenMeta[token].published = true;
        emit Published(token);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T3: TREASURY CLAIM SNIPING
    // ═════════════════════════════════════════════════════════════════════

    function claimFromTreasury(address treasury, address backingAsset, uint256 amount)
        public onlyAuth whenNotPaused nonReentrant returns (uint256 received)
    {
        _approve(IERC20(treasury), treasury, amount);
        uint256 before = IERC20(backingAsset).balanceOf(address(this));
        ITreasuryToken(treasury).Claim(backingAsset, amount);
        received = IERC20(backingAsset).balanceOf(address(this)) - before;
        emit TreasuryClaimed(_op(), treasury, backingAsset, received);
    }

    function batchClaimTreasury(
        address[] calldata treasuries, address[] calldata backingAssets, uint256[] calldata amounts
    ) external onlyAuth whenNotPaused returns (uint256[] memory results) {
        uint256 len = treasuries.length;
        require(len == backingAssets.length && len == amounts.length, "v8:mismatch");
        require(len <= maxBatch, "v8:batch");
        results = new uint256[](len);
        for (uint256 i; i < len; ++i) {
            try this.claimFromTreasury(treasuries[i], backingAssets[i], amounts[i])
                returns (uint256 r) { results[i] = r; }
            catch { results[i] = 0; }
        }
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T4: DEX INTEGRATION — V1, V2, BEST, ATOMIC ARB, NATIVE PLS
    // ═════════════════════════════════════════════════════════════════════

    // ── Router selection ──────────────────────────────────────────────────

    /// @dev Resolve DEX enum to a router. BEST falls through to V2 unless
    ///      caller has already determined the better router via getBestAmountsOut.
    function _getRouter(DEX dex) internal view returns (IPulseXRouter r) {
        if (dex == DEX.V1) {
            require(address(routerV1) != address(0), "v8:V1 not set");
            return routerV1;
        }
        require(address(routerV2) != address(0), "v8:V2 not set");
        return routerV2;
    }

    function _getFactory(DEX dex) internal view returns (IPulseXFactory) {
        if (dex == DEX.V1) return factoryV1;
        return factoryV2;
    }

    // ── Oracle pre-flight ─────────────────────────────────────────────────

    /// @notice Query both routers. Returns which gives more output.
    ///         Call this off-chain (eth_call) before any swap to pick optimal DEX.
    function getBestAmountsOut(uint256 amountIn, address[] calldata path)
        external view
        returns (uint256 v1Out, uint256 v2Out, DEX best, uint256 bestOut)
    {
        if (address(routerV1) != address(0)) {
            try routerV1.getAmountsOut(amountIn, path) returns (uint256[] memory a) {
                v1Out = a[a.length - 1];
            } catch {}
        }
        if (address(routerV2) != address(0)) {
            try routerV2.getAmountsOut(amountIn, path) returns (uint256[] memory a) {
                v2Out = a[a.length - 1];
            } catch {}
        }
        if (v1Out >= v2Out) { best = DEX.V1; bestOut = v1Out; }
        else                { best = DEX.V2; bestOut = v2Out; }
    }

    // ── Standard swaps ────────────────────────────────────────────────────

    /// @notice Swap exact tokens. DEX.BEST auto-routes to higher output router.
    function swapExact(
        address tokenIn, address tokenOut,
        uint256 amountIn, uint256 minOut, DEX dex
    ) public onlyAuth whenNotPaused nonReentrant returns (uint256 amountOut) {
        IPulseXRouter r;
        if (dex == DEX.BEST) {
            address[] memory p = new address[](2);
            p[0] = tokenIn; p[1] = tokenOut;
            uint256 v1Out; uint256 v2Out;
            if (address(routerV1) != address(0)) {
                try routerV1.getAmountsOut(amountIn, p) returns (uint256[] memory a) { v1Out = a[1]; } catch {}
            }
            if (address(routerV2) != address(0)) {
                try routerV2.getAmountsOut(amountIn, p) returns (uint256[] memory a) { v2Out = a[1]; } catch {}
            }
            r = v1Out >= v2Out ? routerV1 : routerV2;
            dex = v1Out >= v2Out ? DEX.V1 : DEX.V2;
        } else {
            r = _getRouter(dex);
        }

        _approve(IERC20(tokenIn), address(r), amountIn);
        address[] memory path = new address[](2);
        path[0] = tokenIn; path[1] = tokenOut;
        uint256[] memory amounts = r.swapExactTokensForTokens(
            amountIn, minOut, path, address(this), block.timestamp
        );
        amountOut = amounts[amounts.length - 1];
        emit Swapped(_op(), tokenIn, tokenOut, amountIn, amountOut, dex);
    }

    /// @notice Multi-hop swap (A→B→C). Uses specified DEX.
    function swapMultiHop(
        address[] calldata path, uint256 amountIn, uint256 minOut, DEX dex
    ) public onlyAuth whenNotPaused nonReentrant returns (uint256 amountOut) {
        require(path.length >= 2, "v8:path < 2");
        IPulseXRouter r = _getRouter(dex);
        _approve(IERC20(path[0]), address(r), amountIn);
        uint256[] memory amounts = r.swapExactTokensForTokens(
            amountIn, minOut, path, address(this), block.timestamp
        );
        amountOut = amounts[amounts.length - 1];
        emit Swapped(_op(), path[0], path[path.length - 1], amountIn, amountOut, dex);
    }

    // ── Native PLS ────────────────────────────────────────────────────────

    /// @notice Wrap PLS held in this contract to WPLS.
    function wrapPLS(uint256 amount) public onlyAuth whenNotPaused {
        require(address(wpls) != address(0), "v8:wpls not set");
        require(address(this).balance >= amount, "v8:insufficient native");
        wpls.deposit{value: amount}();
        emit Wrapped(_op(), amount);
    }

    /// @notice Unwrap WPLS held in this contract to native PLS.
    function unwrapWPLS(uint256 amount) public onlyAuth whenNotPaused {
        require(address(wpls) != address(0), "v8:wpls not set");
        wpls.withdraw(amount);
        emit Unwrapped(_op(), amount);
    }

    /// @notice Swap native PLS directly for tokens (wraps internally).
    ///         Send PLS as msg.value. Output tokens stay in contract.
    function swapNativeForTokens(
        address tokenOut, uint256 minOut, DEX dex
    ) external payable onlyAuth whenNotPaused nonReentrant returns (uint256 amountOut) {
        require(msg.value > 0, "v8:no native");
        require(address(wpls) != address(0), "v8:wpls not set");
        IPulseXRouter r = _getRouter(dex == DEX.BEST ? DEX.V2 : dex);
        address[] memory path = new address[](2);
        path[0] = address(wpls);
        path[1] = tokenOut;
        uint256[] memory amounts = r.swapExactETHForTokens{value: msg.value}(
            minOut, path, address(this), block.timestamp
        );
        amountOut = amounts[amounts.length - 1];
        emit Swapped(_op(), address(wpls), tokenOut, msg.value, amountOut, dex);
    }

    /// @notice Swap tokens for native PLS. PLS lands in contract.
    function swapTokensForNative(
        address tokenIn, uint256 amountIn, uint256 minOut, DEX dex
    ) external onlyAuth whenNotPaused nonReentrant returns (uint256 amountOut) {
        require(address(wpls) != address(0), "v8:wpls not set");
        IPulseXRouter r = _getRouter(dex == DEX.BEST ? DEX.V2 : dex);
        _approve(IERC20(tokenIn), address(r), amountIn);
        address[] memory path = new address[](2);
        path[0] = tokenIn;
        path[1] = address(wpls);
        uint256[] memory amounts = r.swapExactTokensForETH(
            amountIn, minOut, path, address(this), block.timestamp
        );
        amountOut = amounts[amounts.length - 1];
        emit Swapped(_op(), tokenIn, address(wpls), amountIn, amountOut, dex);
    }

    // ── Liquidity ─────────────────────────────────────────────────────────

    /// @notice Add liquidity on V1 or V2.
    function addLiquidity(
        address tokenA, address tokenB,
        uint256 amtA, uint256 amtB,
        uint256 slipBps, address to, DEX dex
    ) public onlyAuth whenNotPaused nonReentrant returns (uint256 lp) {
        require(to != address(0), "v8:zero to");
        IPulseXRouter r = _getRouter(dex == DEX.BEST ? DEX.V2 : dex);
        _approve(IERC20(tokenA), address(r), amtA);
        _approve(IERC20(tokenB), address(r), amtB);
        uint256 minA = amtA * (10000 - slipBps) / 10000;
        uint256 minB = amtB * (10000 - slipBps) / 10000;
        (uint256 usedA, uint256 usedB, uint256 liquidity) = r.addLiquidity(
            tokenA, tokenB, amtA, amtB, minA, minB, to, block.timestamp
        );
        lp = liquidity;
        emit LiquidityAdded(_op(), tokenA, tokenB, usedA, usedB, lp, dex);
    }

    // ── Atomic Cross-DEX Arbitrage ────────────────────────────────────────

    /// @notice Buy tokenOut on buyDex, sell back to tokenIn on sellDex in one TX.
    ///         Reverts atomically if round-trip profit < minProfit.
    ///         tokenIn must be in contract's working balance.
    ///
    ///         Engine 1 substrate — call getBestAmountsOut() off-chain first to
    ///         find the spread, then call this with the profitable direction.
    function atomicArb(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        DEX     buyOn,
        DEX     sellOn,
        uint256 minProfit
    ) external onlyAuth whenNotPaused nonReentrant returns (uint256 profit) {
        require(buyOn != DEX.BEST && sellOn != DEX.BEST, "v8:resolve BEST before arb");
        // Enforce different DEXes (same-DEX arb is a sandwich, not arbitrage)
        require(
            (buyOn == DEX.V1 && sellOn == DEX.V2) ||
            (buyOn == DEX.V2 && sellOn == DEX.V1),
            "v8:arb needs different DEXes"
        );

        IPulseXRouter buyRouter  = _getRouter(buyOn);
        IPulseXRouter sellRouter = _getRouter(sellOn);

        address[] memory path = new address[](2);
        uint256 tokenInBefore = IERC20(tokenIn).balanceOf(address(this));

        // ── Leg 1: buy tokenOut with tokenIn on buyRouter ─────────────────
        path[0] = tokenIn; path[1] = tokenOut;
        _approve(IERC20(tokenIn), address(buyRouter), amountIn);
        uint256[] memory buyAmounts = buyRouter.swapExactTokensForTokens(
            amountIn, 1, path, address(this), block.timestamp
        );
        uint256 received = buyAmounts[buyAmounts.length - 1];
        require(received > 0, "v8:arb buy got zero");

        // ── Leg 2: sell tokenOut back to tokenIn on sellRouter ────────────
        //    minOut = amountIn + minProfit ensures TX reverts if not profitable
        path[0] = tokenOut; path[1] = tokenIn;
        _approve(IERC20(tokenOut), address(sellRouter), received);
        sellRouter.swapExactTokensForTokens(
            received, amountIn + minProfit, path, address(this), block.timestamp
        );

        uint256 tokenInAfter = IERC20(tokenIn).balanceOf(address(this));
        require(tokenInAfter > tokenInBefore, "v8:arb unprofitable");
        profit = tokenInAfter - tokenInBefore;

        emit ArbExecuted(_op(), tokenIn, tokenOut, amountIn, profit, buyOn, sellOn);
    }

    /// @notice Burn LP tokens permanently (Maria's floor-building playbook).
    function burnLP(address pair, uint256 amount) external onlyAuth whenNotPaused {
        _safeTransfer(IERC20(pair), address(0x000000000000000000000000000000000000dEaD), amount);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T5: MULTI-STEP ROUTE EXECUTION
    //  All intermediate tokens stay in the contract between steps.
    //  Step.dex selects V1/V2/BEST per SWAP/ADD_LIQUIDITY step.
    // ═════════════════════════════════════════════════════════════════════

    function executeRoute(Step[] calldata steps)
        external onlyAuth whenNotPaused nonReentrant
    {
        uint256 len = steps.length;
        require(len > 0 && len <= maxBatch, "v8:step count");

        for (uint256 i; i < len; ++i) {
            Step calldata s = steps[i];

            if (s.action == StepType.TRANSFER_IN) {
                _safeTransferFrom(IERC20(s.tokenA), msg.sender, address(this), s.amount);

            } else if (s.action == StepType.TRANSFER_OUT) {
                _safeTransfer(IERC20(s.tokenA), msg.sender, s.amount);

            } else if (s.action == StepType.APPROVE) {
                _approve(IERC20(s.tokenA), s.target, s.amount);

            } else if (s.action == StepType.MINT) {
                _approve(IERC20(s.tokenA), s.target, s.amount);
                _doMint(s.target, s.amount);

            } else if (s.action == StepType.CLAIM) {
                _approve(IERC20(s.tokenA), s.target, s.amount);
                bool ok = _doClaim(s.target, s.tokenA, s.amount);
                require(ok, "v8:route claim failed");

            } else if (s.action == StepType.SWAP) {
                // Resolve BEST inline
                IPulseXRouter r;
                DEX resolvedDex = s.dex;
                if (s.dex == DEX.BEST) {
                    address[] memory p = new address[](2);
                    p[0] = s.tokenA; p[1] = s.tokenB;
                    uint256 v1O; uint256 v2O;
                    if (address(routerV1) != address(0)) {
                        try routerV1.getAmountsOut(s.amount, p) returns (uint256[] memory a) { v1O = a[1]; } catch {}
                    }
                    if (address(routerV2) != address(0)) {
                        try routerV2.getAmountsOut(s.amount, p) returns (uint256[] memory a) { v2O = a[1]; } catch {}
                    }
                    r = v1O >= v2O ? routerV1 : routerV2;
                    resolvedDex = v1O >= v2O ? DEX.V1 : DEX.V2;
                } else {
                    r = _getRouter(s.dex);
                }
                _approve(IERC20(s.tokenA), address(r), s.amount);
                address[] memory path = new address[](2);
                path[0] = s.tokenA; path[1] = s.tokenB;
                r.swapExactTokensForTokens(s.amount, s.amountB, path, address(this), block.timestamp);

            } else if (s.action == StepType.SWAP_MULTI) {
                // 3-hop: tokenA → target → tokenB
                IPulseXRouter r = _getRouter(s.dex == DEX.BEST ? DEX.V2 : s.dex);
                _approve(IERC20(s.tokenA), address(r), s.amount);
                address[] memory path = new address[](3);
                path[0] = s.tokenA; path[1] = s.target; path[2] = s.tokenB;
                r.swapExactTokensForTokens(s.amount, s.amountB, path, address(this), block.timestamp);

            } else if (s.action == StepType.ADD_LIQUIDITY) {
                IPulseXRouter r = _getRouter(s.dex == DEX.BEST ? DEX.V2 : s.dex);
                _approve(IERC20(s.tokenA), address(r), s.amount);
                _approve(IERC20(s.tokenB), address(r), s.amountB);
                uint256 minA = s.amount  * (10000 - s.slipBps) / 10000;
                uint256 minB = s.amountB * (10000 - s.slipBps) / 10000;
                r.addLiquidity(
                    s.tokenA, s.tokenB, s.amount, s.amountB,
                    minA, minB, msg.sender, block.timestamp
                );

            } else if (s.action == StepType.WRAP_PLS) {
                require(address(wpls) != address(0), "v8:wpls not set");
                require(address(this).balance >= s.amount, "v8:low native");
                wpls.deposit{value: s.amount}();

            } else if (s.action == StepType.UNWRAP_WPLS) {
                require(address(wpls) != address(0), "v8:wpls not set");
                wpls.withdraw(s.amount);

            } else {
                revert("v8:unknown step");
            }
        }

        emit RouteExecuted(_op(), len);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T6: TOPOLOGY & AGENT VIEWS
    // ═════════════════════════════════════════════════════════════════════

    function walkParents(address token, uint256 maxDepth)
        external view returns (address[] memory)
    {
        address[] memory buf = new address[](maxDepth);
        address cur = token;
        uint256 d;
        while (d < maxDepth) {
            buf[d++] = cur;
            address p = _parent(cur);
            if (p == address(0) || p == cur) break;
            cur = p;
        }
        address[] memory out = new address[](d);
        for (uint256 i; i < d; ++i) out[i] = buf[i];
        return out;
    }

    function getChildren(address parent_) external view returns (address[] memory) { return _children[parent_]; }
    function getPairs(address token)      external view returns (address[] memory) { return _pairs[token]; }

    function registerPair(address a, address b) external onlyAuth whenNotPaused {
        _pairs[a].push(b);
        _pairs[b].push(a);
        emit PairRegistered(a, b);
    }

    function checkDebenture(address token) external view returns (bool) {
        try ITreasuryToken(token).Debenture() returns (bool d) { return d; } catch { return false; }
    }

    function getMintingKey(address token) external view returns (uint64) {
        try ITreasuryToken(token)._mintingKey() returns (uint64 k) { return k; } catch { return 0; }
    }

    /// @notice Get reserves for a pair on a specific DEX.
    function getReserves(address tokenA, address tokenB, DEX dex)
        external view returns (uint256 rA, uint256 rB)
    {
        IPulseXFactory f = _getFactory(dex);
        if (address(f) == address(0)) return (0, 0);
        address pair = f.getPair(tokenA, tokenB);
        if (pair == address(0)) return (0, 0);
        IUniswapV2Pair p = IUniswapV2Pair(pair);
        (uint112 r0, uint112 r1,) = p.getReserves();
        if (p.token0() == tokenA) return (uint256(r0), uint256(r1));
        else return (uint256(r1), uint256(r0));
    }

    /// @notice Get reserves from BOTH V1 and V2 in one call.
    ///         Useful for spread detection before atomicArb.
    function getReservesBoth(address tokenA, address tokenB)
        external view
        returns (uint256 v1rA, uint256 v1rB, uint256 v2rA, uint256 v2rB)
    {
        if (address(factoryV1) != address(0)) {
            address pair1 = factoryV1.getPair(tokenA, tokenB);
            if (pair1 != address(0)) {
                IUniswapV2Pair p = IUniswapV2Pair(pair1);
                (uint112 r0, uint112 r1,) = p.getReserves();
                if (p.token0() == tokenA) { v1rA = uint256(r0); v1rB = uint256(r1); }
                else                      { v1rA = uint256(r1); v1rB = uint256(r0); }
            }
        }
        if (address(factoryV2) != address(0)) {
            address pair2 = factoryV2.getPair(tokenA, tokenB);
            if (pair2 != address(0)) {
                IUniswapV2Pair p = IUniswapV2Pair(pair2);
                (uint112 r0, uint112 r1,) = p.getReserves();
                if (p.token0() == tokenA) { v2rA = uint256(r0); v2rB = uint256(r1); }
                else                      { v2rA = uint256(r1); v2rB = uint256(r0); }
            }
        }
    }

    function getAmountsOut(uint256 amountIn, address[] calldata path, DEX dex)
        external view returns (uint256[] memory)
    {
        return _getRouter(dex == DEX.BEST ? DEX.V2 : dex).getAmountsOut(amountIn, path);
    }
    // ── Registry views ────────────────────────────────────────────────────
    function registryLen()   external view returns (uint256)          { return registry.length; }
    function getFullRegistry() external view returns (address[] memory) { return registry; }

    function registrySlice(uint256 start, uint256 count)
        external view returns (address[] memory)
    {
        uint256 end = start + count;
        if (end > registry.length) end = registry.length;
        if (start >= registry.length) return new address[](0);
        address[] memory out = new address[](end - start);
        for (uint256 i = start; i < end; ++i) out[i - start] = registry[i];
        return out;
    }


    // ═════════════════════════════════════════════════════════════════════
    //  INTERNALS
    // ═════════════════════════════════════════════════════════════════════

    function _parent(address token) internal view returns (address) {
        if (tokenMeta[token].token != address(0)) return tokenMeta[token].parent;
        try ITreasuryToken(token).Parent() returns (address p) { return p; } catch { return address(0); }
    }

    function _doMint(address token, uint256 amount) internal {
        (bool ok, bytes memory ret) = token.call(abi.encodeWithSignature("mint(uint256)", amount));
        if (!ok) {
            if (ret.length > 0) { assembly { revert(add(ret, 32), mload(ret)) } }
            revert("v8:mint failed");
        }
    }

    function _doClaim(address token, address spend, uint256 amount) internal returns (bool) {
        (bool ok1,) = token.call(abi.encodeWithSignature("Claim(address,uint256)", spend, amount));
        if (ok1) return true;
        (bool ok2,) = token.call(abi.encodeWithSignature("Claim(uint256)", amount));
        if (ok2) return true;
        (bool ok3,) = token.call(abi.encodeWithSignature("claim(address,uint256)", spend, amount));
        return ok3;
    }

    function _register(address token, address parent, uint256 initial, uint8 ver) internal {
        tokenMeta[token] = TokenMeta(token, parent, initial, block.timestamp, ver, false);
        registry.push(token);
        _children[parent].push(token);
        emit TokenCreated(_op(), token, parent, initial, ver);
    }

    function _op() internal returns (uint256) { return ++opNonce; }

    receive() external payable {}
    fallback() external payable {}
}
