"""
Quant Position Size — คำนวณขนาดไม้จากความเสี่ยงที่ยอมรับได้ ไม่ใช่จาก "เงินที่มี"

หลักการ: ตัดสินใจจาก "ถ้าผิดทางจะเสียเท่าไร" ก่อนเสมอ
    เงินเสี่ยงต่อไม้ = equity × risk_pct
    ระยะ stop      = entry − stop
    จำนวนหุ้น       = เงินเสี่ยงต่อไม้ ÷ ระยะ stop

จำนวนที่ได้ยังต้องผ่านเพดานอีก 4 ชั้นก่อนใช้จริง (เงินสด, น้ำหนักต่อตัว, ล็อต, heat)
โมดูลนี้เป็นฟังก์ชันล้วน ไม่แตะ DB และไม่ยิงเน็ต เพื่อให้ทดสอบและเรียกซ้ำได้ทุกที่
"""

import math

# ── ค่าเริ่มต้น ───────────────────────────────────────────────────────
DEFAULT_RISK_PCT = 1.0        # เสี่ยง 1% ของพอร์ตต่อไม้ (ค่ามาตรฐานของ position sizing)
DEFAULT_MAX_WEIGHT_PCT = 20.0  # ไม้เดียวไม่เกิน 20% ของพอร์ต แม้ stop จะแคบมาก
DEFAULT_MAX_HEAT_PCT = 6.0    # ความเสี่ยงรวมของทุกไม้ที่เปิดอยู่ ไม่เกิน 6% ของพอร์ต
SET_BOARD_LOT = 100           # หุ้นไทยซื้อขายเป็นล็อตละ 100 หุ้น
US_BOARD_LOT = 1              # หุ้น US ซื้อเศษหุ้นได้ ไม่มีล็อต

# ค่าธรรมเนียมไป-กลับโดยประมาณ (ใช้ทั้งที่นี่และใน backtest ให้ตรงกัน)
SET_COMMISSION_PCT = 0.157    # ค่านายหน้าออนไลน์ทั่วไป ต่อขา
SET_VAT_PCT = 7.0             # VAT คิดบนค่านายหน้า
US_COMMISSION_PCT = 0.0       # โบรกเกอร์ US ส่วนใหญ่ไม่คิดค่าคอมแล้ว


def board_lot_for(market):
    """ล็อตขั้นต่ำของตลาดนั้น — SET ต้องเป็นพหุคูณของ 100"""
    return SET_BOARD_LOT if str(market or 'SET').upper() == 'SET' else US_BOARD_LOT


def round_trip_cost_pct(market='SET'):
    """ค่าธรรมเนียมไป-กลับเป็น % ของมูลค่าซื้อขาย (ซื้อ 1 ขา + ขาย 1 ขา)"""
    if str(market or 'SET').upper() == 'SET':
        per_side = SET_COMMISSION_PCT * (1 + SET_VAT_PCT / 100.0)
        return round(per_side * 2, 4)
    return round(US_COMMISSION_PCT * 2, 4)


