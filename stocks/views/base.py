# ====== views.py - View หลักของระบบวิเคราะห์หุ้น AI ======
# ทุก view ต้องผ่านการ login (@login_required)
# ใช้ yfinance, yahooquery ดึงข้อมูลตลาด และ Gemini AI วิเคราะห์

import json
import os
import subprocess
import traceback
from decimal import Decimal

import google.genai as genai
import pandas as pd
import pandas_ta as ta
import requests
import yfinance as yf
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from yahooquery import Ticker as YQTicker

from stocks.crew_analysis import MomentumCrew
from stocks.forms import AddPortfolioForm, AddWatchlistForm, SellStockForm
from stocks.models import (
    AnalysisCache,
    AssetCategory,
    InvestmentDashboardInsight,
    MarketType,
    MomentumCandidate,
    MultiFactorCandidate,
    Portfolio,
    PrecisionScanCandidate,
    ScannableSymbol,
    SoldStock,
    TitheRecord,
    ValueScanCandidate,
    Watchlist,
)
from stocks.utils import (
    _fetch_commodity_macro,
    _is_commodity,
    _score_commodity_signal,
    analyze_momentum_technical_v2,
    analyze_with_ai,
    calculate_trailing_stop,
    detect_price_pattern,
    detect_vcp_pattern,
    find_supply_demand_zones,
    find_supply_demand_zones_v2,
    get_stock_data,
    refresh_all_thai_symbols,
)

# Removed custom session for yfinance to let it handle curl_cffi internally

# ====== ฟังก์ชันตรวจสอบสิทธิ์ผู้ใช้ ======

def admin_only(user):
    # อนุญาตให้ผู้ใช้ทุกคนที่ login แล้วเข้าถึงข้อมูลของตัวเองได้
    return user.is_authenticated # Changed to allow any user to see their own data

# ====== _build_us_symbol_set - สร้าง set ของสัญลักษณ์หุ้น US สำหรับ user ======
def _build_us_symbol_set(user):
    """
    Return a set of stock symbols (uppercase, no .BK) that are US stocks for this user.
    Uses MomentumCandidate(market='US') as the source of truth.
    """
    from stocks.models import MomentumCandidate
    return set(
        MomentumCandidate.objects.filter(user=user, market='US')
        .values_list('symbol', flat=True)
    )


def _is_us_symbol(symbol, us_set):
    """True only if symbol is a known US stock. Thai stocks without .BK default to SET."""
    if '.BK' in symbol:
        return False
    return symbol.split('.')[0].upper() in us_set


# ====== _get_usd_thb - ดึงอัตราแลกเปลี่ยน USD/THB (cache 15 นาที) ======
def _get_usd_thb():
    """Return current USD/THB rate, cached 15 min. Fallback = 33.5."""
    from django.core.cache import cache
    rate = cache.get('usd_thb_rate')
    if rate:
        return float(rate)
    try:
        t = yf.Ticker('USDTHB=X')
        hist = t.history(period='2d')
        rate = float(hist['Close'].iloc[-1]) if not hist.empty else 0
        if not rate:
            rate = float(t.info.get('regularMarketPrice') or t.info.get('currentPrice') or 33.5)
    except Exception:
        rate = 33.5
    if rate < 25 or rate > 50:
        rate = 33.5
    cache.set('usd_thb_rate', rate, 900)
    return float(rate)


