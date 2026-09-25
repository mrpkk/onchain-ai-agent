// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title MockPaymaster
/// @notice Локальный paymaster (S5-06): спонсирует газ из своего баланса (тестнет).
/// @dev Платные bundler/paymaster-сервисы не используем (решение владельца) —
///      это демонстрационный локальный спонсор.
contract MockPaymaster {
    address public owner;
    address public immutable entryPoint;

    error NotOwner();
    error InsufficientDeposit();

    event UserOpSponsored(address indexed sender, bytes32 opHash);

    constructor(address entryPoint_) {
        owner = msg.sender;
        entryPoint = entryPoint_;
    }

    function validatePaymasterUserOp(address sender, bytes32 opHash) external returns (bytes memory context) {
        emit UserOpSponsored(sender, opHash);
        return abi.encode(sender);
    }

    /// @notice Оплата бенефициару из депозита paymaster (спонсорство газа).
    function payForGas(address payable beneficiary, uint256 amount) external {
        if (msg.sender != owner && msg.sender != entryPoint) revert NotOwner();
        if (address(this).balance < amount) revert InsufficientDeposit();
        if (amount > 0) {
            (bool ok, ) = beneficiary.call{value: amount}("");
            require(ok, "pay failed");
        }
    }

    receive() external payable {}

    function deposit() external payable {}
}
