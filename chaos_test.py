import sys
sys.path.append('.')
import json
import traceback

import trade_tracker
import kantitatif_otopsi

trade_tracker.TRADE_JOURNAL_CSV = "test_chaos_journal.csv"
trade_tracker.ACTIVE_TRADES_FILE = "test_chaos_trades.json"
kantitatif_otopsi.TRADE_JOURNAL_CSV = "test_chaos_journal.csv"

chaos_trades = [
    # 1. Missing prices, division by zero prone, zero values
    {"ticker": "CHAOS1", "status": "ACTIVE", "signal": "AL", "is_watch": True, "entry_price": 0, "sl": 0, "tp": 0},
    # 2. is_watch=True but normal fields exist
    {"ticker": "CHAOS2", "status": "ACTIVE", "signal": "SAT", "is_watch": True, "entry_price": 100, "sl": 110, "tp": 90, "indicators": "RSI:50 | GARBAGE"},
    # 3. Missing keys entirely
    {"ticker": "CHAOS3", "status": "ACTIVE", "is_watch": False},
    # 4. Extreme values, missing indicator value
    {"ticker": "CHAOS4", "status": "ACTIVE", "signal": "AL", "is_watch": False, "entry_price": 1e-9, "sl": 1e-9, "tp": 1e9, "indicators": "RSI: | ADX:20.5"},
]

with open("test_chaos_trades.json", "w") as f:
    json.dump(chaos_trades, f)

prices = {
    "CHAOS1": 50, # entry is 0, price is 50.
    "CHAOS2": 115, # SL hit (short)
    "CHAOS3": 10, # missing keys
    "CHAOS4": 0.5, # massive pump (TP hit)
}

print("Running check_active_trades with chaos data...")
try:
    trade_tracker._trade_file_lock = type('DummyLock', (), {'acquire': lambda self: None, 'release': lambda self: None})()
    
    # Reload trades logic is internal to check_active_trades
    def mock_load():
        return chaos_trades
    trade_tracker.load_trades = mock_load
    
    msgs = trade_tracker.check_active_trades(prices)
    print("Messages generated:", len(msgs))
    print("Success. No crashes in check_active_trades.")
except Exception as e:
    print("CRASH in check_active_trades:")
    traceback.print_exc()

print("\nRunning otopsi with chaos data...")
try:
    kantitatif_otopsi.run_autopsy()
    print("Success. No crashes in kantitatif_otopsi.")
except Exception as e:
    print("CRASH in kantitatif_otopsi:")
    traceback.print_exc()
