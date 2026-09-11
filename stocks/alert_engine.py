# ====== alert_engine.py — คำนวณแจ้งเตือน Action ของหุ้นในพอร์ต/Watchlist ======
# ใช้ร่วมกันระหว่าง endpoint เช็คแจ้งเตือนในหน้าเว็บ (stocks/views/alerts.py)
# แยกจาก management command monitor_stocks.py (ที่ยิง Telegram) เพื่อไม่ให้กระทบของเดิม

import hashlib
from datetime import time as dtime
from datetime import timedelta

import pytz
import yfinance as yf
from django.core.cache import cache
from django.utils import timezone as dj_timezone

from .models import AssetCategory, MarketType, Portfolio, Watchlist, PrecisionScanCandidate, StockAlertEvent
from .utils import simple_trailing_stop

# ตลาดที่ไม่ควรเติม .BK (หุ้น US, Crypto, Forex ฯลฯ ใช้ symbol ตามที่กรอกตรงๆ)
_NON_SET_MARKETS = {MarketType.US, MarketType.CRYPTO, MarketType.FUND, MarketType.CASH, MarketType.OTHER}
# หมวดที่ไม่มีราคาให้ดึงจาก yfinance (กองทุน/เงินสด บันทึกมูลค่าด้วยมือ)
_NON_PRICEABLE_CATEGORIES = {AssetCategory.FUND, AssetCategory.CASH}

_BKK_TZ = pytz.timezone('Asia/Bangkok')
_US_EASTERN_TZ = pytz.timezone('America/New_York')

# ระยะห่างขั้นต่ำก่อนจะแจ้งเตือน Watchlist entry ซ้ำ ตราบใดที่ราคายังแช่อยู่ในโซนเข้าซื้อเดิม (กันสแปมแต่ไม่ให้เงียบไปเลย)
_WATCHLIST_REALERT_COOLDOWN = timedelta(hours=5)


def _is_set_market_open(now_utc):
    """SET เปิดซื้อขาย จ-ศ 10:00-12:30 และ 14:30-16:30 เวลาไทย (ไม่รวมวันหยุดพิเศษ/นักขัตฤกษ์)"""
    now_bkk = now_utc.astimezone(_BKK_TZ)
    if now_bkk.weekday() >= 5:
        return False
    t = now_bkk.time()
    return (dtime(10, 0) <= t <= dtime(12, 30)) or (dtime(14, 30) <= t <= dtime(16, 30))


def _is_us_market_open(now_utc):
    """US (NYSE/Nasdaq) เปิดซื้อขาย จ-ศ 9:30-16:00 เวลา US Eastern (ปรับ DST ให้อัตโนมัติ, ไม่รวมวันหยุดพิเศษ)"""
    now_et = now_utc.astimezone(_US_EASTERN_TZ)
    if now_et.weekday() >= 5:
        return False
    t = now_et.time()
    return dtime(9, 30) <= t <= dtime(16, 0)


_MARKET_OPEN_CHECKS = {
    MarketType.SET: _is_set_market_open,
    MarketType.US: _is_us_market_open,
}


def is_market_open(market):
    """
    เช็คว่าตลาดของ market นี้อยู่ในเวลาซื้อขายหรือไม่
    ตลาดที่ไม่รู้จัก (Crypto/Forex ฯลฯ ซื้อขาย 24/7 หรือไม่มีเวลาตลาดตายตัว) ถือว่าเปิดเสมอ
    """
    checker = _MARKET_OPEN_CHECKS.get(market)
    if not checker:
        return True
    return checker(dj_timezone.now())


# ตอนตลาดเปิด บีบรอบเช็คให้สั้นสุด (วินาที) เพื่อให้ message ซื้อ/ขายมาไว — ไม่เกินค่านี้
_MARKET_HOURS_MIN_INTERVAL_SEC = 90


def effective_check_interval_seconds(config):
    """
    ช่วงเวลาเช็คแจ้งเตือน "จริง" (วินาที):
    - ตอนตลาด SET หรือ US เปิด → บีบให้ไม่เกิน 90 วินาที แม้ user จะตั้ง interval ไว้ยาว
      (ราคาขยับเร็ว มีผลต่อจังหวะซื้อ/ขาย ต้องเช็คถี่)
    - ตอนตลาดปิดทั้งคู่ → ใช้ค่าที่ user ตั้ง (ไม่ต้องเช็คถี่ ราคาไม่ขยับ)
    ใช้ร่วมกันทั้ง AJAX endpoint, context processor และ cron
    """
    base = max(int(getattr(config, 'check_interval_minutes', 15) or 15), 1) * 60
    now = dj_timezone.now()
    if _is_set_market_open(now) or _is_us_market_open(now):
        return min(base, _MARKET_HOURS_MIN_INTERVAL_SEC)
    return base


def _to_yf_symbol(symbol, market=None):
    """แปลง symbol เป็นรูปแบบที่ yfinance เข้าใจ (เติม .BK เฉพาะหุ้นไทย/ตลาด SET เท่านั้น)"""
    symbol = symbol.strip().upper()
    if symbol.endswith('=F') or '-' in symbol or symbol.endswith('.BK'):
        return symbol
    if market in _NON_SET_MARKETS:
        return symbol
    return f"{symbol}.BK"


def fetch_live_prices(symbol_market_pairs):
    """
    ดึงราคาปัจจุบันแบบ batch
    symbol_market_pairs: iterable ของ (symbol, market) — market ใช้ตัดสินว่าต้องเติม .BK หรือไม่
    คืนค่าเป็น {original_symbol: price}
    """
    pairs = list(dict.fromkeys(symbol_market_pairs))  # unique, คงลำดับ
    if not pairs:
        return {}

    yf_symbols = [_to_yf_symbol(sym, mkt) for sym, mkt in pairs]
    # yf_sym -> original_sym (กรณีชนกันเอาตัวหลัง ไม่เป็นไร ราคาเดียวกัน)
    sym_map = {ys: orig for (orig, _m), ys in zip(pairs, yf_symbols)}
    live_prices = {}

    # ── หลัก: ยิง batch เดียวด้วย yf.download 1m — เร็วกว่า t.info ทีละตัวมาก ──
    try:
        df = yf.download(yf_symbols, period="1d", interval="1m",
                         progress=False, group_by="ticker", threads=True)
        if df is not None and not df.empty:
            if len(yf_symbols) == 1:
                ys = yf_symbols[0]
                _close = df["Close"].dropna() if "Close" in df.columns else df.get(ys, df).get("Close")
                if _close is not None and len(_close):
                    live_prices[sym_map[ys]] = float(_close.iloc[-1])
            else:
                for ys in yf_symbols:
                    try:
                        _close = df[ys]["Close"].dropna()
                        if len(_close):
                            live_prices[sym_map[ys]] = float(_close.iloc[-1])
                    except Exception:
                        continue
    except Exception:
        pass

    # ── fallback: ตัวที่ batch ไม่ได้ราคา ให้ลอง fast_info ทีละตัว ──
    missing = [(sym_map[ys], ys) for ys in yf_symbols if sym_map[ys] not in live_prices]
    for original_sym, ys in missing:
        try:
            p = yf.Ticker(ys).fast_info.last_price
            if p:
                live_prices[original_sym] = float(p)
        except Exception:
            continue

    return live_prices


