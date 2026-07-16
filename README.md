# On-Chain AI Agent Framework

> Autonomous AI agents that own wallets, sign smart contracts, and execute on-chain operations 24/7 — without human intervention.

## What Is This?

A production-ready framework for building AI agents that operate on EVM-compatible blockchains. These agents can:

- **Own wallets** and manage funds with spending limits
- **Execute smart contracts** based on AI reasoning
- **Create Ricardian agreements** — legally binding + code-enforced contracts
- **Identify on-chain** via ERC-8004 agent registry
- **Autonomously optimize yield**, find arbitrage, and manage treasuries

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Agent Core                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │Perception│→│ Reasoning │→│ Planning │        │
│  │(Web3)    │ │(LLM/AI)  │ │(Tasks)   │        │
│  └──────────┘ └──────────┘ └──────────┘        │
│                     ↓                           │
│              ┌──────────┐                       │
│              │ Execution│                       │
│              │(Sign+TX) │                       │
│              └──────────┘                       │
├─────────────────────────────────────────────────┤
│              Smart Contracts                     │
│  ┌────────────────┐ ┌───────────┐ ┌──────────┐ │
│  │Ricardian       │ │AgentReg.  │ │Escrow    │ │
│  │Agreement       │ │(ERC-8004) │ │          │ │
│  └────────────────┘ └───────────┘ └──────────┘ │
├─────────────────────────────────────────────────┤
│  FastAPI Backend + React Frontend + Docker       │
└─────────────────────────────────────────────────┘
```

## Quick Start

### 1. Clone & Configure

```bash
git clone <repo-url>
cd onchain-ai-agent
cp .env.example .env
# Edit .env with your keys
```

### 2. Start with Docker

```bash
docker-compose up -d
```

### 3. Start Without Docker

```bash
cd backend
pip install -r requirements.txt
uvicorn src.api.main:app --host 0.0.0.0 --port 8080
```

### 4. Create Your First Agent

```bash
curl -X POST http://localhost:8080/agents \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "YieldBot",
    "chain": "ethereum",
    "daily_limit": 5.0,
    "per_tx_limit": 1.0,
    "simulation_mode": true
  }'
```

### 5. Give It a Goal

```bash
curl -X POST http://localhost:8080/agents/yieldbot/goal \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"goal": "Find the best DeFi yield on Ethereum and deploy 0.1 ETH"}'
```

## Features

### Agent Core
| Feature | Description |
|---------|-------------|
| **Perception** | Reads blockchain state, monitors mempool, fetches oracle prices |
| **Reasoning** | LLM-powered decision making with Chain-of-Thought prompting |
| **Planning** | Decomposes goals into step-by-step on-chain operations |
| **Execution** | Signs transactions with gas estimation, nonce management, retry logic |
| **Safety** | Spending limits, kill switch, simulation mode, audit logs |

### Smart Contracts
| Contract | Description |
|----------|-------------|
| **RicardianAgreement** | Legally binding + code-enforced agreements with milestones |
| **AgentRegistry** | ERC-8004 on-chain identity for AI agents |
| **Escrow** | Secure fund holding for agent-to-agent commerce |

### Security
- **Spending limits**: Daily and per-transaction caps
- **Kill switch**: Emergency stop for any agent
- **Simulation mode**: Test strategies without real funds
- **Audit logging**: Every decision and transaction recorded
- **Whitelist/blacklist**: Control which addresses agents can interact with

## Supported Chains

| Chain | Status |
|-------|--------|
| Ethereum Mainnet | ✅ |
| BNB Smart Chain | ✅ |
| Polygon | ✅ |
| Sepolia Testnet | ✅ |
| Any EVM chain | ✅ (custom config) |

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/auth/register` | POST | Register user |
| `/auth/login` | POST | Get JWT token |
| `/agents` | POST | Create agent |
| `/agents` | GET | List agents |
| `/agents/{id}` | GET | Get agent state |
| `/agents/{id}/start` | POST | Start autonomous loop |
| `/agents/{id}/stop` | POST | Stop agent |
| `/agents/{id}/goal` | POST | Execute a goal |
| `/agents/{id}/transactions` | GET | Transaction history |
| `/agents/{id}/kill-switch` | POST | Emergency stop |

## Project Structure

```
onchain-ai-agent/
├── backend/
│   ├── src/
│   │   ├── agent/           # Agent Core (perception, reasoning, planning, execution)
│   │   ├── api/             # FastAPI REST API
│   │   ├── config/          # Settings management
│   │   └── database/        # SQLAlchemy models
│   ├── Dockerfile
│   └── requirements.txt
├── smart-contracts/
│   ├── contracts/           # Solidity contracts
│   ├── test/                # Hardhat tests
│   └── hardhat.config.js
├── frontend/                # React dashboard (coming soon)
├── docker-compose.yml
├── .env.example
└── README.md
```

## Environment Variables

```env
# AI
MISTRAL_API_KEY=your_key
MISTRAL_MODEL=mistral-small-latest

# Blockchain
ETHEREUM_RPC_URL=https://eth.llamarpc.com
BSC_RPC_URL=https://bsc-dataseed.binance.org
POLYGON_RPC_URL=https://polygon-rpc.com

# Agent Security
AGENT_PRIVATE_KEY=your_private_key
DAILY_SPEND_LIMIT=5.0
PER_TX_LIMIT=1.0

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/agents

# API
JWT_SECRET=your_secret
ADMIN_EMAIL=admin@example.com
```

## Pricing (for SaaS deployment)

| Plan | Price | Agents | Features |
|------|-------|--------|----------|
| Starter | $500/mo | 3 | Basic monitoring, single chain |
| Pro | $1,500/mo | 10 | Multi-chain, yield optimization, arbitrage |
| Enterprise | $3,000/mo | Unlimited | Custom strategies, priority support, SLA |

## License

MIT
