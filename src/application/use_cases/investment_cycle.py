"""
Investment Cycle Use Case - Orchestrates the full investment workflow.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from src.application.agents.deepseek_manager import DeepSeekManagerAgent
from src.application.agents.gemini_analyst import GeminiAnalystAgent
from src.domain.ports.trading_port import TradingPort
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class CycleMode(str, Enum):
    """Investment cycle execution modes."""
    
    FULL = "full"  # Run both analysis and decision
    ANALYZE_ONLY = "analyze_only"  # Only run Gemini analysis
    DECIDE_ONLY = "decide_only"  # Only run DeepSeek decisions


@dataclass
class CycleResult:
    """Result of an investment cycle."""
    
    mode: CycleMode
    start_time: datetime
    end_time: datetime
    success: bool
    
    # Analysis results
    coins_analyzed: int = 0
    analysis_duration_seconds: float = 0.0
    
    # Decision results
    decisions_generated: int = 0
    decisions_executed: int = 0
    decision_duration_seconds: float = 0.0
    
    # Execution results
    dry_run: bool = True
    execution_results: list[dict] = None  # type: ignore
    
    # Error tracking
    errors: list[str] = None  # type: ignore
    
    def __post_init__(self):
        if self.execution_results is None:
            self.execution_results = []
        if self.errors is None:
            self.errors = []
    
    @property
    def total_duration_seconds(self) -> float:
        """Calculate total duration."""
        return (self.end_time - self.start_time).total_seconds()
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "mode": self.mode.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "total_duration_seconds": self.total_duration_seconds,
            "success": self.success,
            "coins_analyzed": self.coins_analyzed,
            "analysis_duration_seconds": self.analysis_duration_seconds,
            "decisions_generated": self.decisions_generated,
            "decisions_executed": self.decisions_executed,
            "decision_duration_seconds": self.decision_duration_seconds,
            "dry_run": self.dry_run,
            "execution_results": self.execution_results,
            "errors": self.errors,
        }


class InvestmentCycleUseCase:
    """
    Orchestrates the complete investment cycle.
    
    The cycle consists of:
    1. Market Analysis: Gemini analyzes top coins by volume
    2. Portfolio Decision: DeepSeek generates trading decisions
    3. Execution: Execute decisions (or dry run)
    
    Supports different modes:
    - FULL: Complete cycle
    - ANALYZE_ONLY: Only run analysis (useful for data collection)
    - DECIDE_ONLY: Only run decisions (uses existing analyses)
    """
    
    def __init__(
        self,
        analyst_agent: GeminiAnalystAgent,
        manager_agent: DeepSeekManagerAgent,
        trading_port: TradingPort,
        settings: Settings,
        top_coins_count: int = 200,
    ):
        """
        Initialize the investment cycle use case.
        
        Args:
            analyst_agent: Gemini analyst agent
            manager_agent: DeepSeek manager agent
            trading_port: Trading port for portfolio access
            settings: Application settings
            top_coins_count: Number of top coins to analyze
        """
        self.analyst = analyst_agent
        self.manager = manager_agent
        self.trading = trading_port
        self.settings = settings
        self.top_coins_count = top_coins_count
    
    async def run(
        self,
        mode: CycleMode = CycleMode.FULL,
        dry_run: bool = True,
    ) -> CycleResult:
        """
        Run the investment cycle.
        
        Args:
            mode: Execution mode (full, analyze_only, decide_only)
            dry_run: If True, don't execute actual trades
            
        Returns:
            CycleResult with details of the run.
        """
        logger.info(
            "Starting investment cycle",
            mode=mode.value,
            dry_run=dry_run,
            top_coins=self.top_coins_count,
        )
        
        start_time = datetime.now()
        result = CycleResult(
            mode=mode,
            start_time=start_time,
            end_time=start_time,  # Will be updated
            success=True,
            dry_run=dry_run,
        )
        
        try:
            # Phase 1: Market Analysis
            if mode in (CycleMode.FULL, CycleMode.ANALYZE_ONLY):
                await self._run_analysis_phase(result)
            
            # Phase 2: Portfolio Decision & Execution
            if mode in (CycleMode.FULL, CycleMode.DECIDE_ONLY):
                await self._run_decision_phase(result, dry_run)
        
        except Exception as e:
            logger.error("Investment cycle failed", error=str(e))
            result.success = False
            result.errors.append(str(e))
        
        result.end_time = datetime.now()
        
        logger.info(
            "Investment cycle complete",
            success=result.success,
            duration=result.total_duration_seconds,
            analyzed=result.coins_analyzed,
            decisions=result.decisions_generated,
            executed=result.decisions_executed,
        )
        
        return result
    
    async def _run_analysis_phase(self, result: CycleResult) -> None:
        """Run the market analysis phase."""
        logger.info("Starting analysis phase", top_coins=self.top_coins_count)
        
        phase_start = datetime.now()
        
        try:
            # Fetch portfolio symbols to include in analysis
            include_symbols: list[str] = []
            if self.settings.include_portfolio_in_analysis:
                try:
                    portfolio = await self.trading.get_portfolio()
                    min_balance = self.settings.min_portfolio_balance
                    
                    # Filter positions with balance > min_threshold, exclude USDT
                    for position in portfolio.positions:
                        if (
                            position.coin.upper() != "USDT"
                            and position.total_balance > min_balance
                        ):
                            include_symbols.append(position.coin)
                    
                    logger.info(
                        "Portfolio coins for analysis",
                        count=len(include_symbols),
                        coins=include_symbols,
                        min_balance=min_balance,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to fetch portfolio, continuing without portfolio coins",
                        error=str(e),
                    )
            
            analyses = await self.analyst.analyze_top_coins(
                limit=self.top_coins_count,
                include_symbols=include_symbols if include_symbols else None,
            )
            result.coins_analyzed = len(analyses)
            
            logger.info("Analysis phase complete", analyzed=len(analyses))
        
        except Exception as e:
            logger.error("Analysis phase failed", error=str(e))
            result.errors.append(f"Analysis phase: {e}")
            raise
        
        finally:
            phase_end = datetime.now()
            result.analysis_duration_seconds = (phase_end - phase_start).total_seconds()
    
    async def _run_decision_phase(self, result: CycleResult, dry_run: bool) -> None:
        """Run the decision and execution phase."""
        logger.info("Starting decision phase", dry_run=dry_run)
        
        phase_start = datetime.now()
        
        try:
            cycle_result = await self.manager.run_cycle(dry_run=dry_run)
            
            result.decisions_generated = cycle_result.get("decisions_generated", 0)
            result.decisions_executed = cycle_result.get("decisions_executed", 0)
            result.execution_results = cycle_result.get("results", [])
            
            logger.info(
                "Decision phase complete",
                generated=result.decisions_generated,
                executed=result.decisions_executed,
            )
        
        except Exception as e:
            logger.error("Decision phase failed", error=str(e))
            result.errors.append(f"Decision phase: {e}")
            raise
        
        finally:
            phase_end = datetime.now()
            result.decision_duration_seconds = (phase_end - phase_start).total_seconds()
    
    async def run_full_cycle(self, dry_run: bool = True) -> CycleResult:
        """
        Convenience method to run a full investment cycle.
        
        Args:
            dry_run: If True, don't execute actual trades
            
        Returns:
            CycleResult with details of the run.
        """
        return await self.run(mode=CycleMode.FULL, dry_run=dry_run)
    
    async def run_analysis_only(self) -> CycleResult:
        """
        Run only the analysis phase.
        
        Returns:
            CycleResult with analysis details.
        """
        return await self.run(mode=CycleMode.ANALYZE_ONLY, dry_run=True)
    
    async def run_decision_only(self, dry_run: bool = True) -> CycleResult:
        """
        Run only the decision phase (using existing analyses).
        
        Args:
            dry_run: If True, don't execute actual trades
            
        Returns:
            CycleResult with decision details.
        """
        return await self.run(mode=CycleMode.DECIDE_ONLY, dry_run=dry_run)
