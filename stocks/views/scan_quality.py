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


@login_required
def api_scan_quality_ai_analysis(request):
    """
    AJAX endpoint: รวบรวมสถิติ ScanOutcome ทั้งหมด แล้วส่งให้ Gemini AI วิเคราะห์ Edge,
    สรุป Setup ที่ชนะ และวาง Checklist แผนการคัดเลือกหุ้นสำหรับรอบสแกนถัดไป
    """
    from django.conf import settings
    from django.http import JsonResponse
    from google import genai

    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return JsonResponse({'success': False, 'error': 'ไม่พบ GEMINI_API_KEY ในระบบ'}, status=500)

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

    if not rows:
        return JsonResponse({'success': False, 'error': f'ยังไม่มีข้อมูลผลสแกนของตลาด {market} สำหรับวิเคราะห์'}, status=404)

    overall = summarize(rows, horizon=horizon)
    by_score = group_summary(rows, lambda r: r.get('score_bucket') or '0-54', horizon=horizon, min_n=2)
    
    flags = []
    for flag, label in SETUP_FLAGS:
        cmp_ = flag_comparison(rows, flag, horizon=horizon)
        if cmp_['on']['n'] >= 2:
            flags.append({
                'label': label,
                'edge_r': cmp_['edge_r'],
                'on_n': cmp_['on']['n'],
                'on_win': cmp_['on']['win_rate'],
                'on_r': cmp_['on']['avg_r'],
                'off_r': cmp_['off']['avg_r'],
            })
    flags.sort(key=lambda x: x['edge_r'] if x['edge_r'] is not None else -99, reverse=True)

    by_sector = group_summary(rows, lambda r: (r.get('sector') or '').strip() or 'Unknown', horizon=horizon, min_n=2)

    # Active tracking sample
    active_sample = [r for r in rows if (r.get('bars_evaluated') or 0) > 0 or r.get('status') != 'pending'][:20]
    sample_text = ""
    for s in active_sample[:15]:
        sample_text += f"- {s['symbol']}: Entry {s['price_at_scan']}, Score {s.get('technical_score')}, MFE {s.get('mfe_pct')}%, MAE {s.get('mae_pct')}%, R {s.get('r_multiple')}, Hit: {s.get('first_hit') or 'Tracking'}, Days: {s.get('bars_evaluated', 0)}\n"

    score_text = "\n".join([f"- ช่วงคะแนน {b['key']}: n={b['n']}, Win Rate={b['win_rate']}%, Avg Return={b['avg_return']}%, R={b['avg_r']}R" for b in by_score]) or "อยู่ระหว่างสะสมข้อมูล"
    flags_text = "\n".join([f"- {f['label']}: Edge {f['edge_r']}R (ติดธง n={f['on_n']}, R={f['on_r']}R, Win={f['on_win']}% | ไม่ติดธง R={f['off_r']}R)" for f in flags[:10]]) or "อยู่ระหว่างสะสมข้อมูล"
    sector_text = "\n".join([f"- {s['key']}: n={s['n']}, Win Rate={s['win_rate']}%, Avg R={s['avg_r']}R" for s in by_sector[:6]]) or "อยู่ระหว่างสะสมข้อมูล"

    # Build Prompt for Gemini
    prompt = f"""คุณคือ Head of Quantitative Trading และ Chief Trading Strategist ของกองทุน
จงวิเคราะห์ข้อมูลผลลัพธ์จริง (Scan Outcome & Forward Return Tracking) ของระบบ Precision Scanner ในตลาด {market} (รอบวัดผล {horizon} วันทำการ)

[ข้อมูลสถิติภาพรวม]
- จำนวน Snapshot ทั้งหมด: {len(rows)} รายการ
- สถานะที่คำนวณครบ/บางส่วนแล้ว: {sum(1 for r in rows if r.get('status') in ('partial', 'complete'))} รายการ
- Win Rate รวม: {overall.get('win_rate', 'รอสะสมวันทำการ')}% (จาก {overall.get('n', 0)} สัญญาณที่ครบ {horizon} วัน)
- ผลตอบแทนเฉลี่ย: {overall.get('avg_return', 'N/A')}%
- Expectancy R เฉลี่ย: {overall.get('avg_r', 'N/A')}R
- Profit Factor: {overall.get('profit_factor', 'N/A')}
- First Hit: ชน Take Profit (TP) ก่อน {overall.get('tp_first', 0)} ตัว | ชน Stop Loss (SL) ก่อน {overall.get('sl_first', 0)} ตัว

[ประสิทธิภาพแยกตามคะแนนเทคนิค (Score Buckets)]
{score_text}

[การวัด Edge ของ Setup Flags (เทียบตัวที่ติดธง vs ไม่ติดธง)]
{flags_text}

[ผลงานแยกตาม Sector]
{sector_text}

[ตัวอย่างหุ้นที่กำลังติดตามผลจริง (Active Tracking Sample)]
{sample_text or 'ไม่มีตัวอย่าง'}

กรุณาวิเคราะห์เชิงลึกและให้คำแนะนำแก่เทรดเดอร์ในรูปแบบ Markdown ภาษาไทยที่กระชับ คมชัด และนำไปใช้เทรดได้จริง ตามหัวข้อดังนี้:

### 1. 📊 สรุปภาพรวมคุณภาพตัวสแกน (Executive Edge Summary)
(สรุปความแม่นยำ สภาวะตลาดส่งผลต่อสัญญาณอย่างไร และระบบกำลังสร้างความได้เปรียบหรือไม่)

### 2. 🏆 Top Winning Setups (สัญญาณที่พิสูจน์แล้วว่าชนะตลาดจริง)
(ระบุ Setup หรือช่วงคะแนนที่มี Edge เป็นบวกสูงสุดที่ควรให้ความสำคัญเป็นอันดับ 1)

### 3. ⚠️ สัญญาณหลอกและจุดเสี่ยงที่ต้องระวัง (Noise & False Breakout Warning)
(สัญญาณหรือกลุ่ม Sector ใดที่มี Edge ต่ำหรือติดลบ หรือหุ้นที่ย่อตัวลึกเกินไป)

### 4. 🎯 คำแนะนำปรับ Stop Loss & Take Profit ให้คมขึ้น (Risk-Reward Optimization)
(วิเคราะห์จากพฤติกรรมราคา MFE / MAE ของหุ้นในพอร์ตว่าควรตั้ง Stop Loss กว้างหรือแคบเท่าไหร่ถึงจะไม่โดนกวาดและได้ R สูงสุด)

### 5. 📋 Checklist คัดเลือกหุ้นสำหรับรอบสแกนถัดไป (Actionable Playbook)
(ให้ Checklist ข้อกำหนด 3-4 ข้อ ที่เทรดเดอร์สามารถเปิดหน้า Precision Scan แล้วใช้กรองเลือกหุ้นได้ทันทีในวันพรุ่งนี้)

กฎ:
1. ตอบเป็น Markdown เท่านั้น ไม่ต้องใส่บล็อก ```markdown ครอบ
2. ใช้ภาษาไทยระดับมืออาชีพ ชัดเจน มีตัวเลขสถิติอ้างอิง
"""

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        analysis_text = response.text or ""
        if analysis_text.startswith("```markdown"):
            analysis_text = analysis_text[len("```markdown"):].strip()
        if analysis_text.endswith("```"):
            analysis_text = analysis_text[:-3].strip()

        return JsonResponse({
            'success': True,
            'market': market,
            'horizon': horizon,
            'analysis': analysis_text,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': f"เกิดข้อผิดพลาดในการเรียก AI: {str(e)}"}, status=500)

