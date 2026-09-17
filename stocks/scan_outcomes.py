"""
Scan Outcome Tracking — ตามผลว่า "หุ้นที่สแกนเจอ สุดท้ายเป็นยังไง"

ทำไมต้องมี: ตัวสแกนให้คะแนน (technical_score / buy_score / rs_rating) และติดธง
setup ต่างๆ มาตลอด แต่ไม่เคยมีใครย้อนกลับไปถามว่า "คะแนน 85 กับคะแนน 25
ให้ผลต่างกันจริงไหม" ตราบใดที่ไม่วัด ก็ปรับสูตรโดยอาศัยความรู้สึกเท่านั้น

โมดูลนี้เป็นฟังก์ชันล้วน ไม่แตะ DB และไม่ยิงเน็ต (ฝั่งที่แตะ DB อยู่ใน
models.ScanOutcome และ management command evaluate_scan_outcomes)

นิยามที่ใช้วัด — เขียนไว้ตรงนี้ที่เดียว เพื่อไม่ให้ตีความต่างกันในแต่ละหน้า:

  entry  = ราคา ณ วันที่สแกนเจอ (ไม่ใช่ขอบบน demand zone)
           เพราะคำถามคือ "ถ้าเห็นสัญญาณนี้แล้วเข้าเลย จะเป็นยังไง"
           ส่วน RR ของตัวสแกนคิดจากขอบโซน ซึ่งเป็น RR ของ setup คนละคำถามกัน
  ret_dN = (close ของแท่งที่ N หลังวันสแกน − entry) / entry × 100
  MFE    = กำไรสูงสุดที่เคยเห็นระหว่างทาง (Maximum Favourable Excursion)
  MAE    = ขาดทุนหนักสุดที่เคยเห็นระหว่างทาง (Maximum Adverse Excursion)
  first_hit = TP หรือ SL อันไหนโดนก่อน เดินไล่ทีละแท่ง

  ถ้าแท่งเดียวกันแตะทั้ง TP และ SL → นับเป็น SL
  เพราะข้อมูลรายวันไม่บอกว่าอันไหนเกิดก่อน การเดาเข้าข้างตัวเองจะทำให้
  สถิติสวยกว่าความจริง ซึ่งอันตรายกว่าการประเมินตัวเองต่ำไป
"""

# จำนวนแท่งที่ใช้วัดผล — ตัวสุดท้ายคือความยาวหน้าต่างทั้งหมด
HORIZONS = (5, 10, 20)
MAX_HORIZON = max(HORIZONS)

# หน้าต่างย้อนหลังที่ตัวประเมินผลจะยอมแตะ — แถวที่เก่ากว่านี้จะไม่ถูกประเมินอีกเลย
# ต้องเป็นค่าเดียวกันทั้งฝั่ง command ที่เติมผล และฝั่งที่เอาผลไปนับสถิติ ไม่งั้น
# จะมีแถวที่ถูกนับเข้าตัวหารทั้งที่ไม่มีวันรู้ผล
EVALUATION_WINDOW_DAYS = 90

# ช่วงคะแนนที่ใช้จัดกลุ่มรายงาน (ขอบล่าง, ป้าย) เรียงจากมากไปน้อย
SCORE_BUCKETS = (
    (85, '85-100'),
    (70, '70-84'),
    (55, '55-69'),
    (0,  '0-54'),
)

STATUS_PENDING = 'pending'      # ยังไม่ถึงกำหนดวัด
STATUS_PARTIAL = 'partial'      # วัดได้บางช่วง (ยังไม่ครบ 20 แท่ง)
STATUS_COMPLETE = 'complete'    # ครบหน้าต่างแล้ว


def score_bucket(score):
    """แปลงคะแนนเป็นป้ายช่วง — ใช้ร่วมกันทั้งตอนเขียนและตอนรายงาน"""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return SCORE_BUCKETS[-1][1]
    for floor, label in SCORE_BUCKETS:
        if value >= floor:
            return label
    return SCORE_BUCKETS[-1][1]


def _pct(new, base):
    return (new - base) / base * 100.0 if base else 0.0


