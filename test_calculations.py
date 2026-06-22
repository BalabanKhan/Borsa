import pytest
from unittest.mock import patch, Mock
import pandas as pd
from datetime import datetime, timezone, timedelta
from trade_tracker.calculations import (
    _check_scale_out,
    _check_funding_shield,
    _check_danger_zone,
    _check_sfp_mfe_time_filter,
    _check_time_stop,
    _check_black_swan,
    _get_last_completed_candle_close,
)

# ==========================================
# _check_scale_out Tests
# ==========================================
@pytest.mark.parametrize("signal, profit_pct, strategy, expected_partial_hit, expected_sl", [
    ("AL", 4.9, "TEST", False, 48000.0),      # Not enough profit
    ("AL", 5.0, "TEST", True, 50000.0),       # Hit scale-out
    ("SAT", 4.9, "TEST", False, 3200.0),      # Not enough profit
    ("SAT", 5.0, "TEST", True, 3000.0),       # Hit scale-out (normal short)
    ("SAT", 9.9, "FOMO İNFAZI", False, 3200.0), # Not enough profit for FOMO
    ("SAT", 10.0, "FOMO İNFAZI", True, 3000.0), # Hit scale-out for FOMO
])
def test_check_scale_out(mock_long_trade, mock_short_trade, signal, profit_pct, strategy, expected_partial_hit, expected_sl):
    trade = mock_long_trade if signal == "AL" else mock_short_trade
    trade["strategy"] = strategy
    
    updated_t, notifications = _check_scale_out(trade, profit_pct, signal, strategy, current_price=51000.0 if signal == "AL" else 2800.0)
    
    assert updated_t.get("partial_tp_hit", False) is expected_partial_hit
    assert float(updated_t["sl"]) == expected_sl
    if expected_partial_hit:
        assert len(notifications) > 0

def test_check_scale_out_already_hit(mock_long_trade):
    mock_long_trade["partial_tp_hit"] = True
    updated_t, notifications = _check_scale_out(mock_long_trade, 10.0, "AL", "TEST")
    assert len(notifications) == 0

def test_check_scale_out_sl_already_breakeven(mock_long_trade):
    mock_long_trade["sl"] = 51000.0  # Already higher than entry (50000)
    updated_t, notifications = _check_scale_out(mock_long_trade, 5.0, "AL", "TEST")
    assert float(updated_t["sl"]) == 51000.0  # Should not be moved back to entry

def test_check_scale_out_short_sl_already_breakeven(mock_short_trade):
    mock_short_trade["sl"] = 2900.0  # Already lower than entry (3000)
    updated_t, notifications = _check_scale_out(mock_short_trade, 5.0, "SAT", "TEST")
    assert float(updated_t["sl"]) == 2900.0  # Should not be moved back to entry

# ==========================================
# _check_funding_shield Tests
# ==========================================
@patch("trade_tracker.calculations.get_funding_rate")
def test_check_funding_shield_long_trigger(mock_funding, mock_long_trade):
    mock_funding.return_value = 0.05
    t, notifs, should_close = _check_funding_shield(mock_long_trade, 51000.0, 2.0, "AL")
    assert should_close is True
    assert t["status"] == "CLOSED_TP"
    assert len(notifs) == 1

@patch("trade_tracker.calculations.get_funding_rate")
def test_check_funding_shield_short_trigger(mock_funding, mock_short_trade):
    mock_funding.return_value = -0.05
    t, notifs, should_close = _check_funding_shield(mock_short_trade, 2800.0, 2.0, "SAT")
    assert should_close is True
    assert t["status"] == "CLOSED_FUNDING_SHIELD"
    assert len(notifs) == 1

def test_check_funding_shield_no_trigger_if_loss(mock_long_trade):
    t, notifs, should_close = _check_funding_shield(mock_long_trade, 49000.0, -2.0, "AL")
    assert should_close is False

def test_check_funding_shield_no_trigger_if_not_crypto(mock_long_trade):
    mock_long_trade["ticker"] = "AAPL" # No slash
    t, notifs, should_close = _check_funding_shield(mock_long_trade, 150.0, 2.0, "AL")
    assert should_close is False

