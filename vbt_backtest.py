"""
vbt_backtest.py — VectorBT Yüksek Hızlı Backtest Motoru

V3.4/V4.0 Mimarisi kapsamında, yavaş for-loop simülasyonları yerine
numpy matris tabanlı vectorbt motoru ile ışık hızında geriye dönük test
yapmayı sağlayan temel sınıftır.
"""
import pandas as pd
import vectorbt as vbt
import logging

logging.basicConfig(level=logging.INFO)

class VectorBTBacktester:
    def __init__(self, data: pd.DataFrame, fees=0.001, slippage=0.001, init_cash=10000.0):
        """
        data: datetime index'li, 'Close' (veya 'close') sütununa sahip pandas DataFrame.
        """
        self.data = data
        self.fees = fees
        self.slippage = slippage
        self.init_cash = init_cash
        self.portfolio = None
        
        # Sütun isimlerini standartlaştır
        if 'Close' not in self.data.columns and 'close' in self.data.columns:
            self.data.rename(columns={'close': 'Close'}, inplace=True)

    def run_custom_signals(self, entries: pd.Series, exits: pd.Series, short_entries=None, short_exits=None, freq='1h'):
        """
        Dışarıdan gelen bool pandas Series sinyalleri ile nanosaniyede backtest yapar.
        entries ve exits, data index'i ile aynı boyutta True/False matrisleridir.
        """
        logging.info("Running custom signals via vectorbt...")
        
        close_price = self.data['Close']
        
        kwargs = {
            "close": close_price,
            "entries": entries,
            "exits": exits,
            "fees": self.fees,
            "slippage": self.slippage,
            "init_cash": self.init_cash,
            "freq": freq
        }
        
        if short_entries is not None and short_exits is not None:
            kwargs["short_entries"] = short_entries
            kwargs["short_exits"] = short_exits
            
        self.portfolio = vbt.Portfolio.from_signals(**kwargs)
        
        return self.get_stats()

    def get_stats(self):
        if self.portfolio:
            return self.portfolio.stats()
        return None

    def plot(self):
        if self.portfolio:
            return self.portfolio.plot()
        else:
            logging.warning("No portfolio found. Run a backtest first.")
            return None

