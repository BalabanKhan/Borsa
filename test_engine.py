import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from trade_tracker.engine import TradeEngine
from trade_tracker.repository import InMemoryTradeRepository
import config

@pytest.fixture
def repo():
    return InMemoryTradeRepository()

@pytest.fixture
def mock_deps():
    dg = MagicMock()
    dg.validate_signal_output.return_value = (True, "")
    return {
        "data_guard": dg,
        "cb_observer": MagicMock(),
        "penalty_box": MagicMock(),
        "strategy_scorecard": MagicMock(),
        "postmortem": MagicMock(),
    }

@pytest.fixture
def engine(repo, mock_deps):
    return TradeEngine(
        data_guard=mock_deps["data_guard"],
        cb_observer=mock_deps["cb_observer"],
        penalty_box=mock_deps["penalty_box"],
        strategy_scorecard=mock_deps["strategy_scorecard"],
        postmortem=mock_deps["postmortem"],
        repository=repo
    )

def test_engine_init_without_repo():
    engine_no_repo = TradeEngine()
    assert engine_no_repo.repository.__class__.__name__ == "JsonTradeRepository"

def test_add_trade_data_guard_veto(engine, mock_deps):
    mock_deps["data_guard"].validate_signal_output.return_value = (False, "Vetoed")
    trade = engine.add_trade("BTC/USDT", "AL", 50000, 49000, 60000, "Test", "Test")
    assert trade is None

def test_add_trade_success_no_data_guard(repo):
    engine_no_dg = TradeEngine(repository=repo)
    trade = engine_no_dg.add_trade("BTC/USDT", "AL", 50000, 49000, 60000, "Test", "Test")
    assert trade is not None

def test_add_trade_pydantic_veto(engine, mock_deps):
    # trigger validation error inherently using SL > Entry
    trade = engine.add_trade("BTC/USDT", "AL", 50000, 55000, 60000, "Test", "Test")
    assert trade is None

def test_format_close_message_duration_more_than_24h(engine):
    t = {
        "ticker": "BTC/USDT", "entry_price": 50000, "sl": 49000,
        "entry_time": (datetime.now(timezone.utc) - timedelta(days=2, hours=3)).strftime('%Y-%m-%d %H:%M')
    }
    msg = engine._format_close_message(t, 60000, "AL", "TP")
    assert "2g 3s" in msg

def test_format_close_message_duration_exception(engine):
    t = {
        "ticker": "BTC/USDT", "entry_price": 50000, "sl": 49000,
        "entry_time": "invalid_date_format"
    }
    msg = engine._format_close_message(t, 60000, "AL", "TP")
    assert "Hesaplanamadı" in msg