def evaluate_forward(entry, stop, target, highs, lows, closes):
    """
    วัดผลล่วงหน้าจากแท่งราคา *หลัง* วันที่สแกน

    entry/stop/target : ราคาอ้างอิง ณ วันสแกน (stop/target ใส่ None ได้)
    highs/lows/closes : ลำดับราคาของแท่งถัดจากวันสแกนเป็นต้นไป (เก่า→ใหม่)
                        ส่งมาเท่าที่มี ถ้ายังไม่ครบ 20 แท่งจะได้ status partial

    คืน dict ที่ map ตรงกับฟิลด์ของ ScanOutcome
    """
    entry = float(entry or 0)
    bars = min(len(highs), len(lows), len(closes))

    out = {
        'bars_evaluated': 0,
        'mfe_pct': None, 'mae_pct': None,
        'first_hit': '', 'r_multiple': None,
        'status': STATUS_PENDING,
    }
    for h in HORIZONS:
        out[f'ret_d{h}'] = None
        out[f'price_d{h}'] = None

    if entry <= 0 or bars == 0:
        return out

    # ตัดให้ไม่เกินหน้าต่างที่สนใจ — แท่งหลังจากนั้นไม่เกี่ยวกับการวัดรอบนี้
    bars = min(bars, MAX_HORIZON)
    highs = [float(x) for x in highs[:bars]]
    lows = [float(x) for x in lows[:bars]]
    closes = [float(x) for x in closes[:bars]]

    out['bars_evaluated'] = bars
    out['status'] = STATUS_COMPLETE if bars >= MAX_HORIZON else STATUS_PARTIAL

    for h in HORIZONS:
        if bars >= h:
            px = closes[h - 1]
            out[f'price_d{h}'] = round(px, 4)
            out[f'ret_d{h}'] = round(_pct(px, entry), 2)

    out['mfe_pct'] = round(_pct(max(highs), entry), 2)
    out['mae_pct'] = round(_pct(min(lows), entry), 2)

    stop = float(stop) if stop else 0.0
    target = float(target) if target else 0.0
    risk = entry - stop if stop > 0 and stop < entry else 0.0

    # เดินไล่ทีละแท่ง หา TP/SL ตัวที่โดนก่อน (แท่งเดียวกันโดนทั้งคู่ = นับ SL)
    hit = ''
    for i in range(bars):
        if risk > 0 and lows[i] <= stop:
            hit = 'SL'
            break
        if target > entry and highs[i] >= target:
            hit = 'TP'
            break
    out['first_hit'] = hit

    if risk > 0:
        if hit == 'SL':
            out['r_multiple'] = -1.0
        elif hit == 'TP':
            out['r_multiple'] = round((target - entry) / risk, 2)
        else:
            # ยังไม่โดนทั้งสองฝั่ง — ตีมูลค่าด้วยราคาปิดล่าสุดที่วัดได้
            out['r_multiple'] = round((closes[-1] - entry) / risk, 2)

    return out


def _mean(values):
    return sum(values) / len(values) if values else None


def summarize(rows, horizon=20):
    """
    สรุปสถิติจากลิสต์ของ dict (หรืออะไรก็ตามที่ .get ได้)

    นับเฉพาะแถวที่วัดผลได้จริงในช่วง horizon ที่ขอ — แถว pending ไม่ถูกนับ
    เพื่อไม่ให้ตัวเลขถูกเจือจางด้วยรายการที่ยังไม่รู้ผล
    """
    key = f'ret_d{horizon}'
    scored = [r for r in rows if r.get(key) is not None]

    rets = [float(r[key]) for r in scored]
    wins = [r for r in rets if r > 0]
    r_multiples = [float(r['r_multiple']) for r in scored if r.get('r_multiple') is not None]
    tp = sum(1 for r in scored if r.get('first_hit') == 'TP')
    sl = sum(1 for r in scored if r.get('first_hit') == 'SL')

    gains = [r for r in rets if r > 0]
    losses = [-r for r in rets if r < 0]
    total_gain, total_loss = sum(gains), sum(losses)

    return {
        'n': len(scored),
        'n_pending': len(rows) - len(scored),
        'win_rate': round(len(wins) / len(scored) * 100, 1) if scored else None,
        'avg_return': round(_mean(rets), 2) if rets else None,
        'median_return': round(_median(rets), 2) if rets else None,
        'avg_win': round(_mean(gains), 2) if gains else None,
        'avg_loss': round(-_mean(losses), 2) if losses else None,
        'avg_r': round(_mean(r_multiples), 2) if r_multiples else None,
        'expectancy_r': round(_mean(r_multiples), 2) if r_multiples else None,
        # กำไรรวม ÷ ขาดทุนรวม — >1 แปลว่าชุดนี้ทำเงินได้ แม้ win rate จะต่ำ
        'profit_factor': round(total_gain / total_loss, 2) if total_loss > 0 else None,
        'tp_first': tp,
        'sl_first': sl,
        'avg_mfe': round(_mean([float(r['mfe_pct']) for r in scored
                                if r.get('mfe_pct') is not None]) or 0, 2) if scored else None,
        'avg_mae': round(_mean([float(r['mae_pct']) for r in scored
                                if r.get('mae_pct') is not None]) or 0, 2) if scored else None,
    }


