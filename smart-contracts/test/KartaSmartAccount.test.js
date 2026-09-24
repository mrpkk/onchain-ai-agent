const { expect } = require("chai");
const { ethers } = require("hardhat");

// S5-06: локальный ERC-4337 — account + session keys (TTL/лимит/цель) + paymaster + recovery
describe("KartaSmartAccount / KartaEntryPoint (S5-06)", function () {
  async function deploy() {
    const [deployer] = await ethers.getSigners();
    const mk = async (name) => {
      const w = ethers.Wallet.createRandom().connect(ethers.provider);
      await deployer.sendTransaction({ to: w.address, value: ethers.parseEther("1") });
      return [name, w];
    };
    const walletMap = Object.fromEntries(
      await Promise.all(["owner", "sessionKey", "guardian1", "guardian2", "stranger", "recipient"].map(mk))
    );
    const { owner, sessionKey, guardian1, guardian2, stranger, recipient } = walletMap;

    const EntryPoint = await ethers.getContractFactory("KartaEntryPoint");
    const entryPoint = await EntryPoint.deploy();
    const Account = await ethers.getContractFactory("KartaSmartAccount");
    const account = await Account.deploy(owner.address, await entryPoint.getAddress());
    const Paymaster = await ethers.getContractFactory("MockPaymaster");
    const paymaster = await Paymaster.deploy(await entryPoint.getAddress());
    const Token = await ethers.getContractFactory("MockERC20EIP3009");
    const token = await Token.deploy("Mock USDC", "mUSDC");
    await Promise.all([
      entryPoint.waitForDeployment(), account.waitForDeployment(),
      paymaster.waitForDeployment(), token.waitForDeployment(),
    ]);

    await deployer.sendTransaction({ to: await account.getAddress(), value: ethers.parseEther("1") });

    const sign = async (signer, op) => {
      const hash = await entryPoint.getUserOpHash(op);
      const sig = signer.signingKey.sign(hash);
      return ethers.concat([sig.r, sig.s, new Uint8Array([sig.v])]);
    };

    const makeOp = async (signer, { target, value = 0n, data = "0x", paymaster = ethers.ZeroAddress }) => {
      const op = {
        sender: await account.getAddress(),
        nonce: await account.getNonce(),
        target, value, data, paymaster, signature: "0x",
      };
      op.signature = await sign(signer, op);
      return op;
    };

    const handle = async (op, beneficiary = ethers.ZeroAddress) => {
      const tx = await entryPoint.handleOps([op], beneficiary);
      return tx.wait();
    };

    return { entryPoint, account, paymaster, token, owner, sessionKey, guardian1,
             guardian2, recipient, stranger, makeOp, handle, sign };
  }

  it("owner исполняет операцию через EntryPoint (перевод ETH)", async function () {
    const { account, owner, recipient, makeOp, handle } = await deploy();
    const before = await ethers.provider.getBalance(recipient.address);
    const op = await makeOp(owner, {
      target: recipient.address, value: ethers.parseEther("0.1"),
    });
    await handle(op);
    expect(await ethers.provider.getBalance(recipient.address) - before)
      .to.equal(ethers.parseEther("0.1"));
    expect(await account.getNonce()).to.equal(1n);
  });

  it("session key исполняет операцию в пределах лимита и цели", async function () {
    const { account, owner, sessionKey, token, makeOp, handle } = await deploy();
    const validUntil = Math.floor(Date.now() / 1000) + 3600;
    await account.connect(owner).addSessionKey(
      sessionKey.address, validUntil, ethers.parseEther("0.5"), await token.getAddress()
    );
    const data = token.interface.encodeFunctionData("mint", [owner.address, 1000n]);
    const op = await makeOp(sessionKey, { target: await token.getAddress(), data });
    await handle(op);
    expect(await token.balanceOf(owner.address)).to.equal(1000n);
  });

  it("session key: превышение лимита → SpendLimitExceeded", async function () {
    const { account, owner, sessionKey, recipient, makeOp, handle } = await deploy();
    await account.connect(owner).addSessionKey(
      sessionKey.address, 0, ethers.parseEther("0.01"), ethers.ZeroAddress
    );
    const op = await makeOp(sessionKey, { target: recipient.address, value: ethers.parseEther("0.02") });
    await expect(handle(op)).to.be.revertedWithCustomError(account, "SpendLimitExceeded");
  });

  it("session key: чужая цель → TargetNotAllowed", async function () {
    const { account, owner, sessionKey, token, recipient, makeOp, handle } = await deploy();
    await account.connect(owner).addSessionKey(
      sessionKey.address, 0, ethers.parseEther("1"), await token.getAddress()
    );
    const op = await makeOp(sessionKey, { target: recipient.address, value: ethers.parseEther("0.01") });
    await expect(handle(op)).to.be.revertedWithCustomError(account, "TargetNotAllowed");
  });

  it("session key: истёкший TTL → ValidationFailed", async function () {
    const { entryPoint, account, owner, sessionKey, token, makeOp, handle } = await deploy();
    const validUntil = Math.floor(Date.now() / 1000) + 60;
    await account.connect(owner).addSessionKey(
      sessionKey.address, validUntil, ethers.parseEther("1"), await token.getAddress()
    );
    await ethers.provider.send("evm_increaseTime", [120]);
    await ethers.provider.send("evm_mine", []);
    const data = token.interface.encodeFunctionData("mint", [owner.address, 1n]);
    const op = await makeOp(sessionKey, { target: await token.getAddress(), data });
    await expect(handle(op)).to.be.revertedWithCustomError(entryPoint, "ValidationFailed");
  });

  it("session key: отозванный → ValidationFailed", async function () {
    const { entryPoint, account, owner, sessionKey, token, makeOp, handle } = await deploy();
    await account.connect(owner).addSessionKey(
      sessionKey.address, 0, ethers.parseEther("1"), await token.getAddress()
    );
    await account.connect(owner).revokeSessionKey(sessionKey.address);
    const data = token.interface.encodeFunctionData("mint", [owner.address, 1n]);
    const op = await makeOp(sessionKey, { target: await token.getAddress(), data });
    await expect(handle(op)).to.be.revertedWithCustomError(entryPoint, "ValidationFailed");
  });

  it("чужая подпись → ValidationFailed", async function () {
    const { entryPoint, recipient, stranger, makeOp, handle } = await deploy();
    const op = await makeOp(stranger, { target: recipient.address, value: 1n });
    await expect(handle(op)).to.be.revertedWithCustomError(entryPoint, "ValidationFailed");
  });

  it("paymaster спонсирует операцию (beneficiary получает компенсацию)", async function () {
    const { entryPoint, account, paymaster, owner, token, recipient, makeOp, handle } = await deploy();
    await paymaster.deposit({ value: ethers.parseEther("1") });
    const data = token.interface.encodeFunctionData("mint", [owner.address, 5n]);
    const op = await makeOp(owner, {
      target: await token.getAddress(), data, paymaster: await paymaster.getAddress(),
    });
    const beneficiary = recipient;
    const before = await ethers.provider.getBalance(beneficiary.address);
    await handle(op, beneficiary.address);
    expect(await ethers.provider.getBalance(beneficiary.address) - before)
      .to.equal(100000000000000n); // 0.0001 ETH
    await expect(handle(await makeOp(owner, { target: await token.getAddress(), data,
      paymaster: await paymaster.getAddress() }), beneficiary.address))
      .to.emit(entryPoint, "PaymasterPaid");
  });

  it("recovery: 2 guardians + задержка → новый owner", async function () {
    const { account, owner, guardian1, guardian2, recipient, makeOp, handle } = await deploy();
    await account.connect(owner).addGuardian(guardian1.address);
    await account.connect(owner).addGuardian(guardian2.address);

    await account.connect(guardian1).approveRecovery(recipient.address);
    await account.connect(guardian2).approveRecovery(recipient.address);
    await expect(account.connect(guardian1).finalizeRecovery())
      .to.be.revertedWithCustomError(account, "RecoveryNotReady");

    await ethers.provider.send("evm_increaseTime", [2 * 24 * 3600 + 10]);
    await ethers.provider.send("evm_mine", []);
    await account.connect(guardian1).finalizeRecovery();
    expect(await account.owner()).to.equal(recipient.address);

    // новый owner подписывает операцию
    const op = await makeOp(recipient, { target: recipient.address, value: ethers.parseEther("0.01") });
    await handle(op);
  });

  it("recovery: один guardian / без задержки не проходит; owner может отменить", async function () {
    const { account, owner, guardian1, recipient } = await deploy();
    await account.connect(owner).addGuardian(guardian1.address);
    await account.connect(guardian1).approveRecovery(recipient.address);
    await ethers.provider.send("evm_increaseTime", [3 * 24 * 3600]);
    await ethers.provider.send("evm_mine", []);
    await expect(account.connect(guardian1).finalizeRecovery())
      .to.be.revertedWithCustomError(account, "NotGuardian"); // порог 2

    await account.connect(owner).cancelRecovery();
    expect(await account.pendingOwner()).to.equal(ethers.ZeroAddress);
  });
});
