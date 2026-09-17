"""
Scan Edge — เชื่อมโยงสถิติผลลัพธ์ย้อนหลัง (ScanOutcome) เข้าสู่หน้าสแกนหุ้น (Closed-Loop Feedback)

หน้าที่:
1. คำนวณความได้เปรียบ (Edge) ของแต่ละ Setup Flag จากข้อมูลผลลัพธ์จริงใน ScanOutcome
2. นำผลประเมินมาติดป้าย (Badge) และเพิ่มคะแนน (Quality Boost) ให้กับหุ้นในหน้า Precision Scan
3. ช่วยให้เทรดเดอร์กรองเลือกเฉพาะหุ้นที่มีสถิติในอดีตรองรับว่าชนะตลาดจริง (Empirical Edge)

หลักการที่โมดูลนี้ยึด: ป้ายต้องบอกความจริงว่ามันรู้อะไรอยู่
------------------------------------------------------------------
เดิมป้าย "⭐ High Edge" ถูกแจกได้สองทาง และทางที่สองไม่มีสถิติรองรับเลย — ถ้า
ScanOutcome ยังสะสมไม่พอ โค้ดจะ fallback ไปนับว่า "หุ้นตัวนี้ติดรูปแบบกี่อย่าง"
แล้วติดป้ายเดียวกันกับหุ้นที่มีสถิติจริงรองรับ พร้อม tooltip ว่า "Setup ชนะเด่น"
ทั้งที่ยังไม่มีใครรู้ว่ามันชนะหรือเปล่า แถมบวก quality ให้อีก +5

ตอนนี้แยกเป็น 4 ระดับตามน้ำหนักของหลักฐานที่มีจริง:

  high       สถิติพอเชื่อถือได้ (n >= MIN_SAMPLE_RELIABLE) และ edge สูง  → +5 quality
  positive   สถิติพอเชื่อถือได้ และ edge เป็นบวก                          → +2.5 quality
  thin       มีสถิติ แต่ตัวอย่างน้อยเกินกว่าจะสรุป                        → ไม่บวก เตือนไว้
  setup_only ไม่มีสถิติเลย รู้แค่ว่าติดรูปแบบ                             → ไม่บวก เตือนไว้

สองระดับล่างไม่บวกคะแนนเพราะไม่มีหลักฐานอะไรมารองรับการบวก การบวกคะแนนจาก
ข้อมูลที่ยังไม่รู้ผลคือการเอาความไม่รู้ไปปนกับความมั่นใจ
"""

from datetime import timedelta

from django.utils import timezone

from stocks.models import ScanOutcome
from stocks.scan_outcomes import (EVALUATION_WINDOW_DAYS, HORIZONS, SETUP_FLAGS,
                                  flag_comparison)

CORE_HIGH_EDGE_FLAGS = {
    'pocket_pivot': 'Pocket Pivot',
    'vcp_setup': 'VCP Pattern',
    'stage2': 'Weinstein Stage 2',
    'is_explosive': 'Explosive Momentum',
    'volume_surge': 'Volume Surge',
    'htf_setup': 'High Tight Flag',
    'pp_at_ma50': 'Pocket Pivot @ MA50',
}

# ต้องมีผลลัพธ์อย่างน้อยเท่านี้ถึงจะเริ่มคิด edge ของแต่ละ flag
MIN_ROWS_FOR_EDGE = 10

# ตัวอย่างขั้นต่ำที่ยอม "แสดง" ตัวเลข — ต่ำกว่านี้ไม่พูดถึงเลย
MIN_SAMPLE_REPORT = 3

# ตัวอย่างขั้นต่ำที่ยอม "เชื่อ" ตัวเลข — ต่ำกว่านี้แสดงได้แต่ต้องติดคำเตือน
# เดิมใช้ 3 เป็นเกณฑ์เดียว ซึ่งน้อยเกินกว่าจะแยกฝีมือออกจากความบังเอิญ
MIN_SAMPLE_RELIABLE = 20

# ระดับความน่าเชื่อถือของหลักฐาน
EVIDENCE_RELIABLE = 'reliable'      # วัดจากผลจริง ตัวอย่างพอ
EVIDENCE_THIN = 'thin'              # วัดจากผลจริง แต่ตัวอย่างน้อย
EVIDENCE_PROVISIONAL = 'provisional'  # ประเมินหยาบจาก MFE/MAE ของไม้ที่ยังไม่ปิด


