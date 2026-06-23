import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from core.scanner import ScannerService

@pytest.mark.anyio
@patch("core.scanner.load_trades")
@patch("trade_tracker.save_trades")
async def test_scanner_update_conviction_higher(mock_save_trades, mock_load_trades):
    # Setup mock active trade
    active_trade = {
        "id": "trade123",
        "ticker": "EREGL.IS",
        "status": "ACTIVE",
        "conviction_score": 60,
        "conviction_grade": "MEDIUM",
        "position_size_pct": 50,
        "reason": "Initial signal reason"
    }
    mock_load_trades.return_value = [active_trade]

    # Setup new decision with higher conviction
    decision = {
        "ticker": "EREGL.IS",
        "strategy": "BIST_10_SNIPER",
        "conviction_score": 85,
        "conviction_grade": "STRONG",
        "position_size_pct": 100,
        "reason": "Strong divergence pattern"
    }

    mock_notifier = MagicMock()
    mock_notifier.send_message = AsyncMock()
    mock_trade_engine = MagicMock()

    scanner = ScannerService(notifier=mock_notifier, trade_engine=mock_trade_engine)
    scanner._is_on_cooldown = MagicMock(return_value=False)
    
    # Run signal processor
    await scanner._process_signals([decision])

    # Verify active trade conviction updated
    assert active_trade["conviction_score"] == 85
    assert active_trade["conviction_grade"] == "STRONG"
    assert active_trade["position_size_pct"] == 100
    assert "Initial signal reason | [GÜNCELLEME (BIST_10_SNIPER)]" in active_trade["reason"]
    
    # Verify save_trades was called
    mock_save_trades.assert_called_once()
    
    # Verify telegram message was sent
    mock_notifier.send_message.assert_called_once()
    args, kwargs = mock_notifier.send_message.call_args
    assert "SKOR GÜNCELLEMESİ" in args[0]
    assert "Yeni Skor:" in args[0]
    assert "85/100 (STRONG)" in args[0]