# ====== _compute_signals - คำนวณ BUY/SELL Score + Exit Signal จาก PrecisionScanCandidate ======
def _compute_signals(prec, current_price=None, is_turtle=False, turtle_stop=None):
    """Reusable scorer v3 - ใช้ใน Portfolio, Watchlist, และ Precision Scanner."""
    price  = float(current_price or getattr(prec, 'price', 0) or 0)
    dz_s   = getattr(prec, 'demand_zone_start', None)
    dz_e   = getattr(prec, 'demand_zone_end', None)
    prox   = getattr(prec, 'zone_proximity', 999)
    rvol_b = getattr(prec, 'rvol_bullish', True)
    rvol   = getattr(prec, 'rvol', 0)
    rr     = getattr(prec, 'risk_reward_ratio', 0) or 0
    adx    = getattr(prec, 'adx', 0)
    erc    = getattr(prec, 'erc_volume_confirmed', False)
    rsi    = getattr(prec, 'rsi', 0)
    pat    = getattr(prec, 'price_pattern_score', 0)
    rel3   = getattr(prec, 'rel_momentum_3m', 0.0)
    rel1   = getattr(prec, 'rel_momentum_1m', 0.0)
    sz_s   = getattr(prec, 'supply_zone_start', None)
    yr_h   = getattr(prec, 'year_high', 0)
    # v3 new fields (graceful fallback for old records)
    macd_hist  = getattr(prec, 'macd_histogram', None) or 0.0
    macd_cross = getattr(prec, 'macd_crossover', False)
    bb_sq      = getattr(prec, 'bb_squeeze', False)
    ema20_aln  = getattr(prec, 'ema20_aligned', False)
    rs_rat     = getattr(prec, 'rs_rating', 0)
    eps        = getattr(prec, 'eps_growth', 0)
    rev        = getattr(prec, 'rev_growth', 0)
    # v4 trend following fields
    ema20_rising = getattr(prec, 'ema20_rising', False)
    hh_hl        = getattr(prec, 'hh_hl_structure', False)
    ema20_slope  = getattr(prec, 'ema20_slope', 0.0)
    # v7 money flow & breakout
    cmf          = getattr(prec, 'cmf', None)
    is_52w_bo    = getattr(prec, 'is_52w_breakout', False)
    stage2       = getattr(prec, 'stage2', False)

    # ── BUY SCORE ─────────────────────────────────────────────────────
    # base technical: technical_score คือผลลัพธ์จาก tech analyzer (max 100)
    # เราลดน้ำหนักลงเหลือ 0.25 (max 25 pts) เพื่อเปิดทางให้ signals อื่นๆ
    buy = int(getattr(prec, 'technical_score', 0) * 0.25) 

    # Zone proximity (max 25)
    in_zone = dz_s and dz_e and price <= dz_s and price >= dz_e
    if in_zone:         buy += 25
    elif prox <= 10:    buy += 15
    elif prox <= 30:    buy += 8
    elif prox <= 60:    buy += 3

    # RVOL direction-aware (max 22)
    if rvol_b and rvol >= 2.0:   buy += 22
    elif rvol_b and rvol >= 1.5: buy += 17
    elif rvol_b and rvol >= 1.0: buy += 12
    elif rvol_b and rvol >= 0.7: buy += 4

    # R/R ratio (max 15)
    if rr >= 3:     buy += 15
    elif rr >= 2:   buy += 10
    elif rr >= 1.5: buy += 5

    # ADX (max 8) - ปรับ threshold ให้เหมาะกับ SET (liquidity ต่ำกว่า US → ADX มักอยู่ 15-25)
    if adx >= 25:   buy += 8
    elif adx >= 20: buy += 5
    elif adx >= 15: buy += 2

    # ERC confirmed (max 5)
    if erc: buy += 5

    # RSI - v3: optimal zone ขยับเป็น 65-80 (max 8)
    if 65 <= rsi <= 80:  buy += 8
    elif 55 <= rsi < 65: buy += 4
    elif rsi > 80:       buy += 2   # overbought แต่ trend ยังแรง

    # Price pattern (max +10 / min -10)
    buy += pat

    # Relative momentum (max +12 / min -8)
    rel = rel3 if rel3 != 0.0 else rel1
    if rel >= 15:   buy += 12
    elif rel >= 8:  buy += 9
    elif rel >= 3:  buy += 6
    elif rel >= 0:  buy += 3
    elif rel >= -5: buy += 0
    else:           buy -= 8

    # ── v3 new signals ────────────────────────────────────────────────
    # MACD bullish crossover (max 12)
    if macd_cross:          buy += 12
    elif macd_hist > 0:     buy += 8   # histogram positive (buying pressure building)

    # Bollinger Band Squeeze - pending breakout (max 6)
    if bb_sq: buy += 6

    # EMA20 > EMA50 > EMA200 full 3-layer alignment (max 5)
    if ema20_aln: buy += 5

    # ── v3 Relative Strength Rating (0-99 percentile) ───────────────────
    if rs_rat >= 85:   buy += 15
    elif rs_rat >= 70: buy += 8
    elif rs_rat >= 50: buy += 3

    # ── v4 Trend Following quality (max 10 pts) ───────────────────────
    # EMA20 rising = momentum มีโครงสร้างรองรับ ไม่ใช่แค่ spike สั้น
    if ema20_rising and hh_hl:  buy += 10  # ทั้ง EMA rising + HH/HL = trend สมบูรณ์
    elif ema20_rising:           buy += 5   # EMA rising เพียงอย่างเดียว
    elif hh_hl:                  buy += 4   # HH/HL โดยที่ EMA ยังไม่ขึ้นชัด

    # ── v7 CMF buy bonus (max 6 pts) ─────────────────────────────────
    if cmf is not None:
        if cmf >= 0.1:    buy += 6   # สถาบันสะสมชัดเจน
        elif cmf >= 0.05: buy += 3   # มีแรงซื้อสุทธิ

    # ── v8 SET-specific signals ───────────────────────────────────────
    # 52-week breakout (max 15) - signal สำคัญมากใน SET (Minervini/O'Neil)
    if is_52w_bo: buy += 15

    # Stage 2 Weinstein: price > SMA150 AND SMA150 rising (max 8)
    if stage2: buy += 8

    buy_score = max(0, min(100, buy))

    # ── SELL SCORE ────────────────────────────────────────────────────
    sell = 0
    if is_turtle:
        # Turtles only exit on 10D/20D Low (turtle_stop)
        if turtle_stop and price <= turtle_stop:
            sell = 100
        else:
            sell = 0
    else:
        if sz_s and price >= sz_s:              sell += 45
        # ยกเลิกเงื่อนไขขายเมื่อใกล้วน 52w High เพราะเบรกเอาต์คือสัญญาณโมเมนตัมที่ดี
        if rsi > 78:    sell += 20
        elif rsi > 72:  sell += 12
        elif rsi > 68:  sell += 5
        # Volume bearish penalty - ผ่อนลงสำหรับ SET เพราะหลายวัน volume เป็น neutral ไม่ใช่ bearish จริง
        if not rvol_b and rvol >= 2.0:  sell += 18   # volume สูงมากและเป็น bearish = แรงขายจริง
        elif not rvol_b and rvol >= 1.5: sell += 10  # volume สูงปานกลางและ bearish
        # rvol_b = False แต่ volume ปกติ → ไม่ penalty
        if rel1 < -5:   sell += 12
        elif rel1 < 0:  sell += 6
        if pat < -5:    sell += 10
        elif pat < 0:   sell += 5
        if adx < 15:    sell += 8
        elif adx < 20:  sell += 4
        # v3: MACD bearish (histogram negative + no crossover)
        if not macd_cross and macd_hist < 0 and abs(macd_hist) > 0.01:
            sell += 8
        # v7: CMF distribution - เงินไหลออกสุทธิ
        if cmf is not None:
            if cmf < -0.1:    sell += 10  # Distribution ชัดเจน
            elif cmf < -0.05: sell += 5   # เริ่มมีแรงขายสุทธิ
    sell_score = min(100, sell)

    if sell_score >= 70:   exit_signal = 'STRONG EXIT'
    elif sell_score >= 50: exit_signal = 'EXIT'
    elif sell_score >= 30: exit_signal = 'WATCH'
    else:                  exit_signal = ''

    # ── REVERSAL SCORE (0-5): ตรวจจับการเปลี่ยนแปลงจากขาขึ้น → Distribution/ขาลง ──
    # แต่ละเงื่อนไขให้ 1 คะแนน รวม 5 คะแนน (≥3 = REVERSAL ALERT)
    rev_pts = 0
    rev_reasons = []

    # 1. Stage ไม่ใช่ Stage 2 (Weinstein Stage 3/4)
    if not stage2:
        rev_pts += 1
        rev_reasons.append('Stage ≠ 2')

    # 2. EMA20 หักลง (Trend สั้นเริ่มพัง)
    if not ema20_rising:
        rev_pts += 1
        rev_reasons.append('EMA20 ↓')

    # 3. MACD Histogram ติดลบ (Momentum กลับทิศ)
    if macd_hist < 0 and not macd_cross:
        rev_pts += 1
        rev_reasons.append('MACD ↓')

    # 4. CMF ติดลบ (Institutional Distribution)
    if cmf is not None and cmf < -0.05:
        rev_pts += 1
        rev_reasons.append('CMF ↓')

    # 5. RSI ร่วงใต้ 50 + ไม่มี HH/HL structure
    if rsi < 50 and not hh_hl:
        rev_pts += 1
        rev_reasons.append('RSI<50 + LL')

    # ── Stage Label ──
    if stage2 and ema20_rising and hh_hl:
        stage_label = 'Stage 2 ✅'
        stage_color = 'success'
    elif stage2 and (not ema20_rising or not hh_hl):
        stage_label = 'Stage 2⚠️'
        stage_color = 'warning'
    elif not stage2 and rev_pts >= 3:
        stage_label = 'Stage 3/4 ❌'
        stage_color = 'danger'
    elif not stage2:
        stage_label = 'Stage 1/3'
        stage_color = 'secondary'
    else:
        stage_label = 'Unknown'
        stage_color = 'secondary'

    # ── Reversal Alert ──
    if rev_pts >= 4:
        reversal_alert = 'DISTRIBUTION 🔴'
        reversal_color = 'danger'
    elif rev_pts == 3:
        reversal_alert = 'REVERSAL ⚠️'
        reversal_color = 'warning'
    elif rev_pts == 2:
        reversal_alert = 'CAUTION 🟡'
        reversal_color = 'warning'
    else:
        reversal_alert = ''
        reversal_color = 'success'

    return {
        'buy_score':      buy_score,
        'sell_score':     sell_score,
        'exit_signal':    exit_signal,
        'reversal_score': rev_pts,
        'reversal_alert': reversal_alert,
        'reversal_color': reversal_color,
        'reversal_reasons': rev_reasons,
        'stage_label':    stage_label,
        'stage_color':    stage_color,
    }


