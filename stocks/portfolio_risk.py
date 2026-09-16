"""
เพดานความเสี่ยงของพอร์ต — ทำให้ระบบเลิกเงียบเมื่อทะลุเพดานที่ตัวเองตั้งไว้

ปัญหาเดิม: position_sizing.py มีเพดานครบสี่ชั้น (risk / weight / cash / heat)
เขียนไว้ดีมาก แต่ถูกต่อเข้ากับ "หน้าเครื่องคิดเลข" อย่างเดียว ส่วนตอนเพิ่มหุ้นจริง
add_to_portfolio เรียก Portfolio.objects.update_or_create() ตรงๆ ไม่เช็คอะไรเลย
ผลคือพอร์ตจริงมีไม้ที่กินน้ำหนัก 22.6% และ 20.8% ทะลุเพดาน 20% ที่ตั้งไว้เอง
โดยไม่มีอะไรบอกสักคำ

ทำไมถึง "เตือน" ไม่ใช่ "บล็อก": ฟอร์ม Add Position มีช่อง "ราคาทุน" แปลว่ามันคือ
การบันทึกไม้ที่ซื้อไปแล้ว ไม่ใช่ใบสั่งซื้อ ถ้าบล็อกไม่ให้บันทึก พอร์ตจะไม่ตรงกับ
ความจริง ซึ่งแย่กว่าการถือไม้ที่ใหญ่เกินเพดานเสียอีก หน้าที่ของระบบคือบอกให้รู้

โมดูลนี้เป็นฟังก์ชันล้วน ไม่แตะ DB และไม่ยิงเน็ต
ส่วน Portfolio Heat ใช้ของเดิมที่ position_sizing.calculate_portfolio_heat ทำไว้แล้ว
"""
from .position_sizing import DEFAULT_MAX_WEIGHT_PCT


def weight_pct(value, equity):
    """น้ำหนักของไม้นี้เทียบพอร์ตทั้งหมด (%) — คืน None ถ้าคำนวณไม่ได้"""
    try:
        val = float(value or 0)
        eq = float(equity or 0)
    except (TypeError, ValueError):
        return None
    if eq <= 0 or val <= 0:
        return None
    return val / eq * 100.0


def weight_breaches(positions, equity, max_weight_pct=DEFAULT_MAX_WEIGHT_PCT):
    """
    ไม้ที่กินน้ำหนักเกินเพดาน เรียงจากหนักสุดลงมา

    positions: iterable ของ dict ที่มี symbol และ value (มูลค่าตลาด สกุลเดียวกับ equity)
    """
    cap = float(max_weight_pct or 0)
    out = []
    for p in positions or []:
        pct = weight_pct(p.get('value'), equity)
        if pct is None or pct <= cap:
            continue
        out.append({
            'symbol': p.get('symbol', '?'),
            'weight_pct': round(pct, 1),
            'excess_pct': round(pct - cap, 1),
            'value': round(float(p.get('value') or 0), 2),
        })
    out.sort(key=lambda r: r['weight_pct'], reverse=True)
    return out


def concentration_report(positions, equity, max_weight_pct=DEFAULT_MAX_WEIGHT_PCT):
    """
    สรุปการกระจุกตัวของพอร์ต

    top_weight_pct บอกว่าไม้ที่ใหญ่ที่สุดกินพอร์ตกี่ % ซึ่งเป็นตัวเลขที่ควรรู้
    แม้จะยังไม่ทะลุเพดาน เพราะมันคือความเสียหายสูงสุดที่ไม้เดียวทำได้
    """
    cap = float(max_weight_pct or 0)
    rows = []
    for p in positions or []:
        pct = weight_pct(p.get('value'), equity)
        if pct is None:
            continue
        rows.append({'symbol': p.get('symbol', '?'), 'weight_pct': round(pct, 1)})
    rows.sort(key=lambda r: r['weight_pct'], reverse=True)

    breaches = weight_breaches(positions, equity, cap)
    return {
        'max_weight_pct': cap,
        'breaches': breaches,
        'breach_count': len(breaches),
        'has_breach': bool(breaches),
        'top_weight_pct': rows[0]['weight_pct'] if rows else None,
        'top_symbol': rows[0]['symbol'] if rows else None,
        'positions': rows,
        # น้ำหนักรวมของไม้ที่เกินเพดาน — บอกว่าปัญหานี้ใหญ่แค่ไหนเมื่อมองทั้งพอร์ต
        'breached_weight_pct': round(sum(b['weight_pct'] for b in breaches), 1),
    }


def projected_weight(new_value, existing_values, cash=0.0):
    """
    ถ้าเพิ่มไม้มูลค่า new_value เข้าไป มันจะกินน้ำหนักกี่ %

    ใช้ตอนกด Add ซึ่งยังไม่ได้ดึงราคาตลาด จึงคิดจากราคาทุนได้ ตัวเลขจะไม่ตรงเป๊ะ
    กับหน้าพอร์ต (ที่ใช้มูลค่าตลาด) แต่พอบอกได้ว่ากำลังจะเปิดไม้ที่ใหญ่เกินไปไหม

    หมายเหตุ new_value ถูกนับรวมในตัวหารด้วย เพราะหลังเพิ่มแล้วมันเป็นส่วนหนึ่ง
    ของพอร์ต การหารด้วยขนาดพอร์ต "ก่อนเพิ่ม" จะได้ตัวเลขที่สูงเกินจริง
    """
    try:
        new_val = float(new_value or 0)
    except (TypeError, ValueError):
        return None
    if new_val <= 0:
        return None

    total = new_val + float(cash or 0)
    for v in existing_values or []:
        try:
            total += max(float(v or 0), 0.0)
        except (TypeError, ValueError):
            continue
    if total <= 0:
        return None
    return new_val / total * 100.0


def add_position_warning(symbol, new_value, existing_values, cash=0.0,
                         max_weight_pct=DEFAULT_MAX_WEIGHT_PCT):
    """
    ข้อความเตือนตอนบันทึกไม้ใหม่ — คืน None ถ้าไม่มีอะไรต้องเตือน

    ไม่บล็อกการบันทึก แค่บอกให้รู้ว่ากำลังทะลุเพดานที่ตั้งไว้เอง
    """
    pct = projected_weight(new_value, existing_values, cash)
    cap = float(max_weight_pct or 0)
    if pct is None or pct <= cap:
        return None
    return (f"⚠️ {symbol} จะกินน้ำหนัก {pct:.1f}% ของพอร์ต "
            f"ซึ่งเกินเพดาน {cap:.0f}% ที่ตั้งไว้ (บันทึกให้แล้ว) — "
            f"ไม้เดียวที่ใหญ่ขนาดนี้ทำให้พอร์ตเสียหายหนักถ้าผิดทาง")
