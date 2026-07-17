# ====== alert_engine.py — คำนวณแจ้งเตือน Action ของหุ้นในพอร์ต/Watchlist ======
# ใช้ร่วมกันระหว่าง endpoint เช็คแจ้งเตือนในหน้าเว็บ (stocks/views/alerts.py)
# แยกจาก management command monitor_stocks.py (ที่ยิง Telegram) เพื่อไม่ให้กระทบของเดิม

from datetime import time as dtime

import pytz
import yfinance as yf
from django.utils import timezone as dj_timezone

from .models import AssetCategory, MarketType, Portfolio, Watchlist, PrecisionScanCandidate, StockAlertEvent

# ตลาดที่ไม่ควรเติม .BK (หุ้น US, Crypto, Forex ฯลฯ ใช้ symbol ตามที่กรอกตรงๆ)
_NON_SET_MARKETS = {MarketType.US, MarketType.CRYPTO, MarketType.FUND, MarketType.CASH, MarketType.OTHER}
# หมวดที่ไม่มีราคาให้ดึงจาก yfinance (กองทุน/เงินสด บันทึกมูลค่าด้วยมือ)
_NON_PRICEABLE_CATEGORIES = {AssetCategory.FUND, AssetCategory.CASH}

_BKK_TZ = pytz.timezone('Asia/Bangkok')
_US_EASTERN_TZ = pytz.timezone('America/New_York')


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

    new_events = []

    for p in portfolios:
        price = live_prices.get(p.symbol)
        if not price:
            continue

        strategy_label = p.strategy or ''

        if _is_turtle_strategy(strategy_label) and p.highest_price and p.atr:
            if config.alert_stop_loss:
                stop_level = float(p.highest_price) - p.trail_multiplier * p.atr
                if price <= stop_level:
                    new_events.append(StockAlertEvent(
                        user=user, symbol=p.symbol, alert_type=StockAlertEvent.AlertType.STOP_LOSS,
                        strategy=strategy_label, price=price, reference_level=stop_level,
                        message=(
                            f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label}) หลุดแนวรับ Trailing Stop "
                            f"ที่ {stop_level:.2f} แล้ว (ราคาปัจจุบัน {price:.2f}) ควรพิจารณาคัตลอส"
                        ),
                    ))
            continue

        latest_scan = _latest_scan(p.symbol, p.market)
        if not latest_scan:
            continue

        if config.alert_take_profit and latest_scan.supply_zone_start and price >= latest_scan.supply_zone_start:
            new_events.append(StockAlertEvent(
                user=user, symbol=p.symbol, alert_type=StockAlertEvent.AlertType.TAKE_PROFIT,
                strategy=strategy_label, price=price, reference_level=latest_scan.supply_zone_start,
                message=(
                    f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) เข้าสู่โซนขายทำกำไรที่ "
                    f"{latest_scan.supply_zone_start:.2f} แล้ว (ราคาปัจจุบัน {price:.2f})"
                ),
            ))
        elif config.alert_stop_loss and latest_scan.stop_loss and price <= latest_scan.stop_loss:
            new_events.append(StockAlertEvent(
                user=user, symbol=p.symbol, alert_type=StockAlertEvent.AlertType.STOP_LOSS,
                strategy=strategy_label, price=price, reference_level=latest_scan.stop_loss,
                message=(
                    f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) หลุดจุดตัดขาดทุน (SL) ที่ "
                    f"{latest_scan.stop_loss:.2f} แล้ว (ราคาปัจจุบัน {price:.2f}) ควรพิจารณาคัตลอส"
                ),
            ))

        if config.alert_breakout_add and (latest_scan.is_52w_breakout or latest_scan.pocket_pivot):
            new_events.append(StockAlertEvent(
                user=user, symbol=p.symbol, alert_type=StockAlertEvent.AlertType.BREAKOUT,
                strategy=strategy_label, price=price, reference_level=latest_scan.demand_zone_start,
                message=(
                    f"หุ้น {p.symbol} (กลยุทธ์ {strategy_label or 'N/A'}) เกิดสัญญาณ "
                    f"{'เบรค 52w High' if latest_scan.is_52w_breakout else 'Pocket Pivot'} "
                    f"ที่ราคา {price:.2f} — ควรพิจารณาซื้อเพิ่ม"
                ),
            ))

    for w in watchlists:
        price = live_prices.get(w.symbol)
        if not price:
            continue
        latest_scan = _latest_scan(w.symbol)
        if not latest_scan or not latest_scan.demand_zone_start:
            continue
        if price <= latest_scan.demand_zone_start and price >= latest_scan.demand_zone_end:
            new_events.append(StockAlertEvent(
                user=user, symbol=w.symbol, alert_type=StockAlertEvent.AlertType.WATCHLIST_ENTRY,
                strategy='', price=price, reference_level=latest_scan.demand_zone_start,
                message=(
                    f"หุ้น {w.symbol} ราคาย่อลงมาถึงโซนเข้าซื้อ "
                    f"{latest_scan.demand_zone_end:.2f} - {latest_scan.demand_zone_start:.2f} แล้ว "
                    f"(ราคาปัจจุบัน {price:.2f})"
                ),
            ))

    if new_events:
        StockAlertEvent.objects.bulk_create(new_events)

    return sorted(new_events, key=lambda e: e.symbol)