# ====== Dashboard - หน้าแสดง Watchlist พร้อมราคาและ RSI แบบ Real-time ======

def _get_market_condition(set_df):
    """
    วิเคราะห์ SET Index เพื่อกำหนด Market Phase ปัจจุบัน
    คืน dict: phase, label, color, score, indicators
    """
    import pandas as pd
    if set_df is None or set_df.empty:
        return {'phase': 'UNKNOWN', 'label': 'ไม่มีข้อมูล SET', 'color': 'secondary', 'score': 0}

    close = set_df['Close'].dropna()
    if len(close) < 50:
        return {'phase': 'UNKNOWN', 'label': 'ข้อมูลไม่พอ', 'color': 'secondary', 'score': 0}

    curr = float(close.iloc[-1])
    ema50  = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(close) >= 200 else None
    sma150 = float(close.rolling(150).mean().iloc[-1]) if len(close) >= 150 else None

    # SMA150 slope เทียบ 20 วันที่แล้ว
    sma150_slope = None
    if sma150 and len(close) >= 170:
        sma150_20d = float(close.rolling(150).mean().iloc[-21])
        sma150_slope = ((sma150 - sma150_20d) / sma150_20d * 100) if sma150_20d else None

    # 1m / 3m return ของ SET
    m1 = float((close.iloc[-1] - close.iloc[-22]) / close.iloc[-22] * 100) if len(close) >= 22 else 0.0
    m3 = float((close.iloc[-1] - close.iloc[-66]) / close.iloc[-66] * 100) if len(close) >= 66 else 0.0

    score = 0
    bullets = []  # เงื่อนไขที่ผ่าน

    # EMA200
    if ema200:
        if curr > ema200:
            score += 3
            bullets.append(f"SET ({curr:.0f}) > EMA200 ({ema200:.0f}) ✅")
        else:
            score -= 3
            bullets.append(f"SET ({curr:.0f}) < EMA200 ({ema200:.0f}) ❌")

    # SMA150
    if sma150:
        if curr > sma150:
            score += 2
            bullets.append(f"SET > SMA150 ({sma150:.0f}) ✅")
        else:
            score -= 1
            bullets.append(f"SET < SMA150 ({sma150:.0f}) ❌")

    # SMA150 slope
    if sma150_slope is not None:
        if sma150_slope > 0.2:
            score += 2
            bullets.append(f"SMA150 ขาขึ้น (+{sma150_slope:.2f}%) ✅")
        elif sma150_slope < -0.3:
            score -= 2
            bullets.append(f"SMA150 ขาลง ({sma150_slope:.2f}%) ❌")
        else:
            bullets.append(f"SMA150 sideways ({sma150_slope:.2f}%) ⚠️")

    # EMA50
    if curr > ema50:
        score += 1

    # Momentum 1m
    if m1 > 3:
        score += 2
        bullets.append(f"SET +{m1:.1f}% (1 เดือน) ✅")
    elif m1 > 0:
        score += 1
    elif m1 < -5:
        score -= 2
        bullets.append(f"SET {m1:.1f}% (1 เดือน) ❌")
    else:
        bullets.append(f"SET {m1:.1f}% (1 เดือน) ⚠️")

    # กำหนด Phase
    if score >= 7:
        phase, color, label = 'UPTREND',    'success', 'ตลาดขาขึ้น - เหมาะสำหรับ Swing Buy'
    elif score >= 4:
        phase, color, label = 'RECOVERY',   'info',    'ตลาดฟื้นตัว - คัดเฉพาะหุ้นแข็งแกร่ง'
    elif score >= 1:
        phase, color, label = 'MIXED',      'warning', 'ตลาดผสม - เน้น Watchlist และ Risk Management'
    elif score >= -2:
        phase, color, label = 'CORRECTION', 'warning', 'ตลาดพักฐาน - ระวังสูง ลดขนาด Position'
    else:
        phase, color, label = 'DOWNTREND',  'danger',  'ตลาดขาลง - หลีกเลี่ยงการซื้อใหม่'

    return {
        'phase':  phase,
        'color':  color,
        'label':  label,
        'score':  score,
        'curr':   round(curr, 2),
        'ema200': round(ema200, 2) if ema200 else None,
        'sma150': round(sma150, 2) if sma150 else None,
        'sma150_slope': round(sma150_slope, 2) if sma150_slope is not None else None,
        'm1':     round(m1, 2),
        'm3':     round(m3, 2),
        'above_ema200':   bool(ema200 and curr > ema200),
        'above_sma150':   bool(sma150 and curr > sma150),
        'sma150_rising':  bool(sma150_slope and sma150_slope > 0.2),
        'bullets': bullets,
    }


