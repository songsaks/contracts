import numpy as np
import pandas as pd

def calculate_htf_setup(df):
    """
    คำนวณ High Tight Flag (Power Play) Pattern:
    1. Surge: พุ่งขึ้น >= 70-100% ในช่วง 20-60 แท่นเทียนล่าสุด
    2. Base Depth: พักตัวจากจุดสูงสุดไม่เกิน 25%
    """
    try:
        if len(df) < 35:
            return False, 0.0, 0.0

        closes = df['Close'].values
        highs  = df['High'].values
        lows   = df['Low'].values

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

        if max_idx < lookback - 1:
            base_lows = recent_lows[max_idx:]
            lowest_after_peak = np.min(base_lows)
            base_depth = ((max_p - lowest_after_peak) / max_p) * 100.0
        else:
            base_depth = 0.0

        current_price = closes[-1]
        dist_from_peak = ((max_p - current_price) / max_p) * 100.0

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

        sma20 = pd.Series(closes).rolling(period).mean().values
        std20 = pd.Series(closes).rolling(period).std().values
        bb_upper = sma20 + (2.0 * std20)
        bb_lower = sma20 - (2.0 * std20)

        tr = np.maximum(highs[1:] - lows[1:], 
             np.maximum(np.abs(highs[1:] - closes[:-1]), 
                        np.abs(lows[1:] - closes[:-1])))
        tr = np.insert(tr, 0, highs[0] - lows[0])
        atr20 = pd.Series(tr).rolling(period).mean().values
        
        kc_upper = sma20 + (1.5 * atr20)
        kc_lower = sma20 - (1.5 * atr20)

        squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)

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

        daily_ranges = ((highs[-20:] - lows[-20:]) / np.maximum(lows[-20:], 1e-5)) * 100.0
        adr_20d_pct = float(np.mean(daily_ranges))

        return is_extended, round(ma50_dist_pct, 1), round(adr_20d_pct, 1)

    except Exception:
        return False, 0.0, 0.0


def calculate_best_loser_metrics(df, current_price=0.0, target_price=None, stop_price=None):
    """
    คำนวณตัววัด Best Loser Wins (Tom Hougaard):
    1. Pyramiding Ready: หุ้นกำลังอยู่ในขาขึ้น (กำไร +2% ถึง +12% ในช่วง 5 แท่งล่าสุด, ยืนเหนือ EMA10/20, Vol มีทิศทางบวก)
    2. Anti-Averaging Down Alert: หุ้นหลุด Stop Loss หรือหลุด EMA50 (ห้ามถัวเฉลี่ย!)
    3. R:R Ratio & Risk% per share (คำนวณ ATR Stop & Target R:R)
    """
    try:
        if len(df) < 20:
            return {
                'pyramiding_ready': False,
                'anti_avg_down_alert': False,
                'rr_ratio': 0.0,
                'atr_stop_price': 0.0,
                'risk_per_share': 0.0,
                'risk_pct': 0.0,
                'atr14': 0.0
            }

        closes = df['Close'].values
        highs  = df['High'].values
        lows   = df['Low'].values
        vols   = df['Volume'].values

        c_price = current_price if current_price > 0 else float(closes[-1])

        # คำนวณ ATR (14)
        tr = np.maximum(highs[1:] - lows[1:], 
             np.maximum(np.abs(highs[1:] - closes[:-1]), 
                        np.abs(lows[1:] - closes[:-1])))
        tr = np.insert(tr, 0, highs[0] - lows[0])
        atr14 = float(np.mean(tr[-14:])) if len(tr) >= 14 else float(tr.mean())

        # ATR-based Stop Price (default = current_price - 2 * ATR14)
        atr_stop = round(c_price - (2.0 * atr14), 2) if atr14 > 0 else round(c_price * 0.95, 2)
        eff_stop = stop_price if (stop_price and stop_price > 0 and stop_price < c_price) else atr_stop

        risk_per_share = round(c_price - eff_stop, 2)
        risk_pct = round((risk_per_share / c_price) * 100.0, 1) if c_price > 0 else 0.0

        # R:R Ratio
        if target_price and target_price > c_price and risk_per_share > 0:
            reward = target_price - c_price
            rr_ratio = round(reward / risk_per_share, 2)
        else:
            rr_ratio = 0.0

        # EMA 10, 20, 50
        ema10 = pd.Series(closes).ewm(span=10).mean().iloc[-1]
        ema20 = pd.Series(closes).ewm(span=20).mean().iloc[-1]
        ema50 = pd.Series(closes).ewm(span=50).mean().iloc[-1]

        # Pyramiding Ready: ราคา > EMA10 > EMA20, และมีโมเมนตัมกำลังไต่ขึ้นช่วง +2% ถึง +12% ในช่วง 5 แท่งล่าสุด
        min_5d = float(np.min(closes[-5:]))
        gain_from_5d_min = ((c_price - min_5d) / min_5d) * 100.0 if min_5d > 0 else 0.0
        
        avg_vol_20 = np.mean(vols[-20:]) if len(vols) >= 20 else np.mean(vols)
        curr_vol = float(vols[-1])
        vol_surge = curr_vol >= (avg_vol_20 * 1.2) if avg_vol_20 > 0 else False

        pyramiding_ready = (c_price > ema10) and (ema10 >= ema20) and (2.0 <= gain_from_5d_min <= 12.0) and vol_surge

        # Anti-Averaging Down Alert: ราคาหลุด EMA50 หรือ ราคาหลุดจุด Stop Loss
        anti_avg_down_alert = (c_price < ema50) or (stop_price and c_price <= stop_price)

        return {
            'pyramiding_ready': pyramiding_ready,
            'anti_avg_down_alert': anti_avg_down_alert,
            'rr_ratio': rr_ratio,
            'atr_stop_price': atr_stop,
            'risk_per_share': risk_per_share,
            'risk_pct': risk_pct,
            'atr14': round(atr14, 2)
        }

    except Exception:
        return {
            'pyramiding_ready': False,
            'anti_avg_down_alert': False,
            'rr_ratio': 0.0,
            'atr_stop_price': 0.0,
            'risk_per_share': 0.0,
            'risk_pct': 0.0,
            'atr14': 0.0
        }

