import pytest
import os
import csv
from unittest.mock import patch, Mock
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from trade_tracker.repository import (
    InMemoryTradeRepository,
    JsonTradeRepository,
    TRACKER_FILE,
    TRADE_JOURNAL_CSV,
    load_trades,
    save_trades,
    _archive_closed_trades,
    _load_trades_unlocked,
    _save_trades_unlocked
)

def test_in_memory_repository(mock_long_trade):
    repo = InMemoryTradeRepository()
    
    # Test save/load active
    repo.save_active_trades([mock_long_trade])
    active = repo.load_active_trades()
    assert len(active) == 1
    assert active[0]["id"] == mock_long_trade["id"]
    
    # Test archive
    repo.archive_closed_trades([mock_long_trade])
    assert len(repo._history) == 1

def test_json_repository_sanitize():
    repo = JsonTradeRepository()
    
    # Test numpy types
    data = {
        "int_val": np.int64(42),
        "float_val": np.float32(3.14),
        "array_val": np.array([1, 2, 3]),
        "ts": pd.Timestamp("2026-06-20 10:00:00+00:00"),
        "list_val": [np.int32(1)],
        "tuple_val": (np.float64(2.0),)
    }
    
    sanitized = repo._sanitize_for_json(data)
    assert isinstance(sanitized["int_val"], int)
    assert isinstance(sanitized["float_val"], float)
    assert isinstance(sanitized["array_val"], list)
    assert isinstance(sanitized["ts"], str)
    assert isinstance(sanitized["list_val"][0], int)
    assert isinstance(sanitized["tuple_val"], tuple)
    assert isinstance(sanitized["tuple_val"][0], float)

@patch("trade_tracker.repository.DefensiveStateGuard.load_state_safe")
def test_json_repository_load(mock_load):
    repo = JsonTradeRepository()
    mock_load.return_value = [{"id": "123"}]
    
    trades = repo.load_active_trades()
    assert len(trades) == 1
    mock_load.assert_called_once()

@patch("trade_tracker.repository.DefensiveStateGuard.save_state_atomic")
@patch("trade_tracker.repository.logging.error")
def test_json_repository_save(mock_error, mock_save, mock_long_trade):
    repo = JsonTradeRepository()
    
    # Success
    mock_save.return_value = True
    repo.save_active_trades([mock_long_trade])
    mock_save.assert_called_once()
    mock_error.assert_not_called()
    
    # Failure
    mock_save.return_value = False
    repo.save_active_trades([mock_long_trade])
    mock_error.assert_called_once()

@patch("trade_tracker.repository.DefensiveStateGuard.load_state_safe")
@patch("trade_tracker.repository.DefensiveStateGuard.save_state_atomic")
@patch("trade_tracker.repository.JsonTradeRepository._write_trade_journal_csv")
def test_json_repository_archive(mock_csv, mock_save, mock_load, mock_long_trade):
    repo = JsonTradeRepository()
    mock_load.return_value = []
    mock_save.return_value = True
    
    repo.archive_closed_trades([mock_long_trade])
    
    mock_load.assert_called_once()
    mock_save.assert_called_once()
    mock_csv.assert_called_once_with(mock_long_trade)

def test_align_and_migrate_journal_csv_no_file(tmp_path):
    repo = JsonTradeRepository()
    with patch("trade_tracker.repository.TRADE_JOURNAL_CSV", str(tmp_path / "journal.csv")):
        # Should return without doing anything if file doesn't exist
        repo._align_and_migrate_journal_csv()
        assert not os.path.exists(str(tmp_path / "journal.csv"))

def test_align_and_migrate_journal_csv_migrate(tmp_path):
    repo = JsonTradeRepository()
    target_csv = str(tmp_path / "journal.csv")
    with patch("trade_tracker.repository.TRADE_JOURNAL_CSV", target_csv):
        # Create a file with fewer headers
        with open(target_csv, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["tarih", "sembol"])
            writer.writerow(["2026-06-20", "BTC/USDT"])
            
        repo._align_and_migrate_journal_csv()
        
        # Verify migration
        with open(target_csv, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            headers = next(reader)
            row = next(reader)
            assert len(headers) == len(repo._CSV_HEADERS)
            assert len(row) == len(repo._CSV_HEADERS)
            assert row[0] == "2026-06-20"
            assert row[2] == "" # Padded

def test_write_trade_journal_csv_long(tmp_path, mock_long_trade):
    repo = JsonTradeRepository()
    target_csv = str(tmp_path / "journal.csv")
    with patch("trade_tracker.repository.TRADE_JOURNAL_CSV", target_csv):
        # Long trade with profit
        mock_long_trade["exit_price"] = 55000.0
        mock_long_trade["status"] = "CLOSED_TP"
        repo._write_trade_journal_csv(mock_long_trade)
        
        assert os.path.exists(target_csv)
        with open(target_csv, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            headers = next(reader)
            row = next(reader)
            assert row[1] == "BTC/USDT"
            assert row[4] == "AL"
            assert row[13] == "KAZANC" # Sonuc

def test_write_trade_journal_csv_short_loss(tmp_path, mock_short_trade):
    repo = JsonTradeRepository()
    target_csv = str(tmp_path / "journal.csv")
    with patch("trade_tracker.repository.TRADE_JOURNAL_CSV", target_csv):
        # Short trade with loss (SL hit)
        mock_short_trade["exit_price"] = 3200.0 # Entry 3000, SL hit
        mock_short_trade["status"] = "CLOSED_SL"
        repo._write_trade_journal_csv(mock_short_trade)
        
        with open(target_csv, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            headers = next(reader)
            row = next(reader)
            assert row[1] == "ETH/USDT"
            assert row[4] == "SAT"
            assert row[13] == "KAYIP" # Sonuc
            assert row[9].startswith("-") # Net Pnl negative

def test_legacy_shims(mock_long_trade):
    # Just to test coverage of the backward compatibility shims
    with patch("trade_tracker.repository._global_repo") as mock_global:
        load_trades()
        mock_global.load_active_trades.assert_called()
        
        save_trades([mock_long_trade])
        mock_global.save_active_trades.assert_called_with([mock_long_trade])
        
        _archive_closed_trades([mock_long_trade])
        mock_global.archive_closed_trades.assert_called_with([mock_long_trade])
        
        _load_trades_unlocked()
        mock_global.load_active_trades.assert_called()
        
        _save_trades_unlocked([mock_long_trade])
        mock_global.save_active_trades.assert_called_with([mock_long_trade])
