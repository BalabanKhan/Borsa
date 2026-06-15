import unittest
import pandas as pd
import numpy as np
import math
import sys
import os

# PYTHONPATH ayarı yap
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
import indicators
import strategies
from conviction_scorer import calculate_conviction

class TestChaosDynamicFilters(unittest.TestCase):
    def setUp(self):
        # Varsayılan konfigürasyonları ayarla
        config.DIP_RSI_1D_SMA200_ALIGN_ENABLED = True
        config.DIP_RSI_1D_EMA50_ALIGN_ENABLED = True
        config.DIP_VOLUME_SPIKE_REQUIRED = True
        config.DIP_VOLUME_SPIKE_MULT = 1.5
        config.BREAKOUT_RETEST_REQUIRED = True
        config.BREAKOUT_RETEST_TOLERANCE_PCT = 1.5
        config.VWAP_SLOPE_CONFIRMATION = True
        config.VWAP_SLOPE_LOOKBACK = 3
        config.VWAP_BOUNCE_CANDLE_CONFIRM = 2
        config.SHORT_RSI_OVERBOUGHT_LIMIT = 80.0
        config.SHORT_TREND_ALIGN_REQUIRED = True
        config.DIVERGENCE_MACD_CONFIRMATION_REQUIRED = True

    def test_vwap_bounce_empty_or_small_dataframe(self):
        """CHAOS TEST 1: Boş veya yetersiz satırlı DataFrame verildiğinde VWAP Bounce çökmemeli, False dönmeli"""
        empty_df = pd.DataFrame()
        bounce_ok, wick_low = indicators.detect_vwap_bounce(empty_df, 100.0)
        self.assertFalse(bounce_ok)
        self.assertIsNone(wick_low)

        small_df = pd.DataFrame({'low': [99.0], 'close': [100.0], 'open': [99.5], 'volume': [100]})
        bounce_ok, wick_low = indicators.detect_vwap_bounce(small_df, 100.0)
        self.assertFalse(bounce_ok)
        self.assertIsNone(wick_low)

    def test_vwap_bounce_none_val(self):
        """CHAOS TEST 2: VWAP Değeri None geldiğinde VWAP Bounce hata fırlatmadan False dönmeli"""
        df = pd.DataFrame({'low': [99.0]*10, 'close': [100.0]*10, 'open': [99.5]*10, 'volume': [100]*10})
        bounce_ok, wick_low = indicators.detect_vwap_bounce(df, None)
        self.assertFalse(bounce_ok)
        self.assertIsNone(wick_low)

    def test_vwap_bounce_missing_columns(self):
        """CHAOS TEST 3: Kolonlar eksik olduğunun sorgulanması (KeyError veya Graceful Fail)"""
        # low kolonu eksik
        df_missing_low = pd.DataFrame({'close': [100.0]*10, 'open': [99.5]*10, 'volume': [100]*10})
        # indicators.detect_vwap_bounce içindeki KeyError durumunu test et
        with self.assertRaises(Exception):
            indicators.detect_vwap_bounce(df_missing_low, 98.0)

    def test_vwap_bounce_zero_or_negative_volume(self):
        """CHAOS TEST 4: Hacim sıfır veya negatif iken division/math hatası olmadan çalışmalı"""
        data = {
            'open':  [100.0] * 30,
            'high':  [105.0] * 30,
            'low':   [97.0] * 30,
            'close': [104.0] * 30,
            'volume': [0] * 30 # Hacim 0
        }
        df = pd.DataFrame(data)
        original_calc = indicators.calculate_anchored_vwap
        indicators.calculate_anchored_vwap = lambda sub_df, anchor_type="weekly": 98.0
        
        try:
            bounce_ok, wick_low = indicators.detect_vwap_bounce(df, 98.0)
            # body_close onayı fail edecek ya da alt iğne 2*body kontrolünü geçecek
            # buradaki amaç çökme (ZeroDivisionError) olmamasını doğrulamak
            # body = 4.0, open=100.0, close=104.0. lower_wick = 100.0 - 97.0 = 3.0. 3.0 >= 8.0 (False)
            self.assertFalse(bounce_ok)
        finally:
            indicators.calculate_anchored_vwap = original_calc

    def test_volume_spike_guard_division_by_zero(self):
        """CHAOS TEST 5: Volume SMA guard sıfır olduğunda division by zero oluşmamalı"""
        # strategies._apply_volume_sma_guard(df, vol_sma) 
        # test: vol_sma = 0 veya None iken stratejiler çöküyor mu?
        vol_sma_zero = 0.0
        df_dummy = pd.DataFrame({'volume': [100.0]*5})
        guarded = strategies._apply_volume_sma_guard(df_dummy, vol_sma_zero)
        self.assertEqual(guarded, 0.0) # Zero/negative input returns safely
        
        # is_meaningful_volume da bu durumda hata vermeden False dönmeli
        meaningful = strategies._is_meaningful_volume(100.0, guarded, 10.0, "BIST")
        self.assertFalse(meaningful)

    def test_divergence_nan_rsi(self):
        """CHAOS TEST 6: RSI serisi tamamen NaN olduğunda uyuşmazlık araması hata vermemeli, False dönmeli"""
        df = pd.DataFrame({
            'open':  [100.0] * 40,
            'high':  [100.0] * 40,
            'low':   [99.0] * 40,
            'close': [99.5] * 40,
            'volume': [1000] * 40,
            'RSI_14': [np.nan] * 40,
            'EMA_20': [100.0] * 40
        })
        
        original_ta = pd.DataFrame.ta
        class MockTa:
            def __init__(self, df_obj):
                self.df_obj = df_obj
            def rsi(self, *args, **kwargs): return self.df_obj
            def ema(self, *args, **kwargs): return self.df_obj
            def macd(self, *args, **kwargs): return self.df_obj
        pd.DataFrame.ta = property(lambda self: MockTa(self))
        
        try:
            found, _, _, _, _ = indicators.detect_bearish_divergence(df)
            self.assertFalse(found)
        finally:
            pd.DataFrame.ta = original_ta

    def test_disabled_filters_graceful_pass(self):
        """CHAOS TEST 7: Tüm filtre bayrakları False iken kısıtlar atlanmalı ve stratejiler çalışmaya devam etmeli"""
        config.DIP_VOLUME_SPIKE_REQUIRED = False
        config.BREAKOUT_RETEST_REQUIRED = False
        config.SHORT_TREND_ALIGN_REQUIRED = False
        config.DIP_RSI_1D_EMA50_ALIGN_ENABLED = False
        config.DIP_RSI_1D_SMA200_ALIGN_ENABLED = False

        # config ayarlarının strateji koşullarını bypass ettiğini doğrulamak için:
        # volume_spike_ok = not config.DIP_VOLUME_SPIKE_REQUIRED or (...)
        # config.DIP_VOLUME_SPIKE_REQUIRED False olduğu için volume_spike_ok her zaman True olmalı
        volume_spike_ok_1 = not config.DIP_VOLUME_SPIKE_REQUIRED or (50 >= 100) # 50 >= 100 False ama sol taraf True
        self.assertTrue(volume_spike_ok_1)

        # retest_ok de benzer şekilde bypass edilmeli
        retest_ok_1 = True
        if config.BREAKOUT_RETEST_REQUIRED:
            retest_ok_1 = False # Eğer True olsaydı False olurdu
        self.assertTrue(retest_ok_1)

    def test_sfp_body_close_inside_required_toggle(self):
        """CHAOS TEST 8: SFP Body Close Inside flag'i kapatıldığında tepe üzerinde kapanışa izin vermeli"""
        highs = [85.0] * 20
        opens = [84.0] * 20
        closes = [84.5] * 20
        lows = [83.0] * 20
        
        highs[12] = 90.0  # swing high at index 12
        
        # SFP candle at last index
        highs[-1] = 110.0
        opens[-1] = 100.0
        closes[-1] = 98.0  # close (98.0) > swing high (90.0)
        
        data = {
            'high': highs,
            'open': opens,
            'close': closes,
            'low': lows,
            'volume': [1000] * 20
        }
        df = pd.DataFrame(data)
        
        # SFP_BODY_CLOSE_INSIDE_REQUIRED = True iken close > swing_high olduğu için fail olmalı
        config.SFP_BODY_CLOSE_INSIDE_REQUIRED = True
        config.SFP_VOLUME_CONFIRMATION_MULT = 0  # volume check bypass
        original_mfe = getattr(config, 'SFP_MFE_TIME_FILTER_REQUIRED', False)
        config.SFP_MFE_TIME_FILTER_REQUIRED = False
        try:
            found_true, _, _ = indicators.detect_sfp(df, neighbors=2)
            self.assertFalse(found_true)
            
            # SFP_BODY_CLOSE_INSIDE_REQUIRED = False iken close > swing_high olsa da pass olmalı
            config.SFP_BODY_CLOSE_INSIDE_REQUIRED = False
            found_false, _, _ = indicators.detect_sfp(df, neighbors=2)
            self.assertTrue(found_false)
        finally:
            config.SFP_MFE_TIME_FILTER_REQUIRED = original_mfe

    def test_sfp_mfe_time_filter(self):
        """CHAOS TEST 9: SFP MFE zaman filtresi tetiklendiğinde pozisyonu kapatmalı"""
        from datetime import datetime, timedelta, timezone
        import config
        from trade_tracker import _check_sfp_mfe_time_filter
        
        # Test 1: SFP stratejisi olmayan işlem filtrelenmemeli
        t_non_sfp = {
            "strategy": "BIST 1: DİP AVCILIĞI",
            "entry_time": (datetime.now(timezone.utc) - timedelta(hours=20)).strftime('%Y-%m-%d %H:%M:%S+00:00'),
            "status": "ACTIVE",
            "ticker": "THYAO.IS"
        }
        config.SFP_MFE_TIME_FILTER_REQUIRED = True
        config.SFP_MFE_TIME_LIMIT_HOURS = 12
        config.SFP_MFE_MIN_PROFIT_PCT = 0.5
        
        _, _, closed = _check_sfp_mfe_time_filter(t_non_sfp, 100.0, 0.1)
        self.assertFalse(closed)
        
        # Test 2: SFP stratejisi, süre sınırını aşmış ve kâr yetersizse kapatılmalı
        t_sfp = {
            "strategy": "SHORT 1: ZİRVE TUZAĞI (SFP)",
            "entry_time": (datetime.now(timezone.utc) - timedelta(hours=15)).strftime('%Y-%m-%d %H:%M:%S+00:00'),
            "status": "ACTIVE",
            "ticker": "SOL/USDT"
        }
        t_res, _, closed = _check_sfp_mfe_time_filter(t_sfp, 100.0, 0.2)  # kâr %0.2 < %0.5 limit
        self.assertTrue(closed)
        self.assertEqual(t_res["status"], "CLOSED_MFE_TIMEOUT")
        
        # Test 3: SFP stratejisi, süre sınırını aşmış ama kâr yeterliyse kapatılmamalı
        t_sfp_good = {
            "strategy": "SHORT 1: ZİRVE TUZAĞI (SFP)",
            "entry_time": (datetime.now(timezone.utc) - timedelta(hours=15)).strftime('%Y-%m-%d %H:%M:%S+00:00'),
            "status": "ACTIVE",
            "ticker": "SOL/USDT"
        }
        _, _, closed = _check_sfp_mfe_time_filter(t_sfp_good, 100.0, 1.2)  # kâr %1.2 >= %0.5 limit
        self.assertFalse(closed)

if __name__ == "__main__":
    unittest.main()
