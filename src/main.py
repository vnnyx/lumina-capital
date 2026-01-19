"""
Main entry point for local execution.

Usage:
    python -m src.main [OPTIONS]

Options:
    --mode          Execution mode: full, analyze-only, decide-only, backfill-outcomes (default: full)
    --dry-run       Run without executing trades (default: True)
    --live          Execute real trades (sets dry-run to False)
    --coins         Number of top coins to analyze (default: from config)
    --log-level     Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO)
    --json-logs     Output logs as JSON

Examples:
    # Run full cycle in dry-run mode
    python -m src.main
    
    # Run analysis only
    python -m src.main --mode analyze-only
    
    # Run decisions only (uses existing analyses)
    python -m src.main --mode decide-only
    
    # Run outcome backfill (records prediction accuracy)
    python -m src.main --mode backfill-outcomes
    
    # Run full cycle with live trading (CAUTION!)
    python -m src.main --live
"""

import argparse
import asyncio
import sys
from typing import NoReturn

from src.application.use_cases.investment_cycle import CycleMode
from src.infrastructure.config import get_settings
from src.infrastructure.container import cleanup_container, create_container
from src.infrastructure.logging import get_logger, setup_logging


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Lumina Capital - Multi-agent Crypto Investment Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    parser.add_argument(
        "--mode",
        choices=["full", "analyze-only", "decide-only", "backfill-outcomes"],
        default="full",
        help="Execution mode (default: full)",
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run without executing trades (default: True)",
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute real trades (overrides --dry-run)",
    )
    
    parser.add_argument(
        "--coins",
        type=int,
        help="Number of top coins to analyze (default: from config)",
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)",
    )
    
    parser.add_argument(
        "--json-logs",
        action="store_true",
        help="Output logs as JSON",
    )
    
    return parser.parse_args()


def get_cycle_mode(mode_str: str) -> CycleMode:
    """Convert mode string to CycleMode enum."""
    mode_map = {
        "full": CycleMode.FULL,
        "analyze-only": CycleMode.ANALYZE_ONLY,
        "decide-only": CycleMode.DECIDE_ONLY,
    }
    return mode_map.get(mode_str, CycleMode.FULL)


async def run_async(args: argparse.Namespace) -> int:
    """Run the investment cycle asynchronously."""
    logger = get_logger(__name__)
    
    # Get settings
    settings = get_settings()
    
    # Validate required settings
    missing = settings.validate_required()
    if missing:
        logger.error("Missing required settings", missing=missing)
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("Please check your .env file or environment variables.")
        return 1
    
    # Override settings from args
    if args.coins:
        # Create new settings with overridden value
        # Note: In real scenario, you might want to make this more elegant
        settings = settings.model_copy(update={"top_coins_count": args.coins})
    
    # Determine dry_run
    dry_run = not args.live
    
    # Warn about live trading
    if not dry_run:
        logger.warning("LIVE TRADING ENABLED - Real orders will be executed!")
        print("\n⚠️  WARNING: Live trading is enabled!")
        print("Real orders will be executed. Press Ctrl+C within 5 seconds to cancel.")
        try:
            await asyncio.sleep(5)
        except KeyboardInterrupt:
            print("\nCancelled.")
            return 0
    
    try:
        # Create container with dependencies
        logger.info("Initializing application...")
        container = await create_container(settings)
        
        # Handle backfill-outcomes mode separately
        if args.mode == "backfill-outcomes":
            logger.info("Running outcome backfill...")
            stats = await container.outcome_backfill.backfill_pending()
            
            print("\n" + "=" * 60)
            print("OUTCOME BACKFILL COMPLETE")
            print("=" * 60)
            print(f"Processed: {stats['processed']}")
            print(f"Success: {stats['success']}")
            print(f"Failed: {stats['failed']}")
            print(f"Skipped: {stats['skipped']}")
            
            # Show accuracy report
            report = await container.outcome_backfill.get_performance_report()
            overall = report["overall"]
            print(f"\nPrediction Accuracy:")
            print(f"  Total with outcomes: {overall['total']}")
            print(f"  Correct: {overall['correct']}")
            print(f"  Wrong: {overall['wrong']}")
            print(f"  Neutral: {overall['neutral']}")
            print(f"  Accuracy: {overall['accuracy_pct']}%")
            
            print("\nBy Trend:")
            for trend, data in report["by_trend"].items():
                if data["total"] > 0:
                    print(f"  {trend.capitalize()}: {data['correct']}/{data['total']} ({data['accuracy_pct']}%)")
            
            print("=" * 60)
            return 0
        
        # Get cycle mode
        mode = get_cycle_mode(args.mode)
        
        logger.info(
            "Starting investment cycle",
            mode=mode.value,
            dry_run=dry_run,
            top_coins=settings.top_coins_count,
            trade_mode=settings.trade_mode,
        )
        
        # Run the investment cycle
        result = await container.investment_cycle.run(
            mode=mode,
            dry_run=dry_run,
        )
        
        # Print summary
        print("\n" + "=" * 60)
        print("INVESTMENT CYCLE COMPLETE")
        print("=" * 60)
        print(f"Mode: {result.mode.value}")
        print(f"Duration: {result.total_duration_seconds:.2f}s")
        print(f"Success: {'✓' if result.success else '✗'}")
        print(f"Dry Run: {'Yes' if result.dry_run else 'No (LIVE)'}")
        
        if result.coins_analyzed > 0:
            print(f"\nAnalysis Phase:")
            print(f"  Coins Analyzed: {result.coins_analyzed}")
            print(f"  Duration: {result.analysis_duration_seconds:.2f}s")
        
        if result.decisions_generated > 0:
            print(f"\nDecision Phase:")
            print(f"  Decisions Generated: {result.decisions_generated}")
            print(f"  Decisions Executed: {result.decisions_executed}")
            print(f"  Duration: {result.decision_duration_seconds:.2f}s")
        
        if result.errors:
            print(f"\nErrors:")
            for error in result.errors:
                print(f"  - {error}")
        
        print("=" * 60)
        
        return 0 if result.success else 1
        
    except Exception as e:
        logger.exception("Investment cycle failed", error=str(e))
        print(f"\nError: {e}")
        return 1
        
    finally:
        await cleanup_container()


def main() -> NoReturn:
    """Main entry point."""
    args = parse_args()
    
    # Setup logging
    setup_logging(
        log_level=args.log_level,
        json_format=args.json_logs,
    )
    
    # Run async main
    exit_code = asyncio.run(run_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
