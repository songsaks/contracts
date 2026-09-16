"""
R:R จาก "ตรงที่ยืนอยู่ตอนนี้" ไม่ใช่จากขอบโซนตอนสแกน

ปัญหาเดิม: RR ที่ระบบเก็บไว้ (risk_reward_ratio) คำนวณตอนสแกนด้วยสมมติฐานว่า
เข้าซื้อที่ขอบบนของ demand zone —

    entry_price = refined_upper
    risk   = entry_price - stop_loss
    reward = target_price - entry_price

นั่นคือ RR ของ *setup* ซึ่งตอบคำถามว่า "ถ้าได้ราคาที่โซน จะคุ้มไหม" แต่พอถือแล้ว
ราคาขยับ ไม่มีใครคำนวณใหม่ว่า "จากราคาตรงนี้ไปข้างหน้า ยังคุ้มอยู่ไหม" เลย
ผลจริงในพอร์ต: AIT ได้ RR 0.78 และ BCP 0.80 คือเสี่ยงมากกว่าที่จะได้
แต่หน้าจอไม่เตือนอะไรสักคำ

PrecisionScanCandidate.current_rr ทำเรื่องนี้อยู่แล้ว แต่ใช้ได้เฉพาะหน้าสแกน
เพราะต้องมี live_price ที่ scanners.py เซ็ตให้ ส่วนหน้าพอร์ตไม่เคยเซ็ต จึงตกไปใช้
ราคา ณ วันที่สแกน ซึ่งไม่ใช่ "ปัจจุบัน" และยังอิง stop_loss จากผลสแกนที่ไหลลงตามราคา

โมดูลนี้คิดจากราคาสดและ locked stop ของไม้นั้น (stop ที่ไม่เลื่อนลง ดู stop_ratchet.py)
เป็นฟังก์ชันล้วน ไม่แตะ DB และไม่ยิงเน็ต

เกณฑ์ที่ใช้จัดระดับเป็นเกณฑ์เดียวกับที่ระบบใช้อยู่แล้ว ไม่ได้ตั้งใหม่:
  1.0  — ใต้เส้นนี้คือเสี่ยงมากกว่าได้ (utils.py เรียก poor_rr)
  1.5  — เกณฑ์ขั้นต่ำที่ตัวคัดกรองใช้ (scanners.py) และเริ่มให้คะแนน (base.py)
  2.0, 3.0 — ขั้นถัดไปของการให้คะแนนใน base.py
"""

RR_POOR = 1.0       # ต่ำกว่านี้ = เสี่ยงมากกว่าที่จะได้
RR_MIN_OK = 1.5     # เกณฑ์ขั้นต่ำที่ตัวคัดกรองยอมรับ
RR_GOOD = 2.0
RR_GREAT = 3.0

# ถ้า stop ชิดราคากว่านี้ ตัวหารของ R:R เล็กจนอัตราส่วนพองเกินจริง
# เช่น stop ห่าง 0.33% จะได้ R:R 68:1 ซึ่งดูเหมือนดีเลิศ ทั้งที่ความจริงคือ
# stop อยู่ใต้การแกว่งปกติของวัน จะโดนเขี่ยทิ้งก่อนได้ลุ้นเป้าด้วยซ้ำ
# ค่านี้ต้องตรงกับ utils.MIN_STOP_PCT (พื้นระยะ stop ขั้นต่ำ) — มีเทสต์คุมไว้
# ประกาศซ้ำที่นี่แทนการ import เพราะ utils.py ลาก pandas_ta มาด้วย
# ซึ่งจะทำให้โมดูลนี้หมดสภาพ "ฟังก์ชันล้วน ทดสอบได้ทุกที่"
MIN_MEANINGFUL_RISK_PCT = 2.0

# สถานะที่ไม่ใช่ตัวเลข RR ปกติ — ต้องแยกออกมา ไม่ใช่ยัดเป็น 0 แล้วจบ
STATUS_OK = 'ok'
STATUS_THIN = 'thin'              # ยังบวกแต่บางเกินเกณฑ์
STATUS_POOR = 'poor'              # เสี่ยงมากกว่าได้
STATUS_STOP_HIT = 'stop_hit'      # ราคาต่ำกว่า/เท่า stop แล้ว คำนวณ RR ไม่มีความหมาย
STATUS_TARGET_HIT = 'target_hit'  # ราคาถึง/เกินเป้าแล้ว ไม่เหลือ upside ให้ลุ้น
STATUS_UNRELIABLE = 'unreliable'  # stop ชิดจน R:R พองเกินจริง เชื่อตัวเลขไม่ได้
STATUS_UNKNOWN = 'unknown'        # ข้อมูลไม่พอ


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:        # NaN
        return None
    return out