def _sample_warning(evidence, n, horizon_used=None, horizon_asked=None):
    """คำเตือนกำกับตัวเลข — คืนสตริงว่างเมื่อไม่มีอะไรต้องเตือน"""
    # ใช้ horizon สั้นกว่าที่ขอ = ต้องบอก ไม่ใช่สลับเงียบๆ แล้วให้คนอ่านเข้าใจว่า
    # เป็นสถิติ 20 วันทั้งที่จริงเป็น 5 หรือ 10 วัน
    swapped = ''
    if horizon_used and horizon_asked and horizon_used != horizon_asked:
        swapped = (f" (วัดที่ {horizon_used} วัน ไม่ใช่ {horizon_asked} วัน "
                   f"เพราะยังไม่มีไม้ไหนครบ {horizon_asked} วัน)")
    if evidence == EVIDENCE_RELIABLE:
        return swapped.strip()
    if evidence == EVIDENCE_THIN:
        return (f"⚠️ ข้อมูลน้อย (n={n}) ยังสรุปไม่ได้ว่าเป็นความได้เปรียบจริง "
                f"หรือเป็นความบังเอิญ — ต้องมีอย่างน้อย {MIN_SAMPLE_RELIABLE} ไม้{swapped}")
    return (f"⚠️ ยังไม่มีผลลัพธ์ปิดไม้มารองรับ (ประเมินหยาบจาก {n} ไม้ที่ยังติดตามอยู่) "
            f"ถือเป็นการคาดการณ์ ไม่ใช่สถิติ")


def get_setup_edge_map(user, market='SET', horizon=20):
    """
    คำนวณ Edge ของแต่ละ Setup Flag สำหรับตลาดที่ระบุ

    คืน dict: {flag_name: {label, edge_r, win_rate, avg_r, is_positive, is_high,
                           sample_count, evidence, warning}}

    'evidence' บอกว่าตัวเลขชุดนี้เชื่อได้แค่ไหน ผู้เรียกต้องใช้มันตัดสินใจว่าจะ
    แสดงผลแบบมั่นใจหรือแบบตั้งข้อสงสัย — ห้ามอ่านแค่ is_positive แล้วสรุปเอาเอง
    """
    if not user:
        return {}

    # นับเฉพาะแถวที่ "ยังมีสิทธิ์ถูกประเมิน" — ตัวเติมผล (evaluate_scan_outcomes)
    # แตะเฉพาะแถวที่อยู่ในหน้าต่าง EVALUATION_WINDOW_DAYS แถวที่เก่ากว่านั้นและยัง
    # pending อยู่จะค้างแบบนั้นตลอดไป ถ้าปล่อยให้มันอยู่ในกองที่เอามานับ ตัวเลข
    # ตัวอย่างบนป้ายจะดูเยอะกว่าความจริง ทั้งที่ไม่มีวันรู้ผล
    cutoff = timezone.localdate() - timedelta(days=EVALUATION_WINDOW_DAYS)

    # horizon ที่ขอมาอาจยังไม่มีข้อมูล (ต้องรอครบ 20 แท่ง) จึงดึงทุก horizon มา
    # แล้วค่อยเลือกอันที่ใช้ได้ — แต่ต้องบอกผู้ใช้ว่าใช้อันไหน ไม่ใช่สลับเงียบๆ
    rows = list(
        ScanOutcome.objects
        .filter(user=user, market=market, scan_date__gte=cutoff)
        .values(
            'status', 'bars_evaluated', 'r_multiple', 'mfe_pct', 'mae_pct',
            *[f'ret_d{h}' for h in HORIZONS], *[f for f, _ in SETUP_FLAGS]
        )
        [:2000]
    )

    edge_map = {}

    if len(rows) >= MIN_ROWS_FOR_EDGE:
        # ลองจาก horizon ที่ขอก่อน แล้วถอยไปสั้นลงเรื่อยๆ จนกว่าจะมีข้อมูลพอ
        # (20 วันต้องรอนานสุด ช่วงแรกของระบบจึงมักมีแต่ d5/d10)
        ladder = [horizon] + [h for h in sorted(HORIZONS, reverse=True) if h != horizon]
        for h in ladder:
            for flag, label in SETUP_FLAGS:
                cmp_ = flag_comparison(rows, flag, horizon=h)
                on_count = cmp_['on']['n']
                edge_r = cmp_['edge_r']

                if on_count >= MIN_SAMPLE_REPORT and edge_r is not None:
                    evidence = (EVIDENCE_RELIABLE if on_count >= MIN_SAMPLE_RELIABLE
                                else EVIDENCE_THIN)
                    edge_map[flag] = {
                        'label': label,
                        'edge_r': edge_r,
                        'win_rate': cmp_['on']['win_rate'],
                        'avg_r': cmp_['on']['avg_r'],
                        'is_positive': edge_r > 0.05,
                        # is_high สงวนไว้ให้เฉพาะตัวอย่างที่พอเชื่อได้ ตัวอย่าง 3 ไม้
                        # ที่บังเอิญได้ edge สูงไม่ควรได้ป้ายเดียวกับ 50 ไม้
                        'is_high': edge_r >= 0.25 and evidence == EVIDENCE_RELIABLE,
                        'sample_count': on_count,
                        'evidence': evidence,
                        'horizon_used': h,
                        'warning': _sample_warning(evidence, on_count, h, horizon),
                    }
            if edge_map:
                break

    # กรณีข้อมูลยังสะสมไม่ถึง หรือตัวอย่างน้อย: ประเมินจากค่า MFE/MAE ล่าสุดของรายการที่กำลังติดตาม
    # ผลจากทางนี้เป็นการคาดการณ์จากไม้ที่ยังไม่ปิด ไม่ใช่สถิติผลลัพธ์ จึงถูกตี
    # เป็น provisional เสมอ และไม่มีวันเป็น is_high
    if not edge_map and rows:
        for flag, label in SETUP_FLAGS:
            flag_rows = [r for r in rows if r.get(flag)]
            if len(flag_rows) >= 2:
                mfes = [r['mfe_pct'] for r in flag_rows if r.get('mfe_pct') is not None]
                avg_mfe = sum(mfes) / len(mfes) if mfes else 0.0
                rs = [r['r_multiple'] for r in flag_rows if r.get('r_multiple') is not None]
                avg_r = sum(rs) / len(rs) if rs else 0.0

                is_pos = (avg_mfe >= 1.5) or (avg_r > 0)
                edge_map[flag] = {
                    'label': label,
                    'edge_r': round(avg_r, 2),
                    'win_rate': None,
                    'avg_r': round(avg_r, 2),
                    'is_positive': is_pos,
                    'is_high': False,
                    # NOTE: sample_count ของเส้นทางนี้นับ "ทุกแถวที่ติดธง" รวมไม้ที่ยัง
                    # เปิดอยู่ ต่างจากเส้นทางที่วัดผลจริงซึ่ง summarize() นับเฉพาะแถว
                    # ที่มี ret_d{horizon} แล้ว ผู้แสดงผลต้องอ่าน evidence ประกอบเสมอ
                    # ไม่งั้นจะเอาเลขสองชนิดมาเทียบกับเกณฑ์เดียวกัน
                    'sample_count': len(flag_rows),
                    'evidence': EVIDENCE_PROVISIONAL,
                    'horizon_used': None,
                    'warning': _sample_warning(EVIDENCE_PROVISIONAL, len(flag_rows),
                                               None, horizon),
                }

    return edge_map


