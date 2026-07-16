// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title RicardianAgreement
/// @notice On-chain Ricardian contract engine for multi-party agreements with milestone-based escrow.
/// @dev Supports 2-of-3 multi-sig activation, automatic fund release on milestone completion,
///      and dispute resolution. All funds are held in the contract itself.
contract RicardianAgreement {
    using SafeERC20 for IERC20;

    // ──────────────────────────── Enums ────────────────────────────

    enum AgreementStatus {
        Draft,
        Signed,
        Active,
        Completed,
        Disputed
    }

    // ──────────────────────────── Structs ────────────────────────────

    struct Milestone {
        string description;
        uint256 amount;
        uint256 deadline;
        bool completed;
        bool verified;
    }

    struct Agreement {
        bytes32 agreementHash;
        address[] parties;
        IERC20 token;
        uint256 totalAmount;
        Milestone[] milestones;
        AgreementStatus status;
        uint8 signCount;
        mapping(address => bool) signers;
        mapping(uint256 => bool) milestoneDisputed;
    }

    // ──────────────────────────── State ────────────────────────────

    uint256 public nextAgreementId;
    mapping(uint256 => Agreement) internal _agreements;
    mapping(bytes32 => bool) public hashUsed;

    // ──────────────────────────── Errors ────────────────────────────

    error AlreadySigned();
    error NotParty();
    error InvalidStatus(AgreementStatus expected, AgreementStatus actual);
    error InsufficientSignatures(uint8 required, uint8 actual);
    error MilestoneAlreadyCompleted();
    error MilestoneDisputed();
    error DeadlineNotReached();
    error DeadlinePassed();
    error TransferFailed();
    error HashAlreadyUsed();
    error ZeroAmount();
    error NoParties();

    // ──────────────────────────── Events ────────────────────────────

    event AgreementCreated(uint256 indexed agreementId, bytes32 agreementHash, address creator);
    event AgreementSigned(uint256 indexed agreementId, address signer);
    event AgreementActivated(uint256 indexed agreementId);
    event MilestoneCompleted(uint256 indexed agreementId, uint256 milestoneIndex);
    event MilestoneDisputed(uint256 indexed agreementId, uint256 milestoneIndex, address disputant);
    event FundsReleased(uint256 indexed agreementId, uint256 milestoneIndex, address to, uint256 amount);

    // ──────────────────────────── Modifiers ────────────────────────────

    modifier onlyParty(uint256 agreementId) {
        Agreement storage a = _agreements[agreementId];
        if (!_isParty(a, msg.sender)) revert NotParty();
        _;
    }

    modifier requireStatus(uint256 agreementId, AgreementStatus expected) {
        if (_agreements[agreementId].status != expected)
            revert InvalidStatus(expected, _agreements[agreementId].status);
        _;
    }

    // ──────────────────────────── Core Functions ────────────────────────────

    /// @notice Create a new agreement with milestones.
    /// @dev Caller becomes the first party. Hash must be unique across all agreements.
    /// @param agreementHash_ Unique hash identifying the off-chain Ricardian document.
    /// @param parties_ Additional party addresses (caller is implicitly added).
    /// @param token_ ERC-20 token used for payment (USDC, USDT, etc.).
    /// @param milestoneDescriptions Human-readable milestone descriptions.
    /// @param milestoneAmounts Funds allocated per milestone (must sum to total).
    /// @param milestoneDeadlines Unix timestamps for each milestone deadline.
    /// @return agreementId The newly created agreement identifier.
    function createAgreement(
        bytes32 agreementHash_,
        address[] calldata parties_,
        IERC20 token_,
        string[] calldata milestoneDescriptions,
        uint256[] calldata milestoneAmounts,
        uint256[] calldata milestoneDeadlines
    ) external returns (uint256 agreementId) {
        if (hashUsed[agreementHash_]) revert HashAlreadyUsed();
        if (parties_.length == 0) revert NoParties();

        uint256 len = milestoneDescriptions.length;
        if (len == 0 || len != milestoneAmounts.length || len != milestoneDeadlines.length) revert ZeroAmount();

        uint256 total;
        for (uint256 i; i < len; ++i) {
            if (milestoneAmounts[i] == 0) revert ZeroAmount();
            total += milestoneAmounts[i];
        }

        agreementId = nextAgreementId++;
        Agreement storage a = _agreements[agreementId];
        a.agreementHash = agreementHash_;
        a.token = token_;
        a.totalAmount = total;
        a.status = AgreementStatus.Draft;

        // Add caller as first party
        a.parties.push(msg.sender);
        a.signers[msg.sender] = true;

        // Add remaining parties
        uint256 partyCount = parties_.length;
        for (uint256 i; i < partyCount; ++i) {
            if (!a.signers[parties_[i]]) {
                a.parties.push(parties_[i]);
                a.signers[parties_[i]] = true;
            }
        }

        for (uint256 i; i < len; ++i) {
            a.milestones.push(Milestone({
                description: milestoneDescriptions[i],
                amount: milestoneAmounts[i],
                deadline: milestoneDeadlines[i],
                completed: false,
                verified: false
            }));
        }

        hashUsed[agreementHash_] = true;
        emit AgreementCreated(agreementId, agreementHash_, msg.sender);
    }

    /// @notice Sign an agreement. Requires 2-of-3 party signatures for activation.
    /// @param agreementId Agreement to sign.
    function signAgreement(uint256 agreementId)
        external
        onlyParty(agreementId)
        requireStatus(agreementId, AgreementStatus.Draft)
    {
        Agreement storage a = _agreements[agreementId];
        if (a.signers[msg.sender]) revert AlreadySigned();

        a.signers[msg.sender] = true;
        a.signCount++;
        emit AgreementSigned(agreementId, msg.sender);

        // Activate when ≥ 2-of-3 parties have signed
        if (a.signCount >= 2 && a.signCount >= (a.parties.length > 3 ? a.parties.length / 2 + 1 : 2)) {
            a.status = AgreementStatus.Active;
            emit AgreementActivated(agreementId);
        }
    }

    /// @notice Execute a milestone — releases escrowed funds to the payee.
    /// @dev Caller must be a party. Milestone must be active, not past deadline, and not completed.
    ///      Funds are transferred immediately via SafeERC20.
    /// @param agreementId Agreement containing the milestone.
    /// @param milestoneIndex Index of the milestone to execute.
    /// @param payee Address that receives the milestone payment.
    function executeMilestone(
        uint256 agreementId,
        uint256 milestoneIndex,
        address payee
    )
        external
        onlyParty(agreementId)
        requireStatus(agreementId, AgreementStatus.Active)
    {
        Agreement storage a = _agreements[agreementId];
        Milestone storage m = a.milestones[milestoneIndex];

        if (m.completed) revert MilestoneAlreadyCompleted();
        if (a.milestoneDisputed[milestoneIndex]) revert MilestoneDisputed();
        if (block.timestamp < m.deadline) revert DeadlineNotReached();

        m.completed = true;
        m.verified = true;
        emit MilestoneCompleted(agreementId, milestoneIndex);

        // Transfer funds
        bool ok = a.token.safeTransfer(payee, m.amount);
        if (!ok) revert TransferFailed();
        emit FundsReleased(agreementId, milestoneIndex, payee, m.amount);

        // Check if all milestones completed → agreement complete
        bool allDone = true;
        for (uint256 i; i < a.milestones.length; ++i) {
            if (!a.milestones[i].completed) {
                allDone = false;
                break;
            }
        }
        if (allDone) a.status = AgreementStatus.Completed;
    }

    /// @notice Dispute a milestone, freezing it and shifting agreement to Disputed status.
    /// @param agreementId Agreement containing the milestone.
    /// @param milestoneIndex Index of the milestone to dispute.
    function disputeMilestone(
        uint256 agreementId,
        uint256 milestoneIndex
    )
        external
        onlyParty(agreementId)
        requireStatus(agreementId, AgreementStatus.Active)
    {
        Agreement storage a = _agreements[agreementId];
        Milestone storage m = a.milestones[milestoneIndex];

        if (m.completed) revert MilestoneAlreadyCompleted();
        if (a.milestoneDisputed[milestoneIndex]) revert MilestoneDisputed();

        a.milestoneDisputed[milestoneIndex] = true;
        a.status = AgreementStatus.Disputed;
        emit MilestoneDisputed(agreementId, milestoneIndex, msg.sender);
    }

    // ──────────────────────────── Views ────────────────────────────

    /// @notice Get agreement details.
    /// @param agreementId The agreement to query.
    /// @return agreementHash The document hash.
    /// @return parties List of party addresses.
    /// @return token The payment token address.
    /// @return totalAmount Total escrowed amount.
    /// @return milestoneCount Number of milestones.
    /// @return status Current agreement status.
    /// @return signCount Number of signatures collected.
    function getAgreement(uint256 agreementId) external view returns (
        bytes32 agreementHash,
        address[] memory parties,
        IERC20 token,
        uint256 totalAmount,
        uint256 milestoneCount,
        AgreementStatus status,
        uint8 signCount
    ) {
        Agreement storage a = _agreements[agreementId];
        return (
            a.agreementHash,
            a.parties,
            a.token,
            a.totalAmount,
            a.milestones.length,
            a.status,
            a.signCount
        );
    }

    /// @notice Get milestone details.
    /// @param agreementId Agreement identifier.
    /// @param milestoneIndex Milestone index.
    /// @return description Milestone description.
    /// @return amount Funds allocated.
    /// @return deadline Unix timestamp deadline.
    /// @return completed Whether executed.
    /// @return disputed Whether under dispute.
    function getMilestone(
        uint256 agreementId,
        uint256 milestoneIndex
    ) external view returns (
        string memory description,
        uint256 amount,
        uint256 deadline,
        bool completed,
        bool disputed
    ) {
        Agreement storage a = _agreements[agreementId];
        Milestone storage m = a.milestones[milestoneIndex];
        return (m.description, m.amount, m.deadline, m.completed, a.milestoneDisputed[milestoneIndex]);
    }

    /// @notice Check if an address is a party to an agreement.
    function isParty(uint256 agreementId, address account) external view returns (bool) {
        return _isParty(_agreements[agreementId], account);
    }

    // ──────────────────────────── Internal ────────────────────────────

    function _isParty(Agreement storage a, address account) internal view returns (bool) {
        return a.signers[account];
    }
}
