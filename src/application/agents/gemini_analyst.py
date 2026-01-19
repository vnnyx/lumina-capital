"""
Gemini Analyst Agent - Market data analysis using Gemini 3 Pro.
"""

import json
from datetime import datetime
from typing import Optional

from src.domain.entities.analysis_history import AnalysisHistoryEntry
from src.domain.entities.coin_analysis import CoinAnalysis, GeminiInsight
from src.domain.entities.fundamental_data import FundamentalData
from src.domain.entities.market_data import MarketData, TickerData
from src.domain.ports.analysis_history_port import AnalysisHistoryPort
from src.domain.ports.fundamental_data_port import FundamentalDataPort
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
    
    SYSTEM_PROMPT = """You are an expert cryptocurrency market analyst with deep knowledge of technical analysis, fundamental analysis, market microstructure, and crypto trading patterns.

## Your Persona
- Name: Market Analyst Alpha
- Expertise: Technical analysis, fundamental analysis, volume analysis, price action, market sentiment
- Approach: Data-driven, objective, thorough

## Your Context
You are part of an automated investment management system. Your role is to analyze market data and provide structured insights that will be used by a portfolio manager AI to make trading decisions.

## Your Task
Analyze the provided market data and fundamental data for a cryptocurrency and produce a comprehensive analysis. Focus on:

### Technical Analysis
1. **Price Trend**: Identify the current trend (bullish/bearish/sideways) based on recent price action
2. **Momentum**: Assess the strength of the current move (strong/moderate/weak)
3. **Volatility**: Calculate and interpret price volatility
4. **Volume Analysis**: Analyze trading volume patterns and their implications
5. **Support/Resistance**: Identify key price levels

### Fundamental Analysis (when data provided)
6. **Market Sentiment**: Consider Fear & Greed Index implications
7. **Market Position**: Evaluate market cap rank and relative valuation
8. **Supply Dynamics**: Consider circulating supply vs max supply
9. **Price Context**: How far from ATH/ATL, 7d/30d performance

### Synthesis
10. **Risk Factors**: Note any concerning patterns or risks (technical AND fundamental)
11. **Opportunity Factors**: Highlight potential opportunities

## Historical Performance Learning
When historical performance data is provided, use it to calibrate your analysis:
- **Correct predictions**: Learn from patterns that led to successful predictions
- **Wrong predictions**: Avoid patterns that previously led to incorrect predictions
- **Accuracy stats**: Calibrate your confidence based on past accuracy for this coin

## Output Requirements
You MUST respond with valid JSON matching the exact schema provided. Be specific and quantitative where possible. Base all conclusions on the data provided. When fundamental data is available, integrate it into your analysis.
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
        fundamental_data_port: Optional[FundamentalDataPort] = None,
        analysis_history_port: Optional[AnalysisHistoryPort] = None,
    ):
        """
        Initialize the Gemini analyst agent.
        
        Args:
            llm: LLM adapter (Gemini)
            market_data_port: Market data source
            storage_port: Storage for analysis results
            fundamental_data_port: Optional fundamental data source
            analysis_history_port: Optional history storage for prompt fine-tuning
        """
        self.llm = llm
        self.market_data = market_data_port
        self.storage = storage_port
        self.fundamental_data = fundamental_data_port
        self.analysis_history = analysis_history_port
        self._cached_fundamental_data: Optional[FundamentalData] = None
    
    async def _build_history_context(self, ticker: str) -> str:
        """
        Build historical context from past predictions for prompt fine-tuning.
        
        Fetches correct and wrong predictions to provide few-shot examples
        and accuracy stats for confidence calibration.
        
        Args:
            ticker: Coin ticker (e.g., "BTC")
            
        Returns:
            Formatted string with historical context, or empty string if no history.
        """
        if not self.analysis_history:
            return ""
        
        try:
            # Fetch correct predictions (patterns to follow)
            correct_entries = await self.analysis_history.get_history_by_outcome(
                ticker=ticker,
                outcome_label="correct",
                limit=3,
                max_age_days=14,
            )
            
            # Fetch wrong predictions (anti-patterns to avoid)
            wrong_entries = await self.analysis_history.get_history_by_outcome(
                ticker=ticker,
                outcome_label="wrong",
                limit=2,
                max_age_days=14,
            )
            
            # Fetch accuracy stats for calibration
            accuracy_stats = await self.analysis_history.get_accuracy_stats(ticker)
            
            # If no history at all, return empty (cold start)
            if not correct_entries and not wrong_entries and accuracy_stats.get("total", 0) == 0:
                logger.debug("no_history_context_available", ticker=ticker)
                return ""
            
            # Build the context string
            context_parts = ["\n\n## Historical Performance Data"]
            
            # Add accuracy stats section
            if accuracy_stats.get("total", 0) > 0:
                context_parts.append(f"""
