import pytest
from unittest.mock import patch
import math
import pandas as pd
from trade_tracker.trailing import (
    _get_atr_cached,
    _get_structural_floor,
    _calculate_long_trailing_stop,
    _calculate_short_trailing_stop,
    _update_trailing_stop,
    _atr_cache,
)

# Reset cache before tests
@pytest.fixture(autouse=True)
def reset_atr_cache():
    _atr_cache.clear()
    yield
    _atr_cache.clear()

# ==========================================
# _get_atr_cached Tests
# ==========================================
@patch("data_sources.get_bist_data")
def test_get_atr_cached_bist(mock_bist):
    # Mock Series that has ta.atr method
    class MockSeries:
        def __init__(self, val):
            self.val = val
        def iloc(self):
            return self.val
        @property
        def empty(self):
            return False

    class MockDF:
        def __init__(self):
            self.empty = False
            self.ta = self
        def atr(self, length):
            return pd.Series([1.5, 2.0])

    mock_bist.return_value = (None, None, MockDF())
    val = _get_atr_cached("THYAO.IS")
    assert val == 2.0
    # Test cache hit
    val_cached = _get_atr_cached("THYAO.IS")
    assert val_cached == 2.0
    mock_bist.assert_called_once() # Should only be called once due to cache

@patch("data_sources.get_emtia_1h_data")
def test_get_atr_cached_emtia(mock_emtia):
    class MockDF:
        def __init__(self):
            self.empty = False
            self.ta = self
        def atr(self, length):
            return pd.Series([2.5])
    mock_emtia.return_value = MockDF()
    val = _get_atr_cached("GOLD=F")
    assert val == 2.5

@patch("data_sources.get_crypto_1h_data")
def test_get_atr_cached_crypto_empty(mock_crypto):
    mock_crypto.return_value = pd.DataFrame()
    val = _get_atr_cached("BTC/USDT")
    assert val is None

@patch("data_sources.get_crypto_1h_data")
def test_get_atr_cached_error(mock_crypto):
    mock_crypto.side_effect = Exception("API error")
    val = _get_atr_cached("BTC/USDT")
    assert val is None

# ==========================================
# _get_structural_floor Tests
# ==========================================
@patch("data_sources.get_crypto_1h_data")
def test_get_structural_floor_crypto(mock_crypto):
    df_mock = pd.DataFrame({"close": [100.0, 110.0]})
    # Mocking pandas-ta ema method dynamically since we can't easily mock ta pandas extension
    # We'll patch df.ta.ema to do nothing, but set the column manually
    df_mock["EMA_20"] = [95.0, 105.0]
    
    # We need a custom mock to bypass ta.ema
    class CustomMockDF:
        def __init__(self, df):
            self.df = df
            self.empty = False
            self.columns = df.columns
            self.ta = self
        def ema(self, length, append):
            pass
        def __getitem__(self, item):
            return self.df[item]
            
    mock_crypto.return_value = CustomMockDF(df_mock)
    val = _get_structural_floor("BTC/USDT", "AL")
    assert val == 105.0

@patch("data_sources.get_crypto_1h_data")
def test_get_structural_floor_error(mock_crypto):
    mock_crypto.side_effect = Exception("API Error")
    val = _get_structural_floor("BTC/USDT", "AL")
    assert val is None

# ==========================================
# _calculate_long_trailing_stop Tests
# ==========================================
@patch("trade_tracker.trailing._get_atr_cached")
@patch("trade_tracker._get_structural_floor")
def test_calc_long_trailing_stop_hybrid(mock_struct_floor, mock_atr, mock_long_trade):
    mock_atr.return_value = 1000.0
    mock_struct_floor.return_value = 49000.0 # Floor < SL
    
    # Profit < 10%
    new_sl = _calculate_long_trailing_stop(mock_long_trade, 52000.0, 4.0, 2000.0, 500.0)
    # ATR = 1000, MULT = 2.0 => dist = 2000
    # highest = 52000 => 52000 - 2000 = 50000
    # Floor check: max(50000, 49000*0.999) = 50000
    # Noise offset applied => slightly < 50000
    assert 49000.0 <= new_sl <= 50000.0
    
    # Profit > 20%
    new_sl2 = _calculate_long_trailing_stop(mock_long_trade, 65000.0, 30.0, 2000.0, 500.0)
    # dist = 1000 * 2.0 * 0.6 = 1200
    # highest = 65000 => 65000 - 1200 = 63800
    assert 63000.0 <= new_sl2 <= 63800.0

