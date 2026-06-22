import unittest
from unittest.mock import MagicMock, patch
from trade_tracker.engine import TradeEngine
from trade_tracker.models import Trade
from trade_tracker.repository import InMemoryTradeRepository
from pydantic import ValidationError

class TestTradeTrackerSecurity(unittest.TestCase):
    def setUp(self):
        self.repo = InMemoryTradeRepository()
        self.engine = TradeEngine(repository=self.repo)

    def test_pydantic_model_validates_logic_long(self):
        # LONG işleme Stop Loss giriş fiyatından büyük girilemez
        with self.assertRaises(ValidationError) as context:
            Trade(
                ticker="BTC/USDT",
                signal="AL",
                entry_price=50000,
                sl=55000, # Hatalı (SL > Entry)
                tp=60000
            )
        self.assertIn("SL (55000.0) >= Entry (50000.0)", str(context.exception))

    def test_pydantic_model_validates_logic_short(self):
        # SHORT işleme Stop Loss giriş fiyatından küçük girilemez
        with self.assertRaises(ValidationError) as context:
            Trade(
                ticker="ETH/USDT",
                signal="SAT",
                entry_price=3000,
                sl=2500, # Hatalı (SL < Entry)
                tp=2000
            )
        self.assertIn("SL (2500.0) <= Entry (3000.0)", str(context.exception))

    def test_pydantic_model_nan_rejection(self):
        # Pydantic float conversion should reject NaN and Infinity (or value error)
        with self.assertRaises(ValidationError):
            Trade(
                ticker="BTC/USDT",
                signal="AL",
                entry_price=float("nan"),
                sl=49000,
                tp=60000
            )

    def test_pydantic_model_zero_price_rejection(self):
        # Fiyat 0 olamaz (gt=0 kuralı)
        with self.assertRaises(ValidationError) as context:
            Trade(
                ticker="BTC/USDT",
                signal="AL",
                entry_price=0,
                sl=0,
                tp=100
            )
        self.assertIn("Input should be greater than 0", str(context.exception))

    def test_engine_add_trade_handles_pydantic_veto(self):
        # add_trade, pydantic hatası fırlattığında None dönmeli ve patlamamalı
        trade = self.engine.add_trade(
            ticker="BTC/USDT",
            signal="AL",
            entry_price=50000,
            sl=55000, # Hatalı!
            tp=60000,
            reason="Test",
            provider="Test"
        )
        self.assertIsNone(trade)
        
        # Repo'da da kayıt olmamalı
        self.assertEqual(len(self.repo.load_active_trades()), 0)

    def test_engine_add_trade_success(self):
        # Düzgün bir trade eklenebilmeli
        trade = self.engine.add_trade(
            ticker="BTC/USDT",
            signal="AL",
            entry_price=50000,
            sl=49000,
            tp=60000,
            reason="Test",
            provider="Test"
        )
        self.assertIsNotNone(trade)
        self.assertEqual(trade["ticker"], "BTC/USDT")
        
        # Repo'da 1 kayıt olmalı
        self.assertEqual(len(self.repo.load_active_trades()), 1)

    def test_engine_check_active_trades_updates_repo(self):
        # İşlem kapandığında in-memory repoda active azalmalı, history artmalı
        self.engine.add_trade(
            ticker="BTC/USDT", signal="AL", entry_price=50000, sl=49000, tp=60000, reason="T", provider="T"
        )
        self.assertEqual(len(self.repo.load_active_trades()), 1)
        
        # Check ile fiyatı TP'ye değdiriyoruz
        current_prices = {"BTC/USDT": 61000}
        self.engine.check_active_trades(current_prices)
        
        # Active trades 0 olmalı, history 1 olmalı
        self.assertEqual(len(self.repo.load_active_trades()), 0)
        self.assertEqual(len(self.repo._history), 1)
        self.assertEqual(self.repo._history[0]["status"], "CLOSED_TP")

if __name__ == "__main__":
    unittest.main()
