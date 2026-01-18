"""
AWS Lambda handler for scheduled investment cycles.

This handler is designed to be triggered by CloudWatch Events (EventBridge)
on a schedule (e.g., every 6 hours).

Environment Variables:
    - All variables from .env.example
    - CYCLE_MODE: "full", "analyze-only", "decide-only" (default: full)
    - DRY_RUN: "true" or "false" (default: true)

Lambda Event Structure:
    The handler accepts events from CloudWatch scheduled events or
    custom invocations with the following optional fields:
    {
        "mode": "full" | "analyze-only" | "decide-only",
        "dry_run": true | false,
        "top_coins": 200
    }
"""

import asyncio
import os
from typing import Any

from src.application.use_cases.investment_cycle import CycleMode, CycleResult
from src.infrastructure.config import Settings
from src.infrastructure.container import cleanup_container, create_container
from src.infrastructure.logging import get_logger, setup_logging

# Initialize logging for Lambda (JSON format)
setup_logging(
    log_level=os.environ.get("LOG_LEVEL", "INFO"),
    json_format=True,
)

logger = get_logger(__name__)


def get_cycle_mode_from_string(mode_str: str) -> CycleMode:
    """Convert mode string to CycleMode enum."""
    mode_map = {
        "full": CycleMode.FULL,
        "analyze-only": CycleMode.ANALYZE_ONLY,
        "analyze_only": CycleMode.ANALYZE_ONLY,
        "decide-only": CycleMode.DECIDE_ONLY,
        "decide_only": CycleMode.DECIDE_ONLY,
    }
    return mode_map.get(mode_str.lower(), CycleMode.FULL)


async def async_handler(event: dict[str, Any]) -> dict[str, Any]:
    """
    Async Lambda handler implementation.
    
    Args:
        event: Lambda event data
        
    Returns:
        Response with cycle results.
    """
    logger.info("Lambda handler invoked", event=event)
    
    # Parse event parameters
    mode_str = event.get("mode", os.environ.get("CYCLE_MODE", "full"))
    dry_run_str = event.get("dry_run", os.environ.get("DRY_RUN", "true"))
    top_coins = event.get("top_coins")
    
    # Convert dry_run to boolean
    if isinstance(dry_run_str, bool):
        dry_run = dry_run_str
    else:
        dry_run = str(dry_run_str).lower() != "false"
    
    mode = get_cycle_mode_from_string(mode_str)
    
    logger.info(
        "Parsed parameters",
        mode=mode.value,
        dry_run=dry_run,
        top_coins=top_coins,
    )
    
    try:
        # Get settings
        settings = Settings()
        
        # Override top_coins if provided
        if top_coins:
            settings = settings.model_copy(update={"top_coins_count": int(top_coins)})
        
        # Validate required settings
        missing = settings.validate_required()
        if missing:
            logger.error("Missing required settings", missing=missing)
            return {
                "statusCode": 500,
                "body": {
                    "success": False,
                    "error": f"Missing required settings: {', '.join(missing)}",
                },
            }
        
        # Create container
        container = await create_container(settings)
        
        # Run investment cycle
        result: CycleResult = await container.investment_cycle.run(
            mode=mode,
            dry_run=dry_run,
        )
        
        logger.info(
            "Investment cycle complete",
            success=result.success,
            duration=result.total_duration_seconds,
            coins_analyzed=result.coins_analyzed,
            decisions_generated=result.decisions_generated,
            decisions_executed=result.decisions_executed,
        )
        
        return {
            "statusCode": 200 if result.success else 500,
            "body": result.to_dict(),
        }
        
    except Exception as e:
        logger.exception("Lambda handler failed", error=str(e))
        return {
            "statusCode": 500,
            "body": {
                "success": False,
                "error": str(e),
            },
        }
        
    finally:
        await cleanup_container()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    AWS Lambda handler entry point.
    
    Args:
        event: Lambda event data
        context: Lambda context object
        
    Returns:
        Response dictionary with statusCode and body.
    """
    # Log context info
    if context:
        logger.info(
            "Lambda context",
            function_name=getattr(context, "function_name", "unknown"),
            memory_limit=getattr(context, "memory_limit_in_mb", "unknown"),
            remaining_time=getattr(context, "get_remaining_time_in_millis", lambda: 0)(),
        )
    
    # Run async handler
    return asyncio.run(async_handler(event))


# For local testing
if __name__ == "__main__":
    import json
    
    # Test event
    test_event = {
        "mode": "full",
        "dry_run": True,
        "top_coins": 10,  # Small number for testing
    }
    
    result = handler(test_event, None)
    print(json.dumps(result, indent=2, default=str))
