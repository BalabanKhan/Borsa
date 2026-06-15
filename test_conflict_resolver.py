import unittest
import sys
import os

# PYTHONPATH ayarı yap
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from conflict_resolver import SignalConflictResolver
import config

class TestSignalConflictResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = SignalConflictResolver()
        config.CONFLICT_RESOLVER_ENABLED = True
        config.CONFLICT_RESOLVER_ADX_TREND_LIMIT = 40.0
        config.CONFLICT_RESOLVER_ADX_RANGING_LIMIT = 20.0
        config.CONFLICT_RESOLVER_BEAR_TREND_PENALTY = 0.6

    def test_opposite_signals_mutual_exclusivity(self):
        """Zıt sinyaller çelişkisi testi: Yüksek skoru olan kazanmalı"""
        candidate_signals = [
            {
                "ticker": "BTC/USDT",
                "strategy": "KRIPTO-2: Mega Trend Takibi",
                "signal": "AL",
                "conviction_score": 75.0,
                "raw_indicators": {"ADX_4H": 30.0}
            },
            {
                "ticker": "BTC/USDT",
                "strategy": "SHORT-1: FOMO İnfazı",
                "signal": "SAT",
                "conviction_score": 65.0,
                "raw_indicators": {"ADX_4H": 30.0}
            }
        ]
        active_trades = []
        resolved = self.resolver.resolve_conflicts(candidate_signals, active_trades)
        
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["signal"], "AL")
        self.assertEqual(resolved[0]["strategy"], "KRIPTO-2: Mega Trend Takibi")

    def test_opposite_signals_equal_score(self):
        """Skorlar eşitse ikisi de güvenlik amacıyla elenmeli"""
        candidate_signals = [
            {
                "ticker": "ETH/USDT",
                "strategy": "KRIPTO-2: Mega Trend Takibi",
                "signal": "AL",
                "conviction_score": 70.0,
                "raw_indicators": {"ADX_4H": 30.0}
            },
            {
                "ticker": "ETH/USDT",
                "strategy": "SHORT-1: FOMO İnfazı",
                "signal": "SAT",
                "conviction_score": 70.0,
                "raw_indicators": {"ADX_4H": 30.0}
            }
        ]
        active_trades = []
        resolved = self.resolver.resolve_conflicts(candidate_signals, active_trades)
        self.assertEqual(len(resolved), 0)

    def test_same_direction_signals(self):
        """Aynı yöndeki birden fazla sinyalden en yüksek skorlu olanı seçmeli"""
        candidate_signals = [
            {
                "ticker": "SOL/USDT",
                "strategy": "KRIPTO-1: RSI Dip Avcısı",
                "signal": "AL",
                "conviction_score": 60.0,
                "raw_indicators": {"ADX_4H": 18.0} # Düşük ADX dip avı için ok
            },
            {
                "ticker": "SOL/USDT",
                "strategy": "KRIPTO-2: Mega Trend Takibi",
                "signal": "AL",
                "conviction_score": 80.0,
                "raw_indicators": {"ADX_4H": 35.0}
            }
        ]
        active_trades = []
        resolved = self.resolver.resolve_conflicts(candidate_signals, active_trades)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["strategy"], "KRIPTO-2: Mega Trend Takibi")
        self.assertEqual(resolved[0]["conviction_score"], 80.0)

    def test_opposite_active_trade_blocked(self):
        """Aktif pozisyon varken ters yöndeki sinyal bloke edilmeli"""
        candidate_signals = [
            {
                "ticker": "THYAO.IS",
                "strategy": "SHORT-1: FOMO İnfazı",
                "signal": "SAT",
                "conviction_score": 85.0,
                "raw_indicators": {"ADX_4H": 30.0}
            }
        ]
        active_trades = [
            {
                "ticker": "THYAO.IS",
                "signal": "AL",
                "status": "ACTIVE"
            }
        ]
        resolved = self.resolver.resolve_conflicts(candidate_signals, active_trades)
        self.assertEqual(len(resolved), 0)

    def test_adx_regime_mean_reversion_blocked(self):
        """Güçlü trend varken (ADX > 40) Mean Reversion/Dip stratejisi bloke edilmeli"""
        candidate_signals = [
            {
                "ticker": "AVAX/USDT",
                "strategy": "KRIPTO-1: RSI Dip Avcısı", # Dip buying
                "signal": "AL",
                "conviction_score": 75.0,
                "raw_indicators": {"ADX_4H": 45.0} # Trend çok güçlü
            }
        ]
        active_trades = []
        resolved = self.resolver.resolve_conflicts(candidate_signals, active_trades)
        self.assertEqual(len(resolved), 0)

    def test_adx_regime_trend_following_blocked(self):
        """Yatay piyasada (ADX < 20) Trend Takip stratejisi bloke edilmeli"""
        candidate_signals = [
            {
                "ticker": "NEAR/USDT",
                "strategy": "KRIPTO-2: Mega Trend Takibi", # Trend strategy
                "signal": "AL",
                "conviction_score": 75.0,
                "raw_indicators": {"ADX_4H": 15.0} # Trend çok zayıf/Ranging
            }
        ]
        active_trades = []
        resolved = self.resolver.resolve_conflicts(candidate_signals, active_trades)
        self.assertEqual(len(resolved), 0)

    def test_bearish_trend_1d_penalty_passed(self):
        """1D Bearish trend varken LONG sinyal cezalandırılmalı ama WATCH eşiği (45) üstündeyse geçmeli"""
        candidate_signals = [
            {
                "ticker": "XU100.IS",
                "strategy": "BIST-2: Trend Following",
                "signal": "AL",
                "conviction_score": 80.0,
                "raw_indicators": {"Trend_1D": "Bearish", "ADX_4H": 30.0}
            }
        ]
        active_trades = []
        resolved = self.resolver.resolve_conflicts(candidate_signals, active_trades)
        self.assertEqual(len(resolved), 1)
        # 80.0 * 0.6 = 48.0 (> 45.0)
        self.assertEqual(resolved[0]["conviction_score"], 48.0)

    def test_bearish_trend_1d_penalty_blocked(self):
        """1D Bearish trend varken LONG sinyal cezası sonrası skor limitin (< 45) altına inerse bloke edilmeli"""
        candidate_signals = [
            {
                "ticker": "XU100.IS",
                "strategy": "BIST-2: Trend Following",
                "signal": "AL",
                "conviction_score": 70.0,
                "raw_indicators": {"Trend_1D": "Bearish", "ADX_4H": 30.0}
            }
        ]
        active_trades = []
        resolved = self.resolver.resolve_conflicts(candidate_signals, active_trades)
        # 70.0 * 0.6 = 42.0 (< 45.0) -> Bloke edilmeli
        self.assertEqual(len(resolved), 0)

if __name__ == "__main__":
    unittest.main()
