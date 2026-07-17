# ====== alert_engine.py — คำนวณแจ้งเตือน Action ของหุ้นในพอร์ต/Watchlist ======
# ใช้ร่วมกันระหว่าง endpoint เช็คแจ้งเตือนในหน้าเว็บ (stocks/views/alerts.py)
# แยกจาก management command monitor_stocks.py (ที่ยิง Telegram) เพื่อไม่ให้กระทบของเดิม

import yfinance as yf

from .models import Portfolio, Watchlist, PrecisionScanCandidate, StockAlertEvent


def _to_yf_symbol(symbol):
    """แปลง symbol เป็นรูปแบบที่ yfinance เข้าใจ (เติม .BK ให้หุ้นไทยถ้ายังไม่มี)"""
    if symbol.endswith('=F') or '-' in symbol or symbol.endswith('.BK'):
        return symbol
    return f"{symbol}.BK"


def fetch_live_prices(symbols):
    """ดึงราคาปัจจุบันแบบ batch สำหรับ symbol ที่ส่งเข้ามา คืนค่าเป็น {original_symbol: price}"""
    symbols = list(dict.fromkeys(symbols))  # unique, คงลำดับ
    if not symbols:
        return {}

    yf_symbols = [_to_yf_symbol(s) for s in symbols]
    live_prices = {}
    try:
        tickers = yf.Tickers(" ".join(yf_symbols))
        for original_sym, yf_sym in zip(symbols, yf_symbols):
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


def _latest_scan(symbol):
    clean_symbol = symbol.replace('.BK', '')
    return PrecisionScanCandidate.objects.filter(symbol=clean_symbol).order_by('-scan_run').first()


def _is_turtle_strategy(strategy):
    return bool(strategy) and 'turtle' in strategy.lower()


def evaluate_user_alerts(user, config):
    """
    เช็คเงื่อนไข Action (SL/TP/Breakout/Watchlist entry) ของ user คนเดียว
    ตามการตั้งค่าใน config (StockAlertConfig) แล้วบันทึกเป็น StockAlertEvent
    คืนค่าเป็น list ของ StockAlertEvent ที่เพิ่งสร้าง (เรียงใหม่ไปเก่า)
    """
    portfolios = list(Portfolio.objects.filter(user=user))
    watchlists = list(Watchlist.objects.filter(user=user, is_active=True)) if config.alert_watchlist_entry else []

    symbols = {p.symbol for p in portfolios} | {w.symbol for w in watchlists}
    live_prices = fetch_live_prices(symbols)

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

        latest_scan = _latest_scan(p.symbol)
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
