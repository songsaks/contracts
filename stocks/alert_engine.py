# ====== alert_engine.py — คำนวณแจ้งเตือน Action ของหุ้นในพอร์ต/Watchlist ======
# ใช้ร่วมกันระหว่าง endpoint เช็คแจ้งเตือนในหน้าเว็บ (stocks/views/alerts.py)
# แยกจาก management command monitor_stocks.py (ที่ยิง Telegram) เพื่อไม่ให้กระทบของเดิม

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
    live_prices = {}
    try:
        tickers = yf.Tickers(" ".join(yf_symbols))
        for (original_sym, _mkt), yf_sym in zip(pairs, yf_symbols):
            try:
                t = tickers.tickers[yf_sym]
                price = t.info.get('currentPrice') or t.fast_info.last_price
                if price:
                    live_prices[original_sym] = float(price)
            except Exception:
                continue
    except Exception:
        pass
    return live_prices


def _latest_scan(symbol, market=None):
    clean_symbol = symbol.replace('.BK', '')
    qs = PrecisionScanCandidate.objects.filter(symbol=clean_symbol)
    if market:
        qs = qs.filter(market=market)
    return qs.order_by('-scan_run').first()


def _is_turtle_strategy(strategy):
    return bool(strategy) and 'turtle' in strategy.lower()


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
                            f"({sell_qty:,} หุ้น)"
                        ),
                    ))
                    weak_candidates.append({'symbol': p.symbol, 'market': p.market, 'reason': f'หลุด Trailing Stop ที่ {stop_level:.2f}'})
            continue

        latest_scan = _latest_scan(p.symbol, p.market)
        if not latest_scan:
            continue

        entry_price = float(p.entry_price or 0)
        # ถือว่า "มีกำไรจริง" ถ้าราคาปัจจุบันสูงกว่าต้นทุนที่ถือ (ไม่ใช่แค่ถึงโซนเทคนิคของสแกนเนอร์)
        # ถ้าไม่มีต้นทุนบันทึกไว้ (entry_price=0) ให้แจ้งตามโซนเทคนิคไปก่อนเพราะเช็คจริงไม่ได้
        is_in_profit = entry_price <= 0 or price > entry_price
        tp_zone_hit = config.alert_take_profit and latest_scan.supply_zone_start and price >= latest_scan.supply_zone_start

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
                        + f") ควรพิจารณาขายส่วนที่เหลือทั้งหมด ({sell_qty:,} หุ้น)"
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
            new_events.append(StockAlertEvent(
                user=user, symbol=p.symbol, market=p.market, alert_type=StockAlertEvent.AlertType.TP_PARTIAL,
                strategy=strategy_label, price=price, reference_level=latest_scan.supply_zone_start,
                message=(
                    f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) ถึงเป้าหมายกำไรแรกที่ "
                    f"{latest_scan.supply_zone_start:.2f} แล้ว (ราคาปัจจุบัน {price:.2f}"
                    + (f", กำไร {pl_pct:.1f}% จากต้นทุน {entry_price:.2f}" if pl_pct is not None else "")
                    + f") — แนะนำล็อกกำไร {tp_pct*100:.0f}% ({sell_qty:,} หุ้น) ส่วนที่เหลือปล่อยให้วิ่งต่อ "
                    + "(Let Profit Run) ระบบจะเริ่มเทรลราคาให้อัตโนมัติ และแจ้งอีกครั้งถ้าหลุดแนวเทรล"
                ),
            ))
        # ราคาถึงโซนขายทำกำไรทางเทคนิคแล้ว แต่จริง ๆ ยังต่ำกว่าต้นทุนที่ถืออยู่ (ยังขาดทุนอยู่)
        # ไม่ส่งเป็น "ขายทำกำไร" เพราะจะทำให้เข้าใจผิดว่ามีกำไร — ข้ามไปเช็คเงื่อนไข SL ต่อแทน
        elif config.alert_stop_loss and latest_scan.stop_loss and price <= latest_scan.stop_loss:
            sell_qty = _recommended_sell_qty(p.quantity, p.market, pct=1.0)
            new_events.append(StockAlertEvent(
                user=user, symbol=p.symbol, market=p.market, alert_type=StockAlertEvent.AlertType.STOP_LOSS,
                strategy=strategy_label, price=price, reference_level=latest_scan.stop_loss,
                message=(
                    f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) หลุดจุดตัดขาดทุน (SL) ที่ "
                    f"{latest_scan.stop_loss:.2f} แล้ว (ราคาปัจจุบัน {price:.2f}) ควรพิจารณาคัตลอสทั้งหมด "
                    f"({sell_qty:,} หุ้น)"
                ),
            ))
            weak_candidates.append({'symbol': p.symbol, 'market': p.market, 'reason': f'หลุดจุดตัดขาดทุน (SL) ที่ {latest_scan.stop_loss:.2f}'})
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
                    new_events.append(StockAlertEvent(
                        user=user, symbol=p.symbol, market=p.market,
                        alert_type=StockAlertEvent.AlertType.DISTRIBUTION_WARNING,
                        strategy=strategy_label, price=price, reference_level=latest_scan.stop_loss,
                        message=(
                            f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) เริ่มมีสัญญาณกระจายขาย/กลับตัว "
                            f"({signals['reversal_score']}/5: {reasons_txt}) — {signals['stage_label']} "
                            f"ยังไม่ถึงจุดตัดขาดทุน แต่ควรจับตาใกล้ชิด พิจารณาลดสถานะล่วงหน้าถ้ายังไม่มั่นใจ"
                        ),
                    ))
                    cache.set(cache_key, True, timeout=12 * 60 * 60)

        if config.alert_breakout_add and (latest_scan.is_52w_breakout or latest_scan.pocket_pivot):
            # เตือนแฝงถ้าหุ้นตัวเดียวกันมี Reversal Score สูงพร้อมกัน — Pocket Pivot ที่เกิดขณะเทรนด์กำลังอ่อนแอ
            # เชื่อถือได้น้อยกว่า Pocket Pivot ที่เกิดในเทรนด์ Stage 2 แข็งแรง (อาจเป็นแค่เด้งสั้นๆ ไม่ใช่กลับมาสะสมจริง)
            from stocks.views.base import _compute_signals
            _signals = _compute_signals(latest_scan, current_price=price)
            reversal_caveat = ""
            if _signals['reversal_score'] >= 3:
                reversal_caveat = (
                    f" ⚠️ ระวัง: หุ้นนี้มีสัญญาณกระจายขายร่วมด้วย ({_signals['reversal_score']}/5) — "
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
            new_events.append(StockAlertEvent(
                user=user, symbol=p.symbol, market=p.market, alert_type=StockAlertEvent.AlertType.BREAKOUT,
                strategy=strategy_label, price=price, reference_level=latest_scan.demand_zone_start,
                message=(
                    f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) เกิดสัญญาณ "
                    f"{'เบรค 52w High' if latest_scan.is_52w_breakout else 'Pocket Pivot'} "
                    f"ที่ราคา {price:.2f} — ควรพิจารณาซื้อเพิ่ม{add_amount_txt}{reversal_caveat}"
                ),
            ))
            strong_candidates.append({
                'symbol': p.symbol, 'market': p.market,
                'reason': 'เบรค 52w High' if latest_scan.is_52w_breakout else 'Pocket Pivot',
                'score': latest_scan.technical_score,
            })
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
                        f"จับตาใกล้ชิด (ยังไม่ใช่สัญญาณซื้อ)"
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

    for w in watchlists:
        price = live_prices.get(w.symbol)
        if not price:
            continue
        latest_scan = _latest_scan(w.symbol)
        if not latest_scan or not latest_scan.demand_zone_start:
            continue
        in_zone = price <= latest_scan.demand_zone_start and price >= latest_scan.demand_zone_end
        now = dj_timezone.now()
        if in_zone:
            # แจ้งครั้งแรกที่เข้าโซนทันที แล้วถ้ายังแช่อยู่ในโซนต่อ ให้เตือนซ้ำได้เป็นรอบ (ทุก _WATCHLIST_REALERT_COOLDOWN)
            # ไม่ใช่แจ้งทุกครั้งที่เช็ค (สแปม) แต่ก็ไม่เงียบไปตลอดจนลืมว่ายังมีโอกาสซื้ออยู่
            due = w.last_alerted_at is None or (now - w.last_alerted_at) >= _WATCHLIST_REALERT_COOLDOWN
            if due:
                new_events.append(StockAlertEvent(
                    user=user, symbol=w.symbol, market=latest_scan.market, alert_type=StockAlertEvent.AlertType.WATCHLIST_ENTRY,
                    strategy='', price=price, reference_level=latest_scan.demand_zone_start,
                    message=(
                        f"หุ้น {w.symbol} ราคาย่อลงมาถึงโซนเข้าซื้อ "
                        f"{latest_scan.demand_zone_end:.2f} - {latest_scan.demand_zone_start:.2f} แล้ว "
                        f"(ราคาปัจจุบัน {price:.2f})"
                    ),
                ))
                w.last_alerted_at = now
                w.save(update_fields=['last_alerted_at'])
        elif w.last_alerted_at is not None:
            # ราคาหลุดออกจากโซนแล้ว (วิ่งขึ้นเกินหรือหลุดลงต่ำกว่า) — รีเซ็ตให้แจ้งทันทีรอบหน้าที่กลับเข้าโซนใหม่
            w.last_alerted_at = None
            w.save(update_fields=['last_alerted_at'])

    if new_events:
        StockAlertEvent.objects.bulk_create(new_events)

    return sorted(new_events, key=lambda e: e.symbol)
