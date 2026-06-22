import pytest
from unittest.mock import Mock, patch
from trade_tracker.repository import InMemoryTradeRepository

@pytest.fixture(autouse=True)
def default_config_mock(monkeypatch):
    """Her testte kullanılacak varsayılan config mockları."""
    monkeypatch.setattr("config.SFP_MFE_TIME_FILTER_REQUIRED", True)
    monkeypatch.setattr("config.SFP_MFE_TIME_LIMIT_HOURS", 4)
    monkeypatch.setattr("config.SFP_MFE_MIN_PROFIT_PCT", 2.0)
    
    monkeypatch.setattr("config.TIME_STOP_ENABLED", True)
    monkeypatch.setattr("config.TIME_STOP_STRATEGIES", ["TEST_STRAT", "BREAKOUT"])
    monkeypatch.setattr("config.TIME_STOP_HOURS", 24)
    monkeypatch.setattr("config.TIME_STOP_MIN_PROFIT_PCT", 1.0)
    
    monkeypatch.setattr("config.STRUCTURAL_STOP_ENABLED", True)
    monkeypatch.setattr("config.HYBRID_STOP_ENABLED", True)
    monkeypatch.setattr("config.ANTI_HUNT_OFFSET_PCT", 0.001)
    
    monkeypatch.setattr("config.ATR_MULTIPLIER_CRYPTO", 2.0)
    monkeypatch.setattr("config.ATR_MULTIPLIER_BIST", 1.5)
    monkeypatch.setattr("config.EMTIA_ATR_MULT", {"GOLD=F": 2.5})
    
    monkeypatch.setattr("config.IND_ATR_LENGTH", 14)
    monkeypatch.setattr("config.IND_EMA_MID", 20)
    
    monkeypatch.setattr("config.TRAILING_STOP_ACTIVATION_RR", 1.5)

@pytest.fixture
def mock_long_trade():
    """Temel bir LONG işlem mock'u."""
    return {
        "id": "12345",
        "ticker": "BTC/USDT",
        "market": "CRYPTO",
        "strategy": "TEST_STRAT",
        "signal": "AL",
        "entry_price": 50000.0,
        "sl": 48000.0,
        "tp": 55000.0,
        "amount": 0.01,
        "entry_time": "2026-06-20 10:00:00+00:00",
        "status": "ACTIVE",
        "trailing_dist": 2000.0
    }

@pytest.fixture
def mock_short_trade():
    """Temel bir SHORT işlem mock'u."""
    return {
        "id": "67890",
        "ticker": "ETH/USDT",
        "market": "CRYPTO",
        "strategy": "FOMO İNFAZI",
        "signal": "SAT",
        "entry_price": 3000.0,
        "sl": 3200.0,
        "tp": 2500.0,
        "amount": 1.0,
        "entry_time": "2026-06-20 10:00:00+00:00",
        "status": "ACTIVE",
        "trailing_dist": 200.0
    }

@pytest.fixture
def in_memory_repo():
    return InMemoryTradeRepository()