def test_format_close_message_black_swan(engine):
    t = {
        "ticker": "BTC/USDT", "entry_price": 50000, "sl": 45000,
        "strategy": "TestStrategy",
        "entry_time": (datetime.now(timezone.utc) - timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S+00:00')
    }
    msg = engine._format_close_message(t, 40000, "AL", "BLACK_SWAN")
    assert "KARA KUĞU" in msg

def test_format_close_message_trailing_sl(engine):
    t = {"ticker": "BTC/USDT", "entry_price": 50000, "sl": 52000, "highest_high": 55000}
    msg = engine._format_close_message(t, 51000, "AL", "SL")
    assert "KÂR ALINDI (Trailing)" in msg

def test_format_close_message_tp_short(engine):
    t = {"ticker": "BTC/USDT", "entry_price": 50000, "sl": 52000, "lowest_low": 45000}
    msg = engine._format_close_message(t, 45000, "SAT", "TP")
    assert "[SHORT]" in msg

def test_process_active_trade_checks_black_swan(engine):
    from trade_tracker.rules.base import RuleResult
    mock_rule = MagicMock()
    mock_rule.evaluate.return_value = RuleResult(
        updated_trade={"ticker": "BTC/USDT"},
        notifications=["BS notif"],
        should_close=True,
        close_reason="BLACK_SWAN",
        status_override="CLOSED_SL"
    )
    engine.rules = [mock_rule]
    notifications = []
    closed = engine._process_active_trade_checks({"ticker": "BTC/USDT"}, 50000, 50000, 0, 0, "AL", 60000, 40000, "Strat", False, notifications)
    assert closed is True
    assert "BS notif" in notifications

def test_process_active_trade_checks_funding_shield(engine):
    from trade_tracker.rules.base import RuleResult
    mock_rule1 = MagicMock()
    mock_rule1.evaluate.return_value = RuleResult(updated_trade={"ticker": "BTC/USDT", "entry_price": 50000, "sl": 40000}, notifications=[], should_close=False)
    
    mock_rule2 = MagicMock()
    mock_rule2.evaluate.return_value = RuleResult(
        updated_trade={"ticker": "BTC/USDT", "entry_price": 50000, "sl": 40000},
        notifications=["FS notif"],
        should_close=True,
        close_reason="FUNDING"
    )
    engine.rules = [mock_rule1, mock_rule2]
    
    notifications = []
    closed = engine._process_active_trade_checks({"ticker": "BTC/USDT", "entry_price": 50000, "sl": 40000}, 50000, 50000, 0, 0, "AL", 60000, 40000, "Strat", False, notifications)
    assert closed is True
    assert "FS notif" in notifications

def test_process_active_trade_checks_sfp(engine):
    from trade_tracker.rules.base import RuleResult
    mock_rule1 = MagicMock()
    mock_rule1.evaluate.return_value = RuleResult(updated_trade={"ticker": "BTC/USDT", "entry_price": 50000, "sl": 40000}, notifications=[], should_close=False)
    
    mock_rule2 = MagicMock()
    mock_rule2.evaluate.return_value = RuleResult(
        updated_trade={"ticker": "BTC/USDT", "entry_price": 50000, "sl": 40000},
        notifications=["SFP notif"],
        should_close=True,
        close_reason="SL"
    )
    engine.rules = [mock_rule1, mock_rule2]
    
    notifications = []
    closed = engine._process_active_trade_checks({"ticker": "BTC/USDT", "entry_price": 50000, "sl": 40000}, 50000, 50000, 0, 0, "AL", 60000, 40000, "Strat", False, notifications)
    assert closed is True
    assert "SFP notif" in notifications

def test_process_active_trade_checks_al_tp(engine):
    t = {"ticker": "BTC/USDT", "sl": 45000, "entry_price": 50000}
    notifications = []
    closed = engine._process_active_trade_checks(t, 61000, 61000, 0, 0, "AL", 60000, 45000, "Strat", False, notifications)
    assert closed is True
    assert t["status"] == "CLOSED_TP"

def test_process_active_trade_checks_al_sl(engine):
    t = {"ticker": "BTC/USDT", "sl": 45000, "entry_price": 50000}
    notifications = []
    closed = engine._process_active_trade_checks(t, 44000, 44000, 0, 0, "AL", 60000, 45000, "Strat", False, notifications)
    assert closed is True
    assert t["status"] == "CLOSED_SL"

def test_process_active_trade_checks_sat_tp(engine):
    t = {"ticker": "BTC/USDT", "sl": 55000, "entry_price": 50000}
    notifications = []
    closed = engine._process_active_trade_checks(t, 39000, 39000, 0, 0, "SAT", 40000, 55000, "Strat", False, notifications)
    assert closed is True
    assert t["status"] == "CLOSED_TP"

def test_process_active_trade_checks_sat_sl(engine):
    t = {"ticker": "BTC/USDT", "sl": 55000, "entry_price": 50000}
    notifications = []
    closed = engine._process_active_trade_checks(t, 56000, 56000, 0, 0, "SAT", 40000, 55000, "Strat", False, notifications)
    assert closed is True
    assert t["status"] == "CLOSED_SL"

def test_cb_on_trade_closed_helper_win(engine, mock_deps):
    cb_notifs = []
    engine._cb_on_trade_closed_helper("CLOSED_TP", "BTC/USDT", "Strat1", 10.0, 5.0, "2024", {"exit_time": "2024"}, 2.0, cb_notifs)
    mock_deps["cb_observer"].on_trade_closed.assert_called_with({"ticker": "BTC/USDT", "strategy": "Strat1", "pnl_percent": 10.0})
    mock_deps["penalty_box"].record_asset_tp.assert_called_with("BTC/USDT")
    mock_deps["strategy_scorecard"].record_trade_result.assert_called()

def test_cb_on_trade_closed_helper_loss(engine, mock_deps):
    cb_notifs = []
    engine._cb_on_trade_closed_helper("CLOSED_SL", "BTC/USDT", "Strat1", -10.0, 5.0, "2024", {"exit_time": "2024"}, -1.0, cb_notifs)
    mock_deps["cb_observer"].on_trade_closed.assert_called_with({"ticker": "BTC/USDT", "strategy": "Strat1", "pnl_percent": -10.0})
    mock_deps["penalty_box"].record_asset_sl.assert_called_with("BTC/USDT")

def test_cb_on_trade_closed_helper_be(engine, mock_deps):
    cb_notifs = []
    engine._cb_on_trade_closed_helper("CLOSED_SL", "BTC/USDT", "Strat1", 0.0, 5.0, "2024", {"exit_time": "2024"}, 0.0, cb_notifs)
    mock_deps["cb_observer"].on_trade_closed.assert_called_with({"ticker": "BTC/USDT", "strategy": "Strat1", "pnl_percent": 0.0})
    mock_deps["penalty_box"].record_asset_sl.assert_not_called()

def test_cb_on_trade_closed_helper_manual_no_strategy(engine, mock_deps):
    cb_notifs = []
    engine._cb_on_trade_closed_helper("MANUAL_CLOSE", "BTC/USDT", "", 0.0, 5.0, "2024", {}, 0.0, cb_notifs)
    # Shouldn't crash and shouldn't record strategy if strategy is empty

def test_handle_closed_trade_accounting(engine, mock_deps):
    ct = {
        "status": "CLOSED_TP",
        "ticker": "BTC/USDT",
        "strategy": "TestStrat",
        "entry_price": 50000,
        "exit_price": 60000,
        "signal": "AL",
        "sl": 45000,
        "entry_time": (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S+00:00')
    }
    notifications = []
    engine._handle_closed_trade_accounting([ct], notifications)
    assert len(engine.repository._history) == 1
    mock_deps["postmortem"].generate_postmortem.assert_called_with(ct)

def test_handle_closed_trade_accounting_exception(engine, mock_deps, caplog):
    ct = {"status": "CLOSED_TP", "ticker": "BTC/USDT"}
    mock_deps["postmortem"].generate_postmortem.side_effect = Exception("test")
    engine._handle_closed_trade_accounting([ct], [])
    assert "Postmortem generation failed: test" in caplog.text

def test_handle_closed_trade_accounting_hold_hours_exception(engine, mock_deps):
    ct = {"status": "CLOSED_TP", "entry_time": "invalid", "entry_price": 10, "exit_price": 20, "signal": "AL"}
    engine._handle_closed_trade_accounting([ct], [])
    # Should swallow the exception during hold_hours parsing

def test_check_active_trades_missing_price(engine):
    engine.add_trade("BTC/USDT", "AL", 50000, 49000, 60000, "Test", "Test")
    engine.add_trade("ETH/USDT", "AL", 3000, 2900, 4000, "Test", "Test")
    
    notifications = engine.check_active_trades({"BTC/USDT": 51000})
    assert any("FİYAT EKSİK" in n for n in notifications)
    assert "ETH/USDT" in str(notifications)
    assert len(engine.repository.load_active_trades()) == 2

def test_check_active_trades_invalid_trade_type(engine):
    trades = engine.repository.load_active_trades()
    trades.append("NOT_A_DICT")
    engine.repository.save_active_trades(trades)
    engine.check_active_trades({"BTC/USDT": 50000})
    # Should gracefully skip it

def test_check_active_trades_no_ticker(engine):
    trades = engine.repository.load_active_trades()
    trades.append({"status": "ACTIVE"})
    engine.repository.save_active_trades(trades)
    engine.check_active_trades({"BTC/USDT": 50000})
    # Should gracefully skip

@patch("trade_tracker.engine._get_last_completed_candle_close")
def test_check_active_trades_hybrid_stop(mock_candle_close, engine):
    engine.add_trade("BTC/USDT", "AL", 50000, 49000, 60000, "Test", "Test")
    trades = engine.repository.load_active_trades()
    trades[0]["body_close_stop_required"] = True
    engine.repository.save_active_trades(trades)
    
    mock_candle_close.return_value = 48000
    notifications = engine.check_active_trades({"BTC/USDT": 50000})
    
    assert len(engine.repository.load_active_trades()) == 0
    assert len(engine.repository._history) == 1
    assert any("ZARAR KESİLDİ" in n for n in notifications)

def test_check_active_trades_entry_price_zero(engine):
    engine.add_trade("BTC/USDT", "AL", 50000, 49000, 60000, "Test", "Test")
    trades = engine.repository.load_active_trades()
    trades[0]["entry_price"] = 0 # Force a zero
    engine.repository.save_active_trades(trades)
    
    engine.check_active_trades({"BTC/USDT": 50000})
    loaded = engine.repository.load_active_trades()[0]
    assert loaded["entry_price"] == 1e-8

def test_check_active_trades_signal_short(engine):
    engine.add_trade("BTC/USDT", "SAT", 50000, 51000, 40000, "Test", "Test")
    # check with a price that hits TP
    engine.check_active_trades({"BTC/USDT": 39000})
    assert len(engine.repository.load_active_trades()) == 0

def test_check_active_trades_closed_in_repo(engine):
    engine.add_trade("BTC/USDT", "AL", 50000, 49000, 60000, "Test", "Test")
    trades = engine.repository.load_active_trades()
    trades[0]["status"] = "CLOSED_TP"
    engine.repository.save_active_trades(trades)
    
    engine.check_active_trades({"BTC/USDT": 50000})
    # It should immediately close the trade
    assert len(engine.repository.load_active_trades()) == 0