@patch("trade_tracker.trailing._get_atr_cached")
@patch("trade_tracker._get_structural_floor")
def test_calc_long_trailing_stop_fallback(mock_struct_floor, mock_atr, mock_long_trade):
    mock_atr.return_value = None # Fallback to trailing_dist
    mock_struct_floor.return_value = None
    
    new_sl = _calculate_long_trailing_stop(mock_long_trade, 52000.0, 15.0, 2000.0, 500.0)
    # Hybrid 15% => dist * 0.8 = 1600
    # highest = 52000 => 52000 - 1600 = 50400
    assert 50000.0 <= new_sl <= 50400.0

# ==========================================
# _calculate_short_trailing_stop Tests
# ==========================================
@patch("trade_tracker.trailing._get_atr_cached")
@patch("trade_tracker._get_structural_floor")
def test_calc_short_trailing_stop_hybrid(mock_struct_floor, mock_atr, mock_short_trade):
    mock_atr.return_value = 100.0
    mock_struct_floor.return_value = 3100.0
    
    # Profit > 20%
    new_sl = _calculate_short_trailing_stop(mock_short_trade, 2200.0, 26.0, 200.0, 50.0, "TEST")
    # dist = 100 * 2.0 * 0.6 = 120
    # lowest = 2200 => 2200 + 120 = 2320
    assert 2320.0 <= new_sl <= 2350.0

# ==========================================
# _update_trailing_stop Tests
# ==========================================
@patch("trade_tracker.trailing._calculate_long_trailing_stop")
def test_update_trailing_stop_long_activate(mock_calc, mock_long_trade):
    # Activation RR > 1.5, initially risk = 2000. Profit to activate RR 1.5 is 3000.
    # Current price = 53000 (RR = 3000 / 2000 = 1.5)
    mock_calc.return_value = 52000.0
    
    t, notifs = _update_trailing_stop(mock_long_trade, 53000.0, 6.0, "AL", "TEST")
    assert t["trailing_active"] is True
    assert float(t["sl"]) == 52000.0
    assert len(notifs) >= 1
    assert "İzleyen Stop Güncellendi" in notifs[0]

@patch("trade_tracker.trailing._calculate_short_trailing_stop")
def test_update_trailing_stop_short_activate(mock_calc, mock_short_trade):
    # Risk = 200. Activation RR = 1.5 => Profit needed = 300
    # Entry = 3000, current = 2700
    mock_calc.return_value = 2800.0
    
    t, notifs = _update_trailing_stop(mock_short_trade, 2700.0, 10.0, "SAT", "TEST")
    assert t["trailing_active"] is True
    assert float(t["sl"]) == 2800.0
    assert len(notifs) >= 1

def test_update_trailing_stop_not_activated(mock_long_trade):
    # Current = 51000, RR = 0.5 < 1.5
    t, notifs = _update_trailing_stop(mock_long_trade, 51000.0, 2.0, "AL", "TEST")
    assert t.get("trailing_active", False) is False
    assert float(t["sl"]) == 48000.0
    assert len(notifs) == 0

@patch("trade_tracker.trailing._calculate_long_trailing_stop")
def test_update_trailing_stop_ratchet_protect(mock_calc, mock_long_trade):
    mock_long_trade["trailing_active"] = True
    # mock_calc returns a LOWER sl, which should be ignored (Ratchet protection)
    mock_calc.return_value = 47000.0
    
    t, notifs = _update_trailing_stop(mock_long_trade, 53000.0, 6.0, "AL", "TEST")
    assert float(t["sl"]) == 48000.0 # Unchanged
    assert len(notifs) == 0
