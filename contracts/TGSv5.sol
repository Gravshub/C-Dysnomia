// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/security/Pausable.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

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
contract TGSv5 is Ownable, ReentrancyGuard, Pausable {
    using SafeERC20 for IERC20;

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

    error NotAuthorized();
    error TransferFailed();
    error RHOCallFailed(uint256 index);
    error ZeroCount();
    error CountTooHigh(uint256 max);

    // ─── Modifiers ───────────────────────────────────────────────────────────

    modifier onlyAuthorized() {
        if (!authorized[msg.sender] && msg.sender != owner()) revert NotAuthorized();
        _;
    }

    // ─── Constructor ─────────────────────────────────────────────────────────

    constructor() {
        // Deployer (Gravitized) is owner via Ownable(); also authorized as initial operator.
        authorized[msg.sender] = true;
    }

    // =========================================================================
    // TIER 1 — SAFETY
    // =========================================================================

    /// @notice Pause all state-changing functions. Owner only.
    function pause() external onlyOwner {
        _pause();
    }

    /// @notice Resume normal operation. Owner only.
    function unpause() external onlyOwner {
        _unpause();
    }

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
        IERC20(token).safeTransfer(to, amount);
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
     *         Destination wallet depends on WM contract implementation (tx.origin or msg.sender).
     *         Emits WMMinted with actual gas consumed so the Python agent can update estimates.
     * @param  count  Number of times to call RHO — must be in [1, MAX_MINT_COUNT].
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