# ==========================================
# _check_danger_zone Tests
# ==========================================
@pytest.mark.parametrize("signal, current_price, expected_warned", [
    ("AL", 48500.0, True),   # 1.04% away from 48000
    ("AL", 49500.0, False),  # 3.12% away from 48000
    ("SAT", 3150.0, True),   # 1.58% away from 3200
    ("SAT", 3000.0, False),  # 6.66% away from 3200
])
def test_check_danger_zone(mock_long_trade, mock_short_trade, signal, current_price, expected_warned):
    trade = mock_long_trade if signal == "AL" else mock_short_trade
    t, notifs = _check_danger_zone(trade, current_price, signal)
    assert t.get("danger_warned", False) is expected_warned

def test_check_danger_zone_cooldown(mock_long_trade):
    mock_long_trade["danger_warned"] = False
    mock_long_trade["last_danger_time"] = datetime.now(timezone.utc).timestamp() - 100 # 100s ago
    # Not enough time passed for a warning if it was already warned, 
    # but here warned is False, wait, if warned is False and cooldown is checked:
    # Actually cooldown is checked when triggering a NEW warning but it checks `not already_warned`
    # So if `already_warned` is False, it will check cooldown.
    t, notifs = _check_danger_zone(mock_long_trade, 48500.0, "AL")
    assert t.get("danger_warned", False) is False # Due to cooldown
    assert len(notifs) == 0

def test_check_danger_zone_recovery(mock_long_trade):
    mock_long_trade["danger_warned"] = True
    # Price recovers to > 5% away from 48000 (5% of 48000 is 2400 => >50400)
    t, notifs = _check_danger_zone(mock_long_trade, 51000.0, "AL")
    assert t["danger_warned"] is False
    assert len(notifs) == 1

def test_check_danger_zone_no_sl(mock_long_trade):
    mock_long_trade["sl"] = 0
    t, notifs = _check_danger_zone(mock_long_trade, 48500.0, "AL")
    assert len(notifs) == 0

# ==========================================
# _check_sfp_mfe_time_filter Tests
# ==========================================
def test_check_sfp_mfe_time_filter_not_sfp(mock_long_trade):
    t, notifs, should_close = _check_sfp_mfe_time_filter(mock_long_trade, 50000.0, 1.0)
    assert should_close is False

def test_check_sfp_mfe_time_filter_trigger(mock_long_trade):
    mock_long_trade["strategy"] = "SFP_STRAT"
    entry_time = (datetime.now(timezone.utc) - timedelta(hours=5)).strftime('%Y-%m-%d %H:%M:%S+00:00')
    mock_long_trade["entry_time"] = entry_time
    
    t, notifs, should_close = _check_sfp_mfe_time_filter(mock_long_trade, 50500.0, 1.0)
    assert should_close is True
    assert t["status"] == "CLOSED_MFE_TIMEOUT"

def test_check_sfp_mfe_time_filter_no_entry_time(mock_long_trade):
    mock_long_trade["strategy"] = "SFP_STRAT"
    del mock_long_trade["entry_time"]
    t, notifs, should_close = _check_sfp_mfe_time_filter(mock_long_trade, 50500.0, 1.0)
    assert should_close is False

@patch("trade_tracker.calculations.logging.warning")
def test_check_sfp_mfe_time_filter_invalid_date(mock_warn, mock_long_trade):
    mock_long_trade["strategy"] = "SFP_STRAT"
    mock_long_trade["entry_time"] = "invalid_date"
    t, notifs, should_close = _check_sfp_mfe_time_filter(mock_long_trade, 50500.0, 1.0)
    assert should_close is False
    mock_warn.assert_called()

# ==========================================
# _check_time_stop Tests
# ==========================================
def test_check_time_stop_trigger(mock_long_trade):
    entry_time = (datetime.now(timezone.utc) - timedelta(hours=25)).strftime('%Y-%m-%d %H:%M:%S+00:00')
    mock_long_trade["entry_time"] = entry_time
    
    t, notifs, should_close = _check_time_stop(mock_long_trade, 50000.0, 0.5)
    assert should_close is True
    assert t["status"] == "CLOSED_TIME_STOP"

def test_check_time_stop_not_in_strategies(mock_long_trade):
    mock_long_trade["strategy"] = "OTHER_STRAT"
    t, notifs, should_close = _check_time_stop(mock_long_trade, 50000.0, 0.5)
    assert should_close is False

