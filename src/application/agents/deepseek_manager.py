"""
DeepSeek Manager Agent - Autonomous portfolio management using DeepSeek R1.
"""

import json
from datetime import datetime
from typing import Any

from src.domain.entities.coin_analysis import CoinAnalysis
from src.domain.entities.portfolio import Portfolio
from src.domain.entities.trade_decision import TradeAction, TradeDecision
from src.domain.ports.llm_port import LLMMessage, LLMPort
from src.domain.ports.storage_port import StoragePort
from src.domain.ports.trading_port import TradingPort
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
1. Market analysis data from our analyst agent (Gemini) for top 200 coins by volume
2. Current portfolio holdings with PNL data:
   - avg_entry_price: Your average cost basis for the position
   - current_price: Current market price
   - unrealized_pnl: Unrealized profit/loss in USDT
   - unrealized_pnl_pct: Unrealized P&L as a percentage
3. Recent trading decisions for context

## Using PNL Data
The portfolio includes unrealized PNL data for each position. Use this to:
- Identify positions in profit that might be worth taking gains on
- Identify losing positions that may need to be cut or averaged down
- Make informed decisions about position sizing relative to your cost basis
- Consider unrealized_pnl_pct to assess the magnitude of gains/losses
- Note: If PNL shows 0%, it means we don't have historical cost basis data for that position

## Your Task
1. Review all market analyses and current portfolio state (including PNL)
2. Develop your investment thesis and risk management approach
3. Make specific, actionable trading decisions
4. Provide clear reasoning for each decision, referencing PNL when relevant

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
    ):
        """
        Initialize the DeepSeek manager agent.
        
        Args:
            llm: LLM adapter (DeepSeek R1)
            storage_port: Storage for retrieving analyses and storing decisions
            trading_port: Trading interface for execution
            settings: Application settings
        """
        self.llm = llm
        self.storage = storage_port
        self.trading = trading_port
        self.settings = settings
    
    def _format_analyses_summary(self, analyses: list[CoinAnalysis]) -> str:
        """Format analyses into a summary for the manager."""
        summaries = []
        
        for analysis in analyses:
            if analysis.gemini_insight is None:
                continue
            
            insight = analysis.gemini_insight
            summary = {
                "symbol": f"{analysis.ticker}USDT",
                "ticker": analysis.ticker,
                "current_price": analysis.current_price,
                "change_24h": f"{float(analysis.price_change_24h) * 100:.2f}%",
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
            summaries.append(summary)
        
        return json.dumps(summaries, indent=2)
    
    def _format_portfolio_summary(self, portfolio: Portfolio) -> str:
        """Format portfolio into a summary for the manager with PNL data."""
        min_balance = self.settings.min_portfolio_balance
        
        summary = {
            "available_usdt": portfolio.usdt_balance,
            "total_positions": portfolio.total_positions,
            "min_balance_filter": min_balance,
            "positions": [],
            "total_unrealized_pnl": 0.0,
        }
        
        total_pnl = 0.0
        
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
                
                if position.avg_entry_price is not None:
                    pos_data["avg_entry_price"] = round(position.avg_entry_price, 6)
                
                if position.unrealized_pnl is not None:
                    pos_data["unrealized_pnl"] = round(position.unrealized_pnl, 2)
                    total_pnl += position.unrealized_pnl
                
                if position.unrealized_pnl_pct is not None:
                    pos_data["unrealized_pnl_pct"] = round(position.unrealized_pnl_pct, 2)
                
                summary["positions"].append(pos_data)
        
        summary["total_unrealized_pnl"] = round(total_pnl, 2)
        
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
        
        # Fetch current portfolio
        portfolio = await self.trading.get_portfolio()
        
        # Fetch recent decisions for context
        recent_decisions = await self.storage.get_recent_decisions(limit=10)
        
        # Build the prompt
        user_prompt = f"""## Current Market Analyses (Top {len(analyses)} coins by volume)

{self._format_analyses_summary(analyses)}

## Current Portfolio State

{self._format_portfolio_summary(portfolio)}

## Recent Trading Decisions (for context)

{self._format_recent_decisions(recent_decisions)}

## Current Timestamp
{datetime.now().isoformat()}

---

Based on the above data, provide your trading decisions. Consider:
1. Current market conditions and trends
2. Portfolio diversification and risk
3. Liquidity and volume considerations
4. Your confidence in each decision

Remember: You have FULL AUTONOMY. Make the decisions you believe are best for portfolio growth and stability."""

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
        
        for decision in actionable:
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
