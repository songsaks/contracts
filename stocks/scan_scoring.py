"""
คะแนนความพร้อมของ Setup (Setup Readiness Score) สำหรับหน้า Precision Scan

ทำไมถึงไม่เรียกว่า "โอกาสชนะ" อีกต่อไป
----------------------------------------
ตัวเลขนี้เดิมชื่อ win_probability และถูกแสดงบนหน้าจอว่า "โอกาสชนะ %" ซึ่งทำให้
คนอ่านเข้าใจว่าเป็นอัตราชนะที่วัดจากผลเทรดจริง แต่มันไม่ใช่ — มันคือผลรวมคะแนน
จากสูตรที่ตั้งค่าน้ำหนักด้วยมือ เริ่มที่ 35 แล้วบวกตาม RS / เทคนิค / ADX / CMF
โดยไม่เคยถูก calibrate กับ ScanOutcome ที่ระบบเก็บผลจริงไว้เลยสักครั้ง

หุ้นที่ได้ 86% จึงไม่ได้แปลว่าชนะ 86 ครั้งจาก 100 แต่แปลว่า "องค์ประกอบทาง
เทคนิคเข้าเกณฑ์ 86 คะแนนจาก 100" ซึ่งเป็นคนละเรื่องกัน ชื่อใหม่บอกสิ่งที่มันวัด
จริง ส่วน win_probability ยังคงถูกตั้งค่าไว้เป็น alias เพื่อไม่ให้โค้ดเดิมที่
เรียงลำดับด้วยชื่อนั้นพัง

โมดูลนี้เป็นฟังก์ชันล้วน ไม่แตะ DB และไม่ยิงเน็ต
"""

# ค่ากลางของสูตร — รวมไว้ที่เดียวเพื่อให้หน้า SET กับ US ใช้มาตรฐานเดียวกัน
BASE_SCORE = 35.0
SCORE_MIN = 30.0
SCORE_MAX = 98.2

# วอลุ่มต่ำกว่าเท่านี้ถือว่า "แห้ง" — breakout ที่ไม่มีวอลุ่มคือรูปแบบที่ล้มบ่อย
# ที่สุดของทุกระบบที่หน้านี้ใช้ (CAN SLIM / SEPA / Pocket Pivot / HTF)
DRY_VOLUME_THRESHOLD = 0.8
DRY_VOLUME_PENALTY = 8.0


def compute_setup_scores(candidates, markov_regime=None, market_timing=None):
    """
    ให้คะแนนความพร้อมของแต่ละ candidate (แก้ไข object ในที่)

    ตั้งค่าให้แต่ละตัว:
      setup_score        - คะแนน 30-98.2
      setup_caveats      - list ข้อควรระวังที่ทำให้คะแนนนี้ควรถูกอ่านอย่างระวัง
      win_probability    - alias ของ setup_score (ชื่อเดิม เก็บไว้เพื่อ backward compat)

    เดิมโค้ดชุดนี้ถูกคัดลอกไว้สองที่ในไฟล์ scanners.py (หน้า SET กับหน้า US)
    เหมือนกันทุกตัวอักษร 33 บรรทัด การแก้สูตรจึงต้องแก้สองที่ และถ้าลืมที่ใด
    ที่หนึ่ง สองหน้าจะให้คะแนนหุ้นคนละมาตรฐานโดยไม่มีอะไรเตือน
    """
    if not candidates:
        return

    markov_regime = markov_regime or {}
    market_timing = market_timing or {}

    m_state = markov_regime.get('state', 'UNKNOWN')
    m_prob = (markov_regime.get('prob', 0) or 0) / 100.0
    _mt_code = market_timing.get('status_code', 'GREEN')

    for c in candidates:
        score = BASE_SCORE
        caveats = []

        rs_val = getattr(c, 'rs_rating', 0) or 0
        score += (rs_val / 99.0) * 25.0

        tech_val = getattr(c, 'technical_score', 0) or 0
        score += (min(tech_val, 100) / 100.0) * 15.0

        adx_val = getattr(c, 'adx', 0) or 0
        score += (min(adx_val, 50) / 50.0) * 10.0

        cmf_val = getattr(c, 'cmf', 0) or 0
        if cmf_val > 0.15:
            score += 10.0
        elif cmf_val > 0:
            score += 5.0

        # ── วอลุ่ม ──
        # เดิมมีแต่ทางบวก: >=1.5 ได้ +5, >=1.2 ได้ +2 นอกนั้นได้ 0 เท่ากันหมด
        # แปลว่าวอลุ่ม 0.6x (ต่ำกว่าเฉลี่ย 40%) ได้คะแนนเท่ากับ 1.19x ที่ปกติดี
        # ทั้งที่มันเป็นสัญญาณลบชัดเจน ตอนนี้หักคะแนนและติดคำเตือนไว้ให้เห็น
        vol_surge = getattr(c, 'volume_surge', 1.0) or 1.0
        if vol_surge >= 1.5:
            score += 5.0
        elif vol_surge >= 1.2:
            score += 2.0
        elif vol_surge < DRY_VOLUME_THRESHOLD:
            score -= DRY_VOLUME_PENALTY
            caveats.append(
                f"⚠️ วอลุ่ม {vol_surge:.1f}x ต่ำกว่าค่าเฉลี่ย — breakout ที่ไม่มีวอลุ่ม"
                f"รองรับขัดกับเงื่อนไขของ CAN SLIM / SEPA / Pocket Pivot ที่ใช้คัดหุ้นตัวนี้"
            )

        if m_state == 'TRENDING':
            score += 10.0 * (0.5 + 0.5 * m_prob)
        elif m_state == 'CHOPPY':
            score += 4.0
        elif m_state == 'UNKNOWN' and m_prob == 0:
            # ไม่รู้สภาวะตลาด ไม่ใช่เหตุผลให้มั่นใจขึ้น — บอกไว้ว่าคะแนนส่วนนี้เดามา
            score += 5.0
            caveats.append("⚠️ ยังระบุสภาวะตลาด (Markov regime) ไม่ได้ คะแนนส่วนนี้เป็นค่ากลาง")

        prox = getattr(c, 'live_zone_prox', None)
        if prox is None:
            prox = getattr(c, 'zone_proximity', 99.0)
        if prox is None:
            prox = 99.0
        if 15 < prox < 100:
            score -= 10.0
        elif 10 < prox < 100:
            score -= 5.0

        # Market Timing penalty - ตลาดแจกของหนัก (RED) ให้ลดความมั่นใจแรง, YELLOW ลดปานกลาง
        if _mt_code == 'RED':
            score -= 20.0
            caveats.append("⚠️ ตลาดอยู่ในโหมดแจกของ (RED) setup ทุกแบบมีอัตราล้มเหลวสูงขึ้น")
        elif _mt_code == 'YELLOW':
            score -= 8.0
            caveats.append("⚠️ ตลาดอยู่ในโหมดระวัง (YELLOW)")

        c.setup_score = round(max(min(score, SCORE_MAX), SCORE_MIN), 1)
        c.setup_caveats = caveats
        # ชื่อเดิม — โค้ดที่เรียงลำดับและเทมเพลตบางหน้ายังอ้างถึงอยู่
        c.win_probability = c.setup_score
