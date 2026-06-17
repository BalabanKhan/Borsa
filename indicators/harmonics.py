import numpy as np
import pandas as pd
import config
import pandas_ta as ta

def _check_gartley(x_val, a_val, b_val, c_val, d_val, ratio_ab_xa, ratio_bc_ab, ratio_cd_bc, ratio_ad_xa, tol, current_price, idx_d, close_arr, rsi_d, rsi_b):
    if abs(ratio_ab_xa - 0.618) <= tol:
        if 0.382 - tol <= ratio_bc_ab <= 0.886 + tol:
            if 1.272 - tol <= ratio_cd_bc <= 1.618 + tol:
                if abs(ratio_ad_xa - 0.786) <= tol:
                    if current_price > d_val and (len(close_arr) - 1 - idx_d) <= 4:
                        return "Harmonik Gartley Formasyonu (Boğa)", {
                            "pattern": "Harmonic Gartley",
                            "signal": "AL",
                            "sl": d_val * (1.0 - config.PATTERN_SL_BUFFER),
                            "details": f"D Noktasi: {d_val:.2f}, Retracement: {ratio_ad_xa:.3f}, RSI Div: {rsi_d:.1f} > {rsi_b:.1f}"
                        }
    return None, {}

def _check_bat(x_val, a_val, b_val, c_val, d_val, ratio_ab_xa, ratio_bc_ab, ratio_cd_bc, ratio_ad_xa, tol, current_price, idx_d, close_arr, rsi_d, rsi_b):
    if 0.382 - tol <= ratio_ab_xa <= 0.50 + tol:
        if 0.382 - tol <= ratio_bc_ab <= 0.886 + tol:
            if 1.618 - tol <= ratio_cd_bc <= 2.618 + tol:
                if abs(ratio_ad_xa - 0.886) <= tol:
                    if current_price > d_val and (len(close_arr) - 1 - idx_d) <= 4:
                        return "Harmonik Bat Formasyonu (Boğa)", {
                            "pattern": "Harmonic Bat",
                            "signal": "AL",
                            "sl": d_val * (1.0 - config.PATTERN_SL_BUFFER),
                            "details": f"D Noktasi: {d_val:.2f}, Retracement: {ratio_ad_xa:.3f}, RSI Div: {rsi_d:.1f} > {rsi_b:.1f}"
                        }
    return None, {}

def _check_abcd(ab, cd, ratio_bc_ab, ratio_cd_bc, tol, current_price, idx_d, close_arr, rsi_d, rsi_b, d_val):
    if 0.618 - tol <= ratio_bc_ab <= 0.786 + tol:
        if 1.272 - tol <= ratio_cd_bc <= 1.618 + tol:
            if abs(ab - cd) / max(ab, cd) <= tol:
                if current_price > d_val and (len(close_arr) - 1 - idx_d) <= 4:
                    return "Harmonik AB=CD Formasyonu (Boğa)", {
                        "pattern": "Harmonic ABCD",
                        "signal": "AL",
                        "sl": d_val * (1.0 - config.PATTERN_SL_BUFFER),
                        "details": f"AB: {ab:.2f}, CD: {cd:.2f}, RSI Div: {rsi_d:.1f} > {rsi_b:.1f}"
                    }
    return None, {}

def _get_harmonic_pivots(close_arr, peaks, valleys):
    p_candidates = list(peaks[-3:])
    v_candidates = list(valleys[-3:])
    all_pivots = sorted(
        [(idx, 'P', close_arr[idx]) for idx in p_candidates] + 
        [(idx, 'V', close_arr[idx]) for idx in v_candidates],
        key=lambda x: x[0]
    )
    return all_pivots

