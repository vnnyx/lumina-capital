"""
Paper Trades Tracker - Tracks simulated trades for paper trading mode.

Stores entry prices and positions for paper trades to enable PNL calculation
without actual trade execution on the exchange.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.domain.ports.paper_trades_port import PaperPosition, PaperTradesPort
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class PaperTradesTracker(PaperTradesPort):
    """
    Tracks paper trading positions and calculates PNL.

    Stores positions in a JSON file and updates them when paper trades
    are "executed" by the trading adapter.
    """

    def __init__(self, storage_path: str = "data/paper_trades.json"):
        """
        Initialize paper trades tracker.

        Args:
            storage_path: Path to paper trades storage file
        """
        self.storage_path = Path(storage_path)
        self._positions: dict[str, PaperPosition] = {}
        self._trade_history: list[dict] = []
        self._balance: Optional[dict] = None  # USDT balance tracking
        self._load()
    
    def _load(self) -> None:
        """Load positions from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                
                self._positions = {
                    coin: PaperPosition.from_dict(pos_data)
                    for coin, pos_data in data.get("positions", {}).items()
                }
                self._trade_history = data.get("trade_history", [])
                self._balance = data.get("balance")
                
                logger.debug(
                    "Paper trades loaded",
                    positions=len(self._positions),
                    trades=len(self._trade_history),
                )
            except Exception as e:
                logger.warning("Failed to load paper trades", error=str(e))
                self._positions = {}
                self._trade_history = []
        else:
            self._positions = {}
            self._trade_history = []
            self._balance = None
    
    def _save(self) -> None:
        """Save positions to disk."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "positions": {
                    coin: pos.to_dict()
                    for coin, pos in self._positions.items()
                },
                "trade_history": self._trade_history[-100:],  # Keep last 100 trades
                "balance": self._balance,
                "last_updated": datetime.now().isoformat(),
            }
            
            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2)
            
            logger.debug("Paper trades saved", path=str(self.storage_path))
        except Exception as e:
            logger.warning("Failed to save paper trades", error=str(e))
    
    async def record_buy(
        self,
        coin: str,
        quantity: float,
        price: float,
    ) -> PaperPosition:
        """
        Record a paper buy trade.
        
        Updates the average entry price using weighted average.
        
        Args:
            coin: Coin ticker (e.g., "BTC")
            quantity: Quantity bought
            price: Execution price
            
        Returns:
            Updated PaperPosition.
        """
        coin = coin.upper()
        now = datetime.now()
        
        if coin in self._positions:
            # Update existing position with weighted average
            existing = self._positions[coin]
            new_total_cost = existing.total_cost + (quantity * price)
            new_quantity = existing.quantity + quantity
            new_avg_price = new_total_cost / new_quantity if new_quantity > 0 else 0
            
            self._positions[coin] = PaperPosition(
                coin=coin,
                quantity=new_quantity,
                avg_entry_price=new_avg_price,
                total_cost=new_total_cost,
                created_at=existing.created_at,
                updated_at=now,
            )
        else:
            # Create new position
            self._positions[coin] = PaperPosition(
                coin=coin,
                quantity=quantity,
                avg_entry_price=price,
                total_cost=quantity * price,
                created_at=now,
                updated_at=now,
            )
        
        # Deduct USDT for the purchase
        usdt_spent = quantity * price
        await self.deduct_usdt(usdt_spent)

        # Record trade history
        self._trade_history.append({
            "type": "buy",
            "coin": coin,
            "quantity": quantity,
            "price": price,
            "timestamp": now.isoformat(),
        })

        self._save()

        logger.info(
            "Paper buy recorded",
            coin=coin,
            quantity=quantity,
            price=price,
            new_avg_price=self._positions[coin].avg_entry_price,
            usdt_spent=usdt_spent,
        )

        return self._positions[coin]
    
    async def record_sell(
        self,
        coin: str,
        quantity: float,
        price: float,
    ) -> Optional[PaperPosition]:
        """
        Record a paper sell trade.
        
        Reduces position quantity but keeps the same avg entry price
        for remaining position.
        
        Args:
            coin: Coin ticker (e.g., "BTC")
            quantity: Quantity sold
            price: Execution price
            
        Returns:
            Updated PaperPosition or None if position fully closed.
        """
        coin = coin.upper()
        now = datetime.now()
        
        if coin not in self._positions:
            logger.warning("No paper position to sell", coin=coin)
            return None
        
        existing = self._positions[coin]
        new_quantity = existing.quantity - quantity
        
        if new_quantity <= 0:
            # Position fully closed
            del self._positions[coin]
            result = None
        else:
            # Reduce position, keep avg entry price
            new_total_cost = new_quantity * existing.avg_entry_price
            self._positions[coin] = PaperPosition(
                coin=coin,
                quantity=new_quantity,
                avg_entry_price=existing.avg_entry_price,
                total_cost=new_total_cost,
                created_at=existing.created_at,
                updated_at=now,
            )
            result = self._positions[coin]
        
        # Add USDT from the sale
        usdt_received = quantity * price
        await self.add_usdt(usdt_received)

        # Record trade history
        self._trade_history.append({
            "type": "sell",
            "coin": coin,
            "quantity": quantity,
            "price": price,
            "realized_pnl": (price - existing.avg_entry_price) * quantity,
            "timestamp": now.isoformat(),
        })

        self._save()

        logger.info(
            "Paper sell recorded",
            coin=coin,
            quantity=quantity,
            price=price,
            remaining=new_quantity if new_quantity > 0 else 0,
            usdt_received=usdt_received,
        )

        return result
    
    async def get_position(self, coin: str) -> Optional[PaperPosition]:
        """Get paper position for a coin."""
        return self._positions.get(coin.upper())
    
    async def get_all_positions(self) -> dict[str, PaperPosition]:
        """Get all paper positions."""
        return self._positions.copy()
    
    async def get_cost_basis(self, coin: str) -> Optional[float]:
        """Get average entry price for a coin."""
        position = await self.get_position(coin)
        return position.avg_entry_price if position else None
    
    async def clear_all(self) -> None:
        """Clear all paper positions (for testing/reset)."""
        self._positions = {}
        self._trade_history = []
        self._save()
        logger.info("Paper trades cleared")
    
    async def get_trade_history(self, limit: int = 100) -> list[dict]:
        """Get recent trade history."""
        return self._trade_history[-limit:]

    async def initialize_balance(self, real_balance: float) -> None:
        """
        Initialize paper USDT balance from exchange.

        If balance already initialized, this is a no-op.
        """
        if self._balance is not None:
            logger.debug("Balance already initialized", current=self._balance.get("current_balance"))
            return

        self._balance = {
            "initial_balance": real_balance,
            "current_balance": real_balance,
            "last_known_real_balance": real_balance,
            "updated_at": datetime.now().isoformat(),
        }
        self._save()
        logger.info("Paper balance initialized", balance=real_balance)

    async def get_paper_usdt_balance(self, current_real_balance: float) -> float:
        """
        Get paper USDT balance, adjusting for deposits.

        If real balance increased since last check, user deposited funds.
        The difference is added to paper balance.
        """
        if self._balance is None:
            # First access - initialize with real balance
            await self.initialize_balance(current_real_balance)
            return current_real_balance

        current_balance = float(self._balance.get("current_balance", 0))
        last_known_real = float(self._balance.get("last_known_real_balance", 0))

        # Detect deposits: real balance increased
        if current_real_balance > last_known_real:
            deposit_amount = current_real_balance - last_known_real
            current_balance += deposit_amount
            logger.info(
                "Deposit detected, adjusting paper balance",
                deposit=deposit_amount,
                new_balance=current_balance,
            )
            self._balance["current_balance"] = current_balance
            self._balance["last_known_real_balance"] = current_real_balance
            self._balance["updated_at"] = datetime.now().isoformat()
            self._save()

        return current_balance

    async def deduct_usdt(self, amount: float) -> None:
        """Deduct USDT when buying coins."""
        if self._balance is None:
            logger.warning("No balance record to deduct from")
            return

        current_balance = float(self._balance.get("current_balance", 0))
        new_balance = current_balance - amount

        self._balance["current_balance"] = new_balance
        self._balance["updated_at"] = datetime.now().isoformat()
        self._save()
        logger.debug("USDT deducted", amount=amount, new_balance=new_balance)

    async def add_usdt(self, amount: float) -> None:
        """Add USDT when selling coins."""
        if self._balance is None:
            logger.warning("No balance record to add to")
            return

        current_balance = float(self._balance.get("current_balance", 0))
        new_balance = current_balance + amount

        self._balance["current_balance"] = new_balance
        self._balance["updated_at"] = datetime.now().isoformat()
        self._save()
        logger.debug("USDT added", amount=amount, new_balance=new_balance)
