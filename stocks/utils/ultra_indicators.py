import numpy as np
import pandas as pd

def calculate_htf_setup(df):
    """
    คำนวณ High Tight Flag (Power Play) Pattern:
    1. Surge: พุ่งขึ้น >= 70-100% ในช่วง 20-50 แท่นเทียนล่าสุด
    2. Base Depth: พักตัวจากจุดสูงสุดไม่เกิน 25%
    """
    try:
        if len(df) < 35:
            return False, 0.0, 0.0

        closes = df['Close'].values
        highs  = df['High'].values
        lows   = df['Low'].values
        vols   = df['Volume'].values

        n = len(closes)
        lookback = min(60, n)
        recent_highs = highs[-lookback:]
        recent_lows  = lows[-lookback:]

        max_idx = np.argmax(recent_highs)
        min_idx = np.argmin(recent_lows[:max_idx+1]) if max_idx > 0 else 0

        min_p = recent_lows[min_idx]
        max_p = recent_highs[max_idx]

        if min_p <= 0:
            return False, 0.0, 0.0

        surge_pct = ((max_p - min_p) / min_p) * 100.0

        # Base contraction depth from max_p to recent low after peak
        if max_idx < lookback - 1:
            base_lows = recent_lows[max_idx:]
            lowest_after_peak = np.min(base_lows)
            base_depth = ((max_p - lowest_after_peak) / max_p) * 100.0
        else:
            base_depth = 0.0

        current_price = closes[-1]
        dist_from_peak = ((max_p - current_price) / max_p) * 100.0

        # Criteria: Surge >= 70% AND Base Depth <= 25% AND Currently within 20% of peak
        is_htf = (surge_pct >= 70.0) and (base_depth <= 25.0) and (dist_from_peak <= 20.0)
        return is_htf, round(surge_pct, 1), round(base_depth, 1)

    except Exception:
        return False, 0.0, 0.0


def calculate_ttm_squeeze(df):
    """
    คำนวณ TTM Volatility Squeeze (John Carter):
    - Squeeze On (building): Bollinger Bands (20, 2.0) บีบตัวเข้ามาอยู่ข้างใน Keltner Channels (20, 1.5 ATR)
    - Squeeze Fired (fired): เพิ่งหลุดจาก Squeeze On ภายใน 1-3 แท่งแรก
    """
    try:
        if len(df) < 25:
            return 'none', 0

        closes = df['Close'].values
        highs  = df['High'].values
        lows   = df['Low'].values

        n = len(closes)
        period = 20

        # Calculate Bollinger Bands
        sma20 = pd.Series(closes).rolling(period).mean().values
        std20 = pd.Series(closes).rolling(period).std().values
        bb_upper = sma20 + (2.0 * std20)
        bb_lower = sma20 - (2.0 * std20)

        # Calculate Keltner Channels (20, 1.5 ATR)
        tr = np.maximum(highs[1:] - lows[1:], 
             np.maximum(np.abs(highs[1:] - closes[:-1]), 
                        np.abs(lows[1:] - closes[:-1])))
        tr = np.insert(tr, 0, highs[0] - lows[0])
        atr20 = pd.Series(tr).rolling(period).mean().values
        
        kc_upper = sma20 + (1.5 * atr20)
        kc_lower = sma20 - (1.5 * atr20)

        squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)

        # Count consecutive squeeze length
        sq_len = 0
        for b in reversed(squeeze_on):
            if b:
                sq_len += 1
            else:
                break

        curr_sq = squeeze_on[-1]
        prev_1  = squeeze_on[-2] if n >= 2 else False
        prev_2  = squeeze_on[-3] if n >= 3 else False

        if curr_sq:
            state = 'building'
        elif not curr_sq and (prev_1 or prev_2):
            state = 'fired'
        else:
            state = 'none'

        return state, sq_len

    except Exception:
        return 'none', 0


def calculate_episodic_pivot(df):
    """
    คำนวณ Episodic Pivot (EP - Qullamaggie Gap Up):
    - Gap Up >= 4.5%
    - Volume >= 2.5x ของค่าเฉลี่ย 20 วัน
    - ราคาปิดเป็นแท่งเขียว (Close > Open)
    """
    try:
        if len(df) < 20:
            return False, 0.0

        closes = df['Close'].values
        opens  = df['Open'].values
        vols   = df['Volume'].values

        prev_close = closes[-2]
        curr_open  = opens[-1]
        curr_close = closes[-1]
        curr_vol   = vols[-1]
        avg_vol_20 = np.mean(vols[-21:-1]) if len(vols) >= 21 else np.mean(vols[:-1])

        if prev_close <= 0 or avg_vol_20 <= 0:
            return False, 0.0

        gap_pct = ((curr_open - prev_close) / prev_close) * 100.0
        vol_ratio = curr_vol / avg_vol_20

        is_ep = (gap_pct >= 4.5) and (vol_ratio >= 2.5) and (curr_close >= curr_open)
        return is_ep, round(gap_pct, 1)

    except Exception:
        return False, 0.0


def calculate_avoidance_and_adr(df):
    """
    คำนวณ Avoidance / Extended Filter และ ADR% 20d:
    - Distance from MA50 > 25% = Extended (เสี่ยงย่อตัว)
    - ADR% 20d = Average Daily Range %
    """
    try:
        if len(df) < 50:
            return False, 0.0, 0.0

        closes = df['Close'].values
        highs  = df['High'].values
        lows   = df['Low'].values

        curr_close = closes[-1]
        ma50 = np.mean(closes[-50:])

        ma50_dist_pct = ((curr_close - ma50) / ma50) * 100.0 if ma50 > 0 else 0.0
        is_extended = ma50_dist_pct > 25.0

        # ADR% (Average Daily Range) 20d
        daily_ranges = ((highs[-20:] - lows[-20:]) / np.maximum(lows[-20:], 1e-5)) * 100.0
        adr_20d_pct = float(np.mean(daily_ranges))

        return is_extended, round(ma50_dist_pct, 1), round(adr_20d_pct, 1)

    except Exception:
        return False, 0.0, 0.0
