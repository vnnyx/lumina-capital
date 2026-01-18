"""
Gemini Analyst Agent - Market data analysis using Gemini 3 Pro.
"""

import json
from datetime import datetime
from typing import Optional

from src.domain.entities.coin_analysis import CoinAnalysis, GeminiInsight
from src.domain.entities.market_data import MarketData, TickerData
from src.domain.ports.llm_port import LLMMessage, LLMPort
from src.domain.ports.market_data_port import MarketDataPort
from src.domain.ports.storage_port import StoragePort
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class GeminiAnalystAgent:
    """
    Gemini-powered market data analyst agent.
    
    Persona: Expert crypto market analyst focused on data gathering,
             pattern recognition, and trend identification.
    
    Task: Analyze market data for each coin, identify trends, volatility,
          correlations, and external factors. Output structured insights
          for the portfolio manager.
    """
    
    # Coin name mapping for common cryptocurrencies
    COIN_NAMES: dict[str, str] = {
        "BTC": "Bitcoin",
        "ETH": "Ethereum",
        "USDT": "Tether",
        "BNB": "BNB",
        "SOL": "Solana",
        "XRP": "Ripple",
        "USDC": "USD Coin",
        "ADA": "Cardano",
        "AVAX": "Avalanche",
        "DOGE": "Dogecoin",
        "DOT": "Polkadot",
        "TRX": "Tron",
        "LINK": "Chainlink",
        "MATIC": "Polygon",
        "TON": "Toncoin",
        "SHIB": "Shiba Inu",
        "LTC": "Litecoin",
        "BCH": "Bitcoin Cash",
        "ATOM": "Cosmos",
        "UNI": "Uniswap",
        "XLM": "Stellar",
        "NEAR": "NEAR Protocol",
        "APT": "Aptos",
        "ARB": "Arbitrum",
        "OP": "Optimism",
        "FIL": "Filecoin",
        "HBAR": "Hedera",
        "VET": "VeChain",
        "ALGO": "Algorand",
        "AAVE": "Aave",
        "SUI": "Sui",
        "INJ": "Injective",
        "IMX": "Immutable X",
        "FTM": "Fantom",
        "SAND": "The Sandbox",
        "MANA": "Decentraland",
        "AXS": "Axie Infinity",
        "CRV": "Curve DAO",
        "RUNE": "THORChain",
        "GALA": "Gala",
        "APE": "ApeCoin",
        "LDO": "Lido DAO",
        "MKR": "Maker",
        "SNX": "Synthetix",
        "COMP": "Compound",
        "ENS": "Ethereum Name Service",
        "PEPE": "Pepe",
        "WIF": "dogwifhat",
        "BONK": "Bonk",
        "FLOKI": "Floki",
        "BGB": "Bitget Token",
        "LIT": "Litentry",
    }
    
    @classmethod
    def get_coin_name(cls, ticker: str) -> str:
        """Get full coin name from ticker symbol."""
        return cls.COIN_NAMES.get(ticker.upper(), ticker)
    
    SYSTEM_PROMPT = """You are an expert cryptocurrency market analyst with deep knowledge of technical analysis, market microstructure, and crypto trading patterns.

## Your Persona
- Name: Market Analyst Alpha
- Expertise: Technical analysis, volume analysis, price action, market sentiment
- Approach: Data-driven, objective, thorough

## Your Context
You are part of an automated investment management system. Your role is to analyze market data and provide structured insights that will be used by a portfolio manager AI to make trading decisions.

## Your Task
Analyze the provided market data for a cryptocurrency and produce a comprehensive technical analysis. Focus on:

1. **Price Trend**: Identify the current trend (bullish/bearish/sideways) based on recent price action
2. **Momentum**: Assess the strength of the current move (strong/moderate/weak)
3. **Volatility**: Calculate and interpret price volatility
4. **Volume Analysis**: Analyze trading volume patterns and their implications
5. **Support/Resistance**: Identify key price levels
6. **Risk Factors**: Note any concerning patterns or risks
7. **Opportunity Factors**: Highlight potential opportunities

## Output Requirements
You MUST respond with valid JSON matching the exact schema provided. Be specific and quantitative where possible. Base all conclusions on the data provided.
"""
    
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "trend": {
                "type": "string",
                "enum": ["bullish", "bearish", "sideways"],
                "description": "Current price trend direction"
            },
            "momentum": {
                "type": "string",
                "enum": ["strong", "moderate", "weak"],
                "description": "Strength of current price movement"
            },
            "volatility_score": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Volatility score from 0 (low) to 1 (high)"
            },
            "volume_trend": {
                "type": "string",
                "enum": ["increasing", "decreasing", "stable"],
                "description": "Recent volume trend"
            },
            "key_observations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key observations about the market data"
            },
            "support_levels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Identified support price levels"
            },
            "resistance_levels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Identified resistance price levels"
            },
            "risk_factors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Identified risk factors"
            },
            "opportunity_factors": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Identified opportunities"
            },
            "data_quality_notes": {
                "type": "string",
                "description": "Notes about data quality or limitations"
            }
        },
        "required": [
            "trend", "momentum", "volatility_score", "volume_trend",
            "key_observations", "risk_factors", "opportunity_factors"
        ]
    }
    
    def __init__(
        self,
        llm: LLMPort,
        market_data_port: MarketDataPort,
        storage_port: StoragePort,
    ):
        """
        Initialize the Gemini analyst agent.
        
        Args:
            llm: LLM adapter (Gemini)
            market_data_port: Market data source
            storage_port: Storage for analysis results
        """
        self.llm = llm
        self.market_data = market_data_port
        self.storage = storage_port
    
    def _format_market_data_prompt(self, market_data: MarketData, rank: int) -> str:
        """Format market data into a prompt for analysis."""
        ticker = market_data.ticker
        
        # Format candle data
        candle_summary = []
        for candle in market_data.candles[-24:]:  # Last 24 candles
            candle_summary.append({
                "time": candle.datetime.isoformat(),
                "open": candle.open_price,
                "high": candle.high_price,
                "low": candle.low_price,
                "close": candle.close_price,
                "volume": candle.base_volume,
            })
        
        prompt = f"""## Market Data for {ticker.symbol}

### Current Ticker Data
- **Symbol**: {ticker.symbol}
- **Current Price**: ${ticker.last_price}
- **24h High**: ${ticker.high_24h}
- **24h Low**: ${ticker.low_24h}
- **24h Open**: ${ticker.open_price}
- **24h Change**: {ticker.change_24h_percent:.2f}%
- **24h Volume (USDT)**: ${ticker.usdt_volume}
- **Volume Rank**: #{rank} (out of top 200)
- **Bid/Ask Spread**: ${ticker.bid_price} / ${ticker.ask_price}

### Price History (Last {len(candle_summary)} {market_data.granularity} candles)
```json
{json.dumps(candle_summary, indent=2)}
```

### Calculated Metrics
- **Simple Trend**: {market_data.price_trend}
- **Volatility (CV)**: {market_data.volatility:.4f}

Please analyze this data and provide your insights."""
        
        return prompt
    
    async def analyze_coin(
        self,
        symbol: str,
        volume_rank: int,
        coin_name: Optional[str] = None,
    ) -> Optional[CoinAnalysis]:
        """
        Analyze a single coin and store the results.
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            volume_rank: Rank by volume (1 = highest)
            coin_name: Full coin name
            
        Returns:
            CoinAnalysis with Gemini insights or None on failure.
        """
        logger.info("Analyzing coin", symbol=symbol, rank=volume_rank)
        
        # Fetch market data
        market_data = await self.market_data.get_market_data(
            symbol=symbol,
            candle_granularity="1h",
            candle_limit=48,  # 48 hours of data
        )
        
        if not market_data:
            logger.warning("No market data available", symbol=symbol)
            return None
        
        # Extract ticker from symbol (remove USDT suffix)
        ticker = symbol.replace("USDT", "")
        if coin_name is None:
            coin_name = self.get_coin_name(ticker)
        
        # Generate analysis prompt
        user_prompt = self._format_market_data_prompt(market_data, volume_rank)
        
        # Get Gemini analysis
        try:
            messages = [
                LLMMessage(role="system", content=self.SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_prompt),
            ]
            
            result = await self.llm.generate_structured(
                messages=messages,
                output_schema=self.OUTPUT_SCHEMA,
                temperature=0.3,
            )
            
            # Create GeminiInsight from response
            insight = GeminiInsight(
                trend=result.get("trend", "unknown"),
                momentum=result.get("momentum", "unknown"),
                volatility_score=float(result.get("volatility_score", 0.5)),
                volume_trend=result.get("volume_trend", "stable"),
                key_observations=result.get("key_observations", []),
                support_levels=result.get("support_levels", []),
                resistance_levels=result.get("resistance_levels", []),
                risk_factors=result.get("risk_factors", []),
                opportunity_factors=result.get("opportunity_factors", []),
                data_quality_notes=result.get("data_quality_notes", ""),
                raw_analysis=json.dumps(result),
            )
            
            # Create coin analysis record
            partition_key = f"{ticker}-{coin_name.upper().replace(' ', '_')}"
            
            # Convert candles to price history
            price_history = [
                {
                    "timestamp": c.timestamp,
                    "open": c.open_price,
                    "high": c.high_price,
                    "low": c.low_price,
                    "close": c.close_price,
                    "volume": c.base_volume,
                }
                for c in market_data.candles[-24:]  # Store last 24 candles
            ]
            
            analysis = CoinAnalysis(
                partition_key=partition_key,
                ticker=ticker,
                coin_name=coin_name,
                symbol=symbol,
                current_price=market_data.ticker.last_price,
                price_change_24h=market_data.ticker.change_24h,
                volume_24h=market_data.ticker.usdt_volume,
                volume_rank=volume_rank,
                price_history=price_history,
                gemini_insight=insight,
                analysis_timestamp=datetime.now(),
            )
            
            # Store in DynamoDB
            await self.storage.save_coin_analysis(analysis)
            
            logger.info(
                "Coin analysis complete",
                symbol=symbol,
                trend=insight.trend,
                momentum=insight.momentum,
            )
            
            return analysis
            
        except Exception as e:
            logger.error("Analysis failed", symbol=symbol, error=str(e))
            return None
    
    async def analyze_top_coins(self, limit: int = 200) -> list[CoinAnalysis]:
        """
        Analyze top coins by volume.
        
        Args:
            limit: Number of top coins to analyze
            
        Returns:
            List of completed analyses.
        """
        logger.info("Starting analysis of top coins", limit=limit)
        
        # Fetch top coins by volume
        top_tickers = await self.market_data.get_top_coins_by_volume(limit=limit)
        
        analyses = []
        
        for rank, ticker in enumerate(top_tickers, start=1):
            # Extract coin ticker and get full name
            coin_ticker = ticker.symbol.replace("USDT", "")
            coin_name = self.get_coin_name(coin_ticker)
            
            analysis = await self.analyze_coin(
                symbol=ticker.symbol,
                volume_rank=rank,
                coin_name=coin_name,
            )
            
            if analysis:
                analyses.append(analysis)
            
            # Log progress every 10 coins
            if rank % 10 == 0:
                logger.info("Analysis progress", completed=rank, total=limit)
        
        logger.info("Analysis complete", total_analyzed=len(analyses))
        
        # Batch save all analyses
        await self.storage.batch_save_analyses(analyses)
        
        return analyses
