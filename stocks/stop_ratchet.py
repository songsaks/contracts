"""
Stop ที่ไม่เคยเลื่อนลง — กติกาข้อเดียวที่ทำให้ stop เป็น stop จริงๆ

ปัญหาเดิม: ระบบไม่เคยยึด stop ไว้กับวันที่ซื้อเลย ตาราง Portfolio ไม่มีฟิลด์ stop
ด้วยซ้ำ ตัวเลขที่โชว์ในช่อง SL มาจากผลสแกนล่าสุด ซึ่งคำนวณโซน demand ใหม่จาก
ราคาปัจจุบันทุกครั้ง พอราคาลง โซนก็ลงตาม stop จึงไหลตามราคาลงไปเรื่อยๆ
"stop ที่ขยับลงตามราคาได้" ไม่ใช่ stop แต่เป็นคำบรรยายราคาปัจจุบัน

เจอสามช่องทางที่ทำให้ stop ต่ำลงได้:
  1. stop จากผลสแกน คำนวณโซนใหม่ตามราคาที่ลงมา
  2. กลยุทธ์ PMS / Dividend / Value เขียนทับ trailing_stop เอง แล้วข้ามเพดาน
     max(stop, entry × 0.85) ที่ calculate_atr_trailing_stop ใส่ไว้ให้
  3. trailing แบบ highest − k×ATR ตกลงได้เองเมื่อ ATR ขยายตัว แม้ highest จะนิ่ง

โมดูลนี้เป็นฟังก์ชันล้วน ไม่แตะ DB และไม่ยิงเน็ต
"""

# ขาดทุนจากราคาทุนได้มากสุดกี่ % ก่อนถือว่าต้องออก
# calculate_atr_trailing_stop ใส่เพดานนี้ไว้อยู่แล้ว (entry × 0.85) แต่สาขา
# PMS / Dividend / Value เขียนทับ trailing_stop ทีหลังโดยไม่ผ่านเพดาน
MAX_LOSS_FROM_ENTRY_PCT = 15.0


def hard_floor(entry_price, max_loss_pct=MAX_LOSS_FROM_ENTRY_PCT):
    """ราคาต่ำสุดที่ยอมให้ stop อยู่ได้ — ต่ำกว่านี้คือปล่อยให้ขาดทุนเกินเพดาน"""
    try:
        entry = float(entry_price or 0)
    except (TypeError, ValueError):
        return 0.0
    if entry <= 0:
        return 0.0
    return entry * (1.0 - float(max_loss_pct) / 100.0)


def _clean(value):
    """แปลงเป็น float ที่ใช้ได้ หรือ None — กัน NaN / ค่าติดลบ / ข้อความ"""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num or num <= 0:      # NaN หรือ <= 0
        return None
    return num


def ratchet(previous, *candidates):
    """
    stop ใหม่ = ค่าที่สูงที่สุดที่เคยมี — ขยับขึ้นอย่างเดียว ไม่เคยลง

    previous   : stop ที่ล็อกไว้แล้ว (None ได้ ถ้ายังไม่เคยล็อก)
    candidates : stop ที่เสนอเข้ามารอบนี้ ตัวไหนเป็น None/เพี้ยน จะถูกข้าม

    คืน None ถ้าไม่มีค่าที่ใช้ได้เลย
    """
    values = [v for v in (_clean(previous), *(_clean(c) for c in candidates)) if v is not None]
    return max(values) if values else None


def effective_stop(entry_price, *, initial_stop=None, locked_stop=None,
                   trailing_stop=None, max_loss_pct=MAX_LOSS_FROM_ENTRY_PCT):
    """
    stop ที่ควรใช้ตัดสินใจจริง ณ ตอนนี้

    รวมทุกข้อจำกัดเข้าด้วยกันแล้วเอาตัวที่ "สูงที่สุด" เพราะ stop ที่สูงกว่า
    คือ stop ที่คุมความเสี่ยงได้แน่นกว่าเสมอ:
      - initial_stop : stop ที่ตั้งไว้ตอนซื้อ ต้องไม่หลุดไปต่ำกว่านี้
      - locked_stop  : stop ที่เคยขยับขึ้นไปแล้ว ต้องไม่ถอยกลับ
      - trailing_stop: stop ที่เทรลตามราคาขึ้นมา
      - hard floor   : เพดานขาดทุนจากราคาทุน (ห้ามขาดทุนเกิน max_loss_pct)

    หมายเหตุ initial_stop ที่สูงกว่าราคาทุนแปลว่าเป็นข้อมูลเพี้ยน (ซื้อแล้วตั้ง
    stop เหนือราคาซื้อ) จะถูกมองข้าม ไม่เอามาล็อกให้ขายทิ้งทันที

    คืน None เมื่อไม่มีข้อมูลพอจะบอกได้ (ไม่เดาให้)
    """
    entry = _clean(entry_price)
    init = _clean(initial_stop)
    if entry and init and init >= entry:
        init = None                     # stop เหนือราคาทุน = ข้อมูลเพี้ยน

    floor = hard_floor(entry, max_loss_pct) if entry else 0.0
    return ratchet(None, init, _clean(locked_stop), _clean(trailing_stop),
                   floor if floor > 0 else None)


def is_stop_hit(current_price, stop):
    """ราคาหลุด stop แล้วหรือยัง — ไม่มี stop = ตอบไม่ได้ (False)"""
    price = _clean(current_price)
    level = _clean(stop)
    if price is None or level is None:
        return False
    return price <= level


def loss_pct_from_entry(entry_price, current_price):
    """ตอนนี้ขาดทุนจากราคาทุนกี่ % (ค่าบวก = ขาดทุน) — คืน None ถ้าคำนวณไม่ได้"""
    entry = _clean(entry_price)
    price = _clean(current_price)
    if entry is None or price is None:
        return None
    return (entry - price) / entry * 100.0


def breach_report(entry_price, current_price, stop,
                  max_loss_pct=MAX_LOSS_FROM_ENTRY_PCT):
    """
    สรุปว่าสถานะนี้เลยจุดที่ควรออกไปแล้วแค่ไหน

    ใช้บอกผู้ใช้ตรงๆ เมื่อไม้ที่ถืออยู่ขาดทุนเกินเพดานไปแล้ว ซึ่งแปลว่าระบบ
    ปล่อยให้เลยจุดตัดขาดทุนมานานโดยไม่มีอะไรเตือน
    """
    loss = loss_pct_from_entry(entry_price, current_price)
    over = loss is not None and loss > float(max_loss_pct)
    return {
        'loss_pct': round(loss, 2) if loss is not None else None,
        'max_loss_pct': float(max_loss_pct),
        'over_limit': bool(over),
        'excess_pct': round(loss - float(max_loss_pct), 2) if over else 0.0,
        'stop_hit': is_stop_hit(current_price, stop),
    }
