const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("Escrow", function () {
  let escrow, token;
  let arbiter, payer, payee, outsider;
  const AMOUNT = 1_000_000n; // 1.0 токена в минимальных единицах (decimals 18)

  beforeEach(async function () {
    [arbiter, payer, payee, outsider] = await ethers.getSigners();

    const Token = await ethers.getContractFactory("MockERC20");
    token = await Token.deploy("Mock USD", "mUSD");

    const Escrow = await ethers.getContractFactory("Escrow");
    escrow = await Escrow.deploy(arbiter.address);

    await token.mint(payer.address, 10_000_000n);
    await token.connect(payer).approve(await escrow.getAddress(), 10_000_000n);
  });

  async function createEscrow() {
    const tx = await escrow.connect(payer).createEscrow(payee.address, await token.getAddress(), AMOUNT);
    await tx.wait();
    return 0n;
  }

  describe("createEscrow", function () {
    it("pulls tokens and stores escrow data", async function () {
      const tx = await escrow.connect(payer).createEscrow(payee.address, await token.getAddress(), AMOUNT);
      await expect(tx).to.emit(escrow, "EscrowCreated")
        .withArgs(0, payer.address, payee.address, AMOUNT, await token.getAddress());

      expect(await escrow.nextEscrowId()).to.equal(1n);
      expect(await token.balanceOf(await escrow.getAddress())).to.equal(AMOUNT);
      const info = await escrow.getEscrow(0);
      expect(info.payer).to.equal(payer.address);
      expect(info.payee).to.equal(payee.address);
      expect(info.amount).to.equal(AMOUNT);
      expect(info.released).to.equal(false);
      expect(info.refunded).to.equal(false);
      expect(info.disputed).to.equal(false);
      expect(info.arbiter).to.equal(arbiter.address);
    });

    it("reverts on zero amount", async function () {
      await expect(escrow.connect(payer).createEscrow(payee.address, await token.getAddress(), 0))
        .to.be.revertedWithCustomError(escrow, "ZeroAmount");
    });

    it("reverts on zero payee", async function () {
      await expect(escrow.connect(payer).createEscrow(ethers.ZeroAddress, await token.getAddress(), AMOUNT))
        .to.be.revertedWithCustomError(escrow, "InvalidPayee");
    });

    it("reverts without allowance", async function () {
      await token.connect(payer).approve(await escrow.getAddress(), 0);
      await expect(escrow.connect(payer).createEscrow(payee.address, await token.getAddress(), AMOUNT))
        .to.be.reverted;
    });
  });

  describe("release", function () {
    it("payer can release to payee", async function () {
      await createEscrow();
      await expect(escrow.connect(payer).release(0)).to.emit(escrow, "EscrowReleased")
        .withArgs(0, payee.address, AMOUNT);
      expect(await token.balanceOf(payee.address)).to.equal(AMOUNT);
      expect(await escrow.isFinalized(0)).to.equal(true);
    });

    it("arbiter can release", async function () {
      await createEscrow();
      await escrow.connect(arbiter).release(0);
      expect(await token.balanceOf(payee.address)).to.equal(AMOUNT);
    });

    it("outsider cannot release", async function () {
      await createEscrow();
      await expect(escrow.connect(outsider).release(0))
        .to.be.revertedWithCustomError(escrow, "NotPayerOrArbiter");
    });

    it("cannot release twice", async function () {
      await createEscrow();
      await escrow.connect(payer).release(0);
      await expect(escrow.connect(payer).release(0))
        .to.be.revertedWithCustomError(escrow, "EscrowAlreadyFinalized");
    });

    it("cannot release unknown escrow", async function () {
      await expect(escrow.connect(payer).release(42))
        .to.be.revertedWithCustomError(escrow, "NotAuthorized");
    });
  });

  describe("refund", function () {
    it("payer can refund", async function () {
      await createEscrow();
      const before = await token.balanceOf(payer.address);
      await expect(escrow.connect(payer).refund(0)).to.emit(escrow, "EscrowRefunded")
        .withArgs(0, payer.address, AMOUNT);
      expect(await token.balanceOf(payer.address)).to.equal(before + AMOUNT);
    });

    it("non-payer cannot refund", async function () {
      await createEscrow();
      await expect(escrow.connect(payee).refund(0))
        .to.be.revertedWithCustomError(escrow, "NotPayer");
    });

    it("refund blocked after dispute (arbiter only)", async function () {
      await createEscrow();
      await escrow.connect(payee).dispute(0);
      await expect(escrow.connect(payer).refund(0))
        .to.be.revertedWithCustomError(escrow, "NotAuthorized");
    });
  });

  describe("dispute and resolve", function () {
    it("payee can dispute", async function () {
      await createEscrow();
      await expect(escrow.connect(payee).dispute(0)).to.emit(escrow, "EscrowDisputed")
        .withArgs(0, payee.address);
      const info = await escrow.getEscrow(0);
      expect(info.disputed).to.equal(true);
    });

    it("outsider cannot dispute", async function () {
      await createEscrow();
      await expect(escrow.connect(outsider).dispute(0))
        .to.be.revertedWithCustomError(escrow, "NotPayerOrArbiter");
    });

    it("arbiter resolves in favor of payee", async function () {
      await createEscrow();
      await escrow.connect(payer).dispute(0);
      await expect(escrow.connect(arbiter).resolve(0, true)).to.emit(escrow, "EscrowReleased");
      expect(await token.balanceOf(payee.address)).to.equal(AMOUNT);
    });

    it("arbiter resolves in favor of payer", async function () {
      await createEscrow();
      const before = await token.balanceOf(payer.address);
      await escrow.connect(payer).dispute(0);
      await expect(escrow.connect(arbiter).resolve(0, false)).to.emit(escrow, "EscrowRefunded");
      expect(await token.balanceOf(payer.address)).to.equal(before + AMOUNT);
    });

    it("non-arbiter cannot resolve", async function () {
      await createEscrow();
      await escrow.connect(payee).dispute(0);
      await expect(escrow.connect(payer).resolve(0, true))
        .to.be.revertedWithCustomError(escrow, "NotAuthorized");
    });

    it("cannot resolve non-disputed escrow", async function () {
      await createEscrow();
      await expect(escrow.connect(arbiter).resolve(0, true))
        .to.be.revertedWithCustomError(escrow, "NotDisputed");
    });

    it("cannot resolve finalized escrow", async function () {
      await createEscrow();
      await escrow.connect(payee).dispute(0);
      await escrow.connect(arbiter).resolve(0, true);
      await expect(escrow.connect(arbiter).resolve(0, true))
        .to.be.revertedWithCustomError(escrow, "EscrowAlreadyFinalized");
    });
  });
});
