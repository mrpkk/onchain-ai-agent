// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @title MockDEX
/// @notice Минимальный Uniswap-V2-совместимый AMM (x*y=k, комиссия 0.30%) для swap-демо (S5-01).
/// @dev Один пул token0/token1. Агрегаторы из РФ недоступны (geo-block) — локальный контур
///      позволяет проверять slippage-guard на реальных переводах. Только тестнет.
contract MockDEX {
    using SafeERC20 for IERC20;

    IERC20 public immutable token0;
    IERC20 public immutable token1;

    uint112 public reserve0;
    uint112 public reserve1;

    uint256 public constant FEE_BPS = 30;          // 0.30%
    uint256 public constant BPS = 10_000;

    error InvalidPath();
    error Expired();
    error InsufficientOutput(uint256 amountOut, uint256 amountOutMin);
    error InsufficientLiquidity();
    error ZeroAmount();

    event LiquidityAdded(uint256 amount0, uint256 amount1);
    event Swap(address indexed sender, uint256 amountIn, uint256 amountOut,
               address indexed tokenIn, address indexed to);

    constructor(address token0_, address token1_) {
        require(token0_ != token1_, "same token");
        token0 = IERC20(token0_);
        token1 = IERC20(token1_);
    }

    function addLiquidity(uint256 amount0, uint256 amount1) external {
        if (amount0 == 0 || amount1 == 0) revert ZeroAmount();
        token0.safeTransferFrom(msg.sender, address(this), amount0);
        token1.safeTransferFrom(msg.sender, address(this), amount1);
        reserve0 += uint112(amount0);
        reserve1 += uint112(amount1);
        emit LiquidityAdded(amount0, amount1);
    }

    function getAmountOut(uint256 amountIn, uint256 reserveIn, uint256 reserveOut)
        public pure returns (uint256)
    {
        if (amountIn == 0) revert ZeroAmount();
        if (reserveIn == 0 || reserveOut == 0) revert InsufficientLiquidity();
        uint256 amountInWithFee = amountIn * (BPS - FEE_BPS);
        return (amountInWithFee * reserveOut) / (reserveIn * BPS + amountInWithFee);
    }

    /// @notice Uniswap-V2-совместимая котировка (path = [tokenIn, tokenOut]).
    function getAmountsOut(uint256 amountIn, address[] calldata path)
        external view returns (uint256[] memory amounts)
    {
        if (path.length != 2) revert InvalidPath();
        (uint256 reserveIn, uint256 reserveOut, ) = _reservesFor(path[0], path[1]);
        amounts = new uint256[](2);
        amounts[0] = amountIn;
        amounts[1] = getAmountOut(amountIn, reserveIn, reserveOut);
    }

    /// @notice Uniswap-V2-совместимый swap (path = [tokenIn, tokenOut]).
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts) {
        if (block.timestamp > deadline) revert Expired();
        if (path.length != 2) revert InvalidPath();
        (uint256 reserveIn, uint256 reserveOut, bool zeroForOne) = _reservesFor(path[0], path[1]);

        amounts = new uint256[](2);
        amounts[0] = amountIn;
        amounts[1] = getAmountOut(amountIn, reserveIn, reserveOut);
        if (amounts[1] < amountOutMin) revert InsufficientOutput(amounts[1], amountOutMin);

        IERC20(path[0]).safeTransferFrom(msg.sender, address(this), amountIn);
        IERC20(path[1]).safeTransfer(to, amounts[1]);

        if (zeroForOne) {
            reserve0 += uint112(amountIn);
            reserve1 -= uint112(amounts[1]);
        } else {
            reserve1 += uint112(amountIn);
            reserve0 -= uint112(amounts[1]);
        }
        emit Swap(msg.sender, amountIn, amounts[1], path[0], to);
    }

    function _reservesFor(address tokenIn, address tokenOut)
        internal view returns (uint256 reserveIn, uint256 reserveOut, bool zeroForOne)
    {
        if (tokenIn == address(token0) && tokenOut == address(token1)) {
            return (reserve0, reserve1, true);
        }
        if (tokenIn == address(token1) && tokenOut == address(token0)) {
            return (reserve1, reserve0, false);
        }
        revert InvalidPath();
    }
}