### Accuracy Statistics (Last 14 Days)
- Total predictions: {accuracy_stats['total']}
- Correct: {accuracy_stats['correct']} ({accuracy_stats['accuracy_pct']:.1f}%)
- Wrong: {accuracy_stats['wrong']}
- Neutral: {accuracy_stats['neutral']}

Use these stats to calibrate your confidence. {"Higher confidence is justified." if accuracy_stats['accuracy_pct'] >= 60 else "Be more cautious with predictions." if accuracy_stats['accuracy_pct'] < 50 else "Maintain balanced confidence."}""")
            
            # Add correct predictions as patterns to follow
            if correct_entries:
                context_parts.append("\n### Successful Predictions (Patterns to Follow)")
                for i, entry in enumerate(correct_entries, 1):
                    outcome = entry.outcome
                    context_parts.append(f"""
**Example {i}**: {entry.timestamp.strftime('%Y-%m-%d %H:%M')}
- Price at analysis: ${entry.price_at_analysis:,.2f} (24h change: {entry.change_24h_at_analysis:+.2f}%)
- Prediction: {entry.predicted_trend} trend, {entry.predicted_momentum} momentum
- Volatility score: {entry.volatility_score:.2f}
- Outcome: ✅ Price moved {outcome.price_change_pct:+.2f}% in 4h (correctly predicted)
- Key observations: {', '.join(entry.key_observations[:2]) if entry.key_observations else 'N/A'}""")
            
            # Add wrong predictions as anti-patterns
            if wrong_entries:
                context_parts.append("\n### Failed Predictions (Anti-Patterns to Avoid)")
                for i, entry in enumerate(wrong_entries, 1):
                    outcome = entry.outcome
                    context_parts.append(f"""
