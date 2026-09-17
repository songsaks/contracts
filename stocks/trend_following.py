"""
Trend Following ตามต้นตำรับ — Donchian 4-Week Rule และ Turtle Trading System

ทำไมต้องแยกเป็นโมดูล
--------------------
กฎของสายนี้เป็นกฎตายตัวที่มีเจ้าของและมีนิยามชัดเจน ถ้าโค้ดคำนวณเบี่ยงจากนิยาม
แล้วยังใช้ชื่อเดิม ตัวเลขบนหน้าจอจะอ้างอิงอะไรไม่ได้เลย โมดูลนี้เก็บนิยามไว้
ที่เดียว เป็นฟังก์ชันล้วน ไม่แตะ DB ไม่ยิงเน็ต จึงทดสอบได้ตรงๆ

นิยามที่ยึด
-----------
Richard Donchian — 4-Week Rule (ต้นกำเนิดของทั้งสาย):
    ซื้อเมื่อราคาทะลุจุดสูงสุดในรอบ 4 สัปดาห์ (20 วันทำการ)
    ขายเมื่อราคาทะลุจุดต่ำสุดในรอบ 4 สัปดาห์

Richard Dennis / William Eckhardt — Turtle Trading System:
    System 1: เข้าเมื่อทะลุ High 20 วัน  ออกเมื่อหลุด Low 10 วัน
              *** ข้ามสัญญาณถ้า breakout 20 วันครั้งก่อนหน้าเป็นไม้ที่กำไร ***
    System 2: เข้าเมื่อทะลุ High 55 วัน  ออกเมื่อหลุด Low 20 วัน
              เข้าทุกครั้ง ไม่มีตัวกรอง
    N (ความผันผวน) = ATR 20 วัน
    Stop = ราคาเข้า − 2N

กฎ "ข้ามถ้าครั้งก่อนกำไร" ของ System 1 คือหัวใจที่ทำให้ S1 ต่างจาก S2 และเป็น
เหตุผลที่ S2 มีอยู่ (ไว้รับเทรนด์ใหญ่ที่ S1 ข้ามไป) ถ้าตัดกฎนี้ออก สิ่งที่เหลือ
คือ Donchian breakout เฉยๆ ไม่ใช่ Turtle System 1

เรื่องราคาที่ใช้ตัดสิน breakout
--------------------------------
ทั้ง Donchian, Turtle และ Livermore (Pivotal Point) นับ breakout จากการที่ราคา
"ทะลุผ่าน" จุดสูงสุด ซึ่งเกิดระหว่างวัน ไม่ใช่รอราคาปิด โมดูลนี้จึงใช้ High
เป็นค่ามาตรฐาน และเปิดทางให้เลือก Close ได้ผ่าน use_close สำหรับคนที่ต้องการ
เวอร์ชันเข้มกว่าเพื่อกรอง whipsaw — แต่ต้องเลือกเอง ไม่ใช่ค่าเริ่มต้นเงียบๆ
"""

import numpy as np
import pandas as pd

# ค่ามาตรฐานของระบบ — ตัวเลขเหล่านี้มีที่มาจากตำรา ไม่ใช่ค่าที่จูนเอง
DONCHIAN_ENTRY_DAYS = 20      # 4-Week Rule ของ Donchian
SYS1_ENTRY_DAYS = 20
SYS1_EXIT_DAYS = 10
SYS2_ENTRY_DAYS = 55
SYS2_EXIT_DAYS = 20
ATR_PERIOD = 20               # ค่า N ของ Turtle
STOP_N_MULTIPLE = 2.0         # Stop = entry − 2N


def donchian_channel(df, period=DONCHIAN_ENTRY_DAYS):
    """
    Donchian Channel — กรอบสูงสุด/ต่ำสุดในรอบ N วัน

    shift(1) สำคัญ: กรอบของ "วันนี้" ต้องคิดจากข้อมูลถึงเมื่อวานเท่านั้น ไม่งั้น
    ราคาวันนี้จะถูกนับเข้าไปในกรอบที่ตัวมันเองต้องทะลุ ซึ่งทำให้ไม่มีวันทะลุได้
    """
    if df is None or len(df) < period + 1:
        return None
    return pd.DataFrame({
        'upper': df['High'].rolling(period).max().shift(1),
        'lower': df['Low'].rolling(period).min().shift(1),
    }, index=df.index)


def _breakout_series(df, period, use_close=False):
    """คืน Series บูลีนว่าวันไหนทะลุกรอบบนของ N วัน"""
    upper = df['High'].rolling(period).max().shift(1)
    price = df['Close'] if use_close else df['High']
    # ทะลุ = มากกว่า ไม่ใช่เท่ากับ — แค่แตะเท่าจุดเดิมยังไม่เรียกว่าทะลุ
    return price > upper