# ====== Scan Watchlist Views ======

def _get_precision_scan_data(user, market='SET'):
    """Helper to build the scan_data JSON from the latest database records."""
    from stocks.models import PrecisionScanCandidate
    latest_run = PrecisionScanCandidate.objects.filter(user=user, market=market).order_by('-scan_run').values_list('scan_run', flat=True).first()
    
    if not latest_run:
        return None

    candidates = list(PrecisionScanCandidate.objects.filter(user=user, market=market, scan_run=latest_run))

    # คำนวณ buy_score ด้วย _compute_signals ตัวเดียวกับหน้า Scanner เพื่อให้ตัวเลขในรายงานตรงกัน
    for c in candidates:
        c.buy_score = _compute_signals(c)['buy_score']

    # Fully Qualified (Technical Score >= 65)
    qualified = [c for c in candidates if c.technical_score >= 65]
    top_buy = sorted(candidates, key=lambda x: x.buy_score, reverse=True)[:5]
    
    # Sector analysis
    from collections import Counter
    sectors = Counter([c.sector for c in qualified if c.sector])
    top_sectors = [{"name": k, "count": v} for k, v in sectors.most_common(5)]
    
    def _to_dict(c):
        return {
            "symbol": c.symbol,
            "price": float(c.price),
            "buy_score": c.buy_score,
            "rs_rating": c.rs_rating or 0,
            "rsi": float(c.rsi or 0),
            "adx": float(c.adx or 0),
            "rvol": float(c.rvol or 0),
            "rvol_bullish": c.rvol_bullish,
            "risk_reward_ratio": float(c.risk_reward_ratio or 0),
            "zone_proximity": float(c.zone_proximity or 0),
            "sector": c.sector,
            "macd_crossover": c.macd_crossover,
            "ema20_rising": c.ema20_rising,
            "hh_hl_structure": c.hh_hl_structure,
            "bb_squeeze": c.bb_squeeze,
            "ema20_aligned": c.ema20_aligned,
            "is_new_entry": c.is_new_entry,
        }

    return {
        "qualified_stocks": [_to_dict(c) for c in qualified],
        "top_buy_stocks": [_to_dict(c) for c in top_buy],
        "scan_date": latest_run.strftime('%Y-%m-%d %H:%M'),
        "total_passed": candidates.count(),
        "top_sectors": top_sectors
    }