def calculate_position_size(*, equity, entry_price, stop_price, risk_pct=DEFAULT_RISK_PCT,
                            cash_available=None, max_weight_pct=DEFAULT_MAX_WEIGHT_PCT,
                            market='SET', current_heat_pct=0.0,
                            max_heat_pct=DEFAULT_MAX_HEAT_PCT):
    """
    คำนวณจำนวนหุ้นที่ควรซื้อ พร้อมเหตุผลว่าอะไรเป็นตัวจำกัด

    equity          : มูลค่าพอร์ตรวมเงินสด (ฐานคิดความเสี่ยง)
    entry_price     : ราคาที่จะเข้า
    stop_price      : ราคา stop loss — ต้องต่ำกว่า entry
    risk_pct        : ยอมเสียกี่ % ของ equity ถ้าไม้นี้ผิดทาง
    cash_available  : เงินสดที่ซื้อได้จริง (None = ไม่จำกัด)
    max_weight_pct  : เพดานน้ำหนักของไม้เดียวเทียบ equity
    market          : ใช้เลือกขนาดล็อตและค่าธรรมเนียม
    current_heat_pct: ความเสี่ยงรวมของไม้ที่เปิดอยู่แล้ว (จาก calculate_portfolio_heat)
    max_heat_pct    : เพดาน heat รวม

    คืน dict เสมอ — ถ้าคำนวณไม่ได้จะมี error และ shares = 0
    """
    equity = float(equity or 0)
    entry = float(entry_price or 0)
    stop = float(stop_price or 0)
    risk_pct = float(risk_pct or 0)

    def _fail(msg):
        return {'shares': 0, 'error': msg, 'limited_by': None,
                'risk_amount': 0.0, 'risk_pct_actual': 0.0, 'position_value': 0.0,
                'weight_pct': 0.0, 'stop_distance': 0.0, 'stop_distance_pct': 0.0,
                'cost_estimate': 0.0, 'heat_after_pct': round(float(current_heat_pct or 0), 2),
                'caps': {}}

    if equity <= 0:
        return _fail('ยังไม่รู้มูลค่าพอร์ต — เพิ่มหุ้นหรือเงินสดก่อน')
    if entry <= 0:
        return _fail('ไม่มีราคาเข้า')
    if stop <= 0:
        return _fail('ยังไม่ได้ตั้ง Stop Loss — ไม่มี stop ก็คำนวณขนาดไม้ไม่ได้')
    if stop >= entry:
        return _fail(f'Stop ({stop:,.2f}) ต้องต่ำกว่าราคาเข้า ({entry:,.2f})')
    if risk_pct <= 0:
        return _fail('risk_pct ต้องมากกว่า 0')

    stop_distance = entry - stop
    risk_amount = equity * risk_pct / 100.0

    lot = board_lot_for(market)
    caps = {}

    # ── เพดาน 1: ความเสี่ยงต่อไม้ (ตัวหลัก) ──
    shares_by_risk = risk_amount / stop_distance
    caps['risk'] = shares_by_risk

    # ── เพดาน 2: น้ำหนักสูงสุดต่อตัว — กัน stop แคบจนซื้อเกินตัว ──
    caps['weight'] = (equity * float(max_weight_pct) / 100.0) / entry

    # ── เพดาน 3: เงินสดที่มีจริง (หักค่าธรรมเนียมซื้อไว้ด้วย) ──
    if cash_available is not None:
        cost_rate = round_trip_cost_pct(market) / 100.0 / 2   # ขาซื้ออย่างเดียว
        caps['cash'] = max(0.0, float(cash_available)) / (entry * (1 + cost_rate))

    # ── เพดาน 4: Portfolio Heat — ความเสี่ยงรวมทั้งพอร์ต ──
    heat_room_pct = max(0.0, float(max_heat_pct) - float(current_heat_pct or 0))
    caps['heat'] = (equity * heat_room_pct / 100.0) / stop_distance

    limited_by = min(caps, key=caps.get)
    raw_shares = caps[limited_by]

    # ปัดลงเป็นล็อต — ปัดขึ้นจะทำให้ความเสี่ยงเกินเพดานที่ตั้งไว้
    shares = int(math.floor(raw_shares / lot) * lot)

    if shares <= 0:
        reason = {
            'risk': 'ระยะ stop กว้างเกินไปเมื่อเทียบกับความเสี่ยงที่ยอมรับ',
            'weight': 'ราคาต่อหุ้นสูงเกินเพดานน้ำหนักต่อตัว',
            'cash': 'เงินสดไม่พอสำหรับล็อตขั้นต่ำ',
            'heat': 'ความเสี่ยงรวมของพอร์ตเต็มเพดานแล้ว — ปิดไม้เดิมก่อน',
        }[limited_by]
        out = _fail(f'ซื้อไม่ได้แม้แต่ 1 ล็อต ({lot} หุ้น) — {reason}')
        out['limited_by'] = limited_by
        out['stop_distance'] = round(stop_distance, 4)
        out['stop_distance_pct'] = round(stop_distance / entry * 100, 2)
        out['caps'] = {k: int(math.floor(v / lot) * lot) for k, v in caps.items()}
        return out

    position_value = shares * entry
    actual_risk = shares * stop_distance

    return {
        'shares': shares,
        'error': None,
        # ตัวไหนเป็นคนกำหนดจำนวนจริง — บอกผู้ใช้ว่าติดเพดานไหน
        'limited_by': limited_by,
        'risk_amount': round(actual_risk, 2),
        'risk_pct_actual': round(actual_risk / equity * 100, 2),
        'position_value': round(position_value, 2),
        'weight_pct': round(position_value / equity * 100, 2),
        'stop_distance': round(stop_distance, 4),
        'stop_distance_pct': round(stop_distance / entry * 100, 2),
        'cost_estimate': round(position_value * round_trip_cost_pct(market) / 100.0, 2),
        'heat_after_pct': round(float(current_heat_pct or 0) + actual_risk / equity * 100, 2),
        'board_lot': lot,
        'caps': {k: int(math.floor(v / lot) * lot) for k, v in caps.items()},
    }


