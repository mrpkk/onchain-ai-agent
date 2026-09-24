import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", os.path.expanduser("~/.env")),  # локальный + мастер-~/.env (секреты)
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # мастер-~/.env содержит сотни чужих ключей — не падать
    )

    # Application
    app_name: str = "OnChain AI Agent"
    app_version: str = "1.0.0"
    debug: bool = False

    # Ricardian signer (S6-03; тестнет-кошелёк)
    karta_ricardian_private_key: str = ""
    wallet_metamask_eth_erc20_private_key: str = ""

    # API Keys
    mistral_api_key: str = ""
    github_token: str = ""
    signer_private_key: str = ""

    # Server
    host: str = "127.0.0.1"  # deploy переопределяет (Dockerfile: --host 0.0.0.0)
    port: int = 8080

    # Auth — JWT
    jwt_secret_key: str = "CHANGE-ME-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # Database (PostgreSQL async; локальный docker PG — порт 5433)
    database_url: str = "postgresql+asyncpg://agent:agent@127.0.0.1:5433/onchain_ai"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Blockchain
    ethereum_rpc_url: str = "https://ethereum-rpc.publicnode.com"
    ethereum_sepolia_rpc_url: str = "https://ethereum-sepolia-rpc.publicnode.com"  # проверен из РФ 2026-09-22 (306ms); запас: eth.drpc.org, 1rpc.io/eth
    ricardian_rpc_url: str = "https://ethereum-sepolia-rpc.publicnode.com"
    registry_rpc_url: str = "https://ethereum-sepolia-rpc.publicnode.com"
    escrow_rpc_url: str = "https://ethereum-sepolia-rpc.publicnode.com"
    escrow_contract_address: str = "0xB73c9F99d40116501C0a18c4019Ac8E91ED7dE8a"  # Sepolia (S5-03)
    escrow_token_address: str = "0x212774d426519437d5Eb1126fE382fC7b7cCe7B0"  # mUSDC (Sepolia)
    aa_rpc_url: str = "https://ethereum-sepolia-rpc.publicnode.com"
    karta_aa_session_key: str = ""  # демо session key (тестнет, throwaway)
    aa_entrypoint_address: str = "0x40a52b4959cCA148594D8Bd29ccE4C292E8730B0"  # KartaEntryPoint (Sepolia, S5-06)
    aa_account_address: str = "0x2DE1302269746DaD1CC0f828030893D404AC572e"  # KartaSmartAccount (Sepolia, S5-06)
    bridge_provider_url: str = "https://li.quest/v1"  # LI.FI (доступен из РФ, проверено 24.09)
    bridge_api_key: str = ""  # опция (LI.FI работает и без ключа, с лимитами)
    bridge_execution_enabled: bool = False  # STOP-GATE: реальные средства
    bridge_timeout_seconds: float = 20.0
    swap_rpc_url: str = "https://ethereum-sepolia-rpc.publicnode.com"
    swap_router_address: str = "0xd11243Bd90EBc88e3A7D4eeA364Ee204A3aD509d"  # MockDEX (Sepolia, S5-01)
    swap_token_in: str = "0x212774d426519437d5Eb1126fE382fC7b7cCe7B0"   # mUSDC
    swap_token_out: str = "0x0eB3e17862A108Bbbc91989e6Ca1a3ed16f69710"  # xUSDC
    swap_aggregator_url: str = ""  # опция (агрегаторы из РФ гео-заблокированы)
    private_rpc_enabled: bool = False  # private RPC только для mainnet-отправок (вкл. конфигом)
    private_rpc_urls: list[str] = [  # проверены из РФ 2026-09-24: flashbots 884ms, mevblocker 592ms
        "https://rpc.flashbots.net",
        "https://rpc.mevblocker.io",
    ]
    tx_jitter_max_seconds: float = 1.5  # 0 = выкл; случайная задержка перед отправкой (анти-паттерн-детект)
    x402_rpc_url: str = "https://ethereum-sepolia-rpc.publicnode.com"
    x402_token_address: str = "0x0eB3e17862A108Bbbc91989e6Ca1a3ed16f69710"  # xUSDC demo (Sepolia)
    x402_pay_to: str = ""  # default: адрес кошелька KARTA
    x402_price_wei: int = 10**16  # 0.01 xUSDC (демо)
    registry_contract_address: str = "0x773945A9eA400e9c8704a2c02AAAbF449cFc20E5"  # Sepolia (S5-03)
    public_base_url: str = "http://127.0.0.1:8090"  # для metadataURI паспорта
    ricardian_contract_address: str = "0x153010a3f18cf363A87364BB8182Fc13ABF95dF2"  # Sepolia (S5-03)
    mcp_allowed_hosts: list[str] = [  # Host-allowlist MCP (dns-rebinding защита; "host:*" — любой порт)
        "127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "testserver",
    ]  # проверен из РФ 2026-09-22 (306ms); запас: eth.drpc.org, 1rpc.io/eth
    chain_id: int = 1
    agent_wallet_private_key: str = ""

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Agent defaults
    default_max_tx_per_day: int = 50
    default_gas_limit: int = 300000
    kill_switch_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_security(settings_obj) -> list[str]:
    """RTM NFR-1: проверки безопасности при старте. Возвращает список ошибок."""
    errors: list[str] = []
    jwt_default = "CHANGE-ME-in-production-use-openssl-rand-hex-32"
    if not settings_obj.debug and settings_obj.jwt_secret_key == jwt_default:
        errors.append("jwt_secret_key оставлен дефолтным в production — задайте openssl rand -hex 32")
    if not settings_obj.debug and settings_obj.agent_wallet_private_key:
        errors.append(
            "agent_wallet_private_key в открытом виде в env — используйте "
            "KeyVault (src/security/keyvault.py) и ONCHAIN_MASTER_KEY"
        )
    return errors