def simulate_breakout_trades(df, entry_days, exit_days, use_close=False):
    """
    จำลองการเทรดตามกฎ breakout ทั้งชุดจากประวัติราคา

    คืน list ของ dict: {entry_idx, entry_price, exit_idx, exit_price, is_win}
    ใช้สำหรับตอบคำถามเดียวคือ "ไม้ก่อนหน้ากำไรหรือขาดทุน" ซึ่งเป็นข้อมูลที่
    System 1 ต้องใช้ตัดสินใจ ไม่ได้ทำมาเพื่อวัดผลตอบแทนของระบบ

    การจำลองตั้งใจให้เรียบง่ายและตรงกฎ: เข้าที่ระดับ breakout ออกที่ระดับ exit
    ไม่คิดค่าคอมฯ ไม่คิด slippage ไม่ทบไม้ (pyramid) เพราะไม่มีผลต่อคำถามข้างบน
    """
    if df is None or len(df) < entry_days + exit_days + 2:
        return []

    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    n = len(df)

    upper = pd.Series(highs).rolling(entry_days).max().shift(1).values
    lower = pd.Series(lows).rolling(exit_days).min().shift(1).values
    trigger = closes if use_close else highs

    trades = []
    i = max(entry_days, exit_days) + 1
    while i < n:
        up = upper[i]
        if np.isnan(up) or trigger[i] <= up:
            i += 1
            continue

        # เข้าที่ระดับ breakout เอง ไม่ใช่ราคาปิด — ตามกฎที่สั่งซื้อรออยู่ที่ระดับนั้น
        entry_price = float(up) if not use_close else float(closes[i])
        entry_idx = i

        exit_idx, exit_price = None, None
        j = i + 1
        while j < n:
            lo = lower[j]
            if not np.isnan(lo) and (closes[j] if use_close else lows[j]) < lo:
                exit_idx = j
                exit_price = float(lo) if not use_close else float(closes[j])
                break
            j += 1

        if exit_idx is None:
            # ไม้ที่ยังไม่ปิด ไม่นับเป็นผลแพ้ชนะ เพราะยังไม่รู้ผล
            break

        trades.append({
            'entry_idx': entry_idx, 'entry_price': entry_price,
            'exit_idx': exit_idx, 'exit_price': exit_price,
            'is_win': exit_price > entry_price,
        })
        i = exit_idx + 1

    return trades


def system1_should_skip(df, use_close=False):
    """
    System 1 ต้องข้ามสัญญาณนี้หรือไม่

    กฎ Dennis/Eckhardt: ถ้า breakout 20 วันครั้งก่อนหน้าเป็นไม้ที่ "กำไร"
    ให้ข้ามสัญญาณครั้งนี้ไป เหตุผลคือหลังไม้ที่กินเทรนด์ไปแล้ว breakout ถัดมา
    มักเป็นสัญญาณหลอกในกรอบ — Turtle ยอมพลาดเทรนด์ใหญ่บางรอบเพื่อเลี่ยงจุดนี้
    และชดเชยด้วย System 2 ที่ไม่มีตัวกรอง

    คืน (should_skip: bool, reason: str)
    """
    trades = simulate_breakout_trades(df, SYS1_ENTRY_DAYS, SYS1_EXIT_DAYS, use_close)
    if not trades:
        return False, "ยังไม่มีไม้ก่อนหน้าให้อ้างอิง — เข้าได้ตามกฎ"
    last = trades[-1]
    if last['is_win']:
        return True, (f"ข้ามตามกฎ S1: breakout ครั้งก่อนเป็นไม้กำไร "
                      f"({last['entry_price']:.2f} → {last['exit_price']:.2f})")
    return False, (f"เข้าได้: breakout ครั้งก่อนเป็นไม้ขาดทุน "
                   f"({last['entry_price']:.2f} → {last['exit_price']:.2f})")


def turtle_stop(entry_price, n_value, multiple=STOP_N_MULTIPLE):
    """Stop ตามกฎ Turtle = ราคาเข้า − 2N (N คือ ATR 20 วัน)"""
    try:
        entry = float(entry_price)
        n = float(n_value)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or n <= 0:
        return None
    return round(entry - multiple * n, 4)


def unit_size(equity, n_value, risk_pct=1.0, point_value=1.0):
    """
    ขนาดไม้ตามกฎ Turtle: 1 Unit = (equity × 1%) / (N × มูลค่าต่อจุด)

    Turtle เสี่ยง 1% ของพอร์ตต่อหนึ่ง Unit โดยวัดความเสี่ยงด้วย N ไม่ใช่
    เปอร์เซ็นต์ราคาตายตัว หุ้นผันผวนมากจึงได้ไม้เล็กลงโดยอัตโนมัติ
    """
    try:
        eq = float(equity)
        n = float(n_value)
    except (TypeError, ValueError):
        return None
    if eq <= 0 or n <= 0 or point_value <= 0:
        return None
    return int((eq * (risk_pct / 100.0)) / (n * point_value))


