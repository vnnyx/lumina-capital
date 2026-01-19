"""
Application configuration using Pydantic Settings.
"""

from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    All settings can be overridden via environment variables.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Bitget API Configuration
    bitget_api_access_key: str = Field(default="", description="Bitget API access key")
    bitget_api_secret_key: str = Field(default="", description="Bitget API secret key")
    bitget_api_passphrase: str = Field(default="", description="Bitget API passphrase")
    bitget_base_url: str = Field(
        default="https://api.bitget.com",
        description="Bitget API base URL",
    )
    
    # Gemini API Configuration
    gemini_api_key: str = Field(default="", description="Google Gemini API key")
    gemini_model: str = Field(
        default="gemini-2.0-flash",
        description="Gemini model to use",
    )
    
    # DeepSeek API Configuration
    deepseek_api_key: str = Field(default="", description="DeepSeek API key")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        description="DeepSeek API base URL",
    )
    deepseek_model: str = Field(
        default="deepseek-reasoner",
        description="DeepSeek model to use (R1)",
    )
    
    # AWS Configuration
    aws_access_key_id: Optional[str] = Field(
        default=None,
        description="AWS access key ID",
    )
    aws_secret_access_key: Optional[str] = Field(
        default=None,
        description="AWS secret access key",
    )
    aws_region: str = Field(
        default="ap-southeast-1",
        description="AWS region",
    )
    
    # Storage Configuration
    storage_type: str = Field(
        default="json",
        description="Storage type: 'json' for local file or 'dynamodb' for DynamoDB",
    )
    json_storage_path: str = Field(
        default="data/coin_analyses.json",
        description="Path to JSON storage file (for local development)",
    )
    
    # DynamoDB Configuration (used when storage_type='dynamodb')
    dynamodb_table_name: str = Field(
        default="lumina_coin_analysis",
        description="DynamoDB table name for coin analysis",
    )
    dynamodb_endpoint_url: str = Field(
        default="http://localhost:8000",
        description="DynamoDB endpoint URL (for local development)",
    )
    use_local_dynamodb: bool = Field(
        default=True,
        description="Use local DynamoDB instance",
    )
    
    # Application Configuration
    trade_mode: str = Field(
        default="paper",
        description="Trading mode: 'paper' or 'live'",
    )
    top_coins_count: int = Field(
        default=200,
        description="Number of top coins by volume to analyze",
    )
    analysis_interval_hours: int = Field(
        default=6,
        description="Hours between analysis cycles",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
    
    # Fundamental Analysis Configuration
    enable_fundamental_analysis: bool = Field(
        default=True,
        description="Enable fundamental data fetching (Fear & Greed, CoinGecko)",
    )
    fundamental_cache_path: str = Field(
        default="data/fundamental_cache.json",
        description="Path to fundamental data cache file",
    )
    coingecko_api_key: Optional[str] = Field(
        default=None,
        description="CoinGecko API key (optional, for higher rate limits)",
    )
    
    # Portfolio Analysis Configuration
    min_portfolio_balance: float = Field(
        default=1.0,
        description="Minimum balance (in coin units) to include portfolio coin in analysis",
    )
    include_portfolio_in_analysis: bool = Field(
        default=True,
        description="Include portfolio holdings in market analysis",
    )
    
    # PNL Tracking Configuration
    trade_fills_cache_path: str = Field(
        default="data/trade_fills_cache.json",
        description="Path to trade fills cache file",
    )
    paper_trades_path: str = Field(
        default="data/paper_trades.json",
        description="Path to paper trades tracking file",
    )
    trade_fills_cache_ttl_hours: int = Field(
        default=1,
        description="Hours before trade fills cache is refreshed",
    )
    
    @property
    def is_live_trading(self) -> bool:
        """Check if live trading is enabled."""
        return self.trade_mode.lower() == "live"
    
    @property
    def is_paper_trading(self) -> bool:
        """Check if paper trading is enabled."""
        return self.trade_mode.lower() == "paper"
    
    def validate_required(self) -> list[str]:
        """
        Validate that required settings are present.
        
        Returns:
            List of missing required settings.
        """
        missing = []
        
        if not self.bitget_api_access_key:
            missing.append("BITGET_API_ACCESS_KEY")
        if not self.bitget_api_secret_key:
            missing.append("BITGET_API_SECRET_KEY")
        if not self.bitget_api_passphrase:
            missing.append("BITGET_API_PASSPHRASE")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if not self.deepseek_api_key:
            missing.append("DEEPSEEK_API_KEY")
        
        return missing


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    Returns:
        Settings instance loaded from environment.
    """
    return Settings()
