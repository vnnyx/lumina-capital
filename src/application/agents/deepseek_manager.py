"""
DeepSeek Manager Agent - Autonomous portfolio management using DeepSeek R1.
"""

import json
from datetime import datetime
from typing import Any, Optional

from src.domain.entities.coin_analysis import CoinAnalysis
from src.domain.entities.market_data import TickerData
from src.domain.entities.portfolio import Portfolio
from src.domain.entities.trade_decision import TradeAction, TradeDecision
from src.domain.entities.trade_outcome import PortfolioStats, PositionPerformance, TradeOutcome
from src.domain.ports.llm_port import LLMMessage, LLMPort
from src.domain.ports.market_data_port import MarketDataPort
from src.domain.ports.storage_port import StoragePort
from src.domain.ports.trading_port import TradingPort
from src.domain.ports.trade_outcome_port import TradeOutcomePort
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class DeepSeekManagerAgent:
    """
    DeepSeek R1-powered autonomous portfolio manager agent.
    
    Persona: Senior portfolio manager with full autonomy over investment
             decisions. Expert in risk management, position sizing, and
             portfolio optimization.
    
    Task: Evaluate the entire portfolio holistically using Gemini analyses,
          determine optimal allocation, and output trade decisions. The agent
          has complete freedom to determine its own risk management strategy.
    """
    
    SYSTEM_PROMPT = """You are an autonomous senior portfolio manager for a cryptocurrency investment fund with FULL AUTHORITY over all trading decisions.

## Your Persona
- Name: Portfolio Manager Omega
- Role: Chief Investment Officer with complete autonomy
- Philosophy: Data-driven decision making with dynamic risk management
- Experience: 15+ years in quantitative trading and portfolio management

## Your Authority
You have COMPLETE AUTONOMY to:
- Decide position sizes (including going to 0% or 100% in any asset)
- Set your own risk parameters and change them as market conditions evolve
- Determine entry/exit timing
- Choose which coins to trade and which to ignore
- Set your own stop-loss and take-profit strategies
- Rebalance the portfolio as you see fit

There are NO hardcoded constraints on your decisions. You are trusted to manage the portfolio as you see fit based on your analysis.

## Your Context
You receive:
1. Market analysis data from our analyst agent (Gemini) for top coins by volume, including:
   - analysis_price: Price when the analysis was performed
   - change_24h_at_analysis: The 24-hour price change % when analysis was performed
   - fresh_price: Current real-time price (fetched just now)
   - fresh_change_24h: The current 24-hour price change % (fetched just now)
   - price_change_since_analysis: How much the price moved since analysis
   - analysis_age: How long ago the analysis was performed (e.g., "2.5 hours ago")
   - trend, momentum, volatility: Qualitative insights from the analysis
2. Current portfolio holdings with PNL data:
   - avg_entry_price: Your average cost basis for the position
   - current_price: Current market price
   - unrealized_pnl: Unrealized profit/loss in USDT
   - unrealized_pnl_pct: Unrealized P&L as a percentage
3. Recent trading decisions for context
4. **Your Historical Trade Performance** (CRITICAL for learning):
   - Recent closed trades with actual realized P&L
   - Per-coin win rates and average P&L
   - Portfolio-wide statistics: total trades, win rate, current streak
   - USE THIS DATA to learn from past successes and mistakes!

## Using Price Data
The analysis includes both the price at analysis time and the current fresh price. Use this to:
- Identify if a coin has moved significantly since analysis (potential opportunity or warning)
- Make decisions based on FRESH prices, not stale analysis prices
- Consider if a bullish trend + price dip = buy opportunity
- Consider if a bearish trend + price spike = sell opportunity
- Note: If fresh_price is missing, the price fetch failed and analysis_price is shown instead

## Using Momentum Shifts
Compare change_24h_at_analysis with fresh_change_24h to detect momentum shifts:
- If change_24h_at_analysis was +5% but fresh_change_24h is +2%, momentum is fading
- If change_24h_at_analysis was -3% but fresh_change_24h is +1%, momentum has reversed bullish
- Significant divergence between the two suggests rapid market movement since analysis

## Using PNL Data
The portfolio includes unrealized PNL data for each position. Use this to:
- Identify positions in profit that might be worth taking gains on
- Identify losing positions that may need to be cut or averaged down
- Make informed decisions about position sizing relative to your cost basis
- Consider unrealized_pnl_pct to assess the magnitude of gains/losses
- Note: If PNL shows 0%, it means we don't have historical cost basis data for that position

## Learning from Trade History
You receive your historical trade performance data. CRITICAL: Use this to improve decisions:
- If a coin has high win rate in your history, consider it for similar setups
- If a coin has been consistently losing, be more cautious or avoid it
- If your current streak is negative (losing), consider being more conservative
- Review your average holding duration to inform timing decisions
- Your past mistakes are learning opportunities - don't repeat patterns that led to losses

## Your Task
1. Review all market analyses and current portfolio state (including PNL)
2. **Review your trade history to understand what worked and what didn't**
3. Develop your investment thesis and risk management approach
4. Make specific, actionable trading decisions
5. Provide clear reasoning for each decision, referencing PNL and historical performance when relevant

## Decision Framework (suggestions, not requirements)
- Consider correlation between assets
- Think about market regime (bull/bear/sideways)
- Factor in volatility and liquidity
- Consider portfolio concentration risk
- Account for transaction costs
- Use PNL data to inform profit-taking or loss-cutting decisions

## Output Requirements
Return a JSON object with your decisions. Each decision should include:
- symbol: Trading pair (e.g., "BTCUSDT")
- action: "buy", "sell", or "hold"
- quantity: Amount to trade (in quote currency for buys, base currency for sells)
- reasoning: Your detailed reasoning
- confidence: Your confidence level (0.0 to 1.0)
- priority: Execution priority (higher = execute first)

Be decisive. If you believe no action is optimal, explicitly state "hold" with reasoning.
"""
    
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "market_assessment": {
                "type": "string",
                "description": "Overall market assessment and thesis"
            },
            "risk_approach": {
                "type": "string",
                "description": "Your risk management approach for this cycle"
            },
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
                        "quantity": {"type": "string"},
                        "order_type": {"type": "string", "enum": ["market", "limit"]},
                        "price": {"type": "string", "description": "Limit price if order_type is limit"},
                        "reasoning": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "priority": {"type": "integer"}
                    },
                    "required": ["symbol", "action", "reasoning", "confidence"]
                }
            },
            "portfolio_notes": {
                "type": "string",
                "description": "Notes about overall portfolio strategy"
            }
        },
        "required": ["market_assessment", "risk_approach", "decisions"]
    }
    
    def __init__(
        self,
        llm: LLMPort,
        storage_port: StoragePort,
        trading_port: TradingPort,
        settings: Settings,
        market_data_port: Optional[MarketDataPort] = None,
        trade_outcome_port: Optional[TradeOutcomePort] = None,
    ):
        """
        Initialize the DeepSeek manager agent.
        
        Args:
            llm: LLM adapter (DeepSeek R1)
            storage_port: Storage for retrieving analyses and storing decisions
            trading_port: Trading interface for execution
            settings: Application settings
            market_data_port: Optional market data port for fetching fresh prices
            trade_outcome_port: Optional port for trade outcome/P&L history
        """
        self.llm = llm
        self.storage = storage_port
        self.trading = trading_port
        self.settings = settings
        self.market_data = market_data_port
        self.trade_outcomes = trade_outcome_port
    
    def _format_analyses_summary(
        self,
        analyses: list[CoinAnalysis],
        fresh_prices: Optional[dict[str, TickerData]] = None,
    ) -> str:
        """Format analyses into a summary for the manager with fresh prices."""
        summaries = []
        
        for analysis in analyses:
            if analysis.gemini_insight is None:
                continue
            
            insight = analysis.gemini_insight
            symbol = f"{analysis.ticker}USDT"
            
            # Get fresh price if available
            fresh_ticker = fresh_prices.get(symbol) if fresh_prices else None
            analysis_price = float(analysis.current_price)
            
            summary = {
                "symbol": symbol,
                "ticker": analysis.ticker,
                "analysis_price": analysis_price,
                "change_24h_at_analysis": f"{float(analysis.price_change_24h) * 100:.2f}%",
                "volume_24h_usdt": analysis.volume_24h,
                "volume_rank": analysis.volume_rank,
                "trend": insight.trend,
                "momentum": insight.momentum,
                "volatility_score": insight.volatility_score,
                "volume_trend": insight.volume_trend,
                "key_observations": insight.key_observations[:3],  # Top 3
                "risk_factors": insight.risk_factors[:2],  # Top 2
                "opportunity_factors": insight.opportunity_factors[:2],  # Top 2
            }
            
            # Add fresh price data if available
            if fresh_ticker and fresh_ticker.last_price:
                fresh_price = float(fresh_ticker.last_price)
                summary["fresh_price"] = fresh_price
                summary["fresh_change_24h"] = f"{float(fresh_ticker.change_24h) * 100:.2f}%"
                
                # Calculate price change since analysis
                if analysis_price > 0:
                    price_change_pct = ((fresh_price - analysis_price) / analysis_price) * 100
                    summary["price_change_since_analysis"] = f"{price_change_pct:+.2f}%"
            else:
                # Fallback: use stale data from analysis
                summary["fresh_price"] = analysis_price
                summary["fresh_change_24h"] = f"{float(analysis.price_change_24h) * 100:.2f}% (stale)"
                summary["price_change_since_analysis"] = "0.00% (stale)"
            
            # Add analysis age
            if analysis.analysis_timestamp:
                try:
                    analyzed_time = analysis.analysis_timestamp
                    # Handle both datetime and string formats
                    if isinstance(analyzed_time, str):
                        analyzed_time = datetime.fromisoformat(analyzed_time.replace("Z", "+00:00"))
                    
                    now = datetime.now(analyzed_time.tzinfo) if analyzed_time.tzinfo else datetime.now()
                    age_seconds = (now - analyzed_time).total_seconds()
                    if age_seconds < 3600:
                        summary["analysis_age"] = f"{int(age_seconds / 60)} minutes ago"
                    else:
                        summary["analysis_age"] = f"{age_seconds / 3600:.1f} hours ago"
                except (ValueError, TypeError):
                    summary["analysis_age"] = "unknown"
            
            summaries.append(summary)
        
        return json.dumps(summaries, indent=2)
    
    def _format_portfolio_summary(self, portfolio: Portfolio) -> str:
        """Format portfolio into a summary for the manager with PNL data and health metrics."""
        min_balance = self.settings.min_portfolio_balance
        
        # Critical warning for no available capital
        capital_warning = None
        if portfolio.usdt_balance <= 0:
            capital_warning = "⚠️ CRITICAL: NO USDT AVAILABLE FOR BUYING! You CANNOT execute any BUY orders. Only SELL or HOLD actions are possible."
        elif portfolio.usdt_balance < 10:
            capital_warning = f"⚠️ WARNING: Very low USDT balance ({portfolio.usdt_balance:.2f}). Consider selling positions before buying."
        
        summary = {
            "available_usdt": portfolio.usdt_balance,
            "capital_warning": capital_warning,
            "total_positions": portfolio.total_positions,
            "min_balance_filter": min_balance,
            "positions": [],
            "total_unrealized_pnl": 0.0,
            "health_metrics": {},  # Portfolio health indicators
        }
        
        total_pnl = 0.0
        position_values: list[tuple[str, float]] = []  # (coin, value) for concentration calc
        winning_positions = 0
        losing_positions = 0
        
        for position in portfolio.positions:
            # Filter out dust positions below minimum balance threshold
            if position.total_balance > min_balance and position.coin.upper() != "USDT":
                pos_data = {
                    "coin": position.coin,
                    "available": position.available,
                    "frozen": position.frozen,
                    "total": position.total_balance,
                }
                
                # Add PNL data if available
                if position.current_price is not None:
                    pos_data["current_price"] = round(position.current_price, 6)
                    # Calculate position value for concentration metrics
                    pos_value = position.total_balance * position.current_price
                    position_values.append((position.coin, pos_value))
                
                if position.avg_entry_price is not None:
                    pos_data["avg_entry_price"] = round(position.avg_entry_price, 6)
                
                if position.unrealized_pnl is not None:
                    pos_data["unrealized_pnl"] = round(position.unrealized_pnl, 2)
                    total_pnl += position.unrealized_pnl
                    # Track winning/losing positions
                    if position.unrealized_pnl > 0:
                        winning_positions += 1
                    elif position.unrealized_pnl < 0:
                        losing_positions += 1
                
                if position.unrealized_pnl_pct is not None:
                    pos_data["unrealized_pnl_pct"] = round(position.unrealized_pnl_pct, 2)
                
                summary["positions"].append(pos_data)
        
        summary["total_unrealized_pnl"] = round(total_pnl, 2)
        
        # Calculate portfolio health metrics
        total_portfolio_value = portfolio.usdt_balance + sum(v for _, v in position_values)
        
        if total_portfolio_value > 0 and position_values:
            # Sort positions by value (descending)
            position_values.sort(key=lambda x: x[1], reverse=True)
            
            # Calculate concentration metrics
            largest_position = position_values[0]
            largest_pct = (largest_position[1] / total_portfolio_value) * 100
            
            # Top 3 concentration
            top3_value = sum(v for _, v in position_values[:3])
            top3_pct = (top3_value / total_portfolio_value) * 100
            
            # Cash ratio
            cash_pct = (portfolio.usdt_balance / total_portfolio_value) * 100
            
            summary["health_metrics"] = {
                "total_portfolio_value_usdt": round(total_portfolio_value, 2),
                "cash_percentage": round(cash_pct, 1),
                "largest_position": {
                    "coin": largest_position[0],
                    "value_usdt": round(largest_position[1], 2),
                    "percentage": round(largest_pct, 1),
                },
                "top3_concentration_pct": round(top3_pct, 1),
                "winning_positions": winning_positions,
                "losing_positions": losing_positions,
                "diversification_score": len(position_values),  # Number of positions
                "concentration_warning": largest_pct > 30,  # Soft warning, not blocking
            }
        
        return json.dumps(summary, indent=2)
    
    def _format_recent_decisions(self, decisions: list[dict]) -> str:
        """Format recent decisions for context."""
        if not decisions:
            return "No recent decisions."
        
        formatted = []
        for d in decisions[:10]:  # Last 10 decisions
            formatted.append({
                "timestamp": d.get("sk", "unknown"),
                "symbol": d.get("symbol", "unknown"),
                "action": d.get("action", "unknown"),
                "quantity": d.get("quantity", "0"),
                "reasoning": d.get("reasoning", "")[:100],  # Truncate
            })
        
        return json.dumps(formatted, indent=2)
    
    async def _format_trade_history(self) -> str:
        """Format trade outcome history for learning context."""
        if not self.trade_outcomes:
            return "No trade history available yet."
        
        try:
            # Get portfolio-wide stats
            stats = await self.trade_outcomes.get_portfolio_stats()
            
            # Get recent closed trades (last 20)
            recent_outcomes = await self.trade_outcomes.get_recent_outcomes(limit=20)
            
            # Get per-position performance
            position_perfs = await self.trade_outcomes.get_all_position_performance()
            
            history = {
                "portfolio_stats": {
                    "total_closed_trades": stats.total_trades,
                    "winning_trades": stats.winning_trades,
                    "losing_trades": stats.losing_trades,
                    "win_rate_pct": round(stats.win_rate, 1),
                    "total_realized_pnl": round(stats.total_realized_pnl, 2),
                    "largest_win": round(stats.largest_win, 2),
                    "largest_loss": round(stats.largest_loss, 2),
                    "current_streak": stats.current_streak,
                    "max_winning_streak": stats.max_winning_streak,
                    "max_losing_streak": stats.max_losing_streak,
                },
                "per_coin_performance": [],
                "recent_trades": [],
            }
            
            # Add per-coin performance
            for perf in position_perfs:
                if perf.total_trades > 0:
                    history["per_coin_performance"].append({
                        "coin": perf.coin,
                        "total_trades": perf.total_trades,
                        "win_rate_pct": round(perf.win_rate, 1),
                        "total_pnl": round(perf.total_realized_pnl, 2),
                        "avg_pnl_per_trade": round(perf.avg_pnl_per_trade, 2),
                        "avg_holding_hours": round(perf.avg_holding_duration_hours, 1),
                        "best_trade": round(perf.best_trade_pnl, 2),
                        "worst_trade": round(perf.worst_trade_pnl, 2),
                    })
            
            # Add recent trades (last 20)
            for outcome in recent_outcomes:
                trade_summary = {
                    "coin": outcome.coin,
                    "entry_price": round(outcome.entry_price, 6),
                    "exit_price": round(outcome.exit_price, 6) if outcome.exit_price else None,
                    "quantity": round(outcome.entry_quantity, 6),
                    "realized_pnl": round(outcome.realized_pnl, 2) if outcome.realized_pnl else 0,
                    "realized_pnl_pct": round(outcome.realized_pnl_pct, 2) if outcome.realized_pnl_pct else 0,
                    "holding_hours": round(outcome.holding_duration_hours, 1) if outcome.holding_duration_hours else 0,
                    "result": "WIN" if outcome.is_winner else "LOSS",
                }
                history["recent_trades"].append(trade_summary)
            
            if stats.total_trades == 0:
                return "No closed trades yet. This is the beginning of your trading history."
            
            return json.dumps(history, indent=2)
            
        except Exception as e:
            logger.warning("Failed to format trade history", error=str(e))
            return "Trade history temporarily unavailable."
    
    async def generate_decisions(self) -> list[TradeDecision]:
        """
        Generate trading decisions based on current market data and portfolio.
        
        Returns:
            List of TradeDecision objects to execute.
        """
        logger.info("Generating portfolio decisions")
        
        # Fetch all market analyses
        analyses = await self.storage.get_all_analyses()
        if not analyses:
            logger.warning("No analyses available for decision making")
            return []
        
        # Sort by volume rank
        analyses.sort(key=lambda a: a.volume_rank)
        
        # Fetch fresh prices from market data
        fresh_prices: Optional[dict[str, TickerData]] = None
        if self.market_data:
            try:
                all_tickers = await self.market_data.get_all_tickers()
                fresh_prices = {t.symbol: t for t in all_tickers}
                logger.info("Fresh prices fetched", count=len(fresh_prices))
            except Exception as e:
                logger.warning(
                    "Failed to fetch fresh prices, using stale analysis prices",
                    error=str(e),
                )
        
        # Fetch current portfolio
        portfolio = await self.trading.get_portfolio()
        
        # Fetch recent decisions for context
        recent_decisions = await self.storage.get_recent_decisions(limit=10)
        
        # Fetch trade outcome history for learning
        trade_history = await self._format_trade_history()
        
        # Build the prompt
        user_prompt = f"""## Current Market Analyses (Top {len(analyses)} coins by volume)

{self._format_analyses_summary(analyses, fresh_prices)}

## Current Portfolio State

{self._format_portfolio_summary(portfolio)}

## Your Trade History (LEARN FROM THIS!)

{trade_history}

## Recent Trading Decisions (for context)

{self._format_recent_decisions(recent_decisions)}

## Current Timestamp
{datetime.now().isoformat()}

---

Based on the above data, provide your trading decisions. Consider:
1. Current market conditions and trends
2. Portfolio diversification and risk
3. Liquidity and volume considerations
4. **Your historical trade performance - what worked? what didn't?**
5. Your confidence in each decision

Remember: You have FULL AUTONOMY. Make the decisions you believe are best for portfolio growth and stability. LEARN from your past trades!"""

        # Get DeepSeek analysis
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
            
            logger.info(
                "DeepSeek analysis complete",
                market_assessment=result.get("market_assessment", "")[:100],
                decision_count=len(result.get("decisions", [])),
            )
            
            # Parse decisions
            decisions = []
            for d in result.get("decisions", []):
                action_str = d.get("action", "hold").lower()
                try:
                    action = TradeAction(action_str)
                except ValueError:
                    action = TradeAction.HOLD
                
                decision = TradeDecision(
                    symbol=d.get("symbol", ""),
                    action=action,
                    quantity=d.get("quantity"),
                    price=d.get("price"),
                    order_type=d.get("order_type", "market"),
                    reasoning=d.get("reasoning", ""),
                    confidence=float(d.get("confidence", 0.5)),
                    priority=int(d.get("priority", 0)),
                )
                decisions.append(decision)
            
            # Sort by priority (descending) and confidence (descending)
            decisions.sort(key=lambda d: (-d.priority, -d.confidence))
            
            # Save the decision record
            decision_record = {
                "market_assessment": result.get("market_assessment", ""),
                "risk_approach": result.get("risk_approach", ""),
                "portfolio_notes": result.get("portfolio_notes", ""),
                "decision_count": len(decisions),
                "decisions": [d.to_dict() for d in decisions],
            }
            await self.storage.save_trade_decision(decision_record)
            
            return decisions
            
        except Exception as e:
            logger.error("Decision generation failed", error=str(e))
            return []
    
    async def execute_decisions(
        self,
        decisions: list[TradeDecision],
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Execute trading decisions.
        
        Args:
            decisions: List of decisions to execute
            dry_run: If True, log but don't execute
            
        Returns:
            List of execution results.
        """
        logger.info(
            "Executing decisions",
            count=len(decisions),
            dry_run=dry_run,
        )
        
        results = []
        
        # Filter actionable decisions
        actionable = [d for d in decisions if d.is_actionable]
        
        if not actionable:
            logger.info("No actionable decisions to execute")
            return results
        
        # Check available USDT for buy orders - HARD GUARDRAIL
        portfolio = await self.trading.get_portfolio()
        available_usdt = portfolio.usdt_balance
        
        for decision in actionable:
            # Block buy orders when there's no USDT available
            if decision.action == TradeAction.BUY:
                required_amount = float(decision.quantity) if decision.quantity else 0
                if available_usdt <= 0:
                    logger.warning(
                        "BLOCKED: Cannot buy with 0 USDT",
                        symbol=decision.symbol,
                        quantity=decision.quantity,
                        available_usdt=available_usdt,
                    )
                    results.append({
                        "decision": decision.to_dict(),
                        "executed": False,
                        "blocked": True,
                        "reason": "No USDT available for buying",
                    })
                    continue
                elif required_amount > available_usdt:
                    logger.warning(
                        "BLOCKED: Insufficient USDT for buy order",
                        symbol=decision.symbol,
                        quantity=decision.quantity,
                        available_usdt=available_usdt,
                    )
                    results.append({
                        "decision": decision.to_dict(),
                        "executed": False,
                        "blocked": True,
                        "reason": f"Insufficient USDT (need {required_amount}, have {available_usdt})",
                    })
                    continue
                else:
                    # Deduct from available for subsequent orders in this cycle
                    available_usdt -= required_amount
            
            if dry_run:
                logger.info(
                    "DRY RUN: Would execute",
                    symbol=decision.symbol,
                    action=decision.action.value,
                    quantity=decision.quantity,
                    confidence=decision.confidence,
                )
                results.append({
                    "decision": decision.to_dict(),
                    "executed": False,
                    "dry_run": True,
                })
                continue
            
            # Execute the decision
            execution_result = await self.trading.execute_decision(decision)
            
            results.append({
                "decision": decision.to_dict(),
                "executed": True,
                "result": {
                    "order_id": execution_result.order_id,
                    "status": execution_result.status,
                    "success": execution_result.success,
                    "error": execution_result.error_message,
                },
            })
            
            logger.info(
                "Decision executed",
                symbol=decision.symbol,
                action=decision.action.value,
                success=execution_result.success,
                order_id=execution_result.order_id,
            )
        
        return results
    
    async def run_cycle(self, dry_run: bool = False) -> dict[str, Any]:
        """
        Run a complete decision and execution cycle.
        
        Args:
            dry_run: If True, generate decisions but don't execute
            
        Returns:
            Summary of the cycle.
        """
        logger.info("Starting manager cycle", dry_run=dry_run)
        
        start_time = datetime.now()
        
        # Generate decisions
        decisions = await self.generate_decisions()
        
        # Execute decisions
        results = await self.execute_decisions(decisions, dry_run=dry_run)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        summary = {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "decisions_generated": len(decisions),
            "decisions_executed": len([r for r in results if r.get("executed")]),
            "dry_run": dry_run,
            "results": results,
        }
        
        logger.info(
            "Manager cycle complete",
            duration=duration,
            decisions=len(decisions),
            executed=len([r for r in results if r.get("executed")]),
        )
        
        return summary
