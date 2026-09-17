"""
Scan Edge — เชื่อมโยงสถิติผลลัพธ์ย้อนหลัง (ScanOutcome) เข้าสู่หน้าสแกนหุ้น (Closed-Loop Feedback)

หน้าที่:
1. คำนวณความได้เปรียบ (Edge) ของแต่ละ Setup Flag จากข้อมูลผลลัพธ์จริงใน ScanOutcome
2. นำผลประเมินมาติดป้าย (Badge) และเพิ่มคะแนน (Quality Boost) ให้กับหุ้นในหน้า Precision Scan
3. ช่วยให้เทรดเดอร์กรองเลือกเฉพาะหุ้นที่มีสถิติในอดีตรองรับว่าชนะตลาดจริง (Empirical Edge)
"""

from stocks.models import ScanOutcome
from stocks.scan_outcomes import SETUP_FLAGS, flag_comparison

CORE_HIGH_EDGE_FLAGS = {
    'pocket_pivot': 'Pocket Pivot',
    'vcp_setup': 'VCP Pattern',
    'stage2': 'Weinstein Stage 2',
    'is_explosive': 'Explosive Momentum',
    'volume_surge': 'Volume Surge',
    'htf_setup': 'High Tight Flag',
    'pp_at_ma50': 'Pocket Pivot @ MA50',
}


def get_setup_edge_map(user, market='SET', horizon=20):
    """
    คำนวณ Edge ของแต่ละ Setup Flag สำหรับตลาดที่ระบุ
    คืน dict: {flag_name: {'edge_r': float, 'win_rate': float, 'is_positive': bool, 'label': str}}
    """
    if not user:
        return {}

    rows = list(
        ScanOutcome.objects
        .filter(user=user, market=market)
        .values(
            'status', 'bars_evaluated', 'r_multiple', 'mfe_pct', 'mae_pct',
            f'ret_d{horizon}', *[f for f, _ in SETUP_FLAGS]
        )
        [:2000]
    )

    edge_map = {}

    if len(rows) >= 10:
        for flag, label in SETUP_FLAGS:
            cmp_ = flag_comparison(rows, flag, horizon=horizon)
            on_count = cmp_['on']['n']
            edge_r = cmp_['edge_r']

            if on_count >= 3 and edge_r is not None:
                edge_map[flag] = {
                    'label': label,
                    'edge_r': edge_r,
                    'win_rate': cmp_['on']['win_rate'],
                    'avg_r': cmp_['on']['avg_r'],
                    'is_positive': edge_r > 0.05,
                    'is_high': edge_r >= 0.25,
                    'sample_count': on_count,
                }

    # กรณีข้อมูลยังสะสมไม่ถึง หรือตัวอย่างน้อย: ประเมินจากค่า MFE/MAE ล่าสุดของรายการที่กำลังติดตาม
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
                    'is_high': avg_mfe >= 2.5 or avg_r >= 0.3,
                    'sample_count': len(flag_rows),
                }

    return edge_map


def annotate_candidates_with_edge(candidates, user, market='SET', horizon=20):
    """
    ตรวจจับและติดป้าย Edge ให้กับผู้สมัคร (Candidates) ในหน้า Precision Scan
    """
    if not candidates:
        return {'total_edge_count': 0, 'active_edge_map': {}}

    edge_map = get_setup_edge_map(user, market=market, horizon=horizon)
    total_edge_count = 0

    for c in candidates:
        matched_setups = []
        is_high_tier = False
        is_pos_tier = False

        if edge_map:
            for flag, data in edge_map.items():
                if getattr(c, flag, False) and data.get('is_positive'):
                    matched_setups.append(data['label'])
                    if data.get('is_high'):
                        is_high_tier = True
                    else:
                        is_pos_tier = True

        if not matched_setups:
            for flag, label in CORE_HIGH_EDGE_FLAGS.items():
                if getattr(c, flag, False):
                    matched_setups.append(label)
                    is_pos_tier = True
            if len(matched_setups) >= 2:
                is_high_tier = True

        if is_high_tier or len(matched_setups) >= 2:
            c.edge_tier = 'high'
            c.edge_badge_label = '⭐ High Edge'
            c.edge_tooltip = f"Setup ชนะเด่น: {', '.join(matched_setups[:3])}"
            c.edge_reasons = matched_setups
            if hasattr(c, 'quality_score') and c.quality_score is not None:
                c.quality_score = min(round(c.quality_score + 5.0, 1), 100.0)
                if hasattr(c, 'quality_reasons') and isinstance(c.quality_reasons, list):
                    c.quality_reasons.insert(0, f"⭐ High Historical Edge (+5): {', '.join(matched_setups[:2])}")
            total_edge_count += 1

        elif is_pos_tier or len(matched_setups) == 1:
            c.edge_tier = 'positive'
            c.edge_badge_label = '⭐ Edge'
            c.edge_tooltip = f"Setup ชนะ: {matched_setups[0]}"
            c.edge_reasons = matched_setups
            if hasattr(c, 'quality_score') and c.quality_score is not None:
                c.quality_score = min(round(c.quality_score + 2.5, 1), 100.0)
                if hasattr(c, 'quality_reasons') and isinstance(c.quality_reasons, list):
                    c.quality_reasons.insert(0, f"⭐ Historical Edge (+2.5): {matched_setups[0]}")
            total_edge_count += 1
        else:
            c.edge_tier = 'none'
            c.edge_badge_label = ''
            c.edge_tooltip = ''
            c.edge_reasons = []

    return {
        'total_edge_count': total_edge_count,
        'active_edge_map': edge_map,
    }
