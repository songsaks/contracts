"""
หน้ารายงานคุณภาพตัวสแกน — "คะแนนที่ให้ไว้ ทำนายอะไรได้จริงไหม"

ตอบคำถามที่ระบบไม่เคยตอบได้มาก่อน:
  - หุ้นคะแนน 85+ ให้ผลดีกว่าคะแนน 55-69 จริงไหม
  - ธง setup อันไหน (VCP / HTF / Pocket Pivot / ...) มี edge จริง อันไหนเป็นแค่ noise
  - แต่ละ preset ทำเงินได้หรือเปล่า เมื่อวัดด้วย R-multiple ไม่ใช่ความรู้สึก
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from stocks.models import ScanOutcome
from stocks.scan_outcomes import (
    HORIZONS, SCORE_BUCKETS, SETUP_FLAGS,
    flag_comparison, group_summary, summarize,
)

# ฟิลด์ที่ดึงมาทำสถิติ — ระบุให้ชัดเพื่อไม่ให้ query ลากทั้งตารางมาโดยไม่จำเป็น
_STAT_FIELDS = (
    'symbol', 'market', 'scan_date', 'price_at_scan', 'entry_strategy', 'sector',
    'stop_loss', 'target_price', 'technical_score', 'buy_score', 'rs_rating', 'score_bucket',
    'first_hit', 'r_multiple', 'mfe_pct', 'mae_pct', 'status', 'bars_evaluated', 'evaluated_at',
    *[f'ret_d{h}' for h in HORIZONS],
    *[f for f, _ in SETUP_FLAGS],
)

_BUCKET_ORDER = [label for _floor, label in SCORE_BUCKETS]


@login_required
def scan_quality_report(request):
    market = request.GET.get('market', 'SET').upper()
    if market not in ('SET', 'US'):
        market = 'SET'
    try:
        horizon = int(request.GET.get('horizon', 20))
    except (TypeError, ValueError):
        horizon = 20
    if horizon not in HORIZONS:
        horizon = HORIZONS[-1]

    rows = list(
        ScanOutcome.objects
        .filter(user=request.user, market=market)
        .values(*_STAT_FIELDS)
        .order_by('-scan_date')[:5000]
    )

    overall = summarize(rows, horizon=horizon)

    # ── คะแนนเทคนิคทำนายผลได้ไหม ──
    by_score = group_summary(rows, lambda r: r.get('score_bucket') or '0-54',
                             horizon=horizon, min_n=3)
    by_score.sort(key=lambda s: _BUCKET_ORDER.index(s['key'])
                  if s['key'] in _BUCKET_ORDER else 99)

    # ── ธง setup อันไหนมี edge จริง ──
    flags = []
    label_of = dict(SETUP_FLAGS)
    for flag, label in SETUP_FLAGS:
        cmp_ = flag_comparison(rows, flag, horizon=horizon)
        # ต้องมีตัวอย่างทั้งสองฝั่งพอสมควร ไม่งั้นตัวเลขเชื่อไม่ได้
        if cmp_['on']['n'] < 5 or cmp_['off']['n'] < 5:
            continue
        cmp_['label'] = label
        # ความกว้างแถบเปรียบเทียบ — คำนวณที่นี่เพราะ template ทำค่าติดลบไม่ได้
        # เทียบกับ 1.0R เป็นเต็มสเกล แล้วตัดที่ 100%
        edge = cmp_['edge_r'] or 0
        cmp_['edge_width'] = min(abs(edge) / 1.0 * 100, 100)
        flags.append(cmp_)
    flags.sort(key=lambda c: c['edge_r'] if c['edge_r'] is not None else -99, reverse=True)

    by_preset = group_summary(rows, lambda r: (r.get('entry_strategy') or '').strip() or '(ไม่ระบุ)',
                              horizon=horizon, min_n=3)
    by_sector = group_summary(rows, lambda r: (r.get('sector') or '').strip() or 'Unknown',
                              horizon=horizon, min_n=3)

    pending = sum(1 for r in rows if r.get('status') == 'pending')
    evaluated_count = sum(1 for r in rows if r.get('status') in ('partial', 'complete'))
    max_bars = max((r.get('bars_evaluated') or 0 for r in rows), default=0)
    days_left = max(horizon - max_bars, 0)
    recent_tracked = [r for r in rows if (r.get('bars_evaluated') or 0) > 0 or r.get('status') != 'pending'][:60]

    return render(request, 'stocks/scan_quality.html', {
        'market': market,
        'horizon': horizon,
        'horizons': HORIZONS,
        'overall': overall,
        'by_score': by_score,
        'flags': flags,
        'flag_labels': label_of,
        'by_preset': by_preset[:15],
        'by_sector': by_sector[:15],
        'total_rows': len(rows),
        'pending': pending,
        'evaluated_count': evaluated_count,
        'max_bars': max_bars,
        'days_left': days_left,
        'recent_tracked': recent_tracked,
        'has_data': overall['n'] > 0,
    })