def calculate_portfolio_heat(positions, equity, max_heat_pct=DEFAULT_MAX_HEAT_PCT):
    """
    Portfolio Heat = ถ้าทุกไม้ที่เปิดอยู่หลุด stop พร้อมกันวันนี้ พอร์ตเสียกี่ %

    positions: iterable ของ dict — ต้องมี symbol, quantity, current_price, stop_price
               ไม้ที่ไม่มี stop จะถูกนับแยกไว้ เพราะความเสี่ยงของมันคือ "ไม่จำกัด"
               ซึ่งอันตรายกว่าไม้ที่มี stop กว้าง ไม่ใช่ปลอดภัยกว่า

    หมายเหตุ: คิดจาก current_price ไม่ใช่ entry_price — ความเสี่ยงที่แท้จริงคือ
    เงินที่จะเสียนับจาก "ตอนนี้" ไม่ใช่ตอนซื้อ ไม้ที่กำไรจน stop สูงกว่าราคาปัจจุบัน
    ถือว่าความเสี่ยงเป็น 0 (ล็อกกำไรแล้ว)
    """
    equity = float(equity or 0)
    rows, total_risk, unprotected = [], 0.0, []

    for p in positions or []:
        qty = float(p.get('quantity') or 0)
        cur = float(p.get('current_price') or 0)
        stop = float(p.get('stop_price') or 0)
        sym = p.get('symbol', '?')
        if qty <= 0 or cur <= 0:
            continue
        if stop <= 0:
            unprotected.append(sym)
            continue
        # stop สูงกว่าราคาปัจจุบัน = ล็อกกำไรไว้แล้ว ไม่นับเป็นความเสี่ยง
        risk = max(0.0, (cur - stop) * qty)
        total_risk += risk
        rows.append({
            'symbol': sym,
            'risk_amount': round(risk, 2),
            'risk_pct': round(risk / equity * 100, 2) if equity > 0 else 0.0,
            'stop_price': round(stop, 2),
            'locked_profit': stop >= cur,
        })

    rows.sort(key=lambda r: r['risk_amount'], reverse=True)
    heat_pct = round(total_risk / equity * 100, 2) if equity > 0 else 0.0

    if unprotected:
        status, label = 'unknown', 'ประเมินไม่ได้ — มีไม้ที่ยังไม่ตั้ง stop'
    elif heat_pct > max_heat_pct:
        status, label = 'over', 'เกินเพดาน — ไม่ควรเปิดไม้ใหม่'
    elif heat_pct > max_heat_pct * 0.75:
        status, label = 'warm', 'ใกล้เต็มเพดาน — เปิดไม้ใหม่ได้อีกไม่มาก'
    else:
        status, label = 'ok', 'อยู่ในเกณฑ์'

    return {
        'heat_pct': heat_pct,
        'total_risk': round(total_risk, 2),
        'max_heat_pct': float(max_heat_pct),
        'room_pct': round(max(0.0, max_heat_pct - heat_pct), 2),
        'status': status,
        'label': label,
        'positions': rows,
        'unprotected': unprotected,
        'unprotected_count': len(unprotected),
    }