# Shared US symbol universe - ~220 symbols (Nasdaq + S&P 500 leaders)
_US_SECTOR_MAP = {
    # Technology
    "AAPL":"Technology","MSFT":"Technology","NVDA":"Technology","GOOGL":"Technology",
    "GOOG":"Technology","AMZN":"Technology","META":"Technology","TSLA":"Technology",
    "AVGO":"Technology","ORCL":"Technology","AMD":"Technology","ARM":"Technology",
    "DELL":"Technology","HPE":"Technology","WDC":"Technology","TSM":"Technology",
    "QCOM":"Technology","INTC":"Technology","MU":"Technology","AMAT":"Technology",
    "LRCX":"Technology","KLAC":"Technology","MRVL":"Technology","ON":"Technology",
    "TXN":"Technology","SMCI":"Technology","ASML":"Technology","NXPI":"Technology",
    "MPWR":"Technology","WOLF":"Technology","CRM":"Technology","NOW":"Technology",
    "SNOW":"Technology","PLTR":"Technology","PANW":"Technology","CRWD":"Technology",
    "ZS":"Technology","NET":"Technology","DDOG":"Technology","MDB":"Technology",
    "ADBE":"Technology","INTU":"Technology","ANSS":"Technology","CDNS":"Technology",
    "SNPS":"Technology","FTNT":"Technology","OKTA":"Technology","HUBS":"Technology",
    "TWLO":"Technology","TTD":"Technology","BILL":"Technology","GTLB":"Technology",
    "DOCN":"Technology","ZM":"Technology",
    # Financial Services
    "JPM":"Financial Services","BAC":"Financial Services","WFC":"Financial Services",
    "GS":"Financial Services","MS":"Financial Services","BLK":"Financial Services",
    "SCHW":"Financial Services","AXP":"Financial Services","V":"Financial Services",
    "MA":"Financial Services","COF":"Financial Services","DFS":"Financial Services",
    "SYF":"Financial Services","USB":"Financial Services","TFC":"Financial Services",
    "KEY":"Financial Services","RF":"Financial Services","FITB":"Financial Services",
    "COIN":"Financial Services","SQ":"Financial Services","PYPL":"Financial Services",
    # Insurance
    "CB":"Financial Services","PGR":"Financial Services","ALL":"Financial Services",
    "TRV":"Financial Services","MET":"Financial Services","PRU":"Financial Services",
    # Healthcare
    "UNH":"Healthcare","LLY":"Healthcare","JNJ":"Healthcare","ABBV":"Healthcare",
    "MRK":"Healthcare","PFE":"Healthcare","ABT":"Healthcare","TMO":"Healthcare",
    "AMGN":"Healthcare","ISRG":"Healthcare","DXCM":"Healthcare","IDXX":"Healthcare",
    "ILMN":"Healthcare","MRNA":"Healthcare","REGN":"Healthcare","VRTX":"Healthcare",
    "BIIB":"Healthcare","GILD":"Healthcare","BMY":"Healthcare","CVS":"Healthcare",
    "CI":"Healthcare","HUM":"Healthcare","MDT":"Healthcare","SYK":"Healthcare",
    "BSX":"Healthcare","EW":"Healthcare",
    # Consumer Staples
    "COST":"Consumer Staples","WMT":"Consumer Staples","TGT":"Consumer Staples",
    "KR":"Consumer Staples","PG":"Consumer Staples","KO":"Consumer Staples",
    "PEP":"Consumer Staples","CL":"Consumer Staples","MDLZ":"Consumer Staples","MO":"Consumer Staples",
    # Consumer Discretionary
    "HD":"Consumer Discretionary","LOW":"Consumer Discretionary","NKE":"Consumer Discretionary",
    "LULU":"Consumer Discretionary","DECK":"Consumer Discretionary","ONON":"Consumer Discretionary",
    "RH":"Consumer Discretionary","SBUX":"Consumer Discretionary","MCD":"Consumer Discretionary",
    "YUM":"Consumer Discretionary","CMG":"Consumer Discretionary","DPZ":"Consumer Discretionary",
    "NFLX":"Consumer Discretionary","ABNB":"Consumer Discretionary","UBER":"Consumer Discretionary",
    "DASH":"Consumer Discretionary","ETSY":"Consumer Discretionary","EBAY":"Consumer Discretionary",
    "BABA":"Consumer Discretionary","JD":"Consumer Discretionary","PDD":"Consumer Discretionary",
    "SPOT":"Consumer Discretionary","RBLX":"Consumer Discretionary",
    # Energy
    "XOM":"Energy","CVX":"Energy","COP":"Energy","EOG":"Energy","SLB":"Energy",
    "PSX":"Energy","MPC":"Energy","VLO":"Energy","OXY":"Energy","HAL":"Energy",
    "DVN":"Energy","FANG":"Energy","APA":"Energy","MRO":"Energy","WMB":"Energy","KMI":"Energy",
    # Industrials
    "CAT":"Industrials","DE":"Industrials","HON":"Industrials","GE":"Industrials",
    "RTX":"Industrials","LMT":"Industrials","BA":"Industrials","UPS":"Industrials",
    "FDX":"Industrials","CSX":"Industrials","ITW":"Industrials","EMR":"Industrials",
    "ETN":"Industrials","PH":"Industrials","ROK":"Industrials","AME":"Industrials",
    "TT":"Industrials","DHR":"Industrials","NOC":"Industrials","GD":"Industrials",
    # Real Estate
    "AMT":"Real Estate","PLD":"Real Estate","CCI":"Real Estate","EQIX":"Real Estate",
    "O":"Real Estate","WELL":"Real Estate","VICI":"Real Estate","PSA":"Real Estate",
    # Utilities
    "NEE":"Utilities","DUK":"Utilities","SO":"Utilities","AEP":"Utilities","EXC":"Utilities",
    # Communication
    "PINS":"Communication","SNAP":"Communication",
    # Conglomerate
    "BRK-B":"Conglomerate","MSTR":"Technology",
}

