const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("MockERC20EIP3009 (S6-05, x402 demo)", function () {
  async function deploy() {
    const [owner, payer, payee] = await ethers.getSigners();
    const Token = await ethers.getContractFactory("MockERC20EIP3009");
    const token = await Token.deploy("x402 Demo USD", "xUSDC");
    await token.waitForDeployment();
    await token.mint(payer.address, 1_000_000n);
    return { token, owner, payer, payee };
  }

  async function signAuthorization(token, payer, payee, value, nonce, validAfter, validBefore) {
    const network = await ethers.provider.getNetwork();
    const domain = {
      name: "x402 Demo USD",
      version: "1",
      chainId: network.chainId,
      verifyingContract: await token.getAddress(),
    };
    const types = {
      TransferWithAuthorization: [
        { name: "from", type: "address" },
        { name: "to", type: "address" },
        { name: "value", type: "uint256" },
        { name: "validAfter", type: "uint256" },
        { name: "validBefore", type: "uint256" },
        { name: "nonce", type: "bytes32" },
      ],
    };
    const message = {
      from: payer.address,
      to: payee.address,
      value,
      validAfter,
      validBefore,
      nonce,
    };
    const signature = await payer.signTypedData(domain, types, message);
    return ethers.Signature.from(signature);
  }

  it("переносит средства по валидной подписи", async function () {
    const { token, payer, payee } = await deploy();
    const now = (await ethers.provider.getBlock("latest")).timestamp;
    const nonce = ethers.hexlify(ethers.randomBytes(32));
    const sig = await signAuthorization(token, payer, payee, 500n, nonce, 0, now + 3600);

    await expect(
      token.connect(payee).transferWithAuthorization(
        payer.address, payee.address, 500n, 0, now + 3600, nonce, sig.v, sig.r, sig.s
      )
    ).to.emit(token, "Transfer").withArgs(payer.address, payee.address, 500n);

    expect(await token.balanceOf(payee.address)).to.equal(500n);
  });

  it("запрещает повторное использование nonce", async function () {
    const { token, payer, payee } = await deploy();
    const now = (await ethers.provider.getBlock("latest")).timestamp;
    const nonce = ethers.hexlify(ethers.randomBytes(32));
    const sig = await signAuthorization(token, payer, payee, 100n, nonce, 0, now + 3600);

    await token.connect(payee).transferWithAuthorization(
      payer.address, payee.address, 100n, 0, now + 3600, nonce, sig.v, sig.r, sig.s
    );
    await expect(
      token.connect(payee).transferWithAuthorization(
        payer.address, payee.address, 100n, 0, now + 3600, nonce, sig.v, sig.r, sig.s
      )
    ).to.be.revertedWithCustomError(token, "AuthorizationUsed");
  });

  it("отклоняет просроченную авторизацию", async function () {
    const { token, payer, payee } = await deploy();
    const now = (await ethers.provider.getBlock("latest")).timestamp;
    const nonce = ethers.hexlify(ethers.randomBytes(32));
    const sig = await signAuthorization(token, payer, payee, 100n, nonce, 0, now + 60);

    await ethers.provider.send("evm_increaseTime", [120]);
    await ethers.provider.send("evm_mine", []);
    await expect(
      token.connect(payee).transferWithAuthorization(
        payer.address, payee.address, 100n, 0, now + 60, nonce, sig.v, sig.r, sig.s
      )
    ).to.be.revertedWithCustomError(token, "AuthorizationExpired");
  });

  it("отклоняет чужую подпись", async function () {
    const { token, owner, payer, payee } = await deploy();
    const now = (await ethers.provider.getBlock("latest")).timestamp;
    const nonce = ethers.hexlify(ethers.randomBytes(32));
    const sig = await signAuthorization(token, owner, payee, 100n, nonce, 0, now + 3600);

    await expect(
      token.connect(payee).transferWithAuthorization(
        payer.address, payee.address, 100n, 0, now + 3600, nonce, sig.v, sig.r, sig.s
      )
    ).to.be.revertedWithCustomError(token, "InvalidSignature");
  });

  it("отклоняет сумму больше баланса (недостаточно средств)", async function () {
    const { token, payer, payee } = await deploy();
    const now = (await ethers.provider.getBlock("latest")).timestamp;
    const nonce = ethers.hexlify(ethers.randomBytes(32));
    const sig = await signAuthorization(token, payer, payee, 2_000_000n, nonce, 0, now + 3600);

    await expect(
      token.connect(payee).transferWithAuthorization(
        payer.address, payee.address, 2_000_000n, 0, now + 3600, nonce, sig.v, sig.r, sig.s
      )
    ).to.be.revertedWithCustomError(token, "ERC20InsufficientBalance");
  });
});
