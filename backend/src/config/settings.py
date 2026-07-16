from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "OnChain AI Agent"
    app_version: str = "0.1.0"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8080

    # Auth — JWT
    jwt_secret_key: str = "CHANGE-ME-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # Database (PostgreSQL async)
    database_url: str = "postgresql+asyncpg://agent:agent@localhost:5432/onchain_ai"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Blockchain
    ethereum_rpc_url: str = "https://eth.llamarpc.com"
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
