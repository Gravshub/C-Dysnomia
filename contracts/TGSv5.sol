// SPDX-License-Identifier: MIT
// Token Generation Strategy v5 — on-chain WM batch minter for Atropa/Dysnomia
// Self-contained: no external imports. Ownable, ReentrancyGuard, Pausable inlined.
// Pattern: matches DysnomiaSelfSnipev4.sol (no OZ, pragma ^0.8.21, solc-deployable).
// Original logic from claude/implement-wm-minting-z6ldg:contracts/TGSv5.sol
pragma solidity ^0.8.21;

// ─── Minimal ERC20 interface ────────────────────────────────────────────────
interface IERC20 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
}

/**
 * @title  TGSv5
 * @notice Token Generation Strategy v5 — on-chain execution layer for Atropa/Dysnomia
 * @dev    Two-tier implementation:
 *           Tier 1 — Safety (pause, emergency withdraw, approval reset, balance views)
 *           Tier 2 — WM Minting (batch RHO() calls with gas event reporting)
 *
 * Trust Architecture
 * ──────────────────
 *   OWNER (Gravitized)          AUTHORIZED (Operator / Claude wallet)
 *   ─ pause / unpause           ─ mintWM()
 *   ─ emergencyWithdraw         ─ CANNOT pause, withdraw, or re-authorize
 *   ─ setAuthorized
 *   ─ safeApprove
 *
 * Repository: github.com/Gravshub/C-Dysnomia
 */
contract TGSv5 {

    // ─── Inlined: Ownable ───────────────────────────────────────────────────
    address private _owner;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);

    modifier onlyOwner() {
        if (msg.sender != _owner) revert NotOwner();
        _;
    }

    function owner() public view returns (address) {
        return _owner;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(_owner, newOwner);
        _owner = newOwner;
    }

    // ─── Inlined: ReentrancyGuard ───────────────────────────────────────────
    uint8 private _status;          // 1 = not entered, 2 = entered
    uint8 private constant _NOT_ENTERED = 1;
    uint8 private constant _ENTERED     = 2;

    modifier nonReentrant() {
        if (_status == _ENTERED) revert ReentrantCall();
        _status = _ENTERED;
        _;
        _status = _NOT_ENTERED;
    }

    // ─── Inlined: Pausable ──────────────────────────────────────────────────
    bool private _paused;

    event Paused(address account);
    event Unpaused(address account);

    modifier whenNotPaused() {
        if (_paused) revert ContractPaused();
        _;
    }

    function paused() public view returns (bool) {
        return _paused;
    }

    function pause() external onlyOwner {
        _paused = true;
        emit Paused(msg.sender);
    }

    function unpause() external onlyOwner {
        _paused = false;
        emit Unpaused(msg.sender);
    }

    // ─── Constants ───────────────────────────────────────────────────────────

    /// @notice WM (MV) token on PulseChain — 1:1 required to fund minter token supply
    address public constant WM_CONTRACT = 0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29;

    /// @notice Function selector for WM.RHO() — triggers _mintToCap, minting 1 WM per call
    bytes4 public constant RHO_SELECTOR = bytes4(uint32(0xa4566950));

    /// @notice Hard cap on single-call batch size to stay within block gas limits
    uint256 public constant MAX_MINT_COUNT = 100;

    // ─── State ───────────────────────────────────────────────────────────────

    /// @notice Authorized operator wallets (agent, scripts, etc.)
    mapping(address => bool) public authorized;

    // ─── Events ──────────────────────────────────────────────────────────────

    event WMMinted(address indexed caller, uint256 count, uint256 gasUsed);
    event AuthorizationChanged(address indexed account, bool status);
    event EmergencyWithdrawERC20(address indexed token, address indexed to, uint256 amount);
    event EmergencyWithdrawNative(address indexed to, uint256 amount);
    event ApprovalReset(address indexed token, address indexed spender);

    // ─── Errors ──────────────────────────────────────────────────────────────

    error NotOwner();
    error NotAuthorized();
    error TransferFailed();
    error RHOCallFailed(uint256 index);
    error ZeroCount();
    error CountTooHigh(uint256 max);
    error ZeroAddress();
    error ReentrantCall();
    error ContractPaused();

    // ─── Modifiers ───────────────────────────────────────────────────────────

    modifier onlyAuthorized() {
        if (!authorized[msg.sender] && msg.sender != _owner) revert NotAuthorized();
        _;
    }

    // ─── Constructor ─────────────────────────────────────────────────────────

    constructor() {
        _owner = msg.sender;
        authorized[msg.sender] = true;
        _status = _NOT_ENTERED;
        _paused = false;
    }

    // =========================================================================
    // TIER 1 — SAFETY
    // =========================================================================

    /// @notice Grant or revoke operator authorization. Owner only.
    function setAuthorized(address account, bool status) external onlyOwner {
        authorized[account] = status;
        emit AuthorizationChanged(account, status);
    }

    /// @notice Emergency ERC20 withdrawal from this contract. Owner only.
    function emergencyWithdrawERC20(
        address token,
        address to,
        uint256 amount
    ) external onlyOwner {
        bool ok = IERC20(token).transfer(to, amount);
        if (!ok) revert TransferFailed();
        emit EmergencyWithdrawERC20(token, to, amount);
    }

    /// @notice Emergency native PLS withdrawal. Owner only.
    function emergencyWithdrawNative(address payable to, uint256 amount) external onlyOwner {
        (bool success, ) = to.call{value: amount}("");
        if (!success) revert TransferFailed();
        emit EmergencyWithdrawNative(to, amount);
    }

    /// @notice Zero-then-set approval (prevents ERC20 approval front-running). Owner only.
    function safeApprove(
        address token,
        address spender,
        uint256 amount
    ) external onlyOwner {
        IERC20(token).approve(spender, 0);
        IERC20(token).approve(spender, amount);
        emit ApprovalReset(token, spender);
    }

    /// @notice This contract's balance of any ERC20.
    function balanceOfToken(address token) external view returns (uint256) {
        return IERC20(token).balanceOf(address(this));
    }

    /// @notice Convenience: this contract's WM balance.
    function wmBalance() external view returns (uint256) {
        return IERC20(WM_CONTRACT).balanceOf(address(this));
    }

    // =========================================================================
    // TIER 2 — SMART MINTING: WM (MV)
    // =========================================================================

    /**
     * @notice Batch-mint WM tokens by repeatedly calling RHO() on the WM contract.
     * @dev    Each RHO() call triggers _mintToCap() on WM, minting 1 WM per call.
     *         WM goes to tx.origin (Joey's EOA) per WM contract implementation.
     *         Emits WMMinted with actual gas consumed so the Python agent can calibrate.
     * @param  count  Number of RHO() calls — must be in [1, MAX_MINT_COUNT].
     */
    function mintWM(uint256 count)
        external
        nonReentrant
        whenNotPaused
        onlyAuthorized
    {
        if (count == 0) revert ZeroCount();
        if (count > MAX_MINT_COUNT) revert CountTooHigh(MAX_MINT_COUNT);

        uint256 gasBefore = gasleft();

        for (uint256 i = 0; i < count; ) {
            (bool success, ) = WM_CONTRACT.call(abi.encodeWithSelector(RHO_SELECTOR));
            if (!success) revert RHOCallFailed(i);
            unchecked { ++i; }
        }

        emit WMMinted(msg.sender, count, gasBefore - gasleft());
    }

    // ─── Receive ─────────────────────────────────────────────────────────────

    receive() external payable {}
    fallback() external payable {}
}