def _median(values):
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def group_summary(rows, key_fn, horizon=20, min_n=1):
    """
    จัดกลุ่มแล้วสรุปทีละกลุ่ม — ใช้ทำตาราง "คะแนนช่วงนี้ ชนะกี่ %"

    key_fn คืน None เพื่อข้ามแถวนั้น (เช่น ธง setup ที่ไม่ได้ติด)
    min_n  กันไม่ให้กลุ่มที่มี 1-2 ตัวอย่างขึ้นมาอวดตัวเลขที่เชื่อไม่ได้
    """
    buckets = {}
    for row in rows:
        k = key_fn(row)
        if k is None:
            continue
        buckets.setdefault(k, []).append(row)

    out = []
    for k, group in buckets.items():
        stats = summarize(group, horizon=horizon)
        if stats['n'] < min_n:
            continue
        stats['key'] = k
        out.append(stats)
    out.sort(key=lambda s: (s['avg_r'] if s['avg_r'] is not None else -99), reverse=True)
    return out


# ธง setup ที่อยากรู้ว่าอันไหนได้ผลจริง — (ชื่อฟิลด์, ป้ายที่แสดง)
SETUP_FLAGS = (
    ('vcp_setup', 'VCP'),
    ('htf_setup', 'High Tight Flag'),
    ('pocket_pivot', 'Pocket Pivot'),
    ('pp_at_ma50', 'PP ที่ MA50'),
    ('episodic_pivot', 'Episodic Pivot'),
    ('stage2', 'Stage 2'),
    ('is_explosive', 'Explosive'),
    ('is_52w_breakout', '52w Breakout'),
    ('ema20_aligned', 'EMA เรียงตัว'),
    ('wyckoff_spring', 'Wyckoff Spring'),
    ('vdu_near_zone', 'Volume Dry-Up'),
    ('macd_crossover', 'MACD ตัดขึ้น'),
    ('bb_squeeze', 'BB Squeeze'),
    ('inside_bar', 'Inside Bar'),
)


def snapshot_from_candidate(candidate):
    """
    ดึงเฉพาะค่าที่ต้องเก็บจาก PrecisionScanCandidate → dict สำหรับ ScanOutcome

    แยกออกมาเป็นฟังก์ชันเพื่อให้เทสต์ได้โดยไม่ต้องมี DB และเพื่อให้เวลาเพิ่มธงใหม่
    แก้ที่เดียว (ที่นี่ + SETUP_FLAGS + ฟิลด์ในโมเดล)
    """
    def _f(name, default=0.0):
        return getattr(candidate, name, default)

    price = float(_f('price') or 0)
    target = _f('supply_zone_start', None)

    snap = {
        'price_at_scan': price,
        'stop_loss': _f('stop_loss', None),
        'target_price': float(target) if target else None,
        'risk_reward_ratio': _f('risk_reward_ratio', None),
        'entry_strategy': (_f('entry_strategy', '') or '')[:100],
        'sector': (_f('sector', '') or '')[:100],
        'technical_score': int(_f('technical_score', 0) or 0),
        'buy_score': int(getattr(candidate, 'buy_score', 0) or 0),
        'rs_rating': int(_f('rs_rating', 0) or 0),
        'rsi': float(_f('rsi', 0) or 0),
        'adx': float(_f('adx', 0) or 0),
        'rvol': float(_f('rvol', 1) or 1),
        'cmf': _f('cmf', None),
        'volume_surge': float(_f('volume_surge', 1) or 1),
    }
    snap['score_bucket'] = score_bucket(snap['technical_score'])
    for flag, _label in SETUP_FLAGS:
        snap[flag] = bool(getattr(candidate, flag, False))
    return snap