def _clear_edge(c):
    """ล้างฟิลด์ edge ทั้งชุด — ให้ทุกเส้นทางออกมีแอตทริบิวต์ครบเท่ากัน"""
    c.edge_tier = 'none'
    c.edge_badge_label = ''
    c.edge_tooltip = ''
    c.edge_reasons = []
    c.edge_sample_count = 0
    c.edge_evidence = ''
    c.edge_warning = ''
    c.edge_horizon = None


def annotate_candidates_with_edge(candidates, user, market='SET', horizon=20):
    """
    ตรวจจับและติดป้าย Edge ให้กับผู้สมัคร (Candidates) ในหน้า Precision Scan

    ป้ายที่ติดจะสะท้อนน้ำหนักของหลักฐานที่มีจริง ดูคำอธิบาย 4 ระดับที่หัวโมดูล
    """
    if not candidates:
        return {'total_edge_count': 0, 'active_edge_map': {}}

    edge_map = get_setup_edge_map(user, market=market, horizon=horizon)
    total_edge_count = 0

    for c in candidates:
        _clear_edge(c)

        # ── จับคู่กับสถิติที่วัดได้จริง แยกตามน้ำหนักหลักฐาน ──
        reliable_high, reliable_pos, weak = [], [], []
        samples = []
        warnings = []
        weak_evidences = []
        horizons_used = []

        for flag, data in edge_map.items():
            if not getattr(c, flag, False) or not data.get('is_positive'):
                continue
            label = data['label']
            samples.append(data.get('sample_count', 0))
            if data.get('horizon_used'):
                horizons_used.append(data['horizon_used'])
            if data.get('warning'):
                warnings.append(data['warning'])

            if data.get('evidence') == EVIDENCE_RELIABLE:
                (reliable_high if data.get('is_high') else reliable_pos).append(label)
            else:
                weak.append(label)
                weak_evidences.append(data.get('evidence'))

        matched = reliable_high + reliable_pos + weak
        min_n = min(samples) if samples else 0
        # ถ้าหลายธงมาจากคนละ horizon ให้รายงานอันสั้นสุด ซึ่งเป็นอันที่อ่อนที่สุด
        c.edge_horizon = min(horizons_used) if horizons_used else None

        if reliable_high:
            # หลักฐานแน่นจริง — ที่เดียวที่ได้ป้ายเต็มและได้บวกคะแนนเต็ม
            c.edge_tier = 'high'
            c.edge_badge_label = '⭐ High Edge'
            c.edge_evidence = EVIDENCE_RELIABLE
            c.edge_sample_count = min_n
            c.edge_tooltip = (f"Setup ที่มีสถิติชนะเด่น (n≥{MIN_SAMPLE_RELIABLE}, "
                              f"วัดที่ {c.edge_horizon or horizon} วัน): "
                              f"{', '.join(matched[:3])}")
            c.edge_reasons = matched
            _boost(c, 5.0, f"⭐ High Historical Edge (+5): {', '.join(matched[:2])}")
            total_edge_count += 1

        elif reliable_pos:
            c.edge_tier = 'positive'
            c.edge_badge_label = '⭐ Edge'
            c.edge_evidence = EVIDENCE_RELIABLE
            c.edge_sample_count = min_n
            c.edge_tooltip = (f"Setup ที่มีสถิติเป็นบวก (n≥{MIN_SAMPLE_RELIABLE}, "
                              f"วัดที่ {c.edge_horizon or horizon} วัน): "
                              f"{', '.join(matched[:3])}")
            c.edge_reasons = matched
            _boost(c, 2.5, f"⭐ Historical Edge (+2.5): {matched[0]}")
            total_edge_count += 1

        elif weak:
            # มีสถิติ แต่น้อยเกินกว่าจะเชื่อ — แสดงได้ แต่ต้องแสดงเป็นข้อสงสัย
            # ไม่บวกคะแนน เพราะยังไม่รู้ว่าจะบวกจากอะไร
            c.edge_tier = 'thin'
            c.edge_badge_label = '⭐ Edge?'
            # ถ้าทุกตัวที่แมตช์มาจากการประเมินหยาบ ให้บอกตามนั้น ไม่ยกระดับให้
            c.edge_evidence = (EVIDENCE_PROVISIONAL
                               if all(e == EVIDENCE_PROVISIONAL for e in weak_evidences)
                               else EVIDENCE_THIN)
            c.edge_sample_count = min_n
            c.edge_warning = warnings[0] if warnings else _sample_warning(EVIDENCE_THIN, min_n)
            c.edge_tooltip = f"{', '.join(matched[:3])} — {c.edge_warning}"
            c.edge_reasons = matched

        else:
            # ไม่มีสถิติแตะตัวนี้เลย เหลือแค่ "ติดรูปแบบอะไรบ้าง" ซึ่งเป็นคนละเรื่อง
            # กับความได้เปรียบ จึงไม่เรียกว่า Edge และไม่บวกคะแนน
            setups = [label for flag, label in CORE_HIGH_EDGE_FLAGS.items()
                      if getattr(c, flag, False)]
            if setups:
                c.edge_tier = 'setup_only'
                c.edge_badge_label = '◇ Setup'
                c.edge_evidence = ''
                c.edge_sample_count = 0
                c.edge_warning = ("⚠️ ยังไม่มีสถิติผลลัพธ์ของ Setup นี้ในพอร์ตคุณ — "
                                  "ป้ายนี้บอกแค่ว่า 'เข้ารูปแบบ' ไม่ได้บอกว่าชนะ")
                c.edge_tooltip = f"เข้ารูปแบบ: {', '.join(setups[:3])} — {c.edge_warning}"
                c.edge_reasons = setups

    return {
        'total_edge_count': total_edge_count,
        'active_edge_map': edge_map,
    }


def _boost(c, amount, reason):
    """บวก quality score พร้อมบันทึกเหตุผล — ใช้เฉพาะเส้นทางที่มีหลักฐานรองรับ"""
    if getattr(c, 'quality_score', None) is None:
        return
    c.quality_score = min(round(c.quality_score + amount, 1), 100.0)
    if isinstance(getattr(c, 'quality_reasons', None), list):
        c.quality_reasons.insert(0, reason)
