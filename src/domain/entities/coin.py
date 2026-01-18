"""
Coin entity - Represents cryptocurrency information.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CoinChain:
    """Represents a blockchain network that supports a coin."""
    
    chain: str
    need_tag: bool = False
    withdrawable: bool = True
    rechargeable: bool = True
    withdraw_fee: str = "0"
    min_deposit_amount: str = "0"
    min_withdraw_amount: str = "0"
    contract_address: Optional[str] = None
    congestion: str = "normal"


@dataclass
class Coin:
    """Represents a cryptocurrency with its metadata."""
    
    coin_id: str
    coin: str  # Ticker symbol (e.g., BTC)
    name: str  # Full name (e.g., Bitcoin)
    transfer: bool = True
    chains: list[CoinChain] = field(default_factory=list)
    
    @property
    def storage_key(self) -> str:
        """Generate the DynamoDB partition key in format TICKER-COINNAME."""
        return f"{self.coin}-{self.name.upper().replace(' ', '_')}"
    
    def __hash__(self) -> int:
        return hash(self.coin_id)
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Coin):
            return False
        return self.coin_id == other.coin_id
