// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title Escrow
/// @notice Secure escrow contract for agent-to-agent commerce with arbiter dispute resolution.
/// @dev Supports ERC-20 payments. Funds are locked until release, refund, or arbiter resolution.
///      Each escrow is identified by an incrementing ID.
contract Escrow {
    using SafeERC20 for IERC20;

    // ──────────────────────────── Structs ────────────────────────────

    struct EscrowInfo {
        address payer;
        address payee;
        uint256 amount;
        IERC20 token;
        bool released;
        bool refunded;
        bool disputed;
        address arbiter;
    }

    // ──────────────────────────── State ────────────────────────────

    uint256 public nextEscrowId;
    mapping(uint256 => EscrowInfo) internal _escrows;

    /// @dev arbiter address — can resolve disputes.
    address public owner;

    // ──────────────────────────── Errors ────────────────────────────

    error NotAuthorized();
    error NotPayer();
    error NotPayerOrArbiter();
    error EscrowAlreadyFinalized();
    error NotDisputed();
    error TransferFailed();
    error ZeroAmount();
    error InvalidPayee();

    // ──────────────────────────── Events ────────────────────────────

    event EscrowCreated(uint256 indexed escrowId, address indexed payer, address indexed payee, uint256 amount, address token);
    event EscrowReleased(uint256 indexed escrowId, address payee, uint256 amount);
    event EscrowRefunded(uint256 indexed escrowId, address payer, uint256 amount);
    event EscrowDisputed(uint256 indexed escrowId, address by);

    // ──────────────────────────── Modifiers ────────────────────────────

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotAuthorized();
        _;
    }

    // ──────────────────────────── Constructor ────────────────────────────

    /// @param arbiter_ The address that resolves disputes. Typically the deployer or a DAO.
    constructor(address arbiter_) {
        owner = arbiter_;
    }

    // ──────────────────────────── Core Functions ────────────────────────────

    /// @notice Create a new escrow. Caller is the payer; funds are transferred in immediately.
    /// @param payee_ Recipient who will receive funds on release.
    /// @param token_ ERC-20 token address (USDC, USDT, etc.).
    /// @param amount_ Amount of tokens to escrow.
    /// @return escrowId The newly created escrow identifier.
    function createEscrow(
        address payee_,
        IERC20 token_,
        uint256 amount_
    ) external returns (uint256 escrowId) {
        if (payee_ == address(0)) revert InvalidPayee();
        if (amount_ == 0) revert ZeroAmount();

        escrowId = nextEscrowId++;

        _escrows[escrowId] = EscrowInfo({
            payer: msg.sender,
            payee: payee_,
            amount: amount_,
            token: token_,
            released: false,
            refunded: false,
            disputed: false,
            arbiter: owner
        });

        // Pull tokens from payer into this contract
        bool ok = token_.safeTransferFrom(msg.sender, address(this), amount_);
        if (!ok) revert TransferFailed();

        emit EscrowCreated(escrowId, msg.sender, payee_, amount_, address(token_));
    }

    /// @notice Release escrowed funds to the payee. Callable by payer or arbiter.
    /// @param escrowId Escrow to release.
    function release(uint256 escrowId) external {
        EscrowInfo storage e = _escrows[escrowId];
        if (e.payer == address(0)) revert NotAuthorized();
        if (e.released || e.refunded) revert EscrowAlreadyFinalized();
        if (msg.sender != e.payer && msg.sender != e.arbiter) revert NotPayerOrArbiter();

        e.released = true;
        bool ok = e.token.safeTransfer(e.payee, e.amount);
        if (!ok) revert TransferFailed();

        emit EscrowReleased(escrowId, e.payee, e.amount);
    }

    /// @notice Refund escrowed funds to the payer. Callable only by the payer.
    /// @dev Cannot be called after a dispute — only arbiter resolution allowed.
    /// @param escrowId Escrow to refund.
    function refund(uint256 escrowId) external {
        EscrowInfo storage e = _escrows[escrowId];
        if (e.payer == address(0)) revert NotAuthorized();
        if (e.released || e.refunded) revert EscrowAlreadyFinalized();
        if (e.disputed) revert NotAuthorized(); // disputed escrows need arbiter
        if (msg.sender != e.payer) revert NotPayer();

        e.refunded = true;
        bool ok = e.token.safeTransfer(e.payer, e.amount);
        if (!ok) revert TransferFailed();

        emit EscrowRefunded(escrowId, e.payer, e.amount);
    }

    /// @notice Dispute an escrow. Callable by payer or payee.
    /// @dev Freezes the escrow so only the arbiter can resolve it.
    /// @param escrowId Escrow to dispute.
    function dispute(uint256 escrowId) external {
        EscrowInfo storage e = _escrows[escrowId];
        if (e.payer == address(0)) revert NotAuthorized();
        if (e.released || e.refunded) revert EscrowAlreadyFinalized();
        if (msg.sender != e.payer && msg.sender != e.payee) revert NotPayerOrArbiter();

        e.disputed = true;
        emit EscrowDisputed(escrowId, msg.sender);
    }

    /// @notice Resolve a disputed escrow — arbiter decides: release to payee or refund to payer.
    /// @param escrowId Disputed escrow to resolve.
    /// @param releaseToPayee True = release to payee, false = refund to payer.
    function resolve(uint256 escrowId, bool releaseToPayee)
        external
        onlyOwner
    {
        EscrowInfo storage e = _escrows[escrowId];
        if (e.payer == address(0)) revert NotAuthorized();
        if (!e.disputed) revert NotDisputed();
        if (e.released || e.refunded) revert EscrowAlreadyFinalized();

        if (releaseToPayee) {
            e.released = true;
            bool ok = e.token.safeTransfer(e.payee, e.amount);
            if (!ok) revert TransferFailed();
            emit EscrowReleased(escrowId, e.payee, e.amount);
        } else {
            e.refunded = true;
            bool ok = e.token.safeTransfer(e.payer, e.amount);
            if (!ok) revert TransferFailed();
            emit EscrowRefunded(escrowId, e.payer, e.amount);
        }
    }

    // ──────────────────────────── Views ────────────────────────────

    /// @notice Get escrow details.
    /// @param escrowId Escrow to query.
    /// @return payer Payer address.
    /// @return payee Payee address.
    /// @return amount Escrowed amount.
    /// @return token Token address.
    /// @return released Whether funds were released.
    /// @return refunded Whether funds were refunded.
    /// @return disputed Whether under dispute.
    /// @return arbiter Arbiter address.
    function getEscrow(uint256 escrowId) external view returns (
        address payer,
        address payee,
        uint256 amount,
        IERC20 token,
        bool released,
        bool refunded,
        bool disputed,
        address arbiter
    ) {
        EscrowInfo storage e = _escrows[escrowId];
        return (e.payer, e.payee, e.amount, e.token, e.released, e.refunded, e.disputed, e.arbiter);
    }

    /// @notice Check if an escrow has been finalized (released or refunded).
    function isFinalized(uint256 escrowId) external view returns (bool) {
        EscrowInfo storage e = _escrows[escrowId];
        return e.released || e.refunded;
    }
}