def breakout_state(df, use_close=False):
    """
    สรุปสถานะ breakout ของหุ้นตัวหนึ่งตามกฎ Donchian/Turtle ครบชุด

    คืน dict พร้อมใช้: ระดับกรอบ, ทะลุหรือยัง, S1 ต้องข้ามไหม, stop 2N
    """
    if df is None or len(df) < SYS2_ENTRY_DAYS + 1:
        return None

    h20 = float(df['High'].rolling(SYS1_ENTRY_DAYS).max().shift(1).iloc[-1])
    h55 = float(df['High'].rolling(SYS2_ENTRY_DAYS).max().shift(1).iloc[-1])
    l10 = float(df['Low'].rolling(SYS1_EXIT_DAYS).min().shift(1).iloc[-1])
    l20 = float(df['Low'].rolling(SYS2_EXIT_DAYS).min().shift(1).iloc[-1])

    trigger = float(df['Close'].iloc[-1] if use_close else df['High'].iloc[-1])
    close = float(df['Close'].iloc[-1])

    sys1_raw = not np.isnan(h20) and trigger > h20
    sys2 = not np.isnan(h55) and trigger > h55

    skip, skip_reason = (system1_should_skip(df, use_close) if sys1_raw
                         else (False, ''))

    return {
        'high_20d': None if np.isnan(h20) else round(h20, 4),
        'high_55d': None if np.isnan(h55) else round(h55, 4),
        'low_10d': None if np.isnan(l10) else round(l10, 4),
        'low_20d': None if np.isnan(l20) else round(l20, 4),
        # sys1_raw = ทะลุกรอบแล้ว / sys1 = ทะลุแล้วและไม่ถูกกฎข้าม
        'sys1_raw_breakout': sys1_raw,
        'sys1_breakout': sys1_raw and not skip,
        'sys1_skipped': skip,
        'sys1_skip_reason': skip_reason,
        'sys2_breakout': sys2,
        'close': close,
        'trigger_price': trigger,
        'uses_close': use_close,
    }


# ----------------------------------------------------------------------
# Donchian 4-Week Rule — กฎดั้งเดิมที่เป็นต้นทางของทั้งสาย
#
# สิ่งที่ต่างจาก Turtle: Donchian ใช้กรอบ 20 วันทั้งขาเข้าและขาออก
#   ซื้อ/Long  เมื่อราคาทะลุ High 20 วัน
#   ขาย/Short  เมื่อราคาทะลุ Low 20 วัน
# ส่วน Turtle System 1 เข้าที่ High 20 วันแต่ออกเร็วกว่าที่ Low 10 วัน
# สองระบบนี้จึงให้สัญญาณขายคนละจุด และต้องแสดงแยกกัน ไม่ใช่ตัวเลขชุดเดียว
# ----------------------------------------------------------------------

FOUR_WEEK_DAYS = 20


def four_week_rule(df, period=FOUR_WEEK_DAYS, use_close=False):
    """
    สถานะตามกฎ 4-Week Rule ของ Richard Donchian

    คืน dict: upper, lower, signal ('LONG'/'SHORT'/'HOLD'), position_pct
    position_pct = ราคาอยู่ตรงไหนในกรอบ (0% = ก้นกรอบ, 100% = ยอดกรอบ)
    ซึ่งบอกว่ากำลังเข้าใกล้ฝั่งไหนของกรอบ ก่อนที่จะทะลุจริง
    """
    if df is None or len(df) < period + 1:
        return None

    upper = float(df['High'].rolling(period).max().shift(1).iloc[-1])
    lower = float(df['Low'].rolling(period).min().shift(1).iloc[-1])
    if np.isnan(upper) or np.isnan(lower) or upper <= lower:
        return None

    close = float(df['Close'].iloc[-1])
    hi = float(df['Close'].iloc[-1] if use_close else df['High'].iloc[-1])
    lo = float(df['Close'].iloc[-1] if use_close else df['Low'].iloc[-1])

    if hi > upper:
        signal = 'LONG'
    elif lo < lower:
        signal = 'SHORT'
    else:
        signal = 'HOLD'

    return {
        'upper': round(upper, 4),
        'lower': round(lower, 4),
        'signal': signal,
        'position_pct': round((close - lower) / (upper - lower) * 100, 1),
        'period': period,
    }