**Mistake {i}**: {entry.timestamp.strftime('%Y-%m-%d %H:%M')}
- Price at analysis: ${entry.price_at_analysis:,.2f} (24h change: {entry.change_24h_at_analysis:+.2f}%)
- Prediction: {entry.predicted_trend} trend, {entry.predicted_momentum} momentum
- Volatility score: {entry.volatility_score:.2f}
- Outcome: ❌ Price moved {outcome.price_change_pct:+.2f}% in 4h (prediction was wrong)
- Key observations: {', '.join(entry.key_observations[:2]) if entry.key_observations else 'N/A'}
- Lesson: Avoid similar pattern recognition that led to this incorrect prediction.""")
            
            context_parts.append("\n\nUse the above historical data to improve your current analysis accuracy.")
            
            logger.debug(
                "built_history_context",
                ticker=ticker,
                correct_count=len(correct_entries),
                wrong_count=len(wrong_entries),
                total_predictions=accuracy_stats.get("total", 0),
            )
            
            return "\n".join(context_parts)
            
        except Exception as e:
            logger.warning("failed_to_build_history_context", ticker=ticker, error=str(e))
            return ""
    
    def _format_market_data_prompt(
        self,
        market_data: MarketData,
        rank: int,
        fundamental_data: Optional[FundamentalData] = None,
    ) -> str:
        """Format market data and fundamental data into a prompt for analysis."""
        ticker = market_data.ticker
        coin_ticker = ticker.symbol.replace("USDT", "")
        
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
"""
        
        # Add fundamental data section if available
        if fundamental_data:
            fundamental_section = fundamental_data.get_summary_for_prompt(coin_ticker)
            if fundamental_section:
                prompt += f"\n{fundamental_section}\n"
        
        prompt += "\nPlease analyze this data and provide your insights."
        
        return prompt
    
    async def analyze_coin(
        self,
        symbol: str,
        volume_rank: int,
        coin_name: Optional[str] = None,
        fundamental_data: Optional[FundamentalData] = None,
    ) -> Optional[CoinAnalysis]:
        """
        Analyze a single coin and store the results.
        
        Args:
            symbol: Trading pair symbol (e.g., BTCUSDT)
            volume_rank: Rank by volume (1 = highest)
            coin_name: Full coin name
            fundamental_data: Optional pre-fetched fundamental data
            
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
        
        # Use passed fundamental data or cached data
        fund_data = fundamental_data or self._cached_fundamental_data
        
        # Generate analysis prompt
        user_prompt = self._format_market_data_prompt(market_data, volume_rank, fund_data)
        
        # Build historical context for prompt fine-tuning
        history_context = await self._build_history_context(ticker)
        if history_context:
            user_prompt += history_context
        
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
            
            # Save to history for prompt fine-tuning
            if self.analysis_history:
                try:
                    history_entry = AnalysisHistoryEntry.from_coin_analysis(analysis)
                    await self.analysis_history.save_history(history_entry)
                    logger.debug("saved_to_analysis_history", ticker=ticker)
                except Exception as hist_err:
                    logger.warning("failed_to_save_history", ticker=ticker, error=str(hist_err))
            
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
    
    async def analyze_top_coins(
        self,
        limit: int = 200,
        include_symbols: Optional[list[str]] = None,
    ) -> list[CoinAnalysis]:
        """
        Analyze top coins by volume plus additional symbols.
        
        Args:
            limit: Number of top coins to analyze
            include_symbols: Additional symbols to include (e.g., portfolio holdings)
                            These will be deduplicated against top coins.
            
        Returns:
            List of completed analyses.
        """
        logger.info(
            "Starting analysis of top coins",
            limit=limit,
            additional_symbols=len(include_symbols) if include_symbols else 0,
        )
        
        # Fetch top coins by volume
        top_tickers = await self.market_data.get_top_coins_by_volume(limit=limit)
        
        # Build set of symbols already in top coins for deduplication
        top_symbols_set = {t.symbol for t in top_tickers}
        
        # Find additional symbols not already in top coins
        additional_tickers: list[TickerData] = []
        if include_symbols:
            for symbol in include_symbols:
                trading_symbol = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
                if trading_symbol not in top_symbols_set:
                    # Fetch ticker for this symbol
                    try:
                        ticker = await self.market_data.get_ticker(trading_symbol)
                        if ticker:
                            additional_tickers.append(ticker)
                            logger.info(
                                "Added portfolio coin to analysis",
                                symbol=trading_symbol,
                            )
                    except Exception as e:
                        logger.warning(
                            "Failed to fetch ticker for portfolio coin",
                            symbol=trading_symbol,
                            error=str(e),
                        )
        
        # Fetch fundamental data once for all coins (if enabled)
        fundamental_data: Optional[FundamentalData] = None
        if self.fundamental_data:
            try:
                # Get tickers for fundamental data fetch
                tickers_for_fundamentals = [
                    t.symbol.replace("USDT", "") for t in top_tickers[:20]
                ]
                logger.info("Fetching fundamental data", tickers=len(tickers_for_fundamentals))
                fundamental_data = await self.fundamental_data.get_all_fundamental_data(
                    tickers=tickers_for_fundamentals
                )
                # Cache for individual coin analyses
                self._cached_fundamental_data = fundamental_data
                
                if fundamental_data.fear_greed:
                    logger.info(
                        "Fear & Greed Index fetched",
                        value=fundamental_data.fear_greed.value,
                        label=fundamental_data.fear_greed.label,
                    )
                logger.info(
                    "Coin metrics fetched",
                    count=len(fundamental_data.coin_metrics),
                )
            except Exception as e:
                logger.warning("Failed to fetch fundamental data, continuing without it", error=str(e))
        
        analyses = []
        total_coins = len(top_tickers) + len(additional_tickers)
        
        # Analyze top coins by volume
        for rank, ticker in enumerate(top_tickers, start=1):
            # Extract coin ticker and get full name
            coin_ticker = ticker.symbol.replace("USDT", "")
            coin_name = self.get_coin_name(coin_ticker)
            
            analysis = await self.analyze_coin(
                symbol=ticker.symbol,
                volume_rank=rank,
                coin_name=coin_name,
                fundamental_data=fundamental_data,
            )
            
            if analysis:
                analyses.append(analysis)
            
            # Log progress every 10 coins
            if rank % 10 == 0:
                logger.info("Analysis progress", completed=rank, total=total_coins)
        
        # Analyze additional portfolio coins (rank = limit + index)
        for idx, ticker in enumerate(additional_tickers):
            coin_ticker = ticker.symbol.replace("USDT", "")
            coin_name = self.get_coin_name(coin_ticker)
            rank = limit + idx + 1  # Rank after all top coins
            
            analysis = await self.analyze_coin(
                symbol=ticker.symbol,
                volume_rank=rank,
                coin_name=coin_name,
                fundamental_data=fundamental_data,
            )
            
            if analysis:
                analyses.append(analysis)
            
            logger.info(
                "Analyzed portfolio coin",
                symbol=ticker.symbol,
                rank=rank,
            )
        
        logger.info(
            "Analysis complete",
            total_analyzed=len(analyses),
            top_coins=len(top_tickers),
            portfolio_coins=len(additional_tickers),
        )
        
        # Batch save all analyses
        await self.storage.batch_save_analyses(analyses)
        
        return analyses