def _latest_scan(symbol, market=None):
    clean_symbol = symbol.replace('.BK', '')
    qs = PrecisionScanCandidate.objects.filter(symbol=clean_symbol)
    if market:
        qs = qs.filter(market=market)
    return qs.order_by('-scan_run').first()


def _is_turtle_strategy(strategy):
    return bool(strategy) and 'turtle' in strategy.lower()


def _poc_note(latest_scan):
    """
    ข้อความเสริมราคา/สถานะ Volume Profile POC (Point of Control) ต่อท้ายข้อความ Alert
    คืนค่าว่างถ้าไม่มีข้อมูล (เช่น fallback signal ที่คำนวณสดไม่มี field นี้)
    """
    poc_price = getattr(latest_scan, 'vp_poc_price', None)
    if not poc_price:
        return ""
    vp_status = getattr(latest_scan, 'vp_status', None)
    status_txt = f" ({vp_status})" if vp_status else ""
    return f" | POC {poc_price:.2f}{status_txt}"


# กลยุทธ์ถือระยะยาวเพื่อรอปันผล/มูลค่า — เวลาแตะ TP ให้ทยอยขายทีละน้อยกว่ากลยุทธ์โมเมนตัม เพื่อรักษาสถานะไว้กินปันผล/รอมูลค่าต่อ
_LONG_HOLD_STRATEGIES = ('dividend', 'value')

# สัดส่วนที่แนะนำให้ขายเมื่อแตะ TP ครั้งแรก (Let Profit Run) แยกตามกลยุทธ์
_TP_PARTIAL_SELL_PCT_LONG_HOLD = 0.25   # กลยุทธ์ถือยาว (Dividend/Value) — ขายออกแค่บางส่วนน้อยๆ รักษาสถานะหลักไว้
_TP_PARTIAL_SELL_PCT_DEFAULT = 0.50     # กลยุทธ์อื่นๆ (Precision/SEPA/Cup&Handle ฯลฯ) — ขายครึ่งนึงล็อกกำไร ที่เหลือปล่อยวิ่ง


def _recommended_sell_qty(quantity, market, pct=1.0):
    """
    คำนวณจำนวนหุ้นที่แนะนำให้ขาย จากสัดส่วนที่กำหนด (pct) ปัดให้เข้า board lot จริง
    - หุ้นไทย (SET): ปัดเข้า 100 หุ้น/lot (ขั้นต่ำ 100 หุ้นถ้ายังมีเหลือให้ขาย)
    - ตลาดอื่น (US ฯลฯ): ปัดเป็นจำนวนเต็มหุ้น (ขั้นต่ำ 1 หุ้นถ้ายังมีเหลือให้ขาย)
    """
    raw = float(quantity) * pct
    if raw <= 0:
        return 0
    if market == MarketType.SET:
        qty = round(raw / 100) * 100
        return int(qty) if qty > 0 else 100
    qty = round(raw)
    return int(qty) if qty > 0 else 1


def _tp_partial_sell_pct(strategy):
    strategy_lower = (strategy or '').lower()
    if any(s in strategy_lower for s in _LONG_HOLD_STRATEGIES):
        return _TP_PARTIAL_SELL_PCT_LONG_HOLD
    return _TP_PARTIAL_SELL_PCT_DEFAULT


def _passes_inzone_gate(scan):
    """
    เกณฑ์เพิ่มเติมสำหรับ "ย่อในโซนซื้อ" ให้ตรงกับ In-Zone v2 ในหน้าสแกน
    (_compute_signals buy_score ไม่บังคับพวกนี้ — RS เป็นแค่ weight, ไม่มี extended/RSI ceiling)
      RS ≥ 70 · ไม่ extended · RSI ≤ 68 · CMF ≥ 0.05
      + ยืนยันแรงซื้ออย่างน้อย 1 (CMF ≥ 0.1 / Pocket Pivot / RVOL ≥ 1.2) — OR-confirm เดียวกับตาราง
    Wyckoff Spring / 52w breakout / Pocket Pivot ⭐ ข้ามเกณฑ์นี้ (คนละจังหวะ ไม่ใช่ pullback ทั่วไป)
    """
    if getattr(scan, 'wyckoff_spring', False) or getattr(scan, 'is_52w_breakout', False) \
            or getattr(scan, 'pp_at_ma50', False):
        return True
    rs = getattr(scan, 'rs_rating', 0) or 0
    rsi = getattr(scan, 'rsi', 0) or 0
    cmf = getattr(scan, 'cmf', None)
    cmf = 0.0 if cmf is None else cmf
    rvol = getattr(scan, 'rvol', 0) or 0
    pp = bool(getattr(scan, 'pocket_pivot', False))
    is_ext = bool(getattr(scan, 'is_extended', False))
    _confirm = (cmf >= 0.1 or pp or rvol >= 1.2)
    return rs >= 70 and not is_ext and rsi <= 68 and cmf >= 0.05 and _confirm


def _get_sepa_context(symbol, user, market=None):
    """
    เช็คว่าหุ้นตัวนี้ยังอยู่ใน SEPA results ล่าสุดหรือไม่
    ถ้าอยู่ คืนค่าข้อความแจ้ง เช่น " (SEPA: Stage 2 + VCP, RS 82)"
    ถ้าไม่อยู่ คืนค่าว่าง
    """
    try:
        from .models import USSepaCandidate
        # หาสแกนล่าสุด
        latest_sepa = USSepaCandidate.objects.filter(
            user=user, symbol=symbol
        ).order_by('-scan_run').first()
        if not latest_sepa:
            return ""
        # เช็คว่า scan run นี้ยังสด (ไม่เกิน 7 วัน)
        from django.utils import timezone as tz
        age = tz.now() - latest_sepa.scan_run
        if age.days > 7:
            return ""
        # สร้างข้อความ
        sig_parts = []
        if latest_sepa.stage2:
            sig_parts.append("Stage 2")
        if latest_sepa.vcp_setup:
            sig_parts.append("VCP")
        sig_str = " + ".join(sig_parts) if sig_parts else "SEPA"
        return f" (SEPA: {sig_str}, RS {latest_sepa.rs_rating})"
    except Exception:
        return ""


def _get_cup_handle_context(symbol, user):
    """
    เช็คว่าหุ้นตัวนี้ยังอยู่ใน Cup & Handle results ล่าสุดหรือไม่
    ถ้าอยู่ คืนค่าข้อความแจ้ง เช่น " (Cup & Handle: forming, target 45.50)"
    ถ้าไม่อยู่ คืนค่าว่าง
    """
    try:
        from .models import CupHandleCandidate
        # หาสแกนล่าสุด
        latest_ch = CupHandleCandidate.objects.filter(
            user=user, symbol=symbol
        ).order_by('-scan_run').first()
        if not latest_ch:
            return ""
        # เช็คว่า scan run นี้ยังสด (ไม่เกิน 7 วัน)
        from django.utils import timezone as tz
        age = tz.now() - latest_ch.scan_run
        if age.days > 7:
            return ""
        # สร้างข้อความ
        stage_label = getattr(latest_ch, 'stage', 'forming') or 'forming'
        return f" (Cup & Handle: {stage_label}, target {latest_ch.target_price:.2f})"
    except Exception:
        return ""


