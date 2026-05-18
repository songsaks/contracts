import os
import sys
import django

# Set up Django environment
sys.path.append(r"d:\DjangoProjects\contracts")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import pandas as pd
import yfinance as yf
import pandas_ta as ta
from django.utils import timezone
from stocks.models import ScannableSymbol, PrecisionScanCandidate
from stocks.utils import analyze_momentum_technical_v2

def check_tli():
    print("=== Checking TLI in Database ===")
    tli_symbol = ScannableSymbol.objects.filter(symbol="TLI").first()
    if not tli_symbol:
        print("❌ TLI is NOT in ScannableSymbol table!")
        similar = ScannableSymbol.objects.filter(symbol__icontains="TLI")
        print(f"Similar symbols in DB: {[s.symbol for s in similar]}")
        return
    
    print(f"✅ TLI found! is_active: {tli_symbol.is_active}, market: {tli_symbol.market}, market_cap: {tli_symbol.market_cap}")
    
    # Check PrecisionScanCandidate for TLI
    candidates = PrecisionScanCandidate.objects.filter(symbol="TLI").order_by('-scan_run')
    print(f"\n=== PrecisionScanCandidate Entries for TLI: {candidates.count()} ===")
    for c in candidates[:5]:
        print(f"Run: {c.scan_run}, Price: {c.price}, TS: {c.technical_score}, RS: {c.rs_rating}, Stage2: {c.stage2}, ADX: {c.adx}")

    # Check if TLI is in the top ranked symbols list
    from stocks.utils import get_top_ranked_symbols
    top_syms = get_top_ranked_symbols(market='SET', limit=400, auto_refresh=False)
    if "TLI" in top_syms:
        print(f"\n✅ TLI is in the Top 400 Ranked Symbols (Index position: {top_syms.index('TLI')})")
    else:
        print("\n❌ TLI is NOT in the Top 400 Ranked Symbols!")
        return

    # Let's fetch history for all top 400 symbols to calculate RS Rating exactly like the background task
    print("\n=== Calculating Comparative RS Ratings ===")
    from datetime import datetime as dt, timedelta as td
    _now = dt.now()
    scan_end_date  = _now.date() + td(days=1)
    scan_end_str   = scan_end_date.strftime('%Y-%m-%d')
    scan_start_str = (_now.date() - td(days=600)).strftime('%Y-%m-%d')
    
    from yahooquery import Ticker as _TQ
    rs_returns_today = {}
    rs_returns_prev = {}
    chunk_size = 80
    
    # Calculate RS ratings for today (May 18) and 3 days ago (May 13)
    for i in range(0, len(top_syms), chunk_size):
        chunk = top_syms[i : i + chunk_size]
        chunk_bk = [f"{s}.BK" for s in chunk]
        try:
            tq = _TQ(chunk_bk)
            tq_hist = tq.history(start=scan_start_str, end=scan_end_str, interval="1d")
            if tq_hist is not None and not tq_hist.empty:
                if isinstance(tq_hist.index, pd.MultiIndex):
                    for symbol in chunk:
                        try:
                            s_bk = f"{symbol}.BK"
                            if s_bk in tq_hist.index.get_level_values(0):
                                _close = tq_hist.loc[s_bk]['adjclose'].dropna()
                                if len(_close) >= 70:
                                    # Today's close vs 66 trading days ago
                                    ret_today = float((_close.iloc[-1] - _close.iloc[-66]) / abs(_close.iloc[-66]) * 100)
                                    rs_returns_today[symbol] = ret_today
                                    
                                    # 3 trading days ago close vs 66 trading days before that
                                    ret_prev = float((_close.iloc[-4] - _close.iloc[-69]) / abs(_close.iloc[-69]) * 100)
                                    rs_returns_prev[symbol] = ret_prev
                        except Exception: continue
        except Exception as e:
            print(f"Error calculating RS for chunk starting at {i}: {e}")

    # Calculate RS ratings TODAY
    rs_ratings_today_map = {}
    if rs_returns_today:
        _rs_ser_today = pd.Series(rs_returns_today)
        rs_ratings_today_map = (_rs_ser_today.rank(pct=True) * 99).clip(0, 99).astype(int).to_dict()
    
    tli_rs_today = rs_ratings_today_map.get("TLI")
    tli_ret_today = rs_returns_today.get("TLI")
    print(f"\n👉 TODAY (May 18): TLI 66-day (3M) return is {tli_ret_today:.2f}%, RS Rating is {tli_rs_today}")
    if tli_rs_today is not None and tli_rs_today >= 60:
        print("✅ TLI passes Phase 1 screen (RS >= 60)")
    else:
        print("❌ TLI fails Phase 1 screen (RS < 60)")

    # Calculate RS ratings 3 DAYS AGO
    rs_ratings_prev_map = {}
    if rs_returns_prev:
        _rs_ser_prev = pd.Series(rs_returns_prev)
        rs_ratings_prev_map = (_rs_ser_prev.rank(pct=True) * 99).clip(0, 99).astype(int).to_dict()
    
    tli_rs_prev = rs_ratings_prev_map.get("TLI")
    tli_ret_prev = rs_returns_prev.get("TLI")
    print(f"\n👉 3 DAYS AGO (May 13, before surge): TLI 66-day return was {tli_ret_prev:.2f}%, RS Rating was {tli_rs_prev}")
    if tli_rs_prev is not None and tli_rs_prev >= 60:
        print("✅ TLI passed Phase 1 screen 3 days ago")
    else:
        print("❌ TLI failed Phase 1 screen 3 days ago (RS < 60)")

if __name__ == "__main__":
    check_tli()
