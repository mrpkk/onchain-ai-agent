const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("AgentRegistry", function () {
  let registry;
  let owner, user1, user2;

  beforeEach(async function () {
    [owner, user1, user2] = await ethers.getSigners();
    const Registry = await ethers.getContractFactory("AgentRegistry");
    registry = await Registry.deploy();
  });

  describe("registerAgent", function () {
    it("should register a new agent", async function () {
      const tx = await registry.registerAgent("AgentAlpha", "ipfs://Qm123");
      const receipt = await tx.wait();

      expect(await registry.totalRegistered()).to.equal(1);
      expect(await registry.isRegistered(0)).to.equal(true);

      const agent = await registry.getAgent(0);
      expect(agent.name).to.equal("AgentAlpha");
      expect(agent.metadataURI).to.equal("ipfs://Qm123");
      expect(agent.owner).to.equal(owner.address);
      expect(agent.verified).to.equal(false);
      expect(agent.reputation).to.equal(0);
    });

    it("should revert on empty name", async function () {
      await expect(registry.registerAgent("", "ipfs://Qm123"))
        .to.be.revertedWithCustomError(registry, "NameEmpty");
    });

    it("should revert on empty URI", async function () {
      await expect(registry.registerAgent("Agent", ""))
        .to.be.revertedWithCustomError(registry, "URIEmpty");
    });

    it("should revert on duplicate name", async function () {
      await registry.registerAgent("AgentAlpha", "ipfs://Qm1");
      await expect(registry.registerAgent("AgentAlpha", "ipfs://Qm2"))
        .to.be.revertedWithCustomError(registry, "NameTaken");
    });

    it("should emit AgentRegistered event", async function () {
      await expect(registry.registerAgent("AgentBeta", "ipfs://Qm456"))
        .to.emit(registry, "AgentRegistered")
        .withArgs(0, "AgentBeta", owner.address);
    });
  });

  describe("verifyAgent", function () {
    beforeEach(async function () {
      await registry.registerAgent("AgentGamma", "ipfs://Qm789");
    });

    it("should verify an agent (owner only)", async function () {
      await registry.verifyAgent(0);
      const agent = await registry.getAgent(0);
      expect(agent.verified).to.equal(true);
    });

    it("should emit AgentVerified event", async function () {
      await expect(registry.verifyAgent(0))
        .to.emit(registry, "AgentVerified")
        .withArgs(0);
    });

    it("should revert if not owner", async function () {
      await expect(registry.connect(user1).verifyAgent(0))
        .to.be.revertedWithCustomError(registry, "NotOwner");
    });

    it("should be idempotent (no re-emit)", async function () {
      await registry.verifyAgent(0);
      await expect(registry.verifyAgent(0)).to.not.emit(registry, "AgentVerified");
    });
  });

  describe("updateReputation", function () {
    beforeEach(async function () {
      await registry.registerAgent("AgentDelta", "ipfs://QmABC");
    });

    it("should update reputation score", async function () {
      await registry.updateReputation(0, 85);
      const agent = await registry.getAgent(0);
      expect(agent.reputation).to.equal(85);
    });

    it("should emit ReputationUpdated event", async function () {
      await expect(registry.updateReputation(0, 42))
        .to.emit(registry, "ReputationUpdated")
        .withArgs(0, 0, 42);
    });

    it("should revert if score > 100", async function () {
      await expect(registry.updateReputation(0, 101))
        .to.be.revertedWithCustomError(registry, "InvalidReputation");
    });

    it("should allow score of 100", async function () {
      await registry.updateReputation(0, 100);
      const agent = await registry.getAgent(0);
      expect(agent.reputation).to.equal(100);
    });

    it("should revert if not owner", async function () {
      await expect(registry.connect(user1).updateReputation(0, 50))
        .to.be.revertedWithCustomError(registry, "NotOwner");
    });
  });

  describe("views", function () {
    it("getAgentsByOwner returns all agent IDs for an owner", async function () {
      await registry.registerAgent("A1", "ipfs://1");
      await registry.registerAgent("A2", "ipfs://2");
      await registry.connect(user1).registerAgent("A3", "ipfs://3");

      const ownerAgents = await registry.getAgentsByOwner(owner.address);
      expect(ownerAgents.length).to.equal(2);
      expect(ownerAgents[0]).to.equal(0);
      expect(ownerAgents[1]).to.equal(1);

      const user1Agents = await registry.getAgentsByOwner(user1.address);
      expect(user1Agents.length).to.equal(1);
      expect(user1Agents[0]).to.equal(2);
    });

    it("resolveName returns correct agentId", async function () {
      await registry.registerAgent("UniqueAgent", "ipfs://X");
      expect(await registry.resolveName("UniqueAgent")).to.equal(0);
      expect(await registry.resolveName("NonExistent")).to.equal(0);
    });

    it("getAgent reverts for unregistered id", async function () {
      await expect(registry.getAgent(999))
        .to.be.revertedWithCustomError(registry, "AgentNotFound");
    });
  });
});
