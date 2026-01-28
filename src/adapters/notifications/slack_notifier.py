"""
Slack Notifier - Sends trade notifications to Slack via webhook.

Provides minimalist trade notifications with PNL info.
"""

from typing import Optional

import httpx

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class SlackNotifier:
    """
    Sends trade notifications to a Slack channel via webhook.

    Message format is minimalist and easy to read:
    - [BUY] BTCUSDT
      Qty: 0.05 BTC @ $67,500
      Total: $3,375 USDT

    - [SELL] ETHUSDT
      Qty: 1.5 ETH @ $3,200
      Total: $4,800 USDT
      PNL: +$240 (+5.3%)
    """

    TIMEOUT = 10.0

    def __init__(self, webhook_url: str):
        """
        Initialize the Slack notifier.

        Args:
            webhook_url: Slack incoming webhook URL
        """
        self.webhook_url = webhook_url
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.TIMEOUT)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _format_number(self, value: float, decimals: int = 2) -> str:
        """Format a number with thousands separator."""
        if abs(value) >= 1000:
            return f"{value:,.{decimals}f}"
        return f"{value:.{decimals}f}"

    def _build_message(
        self,
        action: str,
        symbol: str,
        quantity: float,
        price: float,
        total_usdt: float,
        pnl_info: Optional[dict] = None,
    ) -> str:
        """
        Build the notification message.

        Args:
            action: "BUY" or "SELL"
            symbol: Trading pair (e.g., "BTCUSDT")
            quantity: Amount of coins traded
            price: Execution price
            total_usdt: Total value in USDT
            pnl_info: Optional PNL data for sells

        Returns:
            Formatted message string
        """
        coin = symbol.replace("USDT", "")

        # Determine quantity decimals based on price
        qty_decimals = 6 if price > 1000 else 4 if price > 10 else 2

        lines = [
            f"*[{action}]* {symbol}",
            f"Qty: {self._format_number(quantity, qty_decimals)} {coin} @ ${self._format_number(price)}",
            f"Total: ${self._format_number(total_usdt)} USDT",
        ]

        # Add PNL info for sells
        if pnl_info and action == "SELL":
            realized_pnl = pnl_info.get("realized_pnl", 0)
            pnl_pct = pnl_info.get("pnl_pct", 0)

            pnl_sign = "+" if realized_pnl >= 0 else ""
            lines.append(
                f"PNL: {pnl_sign}${self._format_number(realized_pnl)} ({pnl_sign}{pnl_pct:.1f}%)"
            )

        return "\n".join(lines)

    async def send_trade_notification(
        self,
        action: str,
        symbol: str,
        quantity: float,
        price: float,
        total_usdt: float,
        reasoning: str = "",
        pnl_info: Optional[dict] = None,
    ) -> bool:
        """
        Send a trade notification to Slack.

        This method is fire-and-forget - it logs errors but doesn't raise
        exceptions to avoid blocking trade execution.

        Args:
            action: "BUY" or "SELL"
            symbol: Trading pair (e.g., "BTCUSDT")
            quantity: Amount of coins traded
            price: Execution price
            total_usdt: Total value in USDT
            reasoning: Trade reasoning (not included in message to keep it minimal)
            pnl_info: Optional PNL data for sells
                      {"realized_pnl": float, "pnl_pct": float}

        Returns:
            True if notification was sent successfully, False otherwise
        """
        try:
            message = self._build_message(
                action=action.upper(),
                symbol=symbol,
                quantity=quantity,
                price=price,
                total_usdt=total_usdt,
                pnl_info=pnl_info,
            )

            payload = {
                "text": message,
                "mrkdwn": True,
            }

            client = await self._get_client()
            response = await client.post(
                self.webhook_url,
                json=payload,
            )

            if response.status_code == 200:
                logger.info(
                    "Slack notification sent",
                    action=action,
                    symbol=symbol,
                )
                return True
            else:
                logger.warning(
                    "Slack notification failed",
                    status_code=response.status_code,
                    response=response.text,
                )
                return False

        except httpx.TimeoutException:
            logger.warning("Slack notification timed out", symbol=symbol)
            return False
        except Exception as e:
            logger.warning(
                "Slack notification error",
                error=str(e),
                symbol=symbol,
            )
            return False

    async def send_message(self, text: str) -> bool:
        """
        Send a raw text message to Slack.

        Args:
            text: Message text

        Returns:
            True if sent successfully
        """
        try:
            client = await self._get_client()
            response = await client.post(
                self.webhook_url,
                json={"text": text},
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("Slack message failed", error=str(e))
            return False
