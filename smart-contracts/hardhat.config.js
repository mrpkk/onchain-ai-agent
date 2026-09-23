require("@nomicfoundation/hardhat-toolbox");

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.20",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
      viaIR: true,
    },
  },
  networks: {
    hardhat: {
      chainId: 31337,
    },
    sepolia: {
      url: process.env.SEPOLIA_RPC_URL || "https://ethereum-sepolia-rpc.publicnode.com",
      accounts: (
        process.env.SEPOLIA_PRIVATE_KEY ||
        process.env.WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY
      )
        ? [process.env.SEPOLIA_PRIVATE_KEY || process.env.WALLET_METAMASK_ETH_ERC20_PRIVATE_KEY]
        : [],
      timeout: 120000,
    },
    // baseSepolia: {
    //   url: process.env.BASE_SEPOLIA_RPC_URL || "",
    //   accounts: process.env.PRIVATE_KEY ? [process.env.PRIVATE_KEY] : [],
    // },
  },
};
