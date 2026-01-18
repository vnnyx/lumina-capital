"""
Bitget Market Data Adapter - Implements MarketDataPort.
"""

from typing import Optional

from src.adapters.bitget.client import BitgetClient
from src.domain.entities.coin import Coin, CoinChain
from src.domain.entities.market_data import CandleStick, MarketData, TickerData
from src.domain.ports.market_data_port import MarketDataPort
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class BitgetMarketDataAdapter(MarketDataPort):
    """
    Bitget implementation of MarketDataPort.
    
    Fetches market data from Bitget Spot API v2.
    """
    
    # Coin name mapping for common cryptocurrencies
    COIN_NAMES = {
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
    }
    
    def __init__(self, client: BitgetClient, settings: Settings):
        """
        Initialize adapter.
        
        Args:
            client: Bitget HTTP client
            settings: Application settings
        """
        self.client = client
        self.settings = settings
    
    def _get_coin_name(self, ticker: str) -> str:
        """Get full coin name from ticker."""
        return self.COIN_NAMES.get(ticker.upper(), ticker)
    
    async def get_all_coins(self) -> list[Coin]:
        """Fetch all available coins."""
        logger.info("Fetching all coins")
        
        data = await self.client.get("/api/v2/spot/public/coins")
        
        coins = []
        for item in data:
            chains = [
                CoinChain(
                    chain=c.get("chain", ""),
                    need_tag=c.get("needTag", "false") == "true",
                    withdrawable=c.get("withdrawable", "true") == "true",
                    rechargeable=c.get("rechargeable", "true") == "true",
                    withdraw_fee=c.get("withdrawFee", "0"),
                    min_deposit_amount=c.get("minDepositAmount", "0"),
                    min_withdraw_amount=c.get("minWithdrawAmount", "0"),
                    contract_address=c.get("contractAddress"),
                    congestion=c.get("congestion", "normal"),
                )
                for c in item.get("chains", [])
            ]
            
            ticker = item.get("coin", "")
            coin = Coin(
                coin_id=item.get("coinId", ""),
                coin=ticker,
                name=self._get_coin_name(ticker),
                transfer=item.get("transfer", "true") == "true",
                chains=chains,
            )
            coins.append(coin)
        
        logger.info("Fetched coins", count=len(coins))
        return coins
    
    async def get_coin_info(self, coin: str) -> Optional[Coin]:
        """Fetch information for a specific coin."""
        logger.debug("Fetching coin info", coin=coin)
        
        data = await self.client.get(
            "/api/v2/spot/public/coins",
            params={"coin": coin.upper()},
        )
        
        if not data:
            return None
        
        item = data[0] if isinstance(data, list) else data
        
        chains = [
            CoinChain(
                chain=c.get("chain", ""),
                need_tag=c.get("needTag", "false") == "true",
                withdrawable=c.get("withdrawable", "true") == "true",
                rechargeable=c.get("rechargeable", "true") == "true",
                withdraw_fee=c.get("withdrawFee", "0"),
                min_deposit_amount=c.get("minDepositAmount", "0"),
                min_withdraw_amount=c.get("minWithdrawAmount", "0"),
                contract_address=c.get("contractAddress"),
                congestion=c.get("congestion", "normal"),
            )
            for c in item.get("chains", [])
        ]
        
        ticker = item.get("coin", "")
        return Coin(
            coin_id=item.get("coinId", ""),
            coin=ticker,
            name=self._get_coin_name(ticker),
            transfer=item.get("transfer", "true") == "true",
            chains=chains,
        )
    
    async def get_all_tickers(self) -> list[TickerData]:
        """Fetch ticker data for all trading pairs."""
        logger.info("Fetching all tickers")
        
        data = await self.client.get("/api/v2/spot/market/tickers")
        
        tickers = [self._parse_ticker(item) for item in data]
        
        logger.info("Fetched tickers", count=len(tickers))
        return tickers
    
    async def get_ticker(self, symbol: str) -> Optional[TickerData]:
        """Fetch ticker data for a specific trading pair."""
        logger.debug("Fetching ticker", symbol=symbol)
        
        data = await self.client.get(
            "/api/v2/spot/market/tickers",
            params={"symbol": symbol.upper()},
        )
        
        if not data:
            return None
        
        item = data[0] if isinstance(data, list) else data
        return self._parse_ticker(item)
    
    async def get_candles(
        self,
        symbol: str,
        granularity: str = "1h",
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list[CandleStick]:
        """Fetch candlestick (OHLCV) data for a trading pair."""
        logger.debug("Fetching candles", symbol=symbol, granularity=granularity, limit=limit)
        
        params = {
            "symbol": symbol.upper(),
            "granularity": granularity,
            "limit": str(limit),
        }
        
        if start_time:
            params["startTime"] = str(start_time)
        if end_time:
            params["endTime"] = str(end_time)
        
        data = await self.client.get("/api/v2/spot/market/candles", params=params)
        
        candles = [
            CandleStick(
                timestamp=int(item[0]),
                open_price=item[1],
                high_price=item[2],
                low_price=item[3],
                close_price=item[4],
                base_volume=item[5],
                usdt_volume=item[6],
                quote_volume=item[7] if len(item) > 7 else item[6],
            )
            for item in data
        ]
        
        # Sort by timestamp ascending
        candles.sort(key=lambda c: c.timestamp)
        
        logger.debug("Fetched candles", symbol=symbol, count=len(candles))
        return candles
    
    async def get_top_coins_by_volume(self, limit: int = 200) -> list[TickerData]:
        """Fetch top trading pairs by USDT volume."""
        logger.info("Fetching top coins by volume", limit=limit)
        
        tickers = await self.get_all_tickers()
        
        # Filter for USDT pairs only
        usdt_pairs = [t for t in tickers if t.symbol.endswith("USDT")]
        
        # Sort by USDT volume descending
        usdt_pairs.sort(key=lambda t: t.usdt_volume_float, reverse=True)
        
        # Return top N
        top_coins = usdt_pairs[:limit]
        
        logger.info("Top coins by volume", count=len(top_coins))
        return top_coins
    
    async def get_market_data(
        self,
        symbol: str,
        candle_granularity: str = "1h",
        candle_limit: int = 24,
    ) -> Optional[MarketData]:
        """Fetch comprehensive market data for a symbol."""
        logger.debug("Fetching market data", symbol=symbol)
        
        ticker = await self.get_ticker(symbol)
        if not ticker:
            return None
        
        candles = await self.get_candles(
            symbol=symbol,
            granularity=candle_granularity,
            limit=candle_limit,
        )
        
        return MarketData(
            symbol=symbol,
            ticker=ticker,
            candles=candles,
            granularity=candle_granularity,
        )
    
    def _parse_ticker(self, item: dict) -> TickerData:
        """Parse ticker data from API response."""
        return TickerData(
            symbol=item.get("symbol", ""),
            high_24h=item.get("high24h", "0"),
            low_24h=item.get("low24h", "0"),
            open_price=item.get("open", "0"),
            last_price=item.get("lastPr", "0"),
            base_volume=item.get("baseVolume", "0"),
            quote_volume=item.get("quoteVolume", "0"),
            usdt_volume=item.get("usdtVolume", "0"),
            bid_price=item.get("bidPr", "0"),
            ask_price=item.get("askPr", "0"),
            bid_size=item.get("bidSz", "0"),
            ask_size=item.get("askSz", "0"),
            change_24h=item.get("change24h", "0"),
            change_utc_24h=item.get("changeUtc24h", "0"),
            timestamp=int(item.get("ts", "0")),
        )
