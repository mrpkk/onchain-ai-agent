const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("MockDEX (S5-01, swap demo)", function () {
  async function deploy() {
    const [owner, trader] = await ethers.getSigners();
    const Token = await ethers.getContractFactory("MockERC20EIP3009");
    const tokenA = await Token.deploy("Mock USDC", "mUSDC");
    const tokenB = await Token.deploy("x402 Demo USD", "xUSDC");
    const DEX = await ethers.getContractFactory("MockDEX");
    const dex = await DEX.deploy(await tokenA.getAddress(), await tokenB.getAddress());
    await Promise.all([tokenA.waitForDeployment(), tokenB.waitForDeployment(), dex.waitForDeployment()]);

    await tokenA.mint(owner.address, 10_000n);
    await tokenB.mint(owner.address, 10_000n);
    await tokenA.mint(trader.address, 1_000n);
    await tokenA.connect(owner).approve(await dex.getAddress(), ethers.MaxUint256);
    await tokenB.connect(owner).approve(await dex.getAddress(), ethers.MaxUint256);
    await tokenA.connect(trader).approve(await dex.getAddress(), ethers.MaxUint256);
    return { dex, tokenA, tokenB, owner, trader };
  }

  it("addLiquidity пополняет резервы", async function () {
    const { dex } = await deploy();
    await dex.addLiquidity(2_000n, 2_000n);
    expect(await dex.reserve0()).to.equal(2_000n);
    expect(await dex.reserve1()).to.equal(2_000n);
  });

  it("getAmountsOut считает по формуле x*y=k с комиссией 0.30%", async function () {
    const { dex } = await deploy();
    await dex.addLiquidity(10_000n, 10_000n);
    const amounts = await dex.getAmountsOut(100n, [await dex.token0(), await dex.token1()]);
    // (100*9970 * 10000) / (10000*10000 + 100*9970) = 99.009...
    expect(amounts[1]).to.equal((100n * 9970n * 10000n) / (10000n * 10000n + 100n * 9970n));
  });

  it("swap переводит токены и обновляет резервы", async function () {
    const { dex, tokenA, tokenB, trader } = await deploy();
    await dex.addLiquidity(10_000n, 10_000n);
    const quoted = await dex.getAmountsOut(100n, [await tokenA.getAddress(), await tokenB.getAddress()]);
    const before = await tokenB.balanceOf(trader.address);

    await dex.connect(trader).swapExactTokensForTokens(
      100n, quoted[1], [await tokenA.getAddress(), await tokenB.getAddress()],
      trader.address, ethers.MaxUint256
    );

    expect(await tokenB.balanceOf(trader.address) - before).to.equal(quoted[1]);
    expect(await dex.reserve0()).to.equal(10_100n);
    expect(await dex.reserve1()).to.equal(10_000n - quoted[1]);
  });

  it("slippage-guard: amountOutMin выше котировки → revert", async function () {
    const { dex, tokenA, tokenB, trader } = await deploy();
    await dex.addLiquidity(10_000n, 10_000n);
    const quoted = await dex.getAmountsOut(100n, [await tokenA.getAddress(), await tokenB.getAddress()]);
    await expect(
      dex.connect(trader).swapExactTokensForTokens(
        100n, quoted[1] + 1n, [await tokenA.getAddress(), await tokenB.getAddress()],
        trader.address, ethers.MaxUint256
      )
    ).to.be.revertedWithCustomError(dex, "InsufficientOutput");
  });

  it("deadline и path валидируются", async function () {
    const { dex, tokenA, tokenB, trader } = await deploy();
    await dex.addLiquidity(1_000n, 1_000n);
    await expect(
      dex.connect(trader).swapExactTokensForTokens(
        10n, 0, [await tokenA.getAddress(), await tokenB.getAddress()], trader.address, 1
      )
    ).to.be.revertedWithCustomError(dex, "Expired");
    await expect(
      dex.connect(trader).swapExactTokensForTokens(
        10n, 0, [await tokenA.getAddress(), await tokenA.getAddress()], trader.address, ethers.MaxUint256
      )
    ).to.be.revertedWithCustomError(dex, "InvalidPath");
  });
});