def _get_exit_advice(symbol, user, market=None):
    """
    สร้างข้อความแนะนำเมื่อต้องออก/ขาย โดยเช็คว่าหุ้นยังอยู่ใน SEPA หรือ Cup & Handle หรือไม่
    และให้ข้อแนะนำเพิ่มเติมตามสถานะ

    ตัวอย่าง output:
    - " ⚠️ ยังใน SEPA (Stage 2 + VCP) — ล็อกกำไรแต่ปล่อยวิ่งเพื่อรอตำแหน่งต่อไป"
    - " ⚠️ Cup & Handle ยังอยู่ห่าง target — ตรวจสอบการแตกตัวของ pattern เมื่อกลับลง"
    """
    sepa_txt = _get_sepa_context(symbol, user, market)
    ch_txt = _get_cup_handle_context(symbol, user)

    advice = ""
    if sepa_txt:
        advice += f"{sepa_txt} — ยังอยู่ใน SEPA setup ล็อกกำไรแต่ปล่อยวิ่งตามเทรนด์ "
    if ch_txt:
        advice += f"{ch_txt} — ตรวจสอบการแตกตัวของ pattern ก่อนตัดสินใจขายขาด"

    if not advice:
        # ถ้าไม่อยู่ใน SEPA หรือ Cup & Handle แล้ว ให้ข้อแนะนำให้ออกแบบชัดเจน
        advice = " (ไม่มี setup ทั้ง SEPA และ Cup & Handle — ออกอย่างแน่นอน)"

    return advice


def _is_safe_pocket_pivot_add(latest_scan, current_price):
    """
    ตรวจสอบว่า Pocket Pivot signal นี้ปลอดภัยจากการ "catch the falling knife" หรือไม่
    Return True ถ้าปลอดภัย, False ถ้าเป็นอันตราย

    Safety Gates:
    1. Stage 2 ต้องยังแข็งแรง (price > SMA150, SMA150 trending up)
    2. CMF ≥ 0.05 (Accumulation, ไม่ distribution)
    3. Retracement ≤ 30% (Healthy pullback, ไม่ deep correction)
    4. RSI ไม่ oversold (ไม่ < 25)
    5. ราคาไม่ตัดขาดจาก MA50 มากเกินไป (ไม่ > 8% ต่ำกว่า)
    """
    # Gate 1: Stage 2 ต้องยังมีอยู่
    stage2 = bool(getattr(latest_scan, 'stage2', False))
    if not stage2:
        return False  # ❌ Stage 2 broken = NOT safe

    # Gate 2: CMF ≥ 0.05 (Accumulation)
    cmf = getattr(latest_scan, 'cmf', None)
    cmf = 0.0 if cmf is None else float(cmf)
    if cmf < 0.05:
        return False  # ❌ Distribution or neutral = NOT safe

    # Gate 3: Retracement ≤ 30% (shallow pullback OK, deep correction NOT OK)
    supply_zone = getattr(latest_scan, 'supply_zone_start', None)
    if supply_zone and current_price and supply_zone > 0:
        retr_pct = ((float(supply_zone) - float(current_price)) / float(supply_zone)) * 100
        if retr_pct > 30:
            return False  # ❌ Deep retracement (>30%) = NOT safe

    # Gate 4: RSI ไม่ oversold (< 25 = too weak to bounce)
    rsi = getattr(latest_scan, 'rsi', 50) or 50
    if float(rsi) < 25:
        return False  # ❌ Oversold = NOT safe (need strength to bounce)

    # Gate 5: ราคาไม่ตัดขาด MA50 มากเกินไป
    ma50 = getattr(latest_scan, 'ma50', None)
    if ma50 and current_price:
        below_ma50_pct = ((float(ma50) - float(current_price)) / float(ma50)) * 100
        if below_ma50_pct > 8:
            return False  # ❌ Too far below MA50 = NOT safe

    return True  # ✅ All gates passed = SAFE to add