def record_candidates(user, market, scan_run, candidates):
    """
    บันทึก snapshot ของผลสแกนรอบนี้ลง ScanOutcome (เรียกหลัง bulk_create)

    ออกแบบให้ "ห้ามพังการสแกน" เด็ดขาด — ถ้าที่นี่ error ขึ้นมา ผลสแกนที่ผู้ใช้
    รอมาทั้งรอบต้องไม่หายไปด้วย จึงกลืน exception แล้ว log ไว้เฉยๆ

    คืนจำนวนแถวที่สร้างใหม่ (แถวของวันเดิมที่มีอยู่แล้วจะไม่ถูกแตะ เพราะ
    snapshot ต้องเป็นค่า ณ ครั้งแรกที่สัญญาณโผล่ ไม่ใช่ค่าที่อัปเดตทีหลัง)
    """
    import logging
    logger = logging.getLogger(__name__)

    if not user or not candidates:
        return 0

    try:
        from django.db import transaction
        from .models import ScanOutcome

        # วันที่ต้องเป็นวันตามเวลาไทย ไม่ใช่วันที่ UTC — scan_run มาจาก timezone.now()
        # ซึ่ง USE_TZ=True ทำให้เป็น UTC การเรียก .date() ตรงๆ จะได้วันก่อนหน้าเมื่อ
        # สแกนช่วงเที่ยงคืนถึง 7 โมงเช้า และเพราะระบบกันซ้ำด้วย scan_date การสแกน
        # ตอนตี 2 จะถูกมองว่าเป็นวันเดียวกับบ่ายวันก่อน แล้วไม่บันทึกอะไรเลย
        from django.utils import timezone as _dj_tz
        if hasattr(scan_run, 'date'):
            scan_date = (_dj_tz.localtime(scan_run).date()
                         if _dj_tz.is_aware(scan_run) else scan_run.date())
        else:
            scan_date = scan_run

        existing = set(
            ScanOutcome.objects
            .filter(user=user, market=market, scan_date=scan_date)
            .values_list('symbol', flat=True)
        )

        rows, seen = [], set()
        for c in candidates:
            symbol = (getattr(c, 'symbol', '') or '').strip().upper()
            if not symbol or symbol in existing or symbol in seen:
                continue
            snap = snapshot_from_candidate(c)
            if snap['price_at_scan'] <= 0:
                continue          # ไม่มีราคาอ้างอิง = วัดผลไม่ได้ ไม่ต้องเก็บ
            seen.add(symbol)
            rows.append(ScanOutcome(
                user=user, market=market, symbol=symbol,
                scan_date=scan_date, scan_run=scan_run,
                status=STATUS_PENDING, **snap
            ))

        if not rows:
            return 0
        with transaction.atomic():
            ScanOutcome.objects.bulk_create(rows, ignore_conflicts=True)
        return len(rows)
    except Exception as e:
        logger.warning(f"record_candidates failed (scan ยังสำเร็จปกติ): {e}")
        return 0


def flag_comparison(rows, flag, horizon=20):
    """
    เทียบ "ติดธงนี้" vs "ไม่ติดธงนี้" — คำถามที่สำคัญกว่า win rate เดี่ยวๆ

    ธงจะมีค่าก็ต่อเมื่อกลุ่มที่ติดธงทำได้ดีกว่ากลุ่มที่ไม่ติด ถ้าพอๆ กัน
    แปลว่าธงนั้นไม่ได้ช่วยคัดอะไรเลย (แต่ยังกินเวลาคำนวณทุกรอบสแกน)
    """
    on = [r for r in rows if r.get(flag)]
    off = [r for r in rows if not r.get(flag)]
    s_on, s_off = summarize(on, horizon), summarize(off, horizon)
    edge = None
    if s_on['avg_r'] is not None and s_off['avg_r'] is not None:
        edge = round(s_on['avg_r'] - s_off['avg_r'], 2)
    return {'flag': flag, 'on': s_on, 'off': s_off, 'edge_r': edge}
