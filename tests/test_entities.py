"""
Tests for domain entities.
"""

from datetime import datetime

import pytest

from src.domain.entities.coin import Coin
from src.domain.entities.market_data import CandleStick, MarketData, TickerData
from src.domain.entities.portfolio import Portfolio, PortfolioPosition
from src.domain.entities.trade_decision import TradeAction, TradeDecision
from src.domain.entities.coin_analysis import CoinAnalysis, GeminiInsight


class TestCoin:
    """Tests for Coin entity."""
    
    def test_storage_key_generation(self):
        """Test that storage key is generated correctly."""
        coin = Coin(
            coin_id="1",
            coin="BTC",
            name="Bitcoin",
        )
        assert coin.storage_key == "BTC-BITCOIN"
    
    def test_storage_key_with_spaces(self):
        """Test storage key with spaces in name."""
        coin = Coin(
            coin_id="2",
            coin="SHIB",
            name="Shiba Inu",
        )
        assert coin.storage_key == "SHIB-SHIBA_INU"


class TestTickerData:
    """Tests for TickerData entity."""
    
    def test_usdt_volume_float(self):
        """Test USDT volume conversion to float."""
        ticker = TickerData(
            symbol="BTCUSDT",
            high_24h="50000",
            low_24h="48000",
            open_price="49000",
            last_price="49500",
            base_volume="100",
            quote_volume="4900000",
            usdt_volume="4900000.50",
            bid_price="49400",
            ask_price="49600",
            bid_size="1.5",
            ask_size="2.0",
            change_24h="0.01",
            change_utc_24h="0.012",
            timestamp=1700000000000,
        )
        assert ticker.usdt_volume_float == 4900000.50
    
    def test_change_24h_percent(self):
        """Test 24h change percentage calculation."""
        ticker = TickerData(
            symbol="BTCUSDT",
            high_24h="50000",
            low_24h="48000",
            open_price="49000",
            last_price="49500",
            base_volume="100",
            quote_volume="4900000",
            usdt_volume="4900000",
            bid_price="49400",
            ask_price="49600",
            bid_size="1.5",
            ask_size="2.0",
            change_24h="0.05",
            change_utc_24h="0.055",
            timestamp=1700000000000,
        )
        assert ticker.change_24h_percent == 5.0


class TestPortfolio:
    """Tests for Portfolio entity."""
    
    def test_get_position(self):
        """Test getting a specific position."""
        portfolio = Portfolio(
            positions=[
                PortfolioPosition(coin="BTC", available="1.5", frozen="0", locked="0", updated_at=0),
                PortfolioPosition(coin="USDT", available="10000", frozen="500", locked="0", updated_at=0),
            ]
        )
        
        btc = portfolio.get_position("BTC")
        assert btc is not None
        assert btc.available == "1.5"
        
        eth = portfolio.get_position("ETH")
        assert eth is None
    
    def test_usdt_balance(self):
        """Test USDT balance retrieval."""
        portfolio = Portfolio(
            positions=[
                PortfolioPosition(coin="USDT", available="5000.50", frozen="0", locked="0", updated_at=0),
            ]
        )
        assert portfolio.usdt_balance == 5000.50


class TestTradeDecision:
    """Tests for TradeDecision entity."""
    
    def test_is_actionable_buy(self):
        """Test actionable check for buy decision."""
        decision = TradeDecision(
            symbol="BTCUSDT",
            action=TradeAction.BUY,
            quantity="100",
            reasoning="Test",
            confidence=0.8,
        )
        assert decision.is_actionable is True
    
    def test_is_actionable_hold(self):
        """Test actionable check for hold decision."""
        decision = TradeDecision(
            symbol="BTCUSDT",
            action=TradeAction.HOLD,
            reasoning="Test",
            confidence=0.8,
        )
        assert decision.is_actionable is False
    
    def test_is_actionable_no_quantity(self):
        """Test actionable check without quantity."""
        decision = TradeDecision(
            symbol="BTCUSDT",
            action=TradeAction.BUY,
            quantity=None,
            reasoning="Test",
            confidence=0.8,
        )
        assert decision.is_actionable is False


class TestGeminiInsight:
    """Tests for GeminiInsight entity."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        insight = GeminiInsight(
            trend="bullish",
            momentum="strong",
            volatility_score=0.6,
            volume_trend="increasing",
            key_observations=["Price breaking resistance"],
            risk_factors=["High volatility"],
            opportunity_factors=["Strong momentum"],
        )
        
        result = insight.to_dict()
        
        assert result["trend"] == "bullish"
        assert result["momentum"] == "strong"
        assert result["volatility_score"] == 0.6
        assert len(result["key_observations"]) == 1
    
    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "trend": "bearish",
            "momentum": "weak",
            "volatility_score": 0.3,
            "volume_trend": "decreasing",
            "key_observations": ["Support broken"],
        }
        
        insight = GeminiInsight.from_dict(data)
        
        assert insight.trend == "bearish"
        assert insight.momentum == "weak"
        assert insight.volatility_score == 0.3


class TestCoinAnalysis:
    """Tests for CoinAnalysis entity."""
    
    def test_to_dynamodb_item(self):
        """Test conversion to DynamoDB item."""
        analysis = CoinAnalysis(
            partition_key="BTC-BITCOIN",
            ticker="BTC",
            coin_name="Bitcoin",
            current_price="50000",
            price_change_24h="0.05",
            volume_24h="1000000000",
            volume_rank=1,
            gemini_insight=GeminiInsight(
                trend="bullish",
                momentum="strong",
                volatility_score=0.5,
                volume_trend="stable",
            ),
        )
        
        item = analysis.to_dynamodb_item()
        
        assert item["pk"] == "BTC-BITCOIN"
        assert item["ticker"] == "BTC"
        assert "gemini_insight" in item
        assert item["gemini_insight"]["trend"] == "bullish"
    
    def test_from_dynamodb_item(self):
        """Test creation from DynamoDB item."""
        item = {
            "pk": "ETH-ETHEREUM",
            "ticker": "ETH",
            "coin_name": "Ethereum",
            "current_price": "3000",
            "price_change_24h": "-0.02",
            "volume_24h": "500000000",
            "volume_rank": 2,
            "analysis_timestamp": "2024-01-15T10:30:00",
            "gemini_insight": {
                "trend": "sideways",
                "momentum": "moderate",
                "volatility_score": 0.4,
                "volume_trend": "stable",
            },
        }
        
        analysis = CoinAnalysis.from_dynamodb_item(item)
        
        assert analysis.partition_key == "ETH-ETHEREUM"
        assert analysis.ticker == "ETH"
        assert analysis.gemini_insight is not None
        assert analysis.gemini_insight.trend == "sideways"