def current_rr(price, stop, target):
    """
    R:R จากราคาปัจจุบัน = (เป้า − ราคา) ÷ (ราคา − stop)

    คืน None เมื่อคำนวณไม่ได้หรือไม่มีความหมาย (ราคาหลุด stop / ถึงเป้าแล้ว)
    ผู้เรียกที่อยากรู้ว่าทำไม ให้ใช้ assess() ซึ่งบอกสถานะมาด้วย
    """
    p, s, t = _num(price), _num(stop), _num(target)
    if p is None or s is None or t is None or p <= 0:
        return None
    risk = p - s
    reward = t - p
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def rr_status(rr):
    """จัดระดับตัวเลข RR ตามเกณฑ์ที่ระบบใช้อยู่"""
    if rr is None:
        return STATUS_UNKNOWN
    if rr < RR_POOR:
        return STATUS_POOR
    if rr < RR_MIN_OK:
        return STATUS_THIN
    return STATUS_OK


def assess(price, stop, target):
    """
    ประเมิน R:R จากตรงนี้ไปข้างหน้า พร้อมเหตุผลที่อ่านออก

    คืน dict เสมอ — ฝั่ง template จะได้ไม่ต้องเช็ค None เอง
    """
    p, s, t = _num(price), _num(stop), _num(target)

    out = {
        'rr': None, 'status': STATUS_UNKNOWN, 'label': '', 'detail': '',
        'risk': None, 'reward': None,
        'risk_pct': None, 'reward_pct': None,
        'is_warning': False,
    }

    if p is None or p <= 0 or s is None or t is None:
        out['detail'] = 'ข้อมูลไม่พอ (ต้องมีทั้งราคา จุดตัดขาดทุน และเป้าหมาย)'
        return out

    risk, reward = p - s, t - p
    out['risk'] = round(risk, 4)
    out['reward'] = round(reward, 4)
    out['risk_pct'] = round(risk / p * 100, 2)
    out['reward_pct'] = round(reward / p * 100, 2)

    if risk <= 0:
        out['status'] = STATUS_STOP_HIT
        out['label'] = 'หลุดจุดตัดขาดทุนแล้ว'
        out['detail'] = 'ราคาต่ำกว่าจุดตัดขาดทุน การคำนวณ R:R ไม่มีความหมายแล้ว'
        out['is_warning'] = True
        return out

    if reward <= 0:
        out['status'] = STATUS_TARGET_HIT
        out['label'] = 'ถึงเป้าหมายแล้ว'
        out['detail'] = ('ราคาเลยเป้าหมายไปแล้ว ไม่เหลือ upside ตามแผนเดิม — '
                         'ตั้งเป้าใหม่หรือเก็บกำไรบางส่วน')
        out['is_warning'] = True
        return out

    rr = reward / risk
    out['rr'] = round(rr, 2)

    # stop ชิดเกินไป -> ตัวหารเล็กจน R:R พองเกินจริง อย่าโชว์เป็นของดี
    if out['risk_pct'] < MIN_MEANINGFUL_RISK_PCT:
        out['status'] = STATUS_UNRELIABLE
        out['label'] = 'ตัวเลขเชื่อไม่ได้'
        out['detail'] = (f'จุดตัดขาดทุนห่างจากราคาแค่ {out["risk_pct"]:.2f}% '
                         f'ซึ่งอยู่ใต้การแกว่งปกติของวัน R:R 1:{rr:.1f} ที่ได้จึงพองเกินจริง — '
                         f'ตั้งจุดตัดขาดทุนให้ห่างอย่างน้อย {MIN_MEANINGFUL_RISK_PCT:.0f}% ก่อน')
        out['is_warning'] = True
        return out

    out['status'] = rr_status(rr)

    if out['status'] == STATUS_POOR:
        out['label'] = 'เสี่ยงมากกว่าได้'
        out['detail'] = (f'จากราคานี้ไปเป้าได้อีก {out["reward_pct"]:.1f}% '
                         f'แต่ถ้าผิดทางเสีย {out["risk_pct"]:.1f}% — '
                         f'ไม่ใช่จุดที่ควรเติมไม้')
        out['is_warning'] = True
    elif out['status'] == STATUS_THIN:
        out['label'] = 'บางเกินเกณฑ์'
        out['detail'] = (f'R:R 1:{rr:.1f} ต่ำกว่าเกณฑ์ขั้นต่ำ {RR_MIN_OK} '
                         f'ที่ตัวคัดกรองใช้')
    else:
        out['label'] = 'อยู่ในเกณฑ์'
        out['detail'] = (f'ได้อีก {out["reward_pct"]:.1f}% ต่อความเสี่ยง '
                         f'{out["risk_pct"]:.1f}%')
    return out


def badge_color(status):
    """สีที่ใช้บนหน้าจอ — รวมไว้ที่เดียวเพื่อไม่ให้แต่ละหน้าเลือกกันเอง"""
    return {
        STATUS_OK: 'success',
        STATUS_THIN: 'warning',
        STATUS_POOR: 'danger',
        STATUS_STOP_HIT: 'danger',
        STATUS_TARGET_HIT: 'primary',
        STATUS_UNRELIABLE: 'warning',
        STATUS_UNKNOWN: 'secondary',
    }.get(status, 'secondary')
