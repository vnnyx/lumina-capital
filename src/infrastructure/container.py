"""
Dependency injection container for the application.
"""

from dataclasses import dataclass
from typing import Optional

from src.adapters.bitget.client import BitgetClient
from src.adapters.bitget.market_data_adapter import BitgetMarketDataAdapter
from src.adapters.bitget.trading_adapter import BitgetTradingAdapter
from src.adapters.bitget.trade_fills_cache import TradeFillsCache
from src.adapters.dynamodb.repository import DynamoDBStorageAdapter
from src.adapters.dynamodb.analysis_history_repository import DynamoDBAnalysisHistoryAdapter
from src.adapters.dynamodb.paper_trades_repository import DynamoDBPaperTradesAdapter
from src.adapters.fundamental.fundamental_data_service import FundamentalDataService
from src.adapters.llm.deepseek_adapter import DeepSeekAdapter
from src.adapters.llm.gemini_adapter import GeminiAdapter
from src.adapters.storage.json_storage_adapter import JSONStorageAdapter
from src.adapters.storage.json_analysis_history import JsonAnalysisHistoryAdapter
from src.adapters.storage.paper_trades_tracker import PaperTradesTracker
from src.domain.ports.storage_port import StoragePort
from src.domain.ports.analysis_history_port import AnalysisHistoryPort
from src.domain.ports.paper_trades_port import PaperTradesPort
from src.domain.ports.fundamental_data_port import FundamentalDataPort
from src.application.agents.deepseek_manager import DeepSeekManagerAgent
from src.application.agents.gemini_analyst import GeminiAnalystAgent
from src.application.services.outcome_backfill import OutcomeBackfillService
from src.application.use_cases.investment_cycle import InvestmentCycleUseCase
from src.infrastructure.config import Settings


@dataclass
class Container:
    """
    Dependency injection container.
    
    Provides configured instances of all application components.
    """
    
    settings: Settings
    
    # Adapters
    bitget_client: BitgetClient
    market_data_adapter: BitgetMarketDataAdapter
    trading_adapter: BitgetTradingAdapter
    storage_adapter: StoragePort  # Can be JSON or DynamoDB
    analysis_history_adapter: AnalysisHistoryPort  # Analysis history storage
    gemini_adapter: GeminiAdapter
    deepseek_adapter: DeepSeekAdapter
    fundamental_data_service: Optional[FundamentalDataPort]  # Fundamental data
    
    # Agents
    analyst_agent: GeminiAnalystAgent
    manager_agent: DeepSeekManagerAgent
    
    # Services
    outcome_backfill: OutcomeBackfillService
    
    # Use cases
    investment_cycle: InvestmentCycleUseCase
    
    _initialized: bool = False


_container: Optional[Container] = None


async def create_container(settings: Optional[Settings] = None) -> Container:
    """
    Create and configure the dependency container.
    
    Args:
        settings: Optional settings override
        
    Returns:
        Configured Container instance.
    """
    global _container
    
    if settings is None:
        from src.infrastructure.config import get_settings
        settings = get_settings()
    
    # Create Bitget client
    bitget_client = BitgetClient(settings)
    
    # Create PNL tracking services
    trade_fills_cache: Optional[TradeFillsCache] = None
    paper_trades_tracker: Optional[PaperTradesPort] = None
    
    if settings.trade_mode == "paper":
        # Paper mode: use paper trades tracker (JSON or DynamoDB based on storage_type)
        if settings.storage_type.lower() == "dynamodb":
            paper_trades_tracker = DynamoDBPaperTradesAdapter(settings)
            await paper_trades_tracker.initialize_table()
        else:
            paper_trades_tracker = PaperTradesTracker(
                storage_path=settings.paper_trades_path,
            )
    else:
        # Live mode: use trade fills cache
        trade_fills_cache = TradeFillsCache(
            client=bitget_client,
            cache_path=settings.trade_fills_cache_path,
            cache_ttl_hours=settings.trade_fills_cache_ttl_hours,
        )
    
    # Create adapters
    market_data_adapter = BitgetMarketDataAdapter(bitget_client, settings)
    trading_adapter = BitgetTradingAdapter(
        client=bitget_client,
        settings=settings,
        trade_fills_cache=trade_fills_cache,
        paper_trades_tracker=paper_trades_tracker,
    )
    gemini_adapter = GeminiAdapter(settings)
    deepseek_adapter = DeepSeekAdapter(settings)
    
    # Create storage adapter based on configuration
    storage_adapter: StoragePort
    analysis_history_adapter: AnalysisHistoryPort
    
    if settings.storage_type.lower() == "json":
        storage_adapter = JSONStorageAdapter(settings.json_storage_path)
        analysis_history_adapter = JsonAnalysisHistoryAdapter()
    else:
        storage_adapter = DynamoDBStorageAdapter(settings)
        analysis_history_adapter = DynamoDBAnalysisHistoryAdapter(settings)
        # Initialize DynamoDB tables
        await storage_adapter.initialize_tables()
        await analysis_history_adapter.initialize_table()
    
    # Create fundamental data service if enabled
    fundamental_data_service: Optional[FundamentalDataPort] = None
    if settings.enable_fundamental_analysis:
        fundamental_data_service = FundamentalDataService(
            cache_path=settings.fundamental_cache_path,
            coingecko_api_key=settings.coingecko_api_key,
        )
    
    # Create agents
    analyst_agent = GeminiAnalystAgent(
        llm=gemini_adapter,
        market_data_port=market_data_adapter,
        storage_port=storage_adapter,
        fundamental_data_port=fundamental_data_service,
        analysis_history_port=analysis_history_adapter,
    )
    
    manager_agent = DeepSeekManagerAgent(
        llm=deepseek_adapter,
        storage_port=storage_adapter,
        trading_port=trading_adapter,
        settings=settings,
        market_data_port=market_data_adapter,
    )
    
    # Create services
    outcome_backfill = OutcomeBackfillService(
        history_port=analysis_history_adapter,
        market_data_port=market_data_adapter,
    )
    
    # Create use cases
    investment_cycle = InvestmentCycleUseCase(
        analyst_agent=analyst_agent,
        manager_agent=manager_agent,
        trading_port=trading_adapter,
        settings=settings,
        top_coins_count=settings.top_coins_count,
    )
    
    _container = Container(
        settings=settings,
        bitget_client=bitget_client,
        market_data_adapter=market_data_adapter,
        trading_adapter=trading_adapter,
        storage_adapter=storage_adapter,
        analysis_history_adapter=analysis_history_adapter,
        gemini_adapter=gemini_adapter,
        deepseek_adapter=deepseek_adapter,
        fundamental_data_service=fundamental_data_service,
        analyst_agent=analyst_agent,
        manager_agent=manager_agent,
        outcome_backfill=outcome_backfill,
        investment_cycle=investment_cycle,
        _initialized=True,
    )
    
    return _container


def get_container() -> Container:
    """
    Get the current container instance.
    
    Returns:
        The configured Container.
        
    Raises:
        RuntimeError: If container not initialized.
    """
    if _container is None:
        raise RuntimeError("Container not initialized. Call create_container() first.")
    return _container


async def cleanup_container() -> None:
    """Clean up container resources."""
    global _container
    
    if _container is not None:
        await _container.bitget_client.close()
        if _container.fundamental_data_service:
            await _container.fundamental_data_service.close()
        _container = None
