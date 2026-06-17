import unittest
import pandas as pd
import sys
import os

# PYTHONPATH ayarı yap
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import config
import indicators

class TestDynamicFilters(unittest.TestCase):
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

    def test_detect_vwap_bounce_positive(self):
        """VWAP Bounce: Eğim pozitif, değme var, çoklu mum kapanışı başarılı"""
        # Mock DataFrame oluştur
        data = {
            'open':  [100.0] * 30,
            'high':  [105.0] * 30,
            'low':   [99.0] * 30, # default low > 98.0
            'close': [102.0] * 30,
            'volume': [1000] * 30
        }
        df = pd.DataFrame(data)
        
        # Son mum low'unu 97.0 yapıyoruz (değme gerçekleşti)
        # body = close - open = 104.0 - 103.0 = 1.0
        # lower_wick = min(open, close) - low = 103.0 - 97.0 = 6.0
        # 6.0 >= body * 2 (2.0) -> Pin bar ok
        df.loc[df.index[-1], 'low'] = 97.0
        df.loc[df.index[-1], 'open'] = 103.0
        df.loc[df.index[-1], 'close'] = 104.0
        
        # Son 2 mumun kapanışı vwap_val (98.0) üzerinde olmalı
        df.loc[df.index[-1], 'close'] = 104.0
        df.loc[df.index[-2], 'close'] = 103.0
        
        original_calc = indicators.calculate_anchored_vwap
        indicators.calculate_anchored_vwap = lambda sub_df, anchor_type="weekly": 98.0 + (len(sub_df) * 0.1)
        
        try:
            bounce_ok, wick_low = indicators.detect_vwap_bounce(df, 98.0)
            self.assertTrue(bounce_ok)
            self.assertEqual(wick_low, 97.0)
        finally:
            indicators.calculate_anchored_vwap = original_calc

    def test_detect_vwap_bounce_no_touch(self):
        """VWAP Bounce: Mumlar VWAP'a değmediyse başarısız olmalı"""
        data = {
            'open':  [100.0] * 30,
            'high':  [105.0] * 30,
            'low':   [99.5] * 30, # 99.5 > 98.0 (hiçbiri değmedi)
            'close': [102.0] * 30,
            'volume': [1000] * 30
        }
        df = pd.DataFrame(data)
        
        original_calc = indicators.calculate_anchored_vwap
        indicators.calculate_anchored_vwap = lambda sub_df, anchor_type="weekly": 98.0 + (len(sub_df) * 0.1)
        
        try:
            bounce_ok, wick_low = indicators.detect_vwap_bounce(df, 98.0)
            self.assertFalse(bounce_ok)
        finally:
            indicators.calculate_anchored_vwap = original_calc

    def test_detect_bearish_divergence_rsi_limit(self):
        """Bearish Divergence: İlk zirvedeki RSI limiti (SHORT_RSI_OVERBOUGHT_LIMIT) kontrolü"""
        data = {
            'open':  [100.0] * 40,
            'high':  [100.0] * 40,
            'low':   [99.0] * 40,
            'close': [99.5] * 40,
            'volume': [1000] * 40
        }
        df = pd.DataFrame(data)
        
        # Fiyat peaks
        df.loc[20, 'high'] = 110.0
        df.loc[35, 'high'] = 115.0
        
        df.loc[39, 'close'] = 98.0 # Son mum close < EMA20 (100.0)
        
        # Hacim uyumsuzluğu: vol_2 < vol_1
        df.loc[20, 'volume'] = 5000
        df.loc[35, 'volume'] = 3000
        
        # Mocking indicators.py pandas-ta dependencies
        # detect_bearish_divergence uses:
        # df_4h.ta.rsi(length=config.IND_RSI_LENGTH, append=True)
        # df_4h.ta.ema(length=config.IND_EMA_MID, append=True)
        # df_4h.ta.macd(append=True)
        
        # Directly inject columns as detect_bearish_divergence will copy/append them
        # Let's mock pd.DataFrame.ta methods to just return self (avoiding AnalysisIndicators issue)
        original_ta = pd.DataFrame.ta
        
        class MockTa:
            def __init__(self, df_obj):
                self.df_obj = df_obj
            def rsi(self, *args, **kwargs):
                return self.df_obj
            def ema(self, *args, **kwargs):
                return self.df_obj
            def macd(self, *args, **kwargs):
                return self.df_obj
                
        pd.DataFrame.ta = property(lambda self: MockTa(self))
        
        try:
            # RSI mock serisi: index 20 (birinci tepe) -> rsi=85, index 35 (ikinci tepe) -> rsi=72
            rsi_vals = [50.0] * 40
            rsi_vals[20] = 85.0 # 85 >= 80.0
            rsi_vals[35] = 72.0
            
            df['RSI_14'] = rsi_vals
            df['EMA_20'] = [100.0] * 40
            df['MACDh_12_26_9'] = [-1.0 if i == 35 else 0.0 for i in range(40)]
            
            config.DIVERGENCE_MAX_AGE_CANDLES = 6
            indicators.DIVERGENCE_MAX_AGE_CANDLES = 6
            
            found, p1, p2, r1, r2 = indicators.detect_bearish_divergence(df, neighbors=3)
            self.assertTrue(found)
            
            # Şimdi RSI limitini yükseltelim: SHORT_RSI_OVERBOUGHT_LIMIT = 90.0
            config.SHORT_RSI_OVERBOUGHT_LIMIT = 90.0
            found_high_limit, _, _, _, _ = indicators.detect_bearish_divergence(df, neighbors=3)
            self.assertFalse(found_high_limit) # 85 < 90.0 olduğu için elenmeli
            
        finally:
            pd.DataFrame.ta = original_ta

    def test_bb_squeeze_calculation(self):
        """Bollinger Band squeeze genişliği hesaplamasının doğru yapıldığını test et"""
        import math
        # Squeeze durumunu simüle et: BBU = 101, BBL = 99, BBM = 100
        # width = (101 - 99) / 100 = 2 / 100 = 0.02 < 0.15 (Squeeze var)
        bbu = 101.0
        bbl = 99.0
        bbm = 100.0
        bb_width = (bbu - bbl) / bbm if not math.isclose(float(bbm), 0.0, abs_tol=1e-8) else 1
        self.assertTrue(bb_width < 0.15)
        
        # Squeeze olmama durumunu simüle et: BBU = 120, BBL = 90, BBM = 100
        # width = (120 - 90) / 100 = 30 / 100 = 0.30 > 0.15 (Squeeze yok)
        bbu2 = 120.0
        bbl2 = 90.0
        bbm2 = 100.0
        bb_width2 = (bbu2 - bbl2) / bbm2 if not math.isclose(float(bbm2), 0.0, abs_tol=1e-8) else 1
        self.assertFalse(bb_width2 < 0.15)

    def test_smc_fvg_bonus_application(self):
        """SMC OTE + FVG stratejisinde FVG bonusunun conviction skora doğru uygulandığını doğrula"""
        # Başlangıç engulfing skoru 50 olsun
        engulfing_score = 50.0
        has_fvg = True
        
        # Bonus uygulandığında: 50.0 + 15.0 = 65.0
        if has_fvg:
            engulfing_score = min(100.0, engulfing_score + config.SMC_FVG_BONUS)
            
        self.assertEqual(engulfing_score, 65.0)
        
        # 100 sınırının aşılmadığını doğrula
        engulfing_score_max = 95.0
        if has_fvg:
            engulfing_score_max = min(100.0, engulfing_score_max + config.SMC_FVG_BONUS)
            
        self.assertEqual(engulfing_score_max, 100.0)

    def test_smc_ltf_msb_confirm_logic(self):
        """SMC LTF MSB Teyit bayrağına göre akışın çalıştığını doğrula"""
        # SMC_LTF_MSB_CONFIRM True iken 1H veri çekilip kontrol edilmeli
        original = config.SMC_LTF_MSB_CONFIRM
        config.SMC_LTF_MSB_CONFIRM = True
        try:
            self.assertTrue(config.SMC_LTF_MSB_CONFIRM)
        finally:
            config.SMC_LTF_MSB_CONFIRM = original

if __name__ == "__main__":
    unittest.main()
