const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("RicardianAgreement", function () {
  let agreement, token;
  let creator, partyB, partyC, outsider;

  const HASH = ethers.keccak256(ethers.toUtf8Bytes("ricardian-doc-1"));
  const M1 = 500_000n;
  const M2 = 300_000n;
  const TOTAL = M1 + M2;

  // AgreementStatus enum: Draft=0, Signed=1, Active=2, Completed=3, Disputed=4
  const DRAFT = 0n, ACTIVE = 2n, COMPLETED = 3n, DISPUTED = 4n;

  let pastDeadline, futureDeadline;

  beforeEach(async function () {
    [creator, partyB, partyC, outsider] = await ethers.getSigners();

    const Token = await ethers.getContractFactory("MockERC20");
    token = await Token.deploy("Mock USD", "mUSD");

    const Agreement = await ethers.getContractFactory("RicardianAgreement");
    agreement = await Agreement.deploy();

    // Контракт должен быть предварительно профинансирован (createAgreement не тянет токены)
    await token.mint(await agreement.getAddress(), 100_000_000n);

    const latest = await ethers.provider.getBlock("latest");
    pastDeadline = latest.timestamp - 10;
    futureDeadline = latest.timestamp + 3600;
  });

  async function createDefault({ deadlines } = {}) {
    const dl = deadlines || [pastDeadline, pastDeadline];
    const tx = await agreement.connect(creator).createAgreement(
      HASH,
      [partyB.address, partyC.address],
      await token.getAddress(),
      ["Milestone 1", "Milestone 2"],
      [M1, M2],
      dl
    );
    await tx.wait();
    return 0n;
  }

  async function activate() {
    await agreement.connect(partyB).signAgreement(0);
    await agreement.connect(partyC).signAgreement(0);
  }

  describe("createAgreement", function () {
    it("stores agreement and milestones", async function () {
      const tx = await agreement.connect(creator).createAgreement(
        HASH, [partyB.address, partyC.address], await token.getAddress(),
        ["M1", "M2"], [M1, M2], [pastDeadline, pastDeadline]
      );
      await expect(tx).to.emit(agreement, "AgreementCreated").withArgs(0, HASH, creator.address);

      const info = await agreement.getAgreement(0);
      expect(info.agreementHash).to.equal(HASH);
      expect(info.parties.length).to.equal(3); // creator + B + C
      expect(info.totalAmount).to.equal(TOTAL);
      expect(info.milestoneCount).to.equal(2n);
      expect(info.status).to.equal(DRAFT);
      expect(info.signCount).to.equal(0n);
      expect(await agreement.isParty(0, creator.address)).to.equal(true);
      expect(await agreement.isParty(0, outsider.address)).to.equal(false);
    });

    it("reverts on duplicate hash", async function () {
      await createDefault();
      await expect(agreement.connect(creator).createAgreement(
        HASH, [partyB.address], await token.getAddress(), ["M"], [M1], [pastDeadline]
      )).to.be.revertedWithCustomError(agreement, "HashAlreadyUsed");
    });

    it("reverts with no parties", async function () {
      await expect(agreement.connect(creator).createAgreement(
        HASH, [], await token.getAddress(), ["M"], [M1], [pastDeadline]
      )).to.be.revertedWithCustomError(agreement, "NoParties");
    });

    it("reverts on zero milestone amount", async function () {
      await expect(agreement.connect(creator).createAgreement(
        HASH, [partyB.address], await token.getAddress(), ["M"], [0], [pastDeadline]
      )).to.be.revertedWithCustomError(agreement, "ZeroAmount");
    });

    it("reverts on mismatched arrays", async function () {
      await expect(agreement.connect(creator).createAgreement(
        HASH, [partyB.address], await token.getAddress(), ["M1", "M2"], [M1], [pastDeadline]
      )).to.be.revertedWithCustomError(agreement, "ZeroAmount");
    });
  });

  describe("signAgreement", function () {
    it("creator already signed (auto) — second sign reverts", async function () {
      await createDefault();
      await expect(agreement.connect(creator).signAgreement(0))
        .to.be.revertedWithCustomError(agreement, "AlreadySigned");
    });

    it("2-of-3 signatures activate the agreement", async function () {
      await createDefault();
      await expect(agreement.connect(partyB).signAgreement(0))
        .to.emit(agreement, "AgreementSigned").withArgs(0, partyB.address);
      await expect(agreement.connect(partyC).signAgreement(0))
        .to.emit(agreement, "AgreementActivated").withArgs(0);

      const info = await agreement.getAgreement(0);
      expect(info.signCount).to.equal(2n);
      expect(info.status).to.equal(ACTIVE);
    });

    it("outsider cannot sign", async function () {
      await createDefault();
      await expect(agreement.connect(outsider).signAgreement(0))
        .to.be.revertedWithCustomError(agreement, "NotParty");
    });

    it("cannot sign after activation", async function () {
      await createDefault();
      await activate();
      await expect(agreement.connect(creator).signAgreement(0))
        .to.be.revertedWithCustomError(agreement, "InvalidStatus")
        .withArgs(DRAFT, ACTIVE);
    });
  });

  describe("executeMilestone", function () {
    it("reverts before deadline", async function () {
      await createDefault({ deadlines: [futureDeadline, futureDeadline] });
      await activate();
      await expect(agreement.connect(creator).executeMilestone(0, 0, partyB.address))
        .to.be.revertedWithCustomError(agreement, "DeadlineNotReached");
    });

    it("reverts in Draft status", async function () {
      await createDefault();
      await expect(agreement.connect(creator).executeMilestone(0, 0, partyB.address))
        .to.be.revertedWithCustomError(agreement, "InvalidStatus")
        .withArgs(ACTIVE, DRAFT);
    });

    it("outsider cannot execute", async function () {
      await createDefault();
      await activate();
      await expect(agreement.connect(outsider).executeMilestone(0, 0, partyB.address))
        .to.be.revertedWithCustomError(agreement, "NotParty");
    });

    it("releases funds to payee and completes milestone", async function () {
      await createDefault();
      await activate();
      const before = await token.balanceOf(partyB.address);
      await expect(agreement.connect(creator).executeMilestone(0, 0, partyB.address))
        .to.emit(agreement, "MilestoneCompleted").withArgs(0, 0)
        .and.to.emit(agreement, "FundsReleased").withArgs(0, 0, partyB.address, M1);
      expect(await token.balanceOf(partyB.address)).to.equal(before + M1);
    });

    it("cannot execute milestone twice", async function () {
      await createDefault();
      await activate();
      await agreement.connect(creator).executeMilestone(0, 0, partyB.address);
      await expect(agreement.connect(creator).executeMilestone(0, 0, partyB.address))
        .to.be.revertedWithCustomError(agreement, "MilestoneAlreadyCompleted");
    });

    it("completes agreement when all milestones executed", async function () {
      await createDefault();
      await activate();
      await agreement.connect(creator).executeMilestone(0, 0, partyB.address);
      await agreement.connect(creator).executeMilestone(0, 1, partyC.address);
      const info = await agreement.getAgreement(0);
      expect(info.status).to.equal(COMPLETED);
    });
  });

  describe("disputeMilestone", function () {
    it("freezes milestone and agreement", async function () {
      await createDefault();
      await activate();
      await expect(agreement.connect(partyC).disputeMilestone(0, 1))
        .to.emit(agreement, "MilestoneDisputed").withArgs(0, 1, partyC.address);

      const milestone = await agreement.getMilestone(0, 1);
      expect(milestone.disputed).to.equal(true);
      const info = await agreement.getAgreement(0);
      expect(info.status).to.equal(DISPUTED);
    });

    it("outsider cannot dispute", async function () {
      await createDefault();
      await activate();
      await expect(agreement.connect(outsider).disputeMilestone(0, 0))
        .to.be.revertedWithCustomError(agreement, "NotParty");
    });

    it("cannot dispute completed milestone", async function () {
      await createDefault();
      await activate();
      await agreement.connect(creator).executeMilestone(0, 0, partyB.address);
      await expect(agreement.connect(partyC).disputeMilestone(0, 0))
        .to.be.revertedWithCustomError(agreement, "MilestoneAlreadyCompleted");
    });

    it("cannot dispute the same milestone twice (agreement already Disputed)", async function () {
      await createDefault();
      await activate();
      await agreement.connect(partyC).disputeMilestone(0, 1);
      await expect(agreement.connect(partyB).disputeMilestone(0, 1))
        .to.be.revertedWithCustomError(agreement, "InvalidStatus")
        .withArgs(ACTIVE, DISPUTED);
    });

    it("execution blocked after dispute (agreement is Disputed)", async function () {
      await createDefault();
      await activate();
      await agreement.connect(partyC).disputeMilestone(0, 0);
      await expect(agreement.connect(creator).executeMilestone(0, 1, partyB.address))
        .to.be.revertedWithCustomError(agreement, "InvalidStatus")
        .withArgs(ACTIVE, DISPUTED);
    });
  });
});
