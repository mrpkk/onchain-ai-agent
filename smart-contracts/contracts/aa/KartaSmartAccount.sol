// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title KartaSmartAccount
/// @notice ERC-4337-совместимый smart account (S5-06): owner + session keys (TTL/лимит/цель) + guardians-recovery.
/// @dev Локальный контур: EntryPoint — наш минимальный (bundler платные, решение владельца).
///      Валидация в validateUserOp: подпись owner ИЛИ активного session key с проверкой
///      allowedTarget / spendLimit / validUntil. Nonce — внутренний счётчик.
contract KartaSmartAccount {
    struct SessionKey {
        uint48 validUntil;      // unix; 0 = бессрочно
        uint96 spendLimitWei;   // лимит нативного value за всё время жизни ключа
        address allowedTarget;  // 0x0 = любая цель
        uint96 spentWei;
        bool active;
    }

    address public owner;
    address public immutable entryPoint;

    uint256 public nonce;
    mapping(address => SessionKey) public sessionKeys;

    // ── recovery ──
    address[] public guardians;
    mapping(address => bool) public isGuardian;
    address public pendingOwner;
    uint256 public recoveryReadyAt;      // 0 = нет активного восстановления
    uint256 public constant RECOVERY_DELAY = 2 days;
    uint256 public constant GUARDIAN_THRESHOLD = 2;
    uint256 public recoveryApprovals;

    error NotOwner();
    error NotEntryPoint();
    error NotGuardian();
    error BadSignature();
    error SessionKeyInvalid();
    error TargetNotAllowed();
    error SpendLimitExceeded();
    error RecoveryNotReady();
    error NoPendingRecovery();
    error GuardianExists();
    error GuardianNotFound();
    error AlreadyApproved();

    event Executed(address indexed target, uint256 value, bytes data);
    event SessionKeyAdded(address indexed key, uint48 validUntil, uint96 spendLimitWei, address allowedTarget);
    event SessionKeyRevoked(address indexed key);
    event GuardianAdded(address indexed guardian);
    event GuardianRemoved(address indexed guardian);
    event RecoveryStarted(address indexed newOwner, uint256 readyAt);
    event RecoveryApproved(address indexed guardian, uint256 approvals);
    event RecoveryFinalized(address indexed newOwner);
    event RecoveryCancelled();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(address owner_, address entryPoint_) {
        require(owner_ != address(0) && entryPoint_ != address(0), "zero addr");
        owner = owner_;
        entryPoint = entryPoint_;
    }

    // ── ERC-4337 ─────────────────────────────────────────────────
    /// @notice Валидация UserOperation. 0 = успех (наш локальный EntryPoint не использует prefund).
    function validateUserOp(
        address sender,
        bytes32 userOpHash,
        bytes calldata signature
    ) external view returns (uint256 validationData) {
        if (msg.sender != entryPoint) revert NotEntryPoint();
        if (sender != address(this)) revert BadSignature();
        if (_validSignature(userOpHash, signature)) return 0;
        return 1; // SIG_VALIDATION_FAILED
    }

    function _validSignature(bytes32 userOpHash, bytes calldata signature) internal view returns (bool) {
        if (signature.length < 65) return false;
        // Формат: [65B ECDSA][20B sessionKey?]
        bytes memory sig = signature[:65];
        (uint8 v, bytes32 r, bytes32 s) = _split(sig);
        address signer = ecrecover(userOpHash, v, r, s);
        if (signer == address(0)) return false;
        if (signer == owner) return true;

        SessionKey memory key = sessionKeys[signer];
        if (!key.active) return false;
        if (key.validUntil != 0 && block.timestamp > key.validUntil) return false;
        return true;
    }

    /// @notice Проверка лимитов session key ПЕРЕД исполнением (target/value).
    function _checkSessionLimits(address signer, address target, uint256 value) internal {
        if (signer == owner) return;
        SessionKey storage key = sessionKeys[signer];
        if (!key.active) revert SessionKeyInvalid();
        if (key.validUntil != 0 && block.timestamp > key.validUntil) revert SessionKeyInvalid();
        if (key.allowedTarget != address(0) && target != key.allowedTarget) revert TargetNotAllowed();
        if (value > 0) {
            if (uint256(key.spentWei) + value > key.spendLimitWei) revert SpendLimitExceeded();
            key.spentWei = uint96(uint256(key.spentWei) + value);
        }
    }

    /// @notice Исполнение UserOperation (вызывает EntryPoint). Подпись уже проверена.
    function executeFromEntryPoint(
        address target,
        uint256 value,
        bytes calldata data,
        address signer,
        uint256 opNonce
    ) external {
        if (msg.sender != entryPoint) revert NotEntryPoint();
        if (opNonce != nonce) revert BadSignature();
        nonce++;
        _checkSessionLimits(signer, target, value);
        (bool ok, bytes memory ret) = target.call{value: value}(data);
        require(ok, string(ret));
        emit Executed(target, value, data);
    }

    function getNonce() external view returns (uint256) {
        return nonce;
    }

    // ── session keys (owner) ─────────────────────────────────────
    function addSessionKey(address key, uint48 validUntil, uint96 spendLimitWei,
                           address allowedTarget) external onlyOwner {
        require(key != address(0), "zero key");
        sessionKeys[key] = SessionKey({
            validUntil: validUntil,
            spendLimitWei: spendLimitWei,
            allowedTarget: allowedTarget,
            spentWei: 0,
            active: true
        });
        emit SessionKeyAdded(key, validUntil, spendLimitWei, allowedTarget);
    }

    function revokeSessionKey(address key) external onlyOwner {
        sessionKeys[key].active = false;
        emit SessionKeyRevoked(key);
    }

    // ── recovery (guardians) ─────────────────────────────────────
    function addGuardian(address guardian) external onlyOwner {
        if (isGuardian[guardian]) revert GuardianExists();
        isGuardian[guardian] = true;
        guardians.push(guardian);
        emit GuardianAdded(guardian);
    }

    function removeGuardian(address guardian) external onlyOwner {
        if (!isGuardian[guardian]) revert GuardianNotFound();
        isGuardian[guardian] = false;
        for (uint256 i; i < guardians.length; ++i) {
            if (guardians[i] == guardian) {
                guardians[i] = guardians[guardians.length - 1];
                guardians.pop();
                break;
            }
        }
        emit GuardianRemoved(guardian);
    }

    /// @notice Guardian запускает/подтверждает восстановление (порог 2). Таймер — с первого вызова.
    function approveRecovery(address newOwner_) external {
        if (!isGuardian[msg.sender]) revert NotGuardian();
        if (newOwner_ == address(0)) revert BadSignature();
        if (recoveryReadyAt == 0) {
            pendingOwner = newOwner_;
            recoveryReadyAt = block.timestamp + RECOVERY_DELAY;
            recoveryApprovals = 0;
        } else if (pendingOwner != newOwner_) {
            revert NoPendingRecovery();
        }
        recoveryApprovals++;
        emit RecoveryApproved(msg.sender, recoveryApprovals);
        emit RecoveryStarted(pendingOwner, recoveryReadyAt);
    }

    function finalizeRecovery() external {
        if (recoveryReadyAt == 0) revert NoPendingRecovery();
        if (recoveryApprovals < GUARDIAN_THRESHOLD) revert NotGuardian();
        if (block.timestamp < recoveryReadyAt) revert RecoveryNotReady();
        owner = pendingOwner;
        pendingOwner = address(0);
        recoveryReadyAt = 0;
        recoveryApprovals = 0;
        emit RecoveryFinalized(owner);
    }

    function cancelRecovery() external onlyOwner {
        pendingOwner = address(0);
        recoveryReadyAt = 0;
        recoveryApprovals = 0;
        emit RecoveryCancelled();
    }

    receive() external payable {}

    // ── utils ────────────────────────────────────────────────────
    function _split(bytes memory sig) internal pure returns (uint8 v, bytes32 r, bytes32 s) {
        assembly {
            r := mload(add(sig, 32))
            s := mload(add(sig, 64))
            v := byte(0, mload(add(sig, 96)))
        }
        if (v < 27) v += 27;
    }
}
