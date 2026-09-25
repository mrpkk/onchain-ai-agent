/**
 * KARTA — деплой контрактов (S5-03) + live-смоук.
 *
 * Использование:
 *   npx hardhat run scripts/deploy.js --network sepolia
 * Переменные: SEPOLIA_RPC_URL (дефолт — PublicNode, проверен из РФ),
 *             SEPOLIA_PRIVATE_KEY (или WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY из ~/.env).
 *
 * Арбитр Escrow в тестнете = деплоер (само-арбитраж; для прода — отдельная сторона, P6).
 * Результат: console + deployments/<network>.json (адреса, tx, смоук-регистрация агента).
 */
const fs = require("fs");
const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const net = await hre.ethers.provider.getNetwork();
  const balance = await hre.ethers.provider.getBalance(deployer.address);

  console.log("Сеть:      ", hre.network.name, "(chainId", net.chainId.toString() + ")");
  console.log("Деплоер:   ", deployer.address);
  console.log("Баланс:    ", hre.ethers.formatEther(balance), "ETH");

  const out = {
    network: hre.network.name,
    chainId: Number(net.chainId),
    deployer: deployer.address,
    timestamp: new Date().toISOString(),
    contracts: {},
    deploymentTxs: {},
    smoke: {},
  };

  const deploy = async (name, ...args) => {
    const factory = await hre.ethers.getContractFactory(name);
    const contract = await factory.deploy(...args);
    await contract.waitForDeployment();
    const address = await contract.getAddress();
    out.contracts[name] = address;
    out.deploymentTxs[name] = contract.deploymentTransaction().hash;
    console.log(`${name}: ${address}`);
    return contract;
  };

  const registry = await deploy("AgentRegistry");
  const escrow = await deploy("Escrow", deployer.address);
  const ricardian = await deploy("RicardianAgreement");
  const usdc = await deploy("MockERC20", "Mock USDC", "mUSDC");

  // Live-смоук: регистрация агента в живой сети (доказывает запись, не только деплой)
  const agentName = `karta-smoke-${Date.now()}`;
  const regTx = await registry.registerAgent(agentName, "https://karta.local/agent/smoke.json");
  const receipt = await regTx.wait();
  out.smoke.registerAgent = {
    name: agentName,
    txHash: receipt.hash,
    block: receipt.blockNumber,
    gasUsed: receipt.gasUsed.toString(),
  };
  console.log("Смоук registerAgent:", receipt.hash);

  const agentId = await registry.resolveName(agentName);
  const record = await registry.getAgent(agentId);
  out.smoke.agent = { agentId: agentId.toString(), owner: record[1] || record.owner };
  console.log("Агент зарегистрирован, agentId =", agentId.toString());

  fs.mkdirSync("deployments", { recursive: true });
  const file = `deployments/${hre.network.name}.json`;
  fs.writeFileSync(file, JSON.stringify(out, null, 2) + "\n");
  console.log("Сохранено:", file);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
