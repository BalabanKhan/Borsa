import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

# Try to import talib, with a fallback to pandas_ta
USE_TALIB = False
USE_PANDAS_TA = False

try:
    import talib
    USE_TALIB = True
    logger.info("TA-Lib successfully loaded. Priority engine set to TA-Lib.")
except ImportError:
    logger.warning("TA-Lib not found. Falling back to pandas_ta.")
    
try:
    import pandas_ta as ta
    USE_PANDAS_TA = True
    if not USE_TALIB:
        logger.info("pandas_ta successfully loaded. Fallback engine active.")
except ImportError:
    if not USE_TALIB:
        logger.error("CRITICAL: Neither TA-Lib nor pandas_ta is installed. Indicator engine will fail.")

class IndicatorEngine:
    """
    A robust, high-performance indicator engine that prioritizes C-based TA-Lib
    and falls back to pandas_ta if TA-Lib is unavailable.
    """
    
    @staticmethod
    def rsi(series: pd.Series, length: int = 14) -> pd.Series:
        if USE_TALIB:
            return pd.Series(talib.RSI(series.values, timeperiod=length), index=series.index)
        elif USE_PANDAS_TA:
            return ta.rsi(series, length=length)
        else:
            raise ImportError("No indicator library available.")

    @staticmethod
    def sma(series: pd.Series, length: int) -> pd.Series:
        if USE_TALIB:
            return pd.Series(talib.SMA(series.values, timeperiod=length), index=series.index)
        elif USE_PANDAS_TA:
            return ta.sma(series, length=length)
        else:
            raise ImportError("No indicator library available.")

    @staticmethod
    def ema(series: pd.Series, length: int) -> pd.Series:
        if USE_TALIB:
            return pd.Series(talib.EMA(series.values, timeperiod=length), index=series.index)
        elif USE_PANDAS_TA:
            return ta.ema(series, length=length)
        else:
            raise ImportError("No indicator library available.")

    @staticmethod
    def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        if USE_TALIB:
            macd_line, macd_signal, macd_hist = talib.MACD(series.values, fastperiod=fast, slowperiod=slow, signalperiod=signal)
            return pd.DataFrame({
                'MACD': macd_line,
                'MACDs': macd_signal,
                'MACDh': macd_hist
            }, index=series.index)
        elif USE_PANDAS_TA:
            return ta.macd(series, fast=fast, slow=slow, signal=signal)
        else:
            raise ImportError("No indicator library available.")

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
        if USE_TALIB:
            return pd.Series(talib.ATR(high.values, low.values, close.values, timeperiod=length), index=close.index)
        elif USE_PANDAS_TA:
            return ta.atr(high, low, close, length=length)
        else:
            raise ImportError("No indicator library available.")

    @staticmethod
    def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14):
        if USE_TALIB:
            # TA-Lib returns only ADX, but pandas_ta returns ADX, DMP, DMN
            adx = talib.ADX(high.values, low.values, close.values, timeperiod=length)
            plus_di = talib.PLUS_DI(high.values, low.values, close.values, timeperiod=length)
            minus_di = talib.MINUS_DI(high.values, low.values, close.values, timeperiod=length)
            return pd.DataFrame({
                f'ADX_{length}': adx,
                f'DMP_{length}': plus_di,
                f'DMN_{length}': minus_di
            }, index=close.index)
        elif USE_PANDAS_TA:
            return ta.adx(high, low, close, length=length)
        else:
            raise ImportError("No indicator library available.")

    @staticmethod
    def bbands(series: pd.Series, length: int = 20, std: float = 2.0):
        if USE_TALIB:
            upper, middle, lower = talib.BBANDS(series.values, timeperiod=length, nbdevup=std, nbdevdn=std, matype=0)
            return pd.DataFrame({
                f'BBL_{length}_{std}': lower,
                f'BBM_{length}_{std}': middle,
                f'BBU_{length}_{std}': upper
            }, index=series.index)
        elif USE_PANDAS_TA:
            # pandas_ta returns BBL, BBM, BBU, BBB, BBP
            df = ta.bbands(series, length=length, std=std)
            return df
        else:
            raise ImportError("No indicator library available.")

    @staticmethod
    def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
        # VWAP usually requires pandas_ta as TA-Lib doesn't have a native VWAP function
        if USE_PANDAS_TA:
            return ta.vwap(high, low, close, volume)
        else:
            # Manual fallback if pandas_ta is not available but TA-Lib is
            typical_price = (high + low + close) / 3
            return (typical_price * volume).cumsum() / volume.cumsum()

    @staticmethod
    def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        if USE_TALIB:
            return pd.Series(talib.OBV(close.values, volume.values), index=close.index)
        elif USE_PANDAS_TA:
            return ta.obv(close, volume)
        else:
            raise ImportError("No indicator library available.")