_US_MOMENTUM_SYMBOLS = [
    # ── Mega-cap Tech ──────────────────────────────────────────────────
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO", "ORCL",
    "AMD", "ARM", "DELL", "HPE", "WDC",
    # ── Semiconductor ──────────────────────────────────────────────────
    "TSM", "QCOM", "INTC", "MU", "AMAT", "LRCX", "KLAC", "MRVL", "ON", "TXN",
    "SMCI", "ASML", "NXPI", "MPWR", "WOLF",
    # ── Cloud / Software ───────────────────────────────────────────────
    "CRM", "NOW", "SNOW", "PLTR", "PANW", "CRWD", "ZS", "NET", "DDOG", "MDB",
    "ADBE", "INTU", "ANSS", "CDNS", "SNPS", "FTNT", "OKTA", "HUBS", "TWLO",
    "TTD", "BILL", "GTLB", "DOCN", "ZM",
    # ── Financials ─────────────────────────────────────────────────────
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "V", "MA",
    "COF", "DFS", "SYF", "USB", "TFC", "KEY", "RF", "FITB",
    "CB", "PGR", "ALL", "TRV", "MET", "PRU",
    # ── Healthcare / Biotech ───────────────────────────────────────────
    "UNH", "LLY", "JNJ", "ABBV", "MRK", "PFE", "ABT", "TMO", "AMGN", "ISRG",
    "DXCM", "IDXX", "ILMN", "MRNA", "REGN", "VRTX", "BIIB", "GILD", "BMY",
    "CVS", "CI", "HUM", "MDT", "SYK", "BSX", "EW",
    # ── Consumer Staples ───────────────────────────────────────────────
    "COST", "WMT", "TGT", "KR", "PG", "KO", "PEP", "CL", "MDLZ", "MO",
    # ── Consumer Discretionary ─────────────────────────────────────────
    "HD", "LOW", "NKE", "LULU", "DECK", "ONON", "RH",
    "SBUX", "MCD", "YUM", "CMG", "DPZ",
    "NFLX", "ABNB", "UBER", "DASH", "ETSY", "EBAY",
    "BABA", "JD", "PDD",
    # ── Energy ─────────────────────────────────────────────────────────
    "XOM", "CVX", "COP", "EOG", "SLB", "PSX", "MPC", "VLO", "OXY", "HAL",
    "DVN", "FANG", "APA", "MRO", "WMB", "KMI",
    # ── Industrials / Aerospace ────────────────────────────────────────
    "CAT", "DE", "HON", "GE", "RTX", "LMT", "BA", "UPS", "FDX", "CSX",
    "ITW", "EMR", "ETN", "PH", "ROK", "AME", "TT", "DHR", "NOC", "GD",
    # ── FinTech / Payments / Crypto ────────────────────────────────────
    "SPOT", "RBLX", "COIN", "SQ", "PYPL", "MSTR",
    # ── REIT / Utilities ───────────────────────────────────────────────
    "AMT", "PLD", "CCI", "EQIX", "O", "WELL", "VICI", "PSA",
    "NEE", "DUK", "SO", "AEP", "EXC",
    # ── Conglomerate / Other ───────────────────────────────────────────
    "BRK-B", "PINS", "SNAP",
    # ── Benchmarks (RS calc only - filtered from results) ──────────────
    "SPY", "QQQ", "IWM",
]

