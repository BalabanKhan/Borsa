"""
🔧 FIX: _get_structural_floor EMA Unpacking Hatası Çözümü

Hata: "too many values to unpack (expected 2)"
Sebep: EMA hesaplama işleminde tuple return edilen değerlerin 
yanlış unpacking'i veya DataFrame column name mismatch

Çözüm: Basit try-except bloğu ile korunan EMA hesaplama
"""

import pandas as pd
import pandas_ta as ta
import logging

def _get_structural_floor_safe(df, symbol):
    """
    Güvenli EMA hesaplama wrapper.
    Hataları gracefully handle eder, None döner.
    
    Args:
        df: OHLCV DataFrame
        symbol: Varlık sembolü (logging için)
    
    Returns:
        float: EMA_20 değeri veya None
    """
    try:
        if df is None or df.empty or len(df) < 20:
            return None
        
        df_copy = df.copy()
        
        # ✅ Method 1: pandas_ta ile EMA (append=True)
        try:
            # Önce var olan kolonları kontrol et
            if 'EMA_20' not in df_copy.columns and 'ema_20' not in df_copy.columns:
                df_copy.ta.ema(length=20, append=True)
            
            # Tüm olası EMA kolon adlarını kontrol et
            ema_cols = [c for c in df_copy.columns if 'ema' in c.lower() and '20' in c.lower()]
            if ema_cols:
                ema_val = df_copy[ema_cols[0]].iloc[-1]
                if pd.notna(ema_val):
                    return float(ema_val)
        except Exception as e:
            logging.debug(f"[_get_structural_floor_safe] pandas_ta.ema hatası ({symbol}): {e}")
        
        # ✅ Method 2: Manual EMA hesaplama (fallback)
        try:
            if 'close' in df_copy.columns:
                close_col = 'close'
            elif 'Close' in df_copy.columns:
                close_col = 'Close'
            else:
                return None
            
            closes = df_copy[close_col].values
            closes = pd.to_numeric(closes, errors='coerce')
            closes = closes[pd.notna(closes)]
            
            if len(closes) < 20:
                return None
            
            # Exponential moving average manual hesaplama
            alpha = 2 / (20 + 1)
            ema_vals = [float(closes[0])]
            for i in range(1, len(closes)):
                ema = float(closes[i]) * alpha + ema_vals[-1] * (1 - alpha)
                ema_vals.append(ema)
            
            return float(ema_vals[-1])
        except Exception as e:
            logging.debug(f"[_get_structural_floor_safe] Manual EMA hatası ({symbol}): {e}")
        
        return None
    
    except Exception as e:
        logging.warning(f"[_get_structural_floor_safe] Beklenmeyen hata ({symbol}): {e}")
        return None


def apply_structural_floor_fix(df, symbol):
    """
    DataFrame'e güvenli EMA hesaplaması ekle.
    
    Parametreler:
    - df: OHLCV DataFrame
    - symbol: Varlık sembolü (logging için)
    
    Returns: Düzeltilmiş DataFrame
    """
    if df is None or df.empty:
        return df
    
    try:
        df_fixed = df.copy()
        
        # Var olan EMA kolonlarını kontrol et
        has_ema = any('ema' in c.lower() for c in df_fixed.columns)
        
        if not has_ema and len(df_fixed) >= 20:
            try:
                # Önce veri türlerini kontrol et ve temizle
                if 'close' in df_fixed.columns:
                    df_fixed['close'] = pd.to_numeric(df_fixed['close'], errors='coerce')
                elif 'Close' in df_fixed.columns:
                    df_fixed['Close'] = pd.to_numeric(df_fixed['Close'], errors='coerce')
                
                # NaN değerleri doldur
                df_fixed = df_fixed.fillna(method='ffill').fillna(method='bfill')
                
                # EMA hesapla
                df_fixed.ta.ema(length=20, append=True)
                logging.debug(f"[apply_structural_floor_fix] {symbol}: EMA başarıyla hesaplandı")
            except Exception as e:
                logging.warning(f"[apply_structural_floor_fix] {symbol} EMA eklemesi başarısız: {e}")
        
        return df_fixed
    
    except Exception as e:
        logging.error(f"[apply_structural_floor_fix] {symbol}: {e}")
        return df


# ═══════════════════════════════════════════════════════════════
# KULLANIM ÖRNEKLERİ
# ═══════════════════════════════════════════════════════════════

"""
💡 ÖRNEK 1: indicators.py içinde kullanım

from fix_structural_floor import _get_structural_floor_safe

def sniper_get_htf_bias(df):
    if len(df) < 50:
        return 0
    df = df.copy()
    
    # ESKI (HATALI):
    # if f'EMA_{config.IND_EMA_MID}' not in df.columns:
    #     df.ta.ema(length=config.IND_EMA_MID, append=True)
    # ema20 = df[f'EMA_{config.IND_EMA_MID}'].iloc[-1]
    
    # YENİ (DÜZELTILMIŞ):
    ema20 = _get_structural_floor_safe(df, "HTF_BIAS_EMA20")
    if ema20 is None:
        return 0
    
    ema50 = _get_structural_floor_safe(df, "HTF_BIAS_EMA50")
    if ema50 is None:
        return 0
    
    close = df['close'].iloc[-1]
    
    if ema20 > ema50 and close > ema20:
        return 1
    elif ema20 < ema50 and close < ema20:
        return -1
    return 0


💡 ÖRNEK 2: strategies.py içinde veri çekimi sonrası

from fix_structural_floor import apply_structural_floor_fix

def analyze_strategies_bist(symbol, df_1d, df_4h, df_1h, ...):
    # Veri çekimi sonrası hemen düzelt
    df_1d = apply_structural_floor_fix(df_1d, symbol)
    df_4h = apply_structural_floor_fix(df_4h, symbol)
    df_1h = apply_structural_floor_fix(df_1h, symbol)
    
    # Artık EMA hesaplamaları güvenli
    ...
"""
