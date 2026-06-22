import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, root_validator, ConfigDict

class Trade(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str = Field(default="")
    ticker: str
    signal: Literal["AL", "SAT"]
    entry_price: float = Field(gt=0)
    sl: float = Field(gt=0)
    tp: float = Field(gt=0)
    reason: str = ""
    provider: str = ""
    strategy: str = "Unknown"
    indicators: Dict[str, Any] = Field(default_factory=dict)
    status: str = "ACTIVE"
    trailing_dist: float = 0.0
    highest_high: float = 0.0
    lowest_low: float = 0.0
    entry_time: str = ""
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    is_watch: bool = False
    market: str = "Unknown"
    conviction_score: Optional[float] = None
    conviction_grade: Optional[str] = None
    position_size_pct: Optional[float] = None
    raw_indicators: Dict[str, Any] = Field(default_factory=dict)
    conviction_details: Dict[str, Any] = Field(default_factory=dict)

    @root_validator(pre=True)
    def init_fields(cls, values):
        if not values.get("id"):
            from .repository import TRACKER_FILE
            trades_len = values.get("existing_trades_count", 0)
            mtime = int(os.path.getmtime(TRACKER_FILE) if os.path.exists(TRACKER_FILE) else 0)
            values["id"] = f"{values.get('ticker')}_{mtime}_{trades_len}"
            
        if "highest_high" not in values and "entry_price" in values:
            values["highest_high"] = values["entry_price"]
        if "lowest_low" not in values and "entry_price" in values:
            values["lowest_low"] = values["entry_price"]
        if not values.get("entry_time"):
            values["entry_time"] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00')
            
        # Calculate trailing dist if missing
        if "trailing_dist" not in values and "entry_price" in values and "sl" in values:
            if values.get("signal") == "AL":
                values["trailing_dist"] = values["entry_price"] - values["sl"]
            else:
                values["trailing_dist"] = values["sl"] - values["entry_price"]
                
        # Remove volatile fields used only during init
        values.pop("existing_trades_count", None)
        return values

    @root_validator(skip_on_failure=True)
    def validate_logic(cls, values):
        signal = values.get('signal')
        entry = values.get('entry_price')
        sl = values.get('sl')
        tp = values.get('tp')
        ticker = values.get('ticker')
        
        # Max Price Limit (from data_guard PRICE_MAX = 1_000_000)
        PRICE_MAX = 1_000_000
        for label, val in [("entry_price", entry), ("sl", sl), ("tp", tp)]:
            if val is not None and val > PRICE_MAX:
                raise ValueError(f"{ticker}: {label} değeri çok yüksek ({val} > {PRICE_MAX})")

        # Logical checks
        if signal == "AL":
            if sl >= entry:
                raise ValueError(f"[{ticker} LONG] SL ({sl}) >= Entry ({entry})")
            if tp <= entry:
                raise ValueError(f"[{ticker} LONG] TP ({tp}) <= Entry ({entry})")
        elif signal == "SAT":
            if sl <= entry:
                raise ValueError(f"[{ticker} SHORT] SL ({sl}) <= Entry ({entry})")
            if tp >= entry:
                raise ValueError(f"[{ticker} SHORT] TP ({tp}) >= Entry ({entry})")
                
        # 0.1% Min distance check
        if entry > 0:
            sl_dist = abs(entry - sl) / entry
            tp_dist = abs(tp - entry) / entry
            if sl_dist < 0.001:
                raise ValueError(f"[{ticker}] SL mesafesi çok küçük (%{sl_dist*100:.3f} < %0.1)")
            if tp_dist < 0.001:
                raise ValueError(f"[{ticker}] TP mesafesi çok küçük (%{tp_dist*100:.3f} < %0.1)")

        return values

    def stamp_exit(self, current_price: float, status: str):
        self.exit_price = current_price
        self.exit_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S+00:00')
        self.status = status