def test_check_time_stop_no_entry_time(mock_long_trade):
    del mock_long_trade["entry_time"]
    t, notifs, should_close = _check_time_stop(mock_long_trade, 50000.0, 0.5)
    assert should_close is False

@patch("trade_tracker.calculations.logging.warning")
def test_check_time_stop_invalid_date(mock_warn, mock_long_trade):
    mock_long_trade["entry_time"] = "invalid_date"
    t, notifs, should_close = _check_time_stop(mock_long_trade, 50000.0, 0.5)
    assert should_close is False
    mock_warn.assert_called()

# ==========================================
# _check_black_swan Tests
# ==========================================
@pytest.mark.parametrize("signal, current_price, expected_black_swan", [
    ("AL", 46000.0, True),   # < 48000 * 0.97 (46560)
    ("AL", 47000.0, False),  # > 46560
    ("SAT", 3400.0, True),   # > 3200 * 1.03 (3296)
    ("SAT", 3250.0, False),  # < 3296
])
@patch("trade_tracker.engine.TradeEngine._format_close_message")
def test_check_black_swan(mock_format, mock_long_trade, mock_short_trade, signal, current_price, expected_black_swan):
    trade = mock_long_trade if signal == "AL" else mock_short_trade
    mock_format.return_value = "FORMATTED_MSG"
    
    t, notifs, is_black_swan = _check_black_swan(trade, current_price, signal)
    assert is_black_swan is expected_black_swan
    if expected_black_swan:
        assert t["status"] == "CLOSED_BLACK_SWAN"
        assert "FORMATTED_MSG" in notifs

def test_check_black_swan_no_sl(mock_long_trade):
    mock_long_trade["sl"] = 0
    t, notifs, is_black_swan = _check_black_swan(mock_long_trade, 46000.0, "AL")
    assert is_black_swan is False

# ==========================================
# _get_last_completed_candle_close Tests
# ==========================================
@patch("trade_tracker.calculations.get_bist_data")
def test_last_candle_bist_1d(mock_bist):
    df_mock = pd.DataFrame({"close": [100.0, 105.0]}, index=[
        datetime.now(timezone.utc) - timedelta(days=2),
        datetime.now(timezone.utc) - timedelta(hours=1) # 1 hour old, so it's not completed for 1D yet
    ])
    mock_bist.return_value = (df_mock, None, None)
    
    val = _get_last_completed_candle_close("THYAO.IS", "1d")
    assert val == 100.0 # Falls back to iloc[-2]

@patch("trade_tracker.calculations.get_crypto_1h_data")
def test_last_candle_crypto_1h_completed(mock_crypto):
    df_mock = pd.DataFrame({"close": [50000.0, 51000.0]}, index=[
        datetime.now(timezone.utc) - timedelta(hours=3),
        datetime.now(timezone.utc) - timedelta(hours=1.5) # 1.5 hours old, so it IS completed for 1H
    ])
    mock_crypto.return_value = df_mock
    
    val = _get_last_completed_candle_close("BTC/USDT", "1h")
    assert val == 51000.0 # Uses iloc[-1]

@patch("trade_tracker.calculations.get_crypto_data")
def test_last_candle_crypto_4h_empty(mock_crypto):
    mock_crypto.return_value = (None, pd.DataFrame()) # Empty dataframe
    val = _get_last_completed_candle_close("BTC/USDT", "4h")
    assert val is None

@patch("trade_tracker.calculations.get_crypto_data")
def test_last_candle_crypto_error(mock_crypto):
    mock_crypto.side_effect = Exception("API error")
    val = _get_last_completed_candle_close("BTC/USDT", "1d")
    assert val is None

@patch("trade_tracker.calculations.get_crypto_1h_data")
def test_last_candle_crypto_not_enough_data(mock_crypto):
    df_mock = pd.DataFrame({"close": [50000.0]}, index=[
        datetime.now(timezone.utc) - timedelta(minutes=10) # 10 mins old, not completed
    ])
    mock_crypto.return_value = df_mock
    
    val = _get_last_completed_candle_close("BTC/USDT", "1h")
    assert val == 50000.0 # Forced to use iloc[-1] because len < 2
