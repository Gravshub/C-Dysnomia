// SPDX-License-Identifier: MIT
pragma solidity ^0.8.21;

/*
 * ╔═══════════════════════════════════════════════════════════════════════╗
 * ║              TREASURY GAME SHARK V8+ (TGSv8PLUS)                     ║
 * ║       Companion Contract · Mint→Harvest→LP→Burn Pipeline             ║
 * ╠═══════════════════════════════════════════════════════════════════════╣
 * ║  TGSv8+ extends TGSv8 with:                                          ║
 * ║  · T1: Silent LAU minting (no Chat, no VOID spam)                    ║
 * ║  · T2: Atomic harvestCycle (mint→sell→LP→burn in one TX)              ║
 * ║  · T3: Batch LP burns (maria-style) + percent burns                  ║
 * ║  · T4: removeLiquidity (pull LP positions)                            ║
 * ║  · T5: Sell functions (single-hop + multi-hop spread)                 ║
 * ║  · T6: Generic execute (arbitrary calls for future mechanics)         ║
 * ║  · T7: Deposits, withdrawals, sweeps                                  ║
 * ║                                                                       ║
 * ║  Generic — works with ANY LAU token. Constructor-configured.          ║
 * ║  Burn address: 0x0000000000000000000000000000000000000369              ║
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

interface ILAU {
    function Purchase(address token, uint256 amount) external;
    function mintToCap() external;
    function Chat(string calldata text) external;
    function totalSupply() external view returns (uint256);
    function maxSupply() external view returns (uint256);
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

    function removeLiquidity(
        address tokenA, address tokenB,
        uint256 liquidity, uint256 amountAMin, uint256 amountBMin,
        address to, uint256 deadline
    ) external returns (uint256 amountA, uint256 amountB);

    function getAmountsOut(uint256 amountIn, address[] calldata path)
        external view returns (uint256[] memory amounts);
}

interface IPulseXFactory {
    function getPair(address tokenA, address tokenB) external view returns (address pair);
}


// ═════════════════════════════════════════════════════════════════════════
//  MAIN CONTRACT
// ═════════════════════════════════════════════════════════════════════════

contract TreasuryGameSharkv8PLUS {

    // ── Inlined: Ownable ─────────────────────────────────────────────────
    address public immutable owner;
    modifier onlyOwner() { require(msg.sender == owner, "v8+:not owner"); _; }

    // ── Inlined: Auth ────────────────────────────────────────────────────
    mapping(address => bool) public authorized;
    modifier onlyAuth() {
        require(msg.sender == owner || authorized[msg.sender], "v8+:unauthorized");
        _;
    }

    // ── Inlined: ReentrancyGuard ─────────────────────────────────────────
    uint256 private _lock = 1;
    modifier nonReentrant() {
        require(_lock == 1, "v8+:reentrant");
        _lock = 2;
        _;
        _lock = 1;
    }

    // ── Burn address ─────────────────────────────────────────────────────
    address constant DEAD = 0x0000000000000000000000000000000000000369;

    // ── External refs ────────────────────────────────────────────────────
    address public lau;
    address public payToken;
    address public wpls;
    address public routerV1;
    address public routerV2;
    address public factoryV1;
    address public factoryV2;

    // ── Stats ────────────────────────────────────────────────────────────
    uint256 public totalLauMinted;
    uint256 public totalPayTokenSpent;
    uint256 public totalLpBurned;
    uint256 public opCounter;

    // ── Events ───────────────────────────────────────────────────────────
    event SilentMint(uint256 indexed op, uint256 count, uint256 lauReceived, uint256 payTokenSpent);
    event HarvestCycle(uint256 indexed op, uint256 lauMinted, uint256 lauSold, uint256 plsReceived, uint256 lauToLP, uint256 lpReceived, uint256 lpBurned);
    event LPBurned(uint256 indexed op, address indexed pair, uint256 amount);
    event LPRemoved(uint256 indexed op, address indexed pair, uint256 liquidity, uint256 amountA, uint256 amountB);
    event Sold(uint256 indexed op, address indexed tokenOut, uint256 amountIn, uint256 amountOut, uint8 dex);
    event Executed(uint256 indexed op, address indexed target, bool success);
    event AuthSet(address indexed who, bool enabled);
    event RefUpdated(string ref, address indexed addr);
    event Deposited(address indexed token, uint256 amount);
    event Withdrawn(address indexed token, uint256 amount);

    // ── Constructor ──────────────────────────────────────────────────────
    constructor(
        address _lau,
        address _payToken,
        address _wpls,
        address _routerV1,
        address _routerV2,
        address _factoryV1,
        address _factoryV2
    ) {
        owner = msg.sender;
        authorized[msg.sender] = true;

        lau       = _lau;
        payToken  = _payToken;
        wpls      = _wpls;
        routerV1  = _routerV1;
        routerV2  = _routerV2;
        factoryV1 = _factoryV1;
        factoryV2 = _factoryV2;

        // Pre-approve LAU to spend payToken (for Purchase)
        IERC20(_payToken).approve(_lau, type(uint256).max);
        // Pre-approve both routers for LAU
        IERC20(_lau).approve(_routerV1, type(uint256).max);
        IERC20(_lau).approve(_routerV2, type(uint256).max);
        // Pre-approve both routers for WPLS
        IERC20(_wpls).approve(_routerV1, type(uint256).max);
        IERC20(_wpls).approve(_routerV2, type(uint256).max);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T1: SILENT LAU MINTING
    // ═════════════════════════════════════════════════════════════════════

    function silentMint(uint256 count) external onlyAuth nonReentrant {
        require(count > 0 && count <= 50, "v8+:count 1-50");
        uint256 lauBefore = IERC20(lau).balanceOf(address(this));
        uint256 payBefore = IERC20(payToken).balanceOf(address(this));

        for (uint256 i; i < count;) {
            ILAU(lau).Purchase(payToken, 1e18);
            unchecked { ++i; }
        }

        uint256 lauGained = IERC20(lau).balanceOf(address(this)) - lauBefore;
        uint256 paySpent = payBefore - IERC20(payToken).balanceOf(address(this));

        totalLauMinted += lauGained;
        totalPayTokenSpent += paySpent;

        emit SilentMint(_op(), count, lauGained, paySpent);
    }

    function safeMint(uint256 count) external onlyAuth nonReentrant {
        require(count > 0 && count <= 50, "v8+:count 1-50");
        uint256 lauBefore = IERC20(lau).balanceOf(address(this));
        uint256 payBefore = IERC20(payToken).balanceOf(address(this));

        for (uint256 i; i < count;) {
            // mintToCap primes 1 token into LAU's self-balance before Purchase
            try ILAU(lau).mintToCap() {} catch {}
            ILAU(lau).Purchase(payToken, 1e18);
            unchecked { ++i; }
        }

        uint256 lauGained = IERC20(lau).balanceOf(address(this)) - lauBefore;
        uint256 paySpent = payBefore - IERC20(payToken).balanceOf(address(this));

        totalLauMinted += lauGained;
        totalPayTokenSpent += paySpent;

        emit SilentMint(_op(), count, lauGained, paySpent);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T2: ATOMIC HARVEST CYCLE
    // ═════════════════════════════════════════════════════════════════════

    function harvestCycle(
        uint256 mintCount,
        uint256 sellBps,
        uint256 minPlsOut,
        uint256 burnBps,
        uint8 sellDex,
        uint8 lpDex
    ) external onlyAuth nonReentrant {
        require(mintCount > 0 && mintCount <= 50, "v8+:count 1-50");
        require(sellBps <= 10000, "v8+:sellBps 0-10000");
        require(burnBps <= 10000, "v8+:burnBps 0-10000");
        require(sellDex <= 1 && lpDex <= 1, "v8+:dex 0 or 1");

        // Step 1: Silent mint
        uint256 lauBefore = IERC20(lau).balanceOf(address(this));
        uint256 payBefore = IERC20(payToken).balanceOf(address(this));

        for (uint256 i; i < mintCount;) {
            ILAU(lau).Purchase(payToken, 1e18);
            unchecked { ++i; }
        }

        uint256 lauMinted = IERC20(lau).balanceOf(address(this)) - lauBefore;
        totalPayTokenSpent += (payBefore - IERC20(payToken).balanceOf(address(this)));
        totalLauMinted += lauMinted;

        // Step 2: Sell sellBps/10000 of minted LAU for WPLS
        uint256 lauToSell = (lauMinted * sellBps) / 10000;
        uint256 plsReceived;

        if (lauToSell > 0) {
            IPulseXRouter router = _router(sellDex);
            address[] memory path = new address[](2);
            path[0] = lau;
            path[1] = wpls;
            uint256[] memory amounts = router.swapExactTokensForTokens(
                lauToSell, minPlsOut, path, address(this), block.timestamp
            );
            plsReceived = amounts[amounts.length - 1];
        }

        // Step 3: addLiquidity with remaining LAU + received WPLS
        uint256 lauToLP = lauMinted - lauToSell;
        uint256 lpReceived;

        if (lauToLP > 0 && plsReceived > 0) {
            IPulseXRouter lpRouter = _router(lpDex);
            uint256 minLau = (lauToLP * 95) / 100;
            uint256 minWpls = (plsReceived * 95) / 100;

            (, , uint256 liq) = lpRouter.addLiquidity(
                lau, wpls,
                lauToLP, plsReceived,
                minLau, minWpls,
                address(this), block.timestamp
            );
            lpReceived = liq;
        }

        // Step 4: Burn burnBps/10000 of received LP tokens
        uint256 lpBurned;
        if (lpReceived > 0 && burnBps > 0) {
            address pair = IPulseXFactory(lpDex == 0 ? factoryV1 : factoryV2).getPair(lau, wpls);
            lpBurned = (lpReceived * burnBps) / 10000;
            if (lpBurned > 0) {
                IERC20(pair).transfer(DEAD, lpBurned);
                totalLpBurned += lpBurned;
            }
        }

        // Step 5: Sweep remaining LP + leftover tokens to owner
        _sweepToken(lau);
        _sweepToken(wpls);
        if (lpReceived > lpBurned) {
            address pair = IPulseXFactory(lpDex == 0 ? factoryV1 : factoryV2).getPair(lau, wpls);
            _sweepToken(pair);
        }

        emit HarvestCycle(_op(), lauMinted, lauToSell, plsReceived, lauToLP, lpReceived, lpBurned);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T3: BATCH LP BURNS (MARIA STYLE)
    // ═════════════════════════════════════════════════════════════════════

    function batchBurnLP(address[] calldata pairs, uint256[] calldata amounts) external onlyAuth nonReentrant {
        uint256 len = pairs.length;
        require(len == amounts.length, "v8+:mismatch");
        require(len <= 20, "v8+:max 20");

        for (uint256 i; i < len;) {
            IERC20(pairs[i]).transferFrom(msg.sender, DEAD, amounts[i]);
            totalLpBurned += amounts[i];
            emit LPBurned(_op(), pairs[i], amounts[i]);
            unchecked { ++i; }
        }
    }

    function burnLPPercent(address pair, uint256 bps) external onlyAuth {
        require(bps > 0 && bps <= 10000, "v8+:bps 1-10000");
        uint256 bal = IERC20(pair).balanceOf(address(this));
        require(bal > 0, "v8+:no LP");
        uint256 burnAmt = (bal * bps) / 10000;
        require(burnAmt > 0, "v8+:zero burn");
        IERC20(pair).transfer(DEAD, burnAmt);
        totalLpBurned += burnAmt;
        emit LPBurned(_op(), pair, burnAmt);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T4: REMOVE LIQUIDITY
    // ═════════════════════════════════════════════════════════════════════

    function removeLiquidity(
        address tokenA,
        address tokenB,
        uint256 liquidity,
        uint256 minA,
        uint256 minB,
        uint8 dex
    ) external onlyAuth nonReentrant {
        require(dex <= 1, "v8+:dex 0 or 1");
        IPulseXRouter router = _router(dex);
        address pair = IPulseXFactory(dex == 0 ? factoryV1 : factoryV2).getPair(tokenA, tokenB);
        require(pair != address(0), "v8+:no pair");

        // Approve router to spend LP
        IERC20(pair).approve(address(router), liquidity);

        (uint256 amountA, uint256 amountB) = router.removeLiquidity(
            tokenA, tokenB, liquidity, minA, minB, owner, block.timestamp
        );

        emit LPRemoved(_op(), pair, liquidity, amountA, amountB);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T5: SELL FUNCTIONS
    // ═════════════════════════════════════════════════════════════════════

    function sellLau(uint256 amount, uint256 minOut, address tokenOut, uint8 dex) external onlyAuth nonReentrant {
        require(dex <= 1, "v8+:dex 0 or 1");
        IPulseXRouter router = _router(dex);
        address[] memory path = new address[](2);
        path[0] = lau;
        path[1] = tokenOut;

        // Ensure router approval
        if (IERC20(lau).allowance(address(this), address(router)) < amount) {
            IERC20(lau).approve(address(router), type(uint256).max);
        }

        uint256[] memory amounts = router.swapExactTokensForTokens(
            amount, minOut, path, address(this), block.timestamp
        );

        emit Sold(_op(), tokenOut, amount, amounts[amounts.length - 1], dex);
    }

    function sellLauMultiHop(uint256 amount, uint256 minOut, address[] calldata path, uint8 dex) external onlyAuth nonReentrant {
        require(dex <= 1, "v8+:dex 0 or 1");
        require(path.length >= 2, "v8+:path < 2");
        require(path[0] == lau, "v8+:path must start with lau");
        IPulseXRouter router = _router(dex);

        if (IERC20(lau).allowance(address(this), address(router)) < amount) {
            IERC20(lau).approve(address(router), type(uint256).max);
        }

        uint256[] memory amounts = router.swapExactTokensForTokens(
            amount, minOut, path, address(this), block.timestamp
        );

        emit Sold(_op(), path[path.length - 1], amount, amounts[amounts.length - 1], dex);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T6: GENERIC EXECUTE
    // ═════════════════════════════════════════════════════════════════════

    function execute(address target, bytes calldata data) external onlyOwner nonReentrant returns (bytes memory) {
        (bool ok, bytes memory result) = target.call(data);
        require(ok, "v8+:execute failed");
        emit Executed(_op(), target, ok);
        return result;
    }

    function executeWithValue(address target, bytes calldata data, uint256 value) external onlyOwner nonReentrant returns (bytes memory) {
        (bool ok, bytes memory result) = target.call{value: value}(data);
        require(ok, "v8+:execute failed");
        emit Executed(_op(), target, ok);
        return result;
    }

    function batchExecute(address[] calldata targets, bytes[] calldata datas) external onlyOwner nonReentrant returns (bytes[] memory results) {
        uint256 len = targets.length;
        require(len == datas.length, "v8+:mismatch");
        require(len <= 20, "v8+:max 20");
        results = new bytes[](len);
        for (uint256 i; i < len;) {
            (bool ok, bytes memory result) = targets[i].call(datas[i]);
            require(ok, "v8+:batch exec failed");
            results[i] = result;
            emit Executed(_op(), targets[i], ok);
            unchecked { ++i; }
        }
    }


    // ═════════════════════════════════════════════════════════════════════
    //  T7: DEPOSITS, WITHDRAWALS, SWEEPS
    // ═════════════════════════════════════════════════════════════════════

    function deposit(address token, uint256 amount) external onlyAuth {
        IERC20(token).transferFrom(msg.sender, address(this), amount);
        emit Deposited(token, amount);
    }

    function withdraw(address token) external onlyAuth {
        uint256 bal = IERC20(token).balanceOf(address(this));
        require(bal > 0, "v8+:zero bal");
        IERC20(token).transfer(owner, bal);
        emit Withdrawn(token, bal);
    }

    function withdrawAmount(address token, uint256 amount) external onlyAuth {
        IERC20(token).transfer(owner, amount);
        emit Withdrawn(token, amount);
    }

    function withdrawPLS() external onlyAuth {
        uint256 bal = address(this).balance;
        require(bal > 0, "v8+:no PLS");
        (bool ok,) = payable(owner).call{value: bal}("");
        require(ok, "v8+:send failed");
        emit Withdrawn(address(0), bal);
    }

    function batchSweep(address[] calldata tokens) external onlyAuth {
        for (uint256 i; i < tokens.length;) {
            _sweepToken(tokens[i]);
            unchecked { ++i; }
        }
    }


    // ═════════════════════════════════════════════════════════════════════
    //  ADMIN
    // ═════════════════════════════════════════════════════════════════════

    function setAuth(address wallet, bool status) external onlyOwner {
        authorized[wallet] = status;
        emit AuthSet(wallet, status);
    }

    function setRef(string calldata ref, address addr) external onlyOwner {
        bytes32 h = keccak256(bytes(ref));
        if (h == keccak256("lau")) {
            lau = addr;
            IERC20(payToken).approve(addr, type(uint256).max);
            IERC20(addr).approve(routerV1, type(uint256).max);
            IERC20(addr).approve(routerV2, type(uint256).max);
        } else if (h == keccak256("payToken")) {
            payToken = addr;
            IERC20(addr).approve(lau, type(uint256).max);
        } else if (h == keccak256("wpls")) {
            wpls = addr;
            IERC20(addr).approve(routerV1, type(uint256).max);
            IERC20(addr).approve(routerV2, type(uint256).max);
        } else if (h == keccak256("routerV1")) {
            routerV1 = addr;
            IERC20(lau).approve(addr, type(uint256).max);
            IERC20(wpls).approve(addr, type(uint256).max);
        } else if (h == keccak256("routerV2")) {
            routerV2 = addr;
            IERC20(lau).approve(addr, type(uint256).max);
            IERC20(wpls).approve(addr, type(uint256).max);
        } else if (h == keccak256("factoryV1")) {
            factoryV1 = addr;
        } else if (h == keccak256("factoryV2")) {
            factoryV2 = addr;
        } else {
            revert("v8+:unknown ref");
        }
        emit RefUpdated(ref, addr);
    }

    function approveMax(address token, address spender) external onlyAuth {
        IERC20(token).approve(spender, type(uint256).max);
    }


    // ═════════════════════════════════════════════════════════════════════
    //  VIEW HELPERS
    // ═════════════════════════════════════════════════════════════════════

    function mintableLAU() external view returns (uint256) {
        uint256 payBal = IERC20(payToken).balanceOf(address(this));
        uint256 remaining = _lauRemaining();
        uint256 fromPay = payBal / 1e18;
        return fromPay < remaining ? fromPay : remaining;
    }

    function lauRemaining() external view returns (uint256) {
        return _lauRemaining();
    }

    function batchBal(address[] calldata tokens) external view returns (uint256[] memory b) {
        b = new uint256[](tokens.length);
        for (uint256 i; i < tokens.length;) {
            b[i] = IERC20(tokens[i]).balanceOf(address(this));
            unchecked { ++i; }
        }
    }

    function quoteSell(uint256 lauAmount, uint8 dex) external view returns (uint256) {
        require(dex <= 1, "v8+:dex 0 or 1");
        IPulseXRouter router = _router(dex);
        address[] memory path = new address[](2);
        path[0] = lau;
        path[1] = wpls;
        uint256[] memory amounts = router.getAmountsOut(lauAmount, path);
        return amounts[amounts.length - 1];
    }


    // ═════════════════════════════════════════════════════════════════════
    //  INTERNALS
    // ═════════════════════════════════════════════════════════════════════

    function _router(uint8 dex) internal view returns (IPulseXRouter) {
        if (dex == 0) return IPulseXRouter(routerV1);
        return IPulseXRouter(routerV2);
    }

    function _lauRemaining() internal view returns (uint256) {
        uint256 max = ILAU(lau).maxSupply();
        uint256 total = ILAU(lau).totalSupply();
        return max > total ? max - total : 0;
    }

    function _sweepToken(address token) internal {
        uint256 bal = IERC20(token).balanceOf(address(this));
        if (bal > 0) {
            IERC20(token).transfer(owner, bal);
        }
    }

    function _op() internal returns (uint256) {
        return ++opCounter;
    }

    receive() external payable {}
    fallback() external payable {}
}