def _check_5_pivot_harmonics(pivots_5, close_arr, rsi_series, current_price):
    is_alt = True
    for i in range(4):
        if pivots_5[i][1] == pivots_5[i+1][1]:
            is_alt = False
            break
            
    if is_alt and pivots_5[4][1] == 'V':
        idx_x, x_val = pivots_5[0][0], pivots_5[0][2]
        idx_a, a_val = pivots_5[1][0], pivots_5[1][2]
        idx_b, b_val = pivots_5[2][0], pivots_5[2][2]
        idx_c, c_val = pivots_5[3][0], pivots_5[3][2]
        idx_d, d_val = pivots_5[4][0], pivots_5[4][2]
        
        xa = abs(a_val - x_val)
        ab = abs(b_val - a_val)
        bc = abs(c_val - b_val)
        cd = abs(d_val - c_val)
        
        ratio_ab_xa = ab / max(xa, 1e-8)
        ratio_bc_ab = bc / max(ab, 1e-8)
        ratio_cd_bc = cd / max(bc, 1e-8)
        ratio_ad_xa = (a_val - d_val) / max(xa, 1e-8)
        
        tol = config.BIST12_HARMONIC_TOLERANCE
        rsi_b = float(rsi_series.iloc[idx_b]) if rsi_series is not None and len(rsi_series) > idx_b else None
        rsi_d = float(rsi_series.iloc[idx_d]) if rsi_series is not None and len(rsi_series) > idx_d else None
        has_rsi_div = (
            rsi_b is not None and rsi_d is not None and 
            not np.isnan(rsi_b) and not np.isnan(rsi_d) and 
            d_val < b_val and rsi_d > rsi_b
        )
        
        if has_rsi_div:
            name, details = _check_gartley(x_val, a_val, b_val, c_val, d_val, ratio_ab_xa, ratio_bc_ab, ratio_cd_bc, ratio_ad_xa, tol, current_price, idx_d, close_arr, rsi_d, rsi_b)
            if name:
                return name, details
            name, details = _check_bat(x_val, a_val, b_val, c_val, d_val, ratio_ab_xa, ratio_bc_ab, ratio_cd_bc, ratio_ad_xa, tol, current_price, idx_d, close_arr, rsi_d, rsi_b)
            if name:
                return name, details
    return None, {}

def _check_4_pivot_harmonics(pivots_4, close_arr, rsi_series, current_price):
    is_alt_4 = True
    for i in range(3):
        if pivots_4[i][1] == pivots_4[i+1][1]:
            is_alt_4 = False
            break
            
    if is_alt_4 and pivots_4[3][1] == 'V':
        idx_a, a_val = pivots_4[0][0], pivots_4[0][2]
        idx_b, b_val = pivots_4[1][0], pivots_4[1][2]
        idx_c, c_val = pivots_4[2][0], pivots_4[2][2]
        idx_d, d_val = pivots_4[3][0], pivots_4[3][2]
        
        ab = abs(b_val - a_val)
        bc = abs(c_val - b_val)
        cd = abs(d_val - c_val)
        
        ratio_bc_ab = bc / max(ab, 1e-8)
        ratio_cd_bc = cd / max(bc, 1e-8)
        tol = config.BIST12_HARMONIC_TOLERANCE
        rsi_b = float(rsi_series.iloc[idx_b]) if rsi_series is not None and len(rsi_series) > idx_b else None
        rsi_d = float(rsi_series.iloc[idx_d]) if rsi_series is not None and len(rsi_series) > idx_d else None
        has_rsi_div = (
            rsi_b is not None and rsi_d is not None and 
            not np.isnan(rsi_b) and not np.isnan(rsi_d) and 
            d_val < b_val and rsi_d > rsi_b
        )
        
        if has_rsi_div:
            name, details = _check_abcd(ab, cd, ratio_bc_ab, ratio_cd_bc, tol, current_price, idx_d, close_arr, rsi_d, rsi_b, d_val)
            if name:
                return name, details
    return None, {}

def _check_harmonic_patterns(df_4h, close_arr, peaks, valleys, current_price):
    if len(peaks) < 2 or len(valleys) < 2:
        return None, {}

    all_pivots = _get_harmonic_pivots(close_arr, peaks, valleys)
    
    rsi_col = f'RSI_{config.IND_RSI_LENGTH}'
    rsi_series = df_4h[rsi_col] if rsi_col in df_4h.columns else ta.rsi(df_4h['close'], length=config.IND_RSI_LENGTH)
    
    if len(all_pivots) >= 5:
        name, details = _check_5_pivot_harmonics(all_pivots[-5:], close_arr, rsi_series, current_price)
        if name:
            return name, details

    if len(all_pivots) >= 4:
        name, details = _check_4_pivot_harmonics(all_pivots[-4:], close_arr, rsi_series, current_price)
        if name:
            return name, details
            
    return None, {}