def _seed_us_symbols():
    """Seed curated US stock universe (~300 symbols, Nasdaq & S&P 500 + Mid-cap Growth) into ScannableSymbol."""
    US_SYMBOLS = [
        # ── Mega-cap Tech ──────────────────────────────────────────────
        "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO", "ORCL",
        "AMD", "ARM", "DELL", "HPE", "WDC",
        # ── Semiconductor ──────────────────────────────────────────────
        "TSM", "QCOM", "INTC", "MU", "AMAT", "LRCX", "KLAC", "MRVL", "ON", "TXN",
        "SMCI", "ASML", "NXPI", "MPWR", "WOLF",
        "COHR", "ACLS", "AEHR", "CAMT", "ONTO", "AMBA", "SWKS", "SITM",
        # ── Cloud / Software ──────────────────────────────────────────
        "CRM", "NOW", "SNOW", "PLTR", "PANW", "CRWD", "ZS", "NET", "DDOG", "MDB",
        "ADBE", "INTU", "ANSS", "CDNS", "SNPS", "FTNT", "OKTA", "HUBS", "TWLO",
        "TTD", "BILL", "GTLB", "DOCN", "ZM",
        "APP", "AXON", "DUOL", "SMAR", "BRZE", "ASAN", "MNDY", "WEX", "PCTY",
        "CWAN", "TOST", "S", "ESTC", "CFLT",
        # ── AI / Data ─────────────────────────────────────────────────
        "AI", "PATH", "SOUN", "BBAI", "IONQ", "QUBT",
        # ── Financials ────────────────────────────────────────────────
        "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "V", "MA",
        "COF", "DFS", "SYF", "USB", "TFC", "KEY", "RF", "FITB",
        "CB", "PGR", "ALL", "TRV", "MET", "PRU",
        "HOOD", "SFM", "FI", "GPN", "AFRM",
        # ── Healthcare / Biotech ──────────────────────────────────────
        "UNH", "LLY", "JNJ", "ABBV", "MRK", "PFE", "ABT", "TMO", "AMGN", "ISRG",
        "DXCM", "IDXX", "ILMN", "MRNA", "REGN", "VRTX", "BIIB", "GILD", "BMY",
        "CVS", "CI", "HUM", "MDT", "SYK", "BSX", "EW",
        "RXRX", "EXAS", "ARWR", "ROIV", "INVA", "RVMD", "KRYS",
        # ── Consumer Staples ──────────────────────────────────────────
        "COST", "WMT", "TGT", "KR", "PG", "KO", "PEP", "CL", "MDLZ", "MO",
        "CELH", "VITL",
        # ── Consumer Discretionary / Restaurants / Leisure ────────────
        "HD", "LOW", "NKE", "LULU", "DECK", "ONON", "RH",
        "SBUX", "MCD", "YUM", "CMG", "DPZ",
        "NFLX", "ABNB", "UBER", "DASH", "LYFT", "ETSY", "EBAY",
        "BABA", "JD", "PDD",
        "WING", "CAVA", "BROS", "ELF", "GSHD", "MODG",
        # ── Energy ────────────────────────────────────────────────────
        "XOM", "CVX", "COP", "EOG", "SLB", "PSX", "MPC", "VLO", "OXY", "HAL",
        "DVN", "FANG", "APA", "MRO", "WMB", "KMI",
        "DINO", "TRGP",
        # ── Industrials / Aerospace / Defense ─────────────────────────
        "CAT", "DE", "HON", "GE", "RTX", "LMT", "BA", "UPS", "FDX", "CSX",
        "ITW", "EMR", "ETN", "PH", "ROK", "AME", "TT", "DHR", "NOC", "GD",
        "ACHR", "JOBY", "SPCE", "RDW",
        # ── FinTech / Payments / Crypto ───────────────────────────────
        "SPOT", "RBLX", "COIN", "SQ", "PYPL", "MSTR",
        "CORZ", "RIOT", "MARA",
        # ── REIT / Utilities ──────────────────────────────────────────
        "AMT", "PLD", "CCI", "EQIX", "O", "WELL", "VICI", "PSA",
        "NEE", "DUK", "SO", "AEP", "EXC",
        # ── Education / Other Growth ──────────────────────────────────
        "LOPE", "PRDO", "STRA",
        # ── Conglomerate / Other ──────────────────────────────────────
        "BRK-B", "PINS", "SNAP",
        # ── Benchmarks ────────────────────────────────────────────────
        "SPY", "QQQ", "IWM",
    ]
    for sym in US_SYMBOLS:
        ScannableSymbol.objects.update_or_create(
            symbol=sym, market='US',
            defaults={'index_name': 'Nasdaq+S&P500', 'is_active': True},
        )
    return US_SYMBOLS


def _seed_value_symbols():
    """~200 US value-oriented stocks across all sectors."""
    return [
        # Financials
        'JPM','BAC','WFC','C','GS','MS','BRK-B','BLK','AXP','USB',
        'TFC','MET','PRU','AFL','CB','ALL','SCHW','COF','DFS','SYF',
        'PNC','HBAN','MTB','CFG','ZION',
        # Healthcare
        'JNJ','PFE','MRK','BMY','ABBV','AMGN','GILD','CVS','UNH',
        'MDT','ABT','SYK','BSX','BIIB','CI','HUM','ELV',
        # Energy
        'XOM','CVX','COP','EOG','SLB','HAL','WMB','KMI','DVN',
        'FANG','MRO','OXY','PSX','VLO','MPC',
        # Consumer Staples
        'KO','PEP','WMT','PG','CL','PM','MO','KMB','GIS','K',
        'CPB','SJM','MKC','HSY','CAG','ADM','BG',
        # Utilities
        'NEE','DUK','SO','D','SRE','AEP','EXC','ED','XEL',
        'WEC','ES','ETR','NI','CMS','AES',
        # Industrials
        'GE','HON','MMM','EMR','ETN','ROK','ITW','PH','GD',
        'LMT','RTX','NOC','UPS','FDX','CSX','NSC','UNP','CAT','DE',
        'CMI','PCAR','IR','AME','ROP',
        # Materials
        'LIN','APD','NEM','FCX','NUE','X','AA','MOS','CF','ALB',
        # Real Estate
        'AMT','PLD','O','VICI','CCI','DLR','EXR','WPC','SPG','PSA',
        # Tech (value-priced)
        'CSCO','IBM','INTC','HPQ','HPE','ORCL','QCOM','TXN',
        'AVGO','AMAT','KLAC','GOOGL','META','MSFT','CTSH','CDW',
        # Consumer Discretionary
        'TGT','KR','GM','F','LEN','PHM','DHI','NVR','TOL',
    ]