def evaluate_user_alerts(user, config):
    """
    เช็คเงื่อนไข Action (SL/TP/Breakout/Watchlist entry) ของ user คนเดียว
    ตามการตั้งค่าใน config (StockAlertConfig) แล้วบันทึกเป็น StockAlertEvent
    คืนค่าเป็น list ของ StockAlertEvent ที่เพิ่งสร้าง (เรียงใหม่ไปเก่า)
    """
    portfolios = [
        p for p in Portfolio.objects.filter(user=user)
        if p.category not in _NON_PRICEABLE_CATEGORIES and is_market_open(p.market)
    ]
    watchlists = list(Watchlist.objects.filter(user=user, is_active=True)) if config.alert_watchlist_entry else []

    # Watchlist ไม่มีฟิลด์ market แยก จึงส่ง market=None ให้ heuristic เดิมตัดสิน (เหมือน monitor_stocks.py)
    symbol_market_pairs = {(p.symbol, p.market) for p in portfolios} | {(w.symbol, None) for w in watchlists}
    live_prices = fetch_live_prices(symbol_market_pairs)

    # มูลค่าพอร์ตหุ้นไทย (SET) รวม — ใช้เป็นฐานคำนวณ "ซื้อเพิ่มกี่บาท" ในสัญญาณ Breakout (เสี่ยง 1% ของพอร์ตนี้ต่อการเพิ่มโพซิชันหนึ่งครั้ง)
    total_set_value = sum(
        float(pf.quantity) * float(live_prices.get(pf.symbol) or pf.entry_price or 0)
        for pf in portfolios if pf.market == MarketType.SET
    )

    new_events = []
    # เก็บหุ้น "อ่อนแอ" (หลุด SL รอบนี้) กับ "แข็งแกร่ง" (เกิด Breakout รอบนี้) ไว้เทียบกันท้ายฟังก์ชัน
    # สำหรับสัญญาณ "สับเปลี่ยนหุ้นในพอร์ต" — ใช้เงื่อนไขเดียวกับ SL/BREAKOUT alert ที่มีอยู่แล้วเป๊ะๆ ไม่คำนวณเพิ่ม
    weak_candidates = []
    strong_candidates = []

    # ====== ภาวะตลาดรวม (Market Timing) — แจ้งครั้งเดียวต่อตลาด ไม่ใช่ต่อหุ้น ======
    # กระทบทุก position ในตลาดนั้นพร้อมกัน: RED = ลดพอร์ต/ขยับ SL/งดซื้อใหม่; FTD = เริ่มกลับเข้าซื้อได้
    if config.alert_market_timing and portfolios:
        from stocks.market_timing import get_market_timing_status
        for _mk in {p.market for p in portfolios}:
            _mk_label = 'SET' if _mk == MarketType.SET else ('US' if _mk == MarketType.US else None)
            if _mk_label is None:
                continue
            try:
                _mt = get_market_timing_status(market=_mk_label)
            except Exception:
                continue
            _code = _mt.get('status_code', 'GREEN')
            _ftd_fresh = bool(_mt.get('ftd_detected') and _mt.get('days_since_ftd') is not None and _mt['days_since_ftd'] <= 3)
            _n_held = sum(1 for p in portfolios if p.market == _mk)
            _sub = None
            if _code == 'RED':
                _sub = ('RED', (
                    f"ตลาด {_mk_label} เข้าภาวะแจกของหนัก ({_mt.get('distribution_count', 0)} วันใน 25 วัน) — "
                    f"พอร์ตของคุณมี {_n_held} ตัวในตลาดนี้ ควรลดขนาดสถานะ ขยับ Stop Loss ขึ้นชิด "
                    f"และงดซื้อหุ้นใหม่จนกว่าจะมี Follow-Through Day ยืนยัน"
                ))
            elif _code == 'YELLOW':
                _sub = ('YELLOW', (
                    f"ตลาด {_mk_label} เริ่มมีแรงขายสถาบัน ({_mt.get('distribution_count', 0)} วันแจกของ) — "
                    f"พอร์ต {_n_held} ตัวในตลาดนี้ ให้ถือเฉพาะตัวที่แข็งแรงกว่าตลาด คุมความเสี่ยงสั้นลง ชะลอการซื้อเพิ่ม"
                ))
            elif _ftd_fresh:
                _sub = ('FTD', (
                    f"ตลาด {_mk_label} ยืนยัน Follow-Through Day แล้ว (เมื่อ {_mt['days_since_ftd']} วันก่อน) — "
                    f"เป็นสัญญาณตลาดกลับตัวขึ้น เริ่มทยอยกลับเข้าซื้อหุ้นผู้นำที่ผ่านเกณฑ์ Precision ได้"
                ))
            if _sub:
                _tag, _msg = _sub
                _k = f"stockalert_markettiming_{user.id}_{_mk_label}_{_tag}"
                if not cache.get(_k):
                    new_events.append(StockAlertEvent(
                        user=user, symbol=f"MKT:{_mk_label}", market=_mk,
                        alert_type=StockAlertEvent.AlertType.MARKET_TIMING,
                        strategy='', price=0.0, message=_msg,
                    ))
                    cache.set(_k, True, timeout=12 * 60 * 60)

    for p in portfolios:
        price = live_prices.get(p.symbol)
        if not price:
            continue

        strategy_label = p.strategy or ''

        if _is_turtle_strategy(strategy_label) and p.highest_price and p.atr:
            if config.alert_stop_loss:
                stop_level = float(p.highest_price) - p.trail_multiplier * p.atr
                if price <= stop_level:
                    sell_qty = _recommended_sell_qty(p.quantity, p.market, pct=1.0)
                    new_events.append(StockAlertEvent(
                        user=user, symbol=p.symbol, market=p.market, alert_type=StockAlertEvent.AlertType.STOP_LOSS,
                        strategy=strategy_label, price=price, reference_level=stop_level,
                        message=(
                            f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label}) หลุดแนวรับ Trailing Stop "
                            f"ที่ {stop_level:.2f} แล้ว (ราคาปัจจุบัน {price:.2f}) ควรพิจารณาคัตลอสทั้งหมด "
                            f"({sell_qty:,} หุ้น)" + _get_exit_advice(p.symbol, user, p.market)
                        ),
                    ))
                    weak_candidates.append({'symbol': p.symbol, 'market': p.market, 'reason': f'หลุด Trailing Stop ที่ {stop_level:.2f}'})
            continue

        latest_scan = _latest_scan(p.symbol, p.market)
        used_fallback = False
        if not latest_scan:
            # ไม่มีข้อมูลใน PrecisionScanCandidate เลย (เช่น ถูกกรองออกด้วย RS pre-filter ของ scanner
            # ตั้งแต่ต้น) — คำนวณสัญญาณพื้นฐานสดจากราคาตรงแทน ดีกว่าข้ามหุ้นตัวนี้ไปเงียบๆ ไม่แจ้งอะไรเลย
            from stocks.utils import compute_fallback_alert_signals
            latest_scan = compute_fallback_alert_signals(p.symbol, p.market)
            used_fallback = True
            if not latest_scan:
                continue

        entry_price = float(p.entry_price or 0)
        # ถือว่า "มีกำไรจริง" ถ้าราคาปัจจุบันสูงกว่าต้นทุนที่ถือ (ไม่ใช่แค่ถึงโซนเทคนิคของสแกนเนอร์)
        # ถ้าไม่มีต้นทุนบันทึกไว้ (entry_price=0) ให้แจ้งตามโซนเทคนิคไปก่อนเพราะเช็คจริงไม่ได้
        is_in_profit = entry_price <= 0 or price > entry_price
        tp_zone_hit = config.alert_take_profit and latest_scan.supply_zone_start and price >= latest_scan.supply_zone_start

        _n_before_chain1 = len(new_events)

        # ====== Let Profit Run: TP แรกล็อกกำไรบางส่วน แล้วเทรลราคาส่วนที่เหลือแทนการเทขายทั้งหมดทันที ======
        if p.tp1_hit:
            # อยู่ในโหมดเทรลอยู่แล้ว (ล็อกกำไรบางส่วนไปรอบก่อนหน้า) — อัปเดตจุดสูงสุดแล้วเช็คว่าหลุด trailing stop หรือยัง
            if price > float(p.highest_price or 0):
                p.highest_price = price
                p.save(update_fields=['highest_price'])
            trail_stop = simple_trailing_stop(p.highest_price, p.atr, p.trail_multiplier)
            if config.alert_take_profit and trail_stop and price <= trail_stop:
                pl_pct = ((price - entry_price) / entry_price * 100) if entry_price > 0 else None
                sell_qty = _recommended_sell_qty(p.quantity, p.market, pct=1.0)
                new_events.append(StockAlertEvent(
                    user=user, symbol=p.symbol, market=p.market, alert_type=StockAlertEvent.AlertType.TRAILING_EXIT,
                    strategy=strategy_label, price=price, reference_level=trail_stop,
                    message=(
                        f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) หลุด Trailing Stop ที่ "
                        f"{trail_stop:.2f} แล้ว (ราคาปัจจุบัน {price:.2f}"
                        + (f", กำไรสะสม {pl_pct:.1f}% จากต้นทุน {entry_price:.2f}" if pl_pct is not None else "")
                        + f") ควรพิจารณาขายส่วนที่เหลือทั้งหมด ({sell_qty:,} หุ้น){_poc_note(latest_scan)}"
                        + _get_exit_advice(p.symbol, user, p.market)
                    ),
                ))
                p.tp1_hit = False
                p.tp1_price = None
                p.save(update_fields=['tp1_hit', 'tp1_price'])
        elif tp_zone_hit and is_in_profit:
            pl_pct = ((price - entry_price) / entry_price * 100) if entry_price > 0 else None
            p.tp1_hit = True
            p.tp1_price = price
            update_fields = ['tp1_hit', 'tp1_price']
            if price > float(p.highest_price or 0):
                p.highest_price = price
                update_fields.append('highest_price')
            p.save(update_fields=update_fields)
            tp_pct = _tp_partial_sell_pct(strategy_label)
            sell_qty = _recommended_sell_qty(p.quantity, p.market, pct=tp_pct)
            from stocks.utils import compute_exit_action as _cea
            _tp_ea = _cea(latest_scan, current_price=price, entry_price=entry_price,
                          quantity=float(p.quantity or 0), market=p.market)
            new_events.append(StockAlertEvent(
                user=user, symbol=p.symbol, market=p.market, alert_type=StockAlertEvent.AlertType.TP_PARTIAL,
                strategy=strategy_label, price=price, reference_level=latest_scan.supply_zone_start,
                message=(
                    f"[{_tp_ea['action']}] {_tp_ea['action_detail']} "
                    f"— ล็อกกำไร {tp_pct*100:.0f}% ({sell_qty:,} หุ้น) · ระบบจะเทรลราคาส่วนที่เหลือให้อัตโนมัติ "
                    f"และแจ้งอีกครั้งถ้าหลุดแนวเทรล{_poc_note(latest_scan)}"
                ),
            ))
        # ราคาถึงโซนขายทำกำไรทางเทคนิคแล้ว แต่จริง ๆ ยังต่ำกว่าต้นทุนที่ถืออยู่ (ยังขาดทุนอยู่)
        # ไม่ส่งเป็น "ขายทำกำไร" เพราะจะทำให้เข้าใจผิดว่ามีกำไร — ข้ามไปเช็คเงื่อนไข SL ต่อแทน
        elif config.alert_stop_loss and latest_scan.stop_loss and price <= latest_scan.stop_loss:
            # ข้อความ = ตัวเดียวกับหน้า /portfolio/exit-plan/ (compute_exit_action) เพื่อให้สอดคล้องกัน
            from stocks.utils import compute_exit_action as _cea
            _sl_ea = _cea(latest_scan, current_price=price, entry_price=entry_price,
                          quantity=float(p.quantity or 0), market=p.market)
            sell_qty = _recommended_sell_qty(p.quantity, p.market, pct=1.0)
            fallback_note = " (⚠️ ประเมินจากราคาสด ไม่มีข้อมูล Precision Scan ของหุ้นนี้ — SL คำนวณแบบ ATR คร่าวๆ)" if used_fallback else ""
            new_events.append(StockAlertEvent(
                user=user, symbol=p.symbol, market=p.market, alert_type=StockAlertEvent.AlertType.STOP_LOSS,
                strategy=strategy_label, price=price, reference_level=latest_scan.stop_loss,
                message=(
                    f"[{_sl_ea['action']}] {_sl_ea['action_detail']} "
                    f"— ขายเต็มจำนวน ({sell_qty:,} หุ้น){fallback_note}{_poc_note(latest_scan)}"
                    + _get_exit_advice(p.symbol, user, p.market)
                ),
            ))
            weak_candidates.append({'symbol': p.symbol, 'market': p.market, 'reason': f"{_sl_ea['action']} ที่ {latest_scan.stop_loss:.2f}"})
        # ====== Distribution / Reversal Warning — เตือนล่วงหน้าก่อนราคาจะหลุด SL จริง ======
        # ใช้ _compute_signals() ตัวเดียวกับที่หน้า Portfolio ใช้แสดง badge "REVERSAL ⚠️"/"Stage 3/4 ❌"
        # แค่ยังไม่เคยถูกส่งเป็น alert มาก่อน — reversal_score >= 3/5 ถือว่าน่าเป็นห่วงพอจะเตือน
        elif config.alert_distribution_warning:
            from stocks.views.base import _compute_signals
            signals = _compute_signals(latest_scan, current_price=price)
            if signals['reversal_score'] >= 3:
                cache_key = f"stockalert_distwarn_{user.id}_{p.symbol}"
                if not cache.get(cache_key):
                    reasons_txt = ', '.join(signals['reversal_reasons'])
                    fallback_note = " (⚠️ ประเมินจากราคาสด ไม่มีข้อมูล Precision Scan ของหุ้นนี้)" if used_fallback else ""
                    new_events.append(StockAlertEvent(
                        user=user, symbol=p.symbol, market=p.market,
                        alert_type=StockAlertEvent.AlertType.DISTRIBUTION_WARNING,
                        strategy=strategy_label, price=price, reference_level=latest_scan.stop_loss,
                        message=(
                            f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) เริ่มมีสัญญาณกระจายขาย/กลับตัว "
                            f"({signals['reversal_score']}/8: {reasons_txt}) — {signals['stage_label']} "
                            f"ยังไม่ถึงจุดตัดขาดทุน แต่ควรจับตาใกล้ชิด พิจารณาลดสถานะล่วงหน้าถ้ายังไม่มั่นใจ{fallback_note}{_poc_note(latest_scan)}"
                        ),
                    ))
                    cache.set(cache_key, True, timeout=12 * 60 * 60)

        # ====== Exit Action — ข้อความเดียวกับหน้า /stocks/portfolio/exit-plan/ ======
        # ยิงเฉพาะเมื่อ chain ด้านบน (SL hit / TP / Distribution) ยังไม่ได้แจ้งอะไร และคำแนะนำเป็น danger/warning
        # กัน spam ด้วย cache-key ที่ผูกกับ "ชื่อ action" — เปลี่ยนสถานะเมื่อไหร่ค่อยแจ้งใหม่
        _chain1_fired = len(new_events) > _n_before_chain1
        if (not _chain1_fired
                and (config.alert_stop_loss or config.alert_take_profit
                     or getattr(config, 'alert_distribution_warning', False))):
            try:
                from stocks.utils import compute_exit_action
                _ea = compute_exit_action(
                    latest_scan, current_price=price,
                    entry_price=entry_price, quantity=float(p.quantity or 0),
                    market=p.market,
                )
                # ใกล้จุดตัดสินใจ → ดึง history สั้นๆ มาคำนวณ Turtle S1/S2 ให้ตรงกับหน้า
                if _ea['near_sl'] or _ea['tp_hit'] or _ea['action_style'] != 'success':
                    try:
                        _h = yf.Ticker(_to_yf_symbol(p.symbol, p.market)).history(period='1mo')
                        if _h is not None and not _h.empty:
                            _lows = _h['Low'].dropna()
                            _t1 = float(_lows.tail(10).min()) if len(_lows) >= 10 else 0.0
                            _t2 = float(_lows.tail(20).min()) if len(_lows) >= 20 else 0.0
                            _ea = compute_exit_action(
                                latest_scan, current_price=price,
                                entry_price=entry_price, quantity=float(p.quantity or 0),
                                turtle_s1=_t1, turtle_s2=_t2, market=p.market,
                            )
                    except Exception:
                        pass

                if _ea['action_style'] in ('danger', 'warning', 'warning-soft'):
                    _k = f"stockalert_exitaction_{user.id}_{p.symbol}_{_ea['action']}"
                    if not cache.get(_k):
                        new_events.append(StockAlertEvent(
                            user=user, symbol=p.symbol, market=p.market,
                            alert_type=StockAlertEvent.AlertType.EXIT_ACTION,
                            strategy=strategy_label, price=price,
                            reference_level=latest_scan.stop_loss,
                            message=f"[{_ea['action']}] {_ea['action_detail']}{_poc_note(latest_scan)}" + _get_exit_advice(p.symbol, user, p.market),
                        ))
                        cache.set(_k, True, timeout=12 * 60 * 60)
                        if _ea['action_style'] == 'danger':
                            weak_candidates.append({'symbol': p.symbol, 'market': p.market, 'reason': _ea['action']})
            except Exception:
                pass

        if config.alert_breakout_add and (latest_scan.is_52w_breakout or latest_scan.pocket_pivot or latest_scan.wyckoff_spring):
            # ── ระบุชนิด/ความแรงของสัญญาณให้ตรงกับ Precision scanner ──
            #   PK ⭐ (pp_at_ma50) = เด้งจาก SMA50 ในฐาน + CMF ≥ 0 → มั่นใจสูง (เทียบ badge PK★)
            #   PK ธรรมดา (pocket_pivot อย่างเดียว) = up-day + volume trigger → มั่นใจต่ำกว่า (เทียบ badge PK⚡)
            _pk_strict = bool(getattr(latest_scan, 'pp_at_ma50', False))
            _pk_plain  = bool(latest_scan.pocket_pivot) and not _pk_strict
            _is_ext    = bool(getattr(latest_scan, 'is_extended', False))   # ยืด > 25% จาก MA50 (Avoidance ของ scanner)
            if latest_scan.is_52w_breakout:
                _sig_label, _sig_reason = 'เบรค 52w High', 'เบรค 52w High'
            elif latest_scan.wyckoff_spring:
                _sig_label, _sig_reason = 'Wyckoff Spring 🌀', 'Wyckoff Spring'
            elif _pk_strict:
                _sig_label, _sig_reason = 'Pocket Pivot ⭐ (เด้งจาก MA50 ในฐาน)', 'Pocket Pivot ⭐'
            else:
                _sig_label, _sig_reason = 'Pocket Pivot', 'Pocket Pivot'

            # PK ธรรมดา + ราคายืด/ยังไม่ยืนยัน Stage 2 = ความมั่นใจต่ำ (เกณฑ์เดียวกับ badge PK⚡ / ตัวกรอง Safe ของ scanner)
            pk_weak_caveat = ""
            if _pk_plain and (_is_ext or not latest_scan.stage2):
                pk_weak_caveat = (
                    " ⚠️ เป็น Pocket Pivot แบบทั่วไป (ไม่ใช่ ⭐ เด้งจาก MA50 ในฐาน)"
                    + (" และราคายืดเกิน 25% จาก MA50 แล้ว" if _is_ext else " และยังไม่ยืนยัน Stage 2")
                    + " — เชื่อถือได้น้อยกว่า ควรเช็คฐาน/แนวรับก่อนซื้อเพิ่ม"
                )

            # เตือนแฝงถ้าหุ้นตัวเดียวกันมี Reversal Score สูงพร้อมกัน — Pocket Pivot ที่เกิดขณะเทรนด์กำลังอ่อนแอ
            # เชื่อถือได้น้อยกว่า Pocket Pivot ที่เกิดในเทรนด์ Stage 2 แข็งแรง (อาจเป็นแค่เด้งสั้นๆ ไม่ใช่กลับมาสะสมจริง)
            from stocks.views.base import _compute_signals
            _signals = _compute_signals(latest_scan, current_price=price)
            reversal_caveat = ""
            if _signals['reversal_score'] >= 3:
                reversal_caveat = (
                    f" ⚠️ ระวัง: หุ้นนี้มีสัญญาณกระจายขายร่วมด้วย ({_signals['reversal_score']}/8) — "
                    f"อาจเป็นการเด้งชั่วคราว ไม่ใช่สัญญาณกลับตัวจริง ควรรอดูยืนยันเพิ่มก่อนซื้อเพิ่ม"
                )

            # แนะนำจำนวนเงินซื้อเพิ่ม (SET เท่านั้น) แบบ ATR-based risk sizing:
            # เสี่ยง 1% ของมูลค่าพอร์ต SET รวม หารด้วยระยะห่างจากราคาปัจจุบันถึง Stop Loss = จำนวนหุ้นที่ซื้อเพิ่มได้
            add_amount_txt = ""
            if p.market == MarketType.SET and total_set_value > 0 and latest_scan.stop_loss and price > latest_scan.stop_loss:
                risk_per_share = price - latest_scan.stop_loss
                risk_budget = total_set_value * 0.01
                suggested_shares = risk_budget / risk_per_share
                suggested_amount = suggested_shares * price

                # เพดานกันถือหุ้นตัวเดียวกระจุกตัวเกินไป — ดูจาก "มูลค่าที่ถืออยู่แล้ว" ของหุ้นตัวนี้ ไม่ใช่แค่ยอดจะซื้อเพิ่มเฉยๆ
                # (ถ้าดูแค่ยอดซื้อเพิ่มอย่างเดียว คนที่ถืออยู่แล้วเยอะจะยิ่งซื้อเพิ่มได้จนเกินเพดานจริง)
                current_position_value = float(p.quantity) * price
                max_position_value = total_set_value * 0.15
                remaining_room = max_position_value - current_position_value

                if remaining_room <= 0:
                    add_amount_txt = " — แต่ถือหุ้นตัวนี้เต็มโควต้าแล้ว (เกิน 15% ของพอร์ต SET) ไม่แนะนำซื้อเพิ่ม"
                else:
                    capped = suggested_amount > remaining_room
                    if capped:
                        suggested_amount = remaining_room
                        suggested_shares = suggested_amount / price
                    cap_note = " (จำกัดตามโควต้าคงเหลือของหุ้นตัวนี้ ไม่ให้เกิน 15% ของพอร์ต)" if capped else ""
                    add_amount_txt = (
                        f" — แนะนำซื้อเพิ่มประมาณ {suggested_amount:,.0f} บาท (~{suggested_shares:,.0f} หุ้น, "
                        f"เสี่ยง 1% ของพอร์ต SET ที่ SL {latest_scan.stop_loss:.2f}{cap_note})"
                    )
            reasons_txt = ", ".join(_signals.get('buy_reasons', []))
            reasons_msg = f" (ปัจจัยหนุน: {reasons_txt})" if reasons_txt else ""

            # ── Safety Gate Check: Is this a SAFE add or FALLING KNIFE? ──
            # Before recommending "buy more" on Pocket Pivot, verify it's not catching a knife
            is_safe_add = _is_safe_pocket_pivot_add(latest_scan, price)
            knife_warning = ""
            if latest_scan.pocket_pivot and not is_safe_add:
                knife_warning = (
                    " ⚠️ KNIFE CHECK FAILED — หุ้นนี้มีสัญญาณเด้งแต่ยังต่ำอยู่ในหลายประเด็น: "
                )
                if not bool(getattr(latest_scan, 'stage2', False)):
                    knife_warning += "Stage 2 ทำลาย "
                if float(getattr(latest_scan, 'cmf', 0) or 0) < 0.05:
                    knife_warning += "CMF เชิงลบ "
                if float(getattr(latest_scan, 'rsi', 50) or 50) < 25:
                    knife_warning += "RSI oversold "
                knife_warning += "— ไม่แนะนำซื้อเพิ่มตอนนี้ รอให้มั่นใจก่อน"

            new_events.append(StockAlertEvent(
                user=user, symbol=p.symbol, market=p.market, alert_type=StockAlertEvent.AlertType.BREAKOUT,
                strategy=strategy_label, price=price, reference_level=latest_scan.demand_zone_start,
                message=(
                    f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) เกิดสัญญาณ "
                    f"{_sig_label} "
                    f"ที่ราคา {price:.2f} — "
                    + ("✅ ควรพิจารณาซื้อเพิ่ม" if is_safe_add else "⚠️ HOLD ก่อน") + f"{add_amount_txt}{knife_warning}{pk_weak_caveat}{reversal_caveat}{reasons_msg}{_poc_note(latest_scan)}"
                ),
            ))
            # นับเป็น "หุ้นเด่น" เฉพาะสัญญาณแรง — เบรค 52w High / Wyckoff Spring / PK ⭐ (pp_at_ma50)
            # PK ธรรมดาอย่างเดียวยังยิง alert เป็นข้อมูล แต่ไม่ดันขึ้นสรุป (ตรงกับ scanner ที่ให้ PK⚡ เป็นข้อมูล, PK★ เป็นคุณภาพ)
            if latest_scan.is_52w_breakout or latest_scan.wyckoff_spring or _pk_strict:
                strong_candidates.append({
                    'symbol': p.symbol, 'market': p.market,
                    'reason': _sig_reason,
                    'score': latest_scan.technical_score,
                })
        # ====== Buy Zone Add — เตือนสะสม/ซื้อเพิ่ม เมื่อหุ้นในพอร์ตย่อลงมาอยู่ในโซนได้เปรียบ (IN ZONE) ======
        elif config.alert_breakout_add and latest_scan.demand_zone_start and latest_scan.demand_zone_end and (latest_scan.demand_zone_end <= price <= latest_scan.demand_zone_start):
            from stocks.views.base import _compute_signals
            _sig = _compute_signals(latest_scan, current_price=price)
            if _sig['buy_score'] >= 75 and _sig['reversal_score'] < 3 and _passes_inzone_gate(latest_scan):
                cache_key = f"stockalert_buyzone_{user.id}_{p.symbol}"
                if not cache.get(cache_key):
                    add_amount_txt = ""
                    if p.market == MarketType.SET and total_set_value > 0 and latest_scan.stop_loss and price > latest_scan.stop_loss:
                        risk_per_share = price - latest_scan.stop_loss
                        risk_budget = total_set_value * 0.01
                        suggested_shares = risk_budget / risk_per_share
                        suggested_amount = suggested_shares * price

                        current_position_value = float(p.quantity) * price
                        max_position_value = total_set_value * 0.15
                        remaining_room = max_position_value - current_position_value

                        if remaining_room <= 0:
                            add_amount_txt = " — แต่ถือหุ้นตัวนี้เต็มโควต้าแล้ว (เกิน 15% ของพอร์ต SET)"
                        else:
                            capped = suggested_amount > remaining_room
                            if capped:
                                suggested_amount = remaining_room
                                suggested_shares = suggested_amount / price
                            cap_note = " (จำกัดตามโควต้า 15% ของพอร์ต)" if capped else ""
                            add_amount_txt = (
                                f" — แนะนำแบ่งไม้ซื้อเพิ่มประมาณ {suggested_amount:,.0f} บาท (~{suggested_shares:,.0f} หุ้น, "
                                f"เสี่ยง 1% ของพอร์ต SET ที่ SL {latest_scan.stop_loss:.2f}{cap_note})"
                            )

                    reasons_txt = ", ".join(_sig.get('buy_reasons', []))
                    reasons_msg = f" (ปัจจัยหนุน: {reasons_txt})" if reasons_txt else ""

                    new_events.append(StockAlertEvent(
                        user=user, symbol=p.symbol, market=p.market,
                        alert_type=StockAlertEvent.AlertType.WATCHLIST_ENTRY,
                        strategy=strategy_label, price=price, reference_level=latest_scan.demand_zone_start,
                        message=(
                            f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) ย่อลงมาอยู่ในโซนสะสม/ซื้อเพิ่มที่ได้เปรียบ "
                            f"{latest_scan.demand_zone_end:.2f} - {latest_scan.demand_zone_start:.2f} แล้ว "
                            f"(ราคาปัจจุบัน {price:.2f}, สัญญาณซื้อ {_sig['buy_score']}/100){add_amount_txt}{reasons_msg}{_poc_note(latest_scan)}"
                        ),
                    ))
                    cache.set(cache_key, True, timeout=12 * 60 * 60)
        # ====== Volume Dry-Up (VDU) — สัญญาณ "จับตาใกล้ชิด" ก่อน Pocket Pivot จะเกิดจริง ======
        # เช็คเป็น elif ต่อจาก Breakout/Pocket Pivot เพราะสองเงื่อนไขขัดกันเองในทางคณิตศาสตร์
        # (VDU=volume ต่ำ/เงียบ ณ ตอนนี้, Pocket Pivot=volume พุ่งสูง ณ ตอนนี้ ไม่เกิดพร้อมกันในวันเดียว)
        elif config.alert_vdu_watch and getattr(latest_scan, 'vdu_near_zone', False):
            cache_key = f"stockalert_vdu_{user.id}_{p.symbol}"
            if not cache.get(cache_key):
                new_events.append(StockAlertEvent(
                    user=user, symbol=p.symbol, market=p.market,
                    alert_type=StockAlertEvent.AlertType.VDU_WATCH,
                    strategy=strategy_label, price=price, reference_level=latest_scan.demand_zone_start,
                    message=(
                        f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) เข้าสู่ภาวะ Volume Dry-Up "
                        f"(แรงขายเริ่มหมด) ที่ราคา {price:.2f} — สัญญาณ Pocket Pivot อาจเกิดขึ้นได้ทุกเมื่อ "
                        f"จับตาใกล้ชิด (ยังไม่ใช่สัญญาณซื้อ){_poc_note(latest_scan)}"
                    ),
                ))
                cache.set(cache_key, True, timeout=24 * 60 * 60)

    # ====== แนะนำสับเปลี่ยนหุ้นในพอร์ต: ขายตัวที่หลุด SL รอบนี้ เพื่อนำเงินไปเพิ่มตัวที่เกิด Breakout รอบนี้ ======
    # แจ้งแค่คู่เดียว (อ่อนแอที่สุด x แข็งแกร่งที่สุดตาม technical_score) กัน spam ถ้ามีหลายคู่พร้อมกัน
    # และ mute ไว้ 24 ชม.ต่อคู่ กันแจ้งซ้ำถี่เกินไปเพราะเป็นการตัดสินใจระดับภาพรวมพอร์ต ไม่ใช่รายวินาที
    if config.alert_reallocate and weak_candidates and strong_candidates:
        weak = weak_candidates[0]
        strong = max(strong_candidates, key=lambda c: c['score'])
        if weak['symbol'] != strong['symbol']:
            cache_key = f"stockalert_reallocate_{user.id}_{weak['symbol']}_{strong['symbol']}"
            if not cache.get(cache_key):
                new_events.append(StockAlertEvent(
                    user=user, symbol=weak['symbol'], market=weak['market'],
                    alert_type=StockAlertEvent.AlertType.REALLOCATE,
                    strategy='', price=live_prices.get(weak['symbol']) or 0,
                    message=(
                        f"ภาพรวมพอร์ต: หุ้น {weak['symbol']} มีสัญญาณอ่อนแอ ({weak['reason']}) "
                        f"ขณะที่ {strong['symbol']} เกิดสัญญาณแข็งแกร่งกว่า ({strong['reason']}, คะแนน {strong['score']}) "
                        f"— พิจารณาขาย {weak['symbol']} เพื่อนำเงินไปเพิ่ม {strong['symbol']} แทน"
                    ),
                ))
                cache.set(cache_key, True, timeout=24 * 60 * 60)

    # ====== การหมุนกลุ่มอุตสาหกรรม (Sector Rotation) ======
    # จัดอันดับกลุ่มด้วย sector_strength_pct (% หุ้นในกลุ่มที่อยู่ Stage 2) แบบสัมพัทธ์
    # หุ้นในพอร์ตที่อยู่กลุ่มซึ่งอ่อนกว่าค่ากลาง และมีกลุ่มนำที่แข็งกว่า >= 15 จุด
    # → แนะนำลดน้ำหนักกลุ่มอ่อน แล้วมองหาตัวนำในกลุ่มที่แข็งแรงกว่า
    if config.alert_sector_rotation and portfolios:
        _held_by_market = {}
        for p in portfolios:
            _held_by_market.setdefault(p.market, set()).add(p.symbol)
        for _mk, _syms in _held_by_market.items():
            _latest_run = (PrecisionScanCandidate.objects
                           .filter(user=user, market=_mk).order_by('-scan_run')
                           .values_list('scan_run', flat=True).first())
            if not _latest_run:
                continue
            _rows = list(PrecisionScanCandidate.objects.filter(
                user=user, market=_mk, scan_run=_latest_run
            ).values('symbol', 'sector', 'sector_strength_pct'))
            if not _rows:
                continue
            # strength ต่อกลุ่ม (ค่าเดียวทั้งกลุ่ม — เอา max กันเผื่อมีความต่าง)
            _sector_strength = {}
            for r in _rows:
                sec = r['sector']
                if not sec or sec == 'Unknown':
                    continue
                _sector_strength[sec] = max(_sector_strength.get(sec, 0.0), r['sector_strength_pct'] or 0.0)
            if len(_sector_strength) < 3:
                continue
            _sorted_secs = sorted(_sector_strength.items(), key=lambda kv: kv[1], reverse=True)
            _vals = sorted(_sector_strength.values())
            _median = _vals[len(_vals) // 2]
            _top_names = [s for s, _v in _sorted_secs[:3]]
            _top_strength = _sorted_secs[0][1]
            _sector_of = {r['symbol']: r['sector'] for r in _rows}

            _weak_groups = {}
            for s in _syms:
                sec = _sector_of.get(s)
                if not sec or sec == 'Unknown' or sec in _top_names:
                    continue
                _sec_str = _sector_strength.get(sec, 0.0)
                if _sec_str < _median and (_top_strength - _sec_str) >= 15.0:
                    _weak_groups.setdefault(sec, []).append(s)

            for sec, held in _weak_groups.items():
                # sector อาจเป็นภาษาไทย/มีอักขระพิเศษ — hash ให้ cache key เป็น ASCII ล้วน
                _sec_hash = hashlib.md5(sec.encode('utf-8')).hexdigest()[:10]
                _k = f"stockalert_sectorrot_{user.id}_{_mk}_{_sec_hash}"
                if cache.get(_k):
                    continue
                _sec_str = _sector_strength.get(sec, 0.0)
                _lead_txt = ", ".join(f"{s} ({_sector_strength[s]:.0f}%)" for s in _top_names)
                new_events.append(StockAlertEvent(
                    user=user, symbol=held[0], market=_mk,
                    alert_type=StockAlertEvent.AlertType.SECTOR_ROTATION,
                    strategy='', price=live_prices.get(held[0]) or 0.0,
                    message=(
                        f"กลุ่ม \"{sec}\" ที่คุณถือหุ้นอยู่ ({', '.join(sorted(held))}) กำลังอ่อนแรงกว่าตลาด "
                        f"(หุ้น Stage 2 ในกลุ่มมีเพียง {_sec_str:.0f}% ต่ำกว่าค่ากลาง {_median:.0f}%) "
                        f"ขณะที่กลุ่มที่กำลังนำตลาดคือ {_lead_txt} — "
                        f"พิจารณาลดน้ำหนักกลุ่ม \"{sec}\" แล้วมองหาตัวนำในกลุ่มที่แข็งแรงกว่า"
                    ),
                ))
                cache.set(_k, True, timeout=24 * 60 * 60)

    if config.alert_watchlist_entry or config.alert_breakout_add:
        for w in watchlists:
            price = live_prices.get(w.symbol)
            if not price:
                continue
            latest_scan = _latest_scan(w.symbol)
            if not latest_scan:
                continue

            now = dj_timezone.now()

            # ── 1. ตรวจจับสัญญาณ Breakout วันนี้ (BUY NOW / Preset 7) สำหรับหุ้นใน Watchlist ──
            if config.alert_breakout_add:
                _is_ext = bool(getattr(latest_scan, 'is_extended', False))
                _rvol = float(getattr(latest_scan, 'rvol', 0) or 0)
                _st2 = bool(getattr(latest_scan, 'stage2', False))
                _b52 = bool(getattr(latest_scan, 'is_52w_breakout', False))
                _pk = bool(getattr(latest_scan, 'pocket_pivot', False))
                _wy = bool(getattr(latest_scan, 'wyckoff_spring', False))

                # สัญญาณ Breakout หรือ BUY NOW (Preset 7: Stage 2 + RVOL >= 1.5)
                is_breakout_signal = _b52 or _pk or _wy or (_st2 and _rvol >= 1.5)
                if is_breakout_signal and not _is_ext:
                    cache_key = f"stockalert_wl_breakout_{user.id}_{w.symbol}"
                    if not cache.get(cache_key):
                        if _b52:
                            sig_title = "เบรค 52w High 🔥"
                        elif _wy:
                            sig_title = "Wyckoff Spring 🌀"
                        elif _pk:
                            sig_title = "Pocket Pivot ⚡"
                        else:
                            sig_title = "Breakout วันนี้ (BUY NOW / Preset 7) 🔥"

                        new_events.append(StockAlertEvent(
                            user=user, symbol=w.symbol, market=latest_scan.market,
                            alert_type=StockAlertEvent.AlertType.BREAKOUT,
                            strategy='Watchlist Breakout', price=price, reference_level=getattr(latest_scan, 'demand_zone_start', None),
                            message=(
                                f"🔥 [BREAKOUT วันนี้] หุ้น {w.symbol} ใน Watchlist เกิดสัญญาณ {sig_title} "
                                f"ที่ราคา {price:.2f} (RVOL {_rvol:.1f}x) — สัญญาณเบรคแนวต้านพร้อมวอลุ่มระเบิด!{_poc_note(latest_scan)}"
                            ),
                        ))
                        cache.set(cache_key, True, timeout=12 * 60 * 60)

            # ── 2. ตรวจจับการย่อเข้าโซนซื้อ (Buy Zone Entry) สำหรับหุ้นใน Watchlist ──
            if config.alert_watchlist_entry and latest_scan.demand_zone_start:
                in_zone = price <= latest_scan.demand_zone_start and price >= latest_scan.demand_zone_end
                if in_zone:
                    from stocks.views.base import _compute_signals
                    _sig = _compute_signals(latest_scan, current_price=price)
                    is_qualified = _sig['buy_score'] >= 75 and _sig['reversal_score'] < 3 and _passes_inzone_gate(latest_scan)

                    due = w.last_alerted_at is None or (now - w.last_alerted_at) >= _WATCHLIST_REALERT_COOLDOWN
                    if due and is_qualified:
                        reasons_txt = ", ".join(_sig.get('buy_reasons', []))
                        reasons_msg = f" (ปัจจัยหนุน: {reasons_txt})" if reasons_txt else ""

                        new_events.append(StockAlertEvent(
                            user=user, symbol=w.symbol, market=latest_scan.market, alert_type=StockAlertEvent.AlertType.WATCHLIST_ENTRY,
                            strategy='', price=price, reference_level=latest_scan.demand_zone_start,
                            message=(
                                f"หุ้น {w.symbol} ราคาย่อลงมาถึงโซนเข้าซื้อ "
                                f"{latest_scan.demand_zone_end:.2f} - {latest_scan.demand_zone_start:.2f} แล้ว "
                                f"(ราคาปัจจุบัน {price:.2f}, สัญญาณซื้อ {_sig['buy_score']}/100){reasons_msg}{_poc_note(latest_scan)}"
                            ),
                        ))
                        w.last_alerted_at = now
                        w.save(update_fields=['last_alerted_at'])
                elif w.last_alerted_at is not None:
                    w.last_alerted_at = None
                    w.save(update_fields=['last_alerted_at'])

    if new_events:
        StockAlertEvent.objects.bulk_create(new_events)

    return sorted(new_events, key=lambda e: e.symbol)
