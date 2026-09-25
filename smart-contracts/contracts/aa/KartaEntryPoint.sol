// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./KartaSmartAccount.sol";

/// @title KartaEntryPoint
/// @notice Минимальный локальный ERC-4337 EntryPoint (S5-06): validate → execute, опциональный paymaster.
/// @dev Решение владельца: bundler/paymaster платные → локальный EntryPoint. Не претендует на
///      полную спецификацию (deposits/stake/aggregation опущены осознанно; gas-учёт упрощён).
contract KartaEntryPoint {
    struct UserOperation {
        address sender;
        uint256 nonce;
        address target;
        uint256 value;
        bytes data;
        address paymaster;
        bytes signature;
    }

    error ValidationFailed(address sender);

    event UserOperationEvent(address indexed sender, address indexed paymaster, bool success);
    event PaymasterPaid(address indexed paymaster, address indexed beneficiary, uint256 amount);

    /// @notice Обработка пачки операций (вызывает bundler). beneficiary получает газ-компенсацию.
    function handleOps(UserOperation[] calldata ops, address payable beneficiary) external {
        for (uint256 i; i < ops.length; ++i) {
            UserOperation calldata op = ops[i];
            bytes32 opHash = getUserOpHash(op);

            uint256 validation = KartaSmartAccount(payable(op.sender)).validateUserOp(
                op.sender, opHash, op.signature
            );
            if (validation != 0) revert ValidationFailed(op.sender);

            // Paymaster-путь: локальный спонсор подтверждает операцию
            if (op.paymaster != address(0)) {
                (bool pmOk, ) = op.paymaster.call(
                    abi.encodeWithSignature("validatePaymasterUserOp(address,bytes32)", op.sender, opHash)
                );
                require(pmOk, "paymaster validation failed");
            }

            address signer = _recoverSigner(opHash, op.signature);
            (bool ok, bytes memory ret) = op.sender.call(
                abi.encodeWithSelector(
                    KartaSmartAccount.executeFromEntryPoint.selector,
                    op.target, op.value, op.data, signer, op.nonce
                )
            );
            if (!ok) {
                // Пробрасываем оригинальную ошибку аккаунта (SpendLimitExceeded/TargetNotAllowed/…)
                assembly {
                    revert(add(ret, 32), mload(ret))
                }
            }
            emit UserOperationEvent(op.sender, op.paymaster, true);

            // Оплата бенефициару: paymaster (если задан) платит фиксированную компенсацию
            if (beneficiary != address(0) && op.paymaster != address(0)) {
                uint256 fee = 100_000_000_000_000; // 0.0001 ETH (демо-компенсация)
                (bool paid, ) = op.paymaster.call(
                    abi.encodeWithSignature("payForGas(address,uint256)", beneficiary, fee)
                );
                if (paid) emit PaymasterPaid(op.paymaster, beneficiary, fee);
            }
        }
    }

    function getUserOpHash(UserOperation calldata op) public view returns (bytes32) {
        return keccak256(abi.encode(
            op.sender, op.nonce, op.target, op.value, op.data, op.paymaster, block.chainid, address(this)
        ));
    }

    function _recoverSigner(bytes32 opHash, bytes calldata signature) internal pure returns (address) {
        if (signature.length < 65) return address(0);
        bytes32 r = bytes32(signature[0:32]);
        bytes32 s = bytes32(signature[32:64]);
        uint8 v = uint8(signature[64]);
        if (v < 27) v += 27;
        return ecrecover(opHash, v, r, s);
    }
}