def _score_value_candidate(info, df):
    """
    Score a stock on value criteria. Returns (val_score, qual_score, price_score, total).
    """
    import pandas_ta as ta

    val_score = 0
    qual_score = 0
    price_score = 0

    # ── Extract fundamentals ──────────────────────────────
    pe  = info.get('trailingPE') or info.get('forwardPE')
    fpe = info.get('forwardPE')
    pb  = info.get('priceToBook')
    peg = info.get('pegRatio')
    ps  = info.get('priceToSalesTrailing12Months')
    div = (info.get('dividendYield') or 0) * 100          # fraction → %
    roe = (info.get('returnOnEquity') or 0) * 100          # fraction → %
    margin = (info.get('profitMargins') or 0) * 100        # fraction → %
    de_raw = info.get('debtToEquity')
    de  = (de_raw / 100) if de_raw is not None else None   # yf sends %, convert to ratio
    cr  = info.get('currentRatio')
    rev_g = (info.get('revenueGrowth') or 0) * 100
    mkt_cap = (info.get('marketCap') or 0) / 1e9           # → USD billions
    fcf_raw = info.get('freeCashflow') or 0
    fcf_yield = (fcf_raw / (info.get('marketCap') or 1)) * 100 if fcf_raw and mkt_cap > 0 else 0

    # ── Valuation Score (max 40) ──────────────────────────
    if pe and pe > 0:
        if pe < 10:    val_score += 15
        elif pe < 15:  val_score += 12
        elif pe < 20:  val_score += 8
        elif pe < 25:  val_score += 4

    if pb and pb > 0:
        if pb < 1:     val_score += 10
        elif pb < 1.5: val_score += 7
        elif pb < 2.5: val_score += 4

    if div > 0:
        if div >= 4:   val_score += 10
        elif div >= 3: val_score += 7
        elif div >= 2: val_score += 4
        elif div >= 1: val_score += 2

    if peg and peg > 0:
        if peg < 1:    val_score += 5
        elif peg < 1.5: val_score += 3

    # ── Quality Score (max 35) ────────────────────────────
    if roe > 0:
        if roe > 25:   qual_score += 15
        elif roe > 20: qual_score += 12
        elif roe > 15: qual_score += 8
        elif roe > 10: qual_score += 5

    if margin > 0:
        if margin > 25:  qual_score += 10
        elif margin > 15: qual_score += 7
        elif margin > 10: qual_score += 5
        elif margin > 5:  qual_score += 3

    if de is not None:
        if de < 0.3:   qual_score += 10
        elif de < 0.5: qual_score += 7
        elif de < 1.0: qual_score += 4
        elif de < 1.5: qual_score += 2

    # ── Price Action Score (max 25) ───────────────────────
    if df is not None and len(df) >= 50:
        try:
            close = df['Close']
            ema200 = ta.ema(close, length=200)
            rsi14  = ta.rsi(close, length=14)
            last_close = float(close.iloc[-1])
            y_high = float(df['High'].max())
            y_low  = float(df['Low'].min())
            pct_from_high = ((y_high - last_close) / y_high * 100) if y_high > 0 else 0

            # EMA200 trend
            if ema200 is not None and not ema200.dropna().empty:
                ema200_val = float(ema200.dropna().iloc[-1])
                if last_close > ema200_val:
                    price_score += 10

            # RSI - underowned zone
            if rsi14 is not None and not rsi14.dropna().empty:
                rsi_val = float(rsi14.dropna().iloc[-1])
                if 30 <= rsi_val <= 50:  price_score += 7
                elif 50 < rsi_val <= 60: price_score += 4

            # Distance from 52w high
            if pct_from_high > 20:   price_score += 5
            elif pct_from_high > 10: price_score += 3

        except Exception:
            pass

    # FCF yield bonus
    if fcf_yield > 5:   price_score += 3
    elif fcf_yield > 3: price_score += 1

    total = min(val_score + qual_score + price_score, 100)
    return val_score, qual_score, price_score, total


def _check_rate_limit(user_id, key, limit, window):
    """Returns True if rate limit is exceeded (limit calls per window seconds)."""
    from django.core.cache import cache
    cache_key = f"rl:{key}:{user_id}"
    count = cache.get(cache_key, 0)
    if count >= limit:
        return True
    cache.set(cache_key, count + 1, window)
    return False

