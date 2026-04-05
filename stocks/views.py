# ====== views.py — View หลักของระบบวิเคราะห์หุ้น AI ======
# ทุก view ต้องผ่านการ login (@login_required)
# ใช้ yfinance, yahooquery ดึงข้อมูลตลาด และ Gemini AI วิเคราะห์

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages
from django.conf import settings
from google import genai
from .models import (
    Watchlist, AnalysisCache, AssetCategory, Portfolio,
    MomentumCandidate, ScannableSymbol, MultiFactorCandidate, SoldStock,
    TitheRecord, ValueScanCandidate,
)
from .utils import (
    get_stock_data, analyze_with_ai, calculate_trailing_stop,
    refresh_set100_symbols, find_supply_demand_zones, find_supply_demand_zones_v2,
    detect_price_pattern, _is_commodity, _fetch_commodity_macro, _score_commodity_signal
)
from .crew_analysis import MomentumCrew
from decimal import Decimal
from yahooquery import Ticker as YQTicker
import requests
import yfinance as yf
import pandas as pd
import json
import os
import traceback
import pandas_ta as ta

# Removed custom session for yfinance to let it handle curl_cffi internally

# ====== ฟังก์ชันตรวจสอบสิทธิ์ผู้ใช้ ======

def admin_only(user):
    # อนุญาตให้ผู้ใช้ทุกคนที่ login แล้วเข้าถึงข้อมูลของตัวเองได้
    return user.is_authenticated # Changed to allow any user to see their own data

# ====== _compute_signals — คำนวณ BUY/SELL Score + Exit Signal จาก PrecisionScanCandidate ======
def _compute_signals(prec, current_price=None):
    """Reusable scorer v3 — ใช้ใน Portfolio, Watchlist, และ Precision Scanner."""
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

    # ADX (max 8)
    if adx >= 35:   buy += 8
    elif adx >= 30: buy += 5
    elif adx >= 25: buy += 2

    # ERC confirmed (max 5)
    if erc: buy += 5

    # RSI — v3: optimal zone ขยับเป็น 65-80 (max 8)
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

    # Bollinger Band Squeeze — pending breakout (max 6)
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

    buy_score = max(0, min(100, buy))

    # ── SELL SCORE ────────────────────────────────────────────────────
    sell = 0
    if sz_s and price >= sz_s:              sell += 45
    # ยกเลิกเงื่อนไขขายเมื่อใกล้วน 52w High เพราะเบรกเอาต์คือสัญญาณโมเมนตัมที่ดี
    if rsi > 78:    sell += 20
    elif rsi > 72:  sell += 12
    elif rsi > 68:  sell += 5
    if not rvol_b and rvol >= 1.5:  sell += 18
    elif not rvol_b:                sell += 10
    if rel1 < -5:   sell += 12
    elif rel1 < 0:  sell += 6
    if pat < -5:    sell += 10
    elif pat < 0:   sell += 5
    if adx < 15:    sell += 8
    elif adx < 20:  sell += 4
    # v3: MACD bearish (histogram negative + no crossover)
    if not macd_cross and macd_hist < 0 and abs(macd_hist) > 0.01:
        sell += 8
    # v7: CMF distribution — เงินไหลออกสุทธิ
    if cmf is not None:
        if cmf < -0.1:    sell += 10  # Distribution ชัดเจน
        elif cmf < -0.05: sell += 5   # เริ่มมีแรงขายสุทธิ
    sell_score = min(100, sell)

    if sell_score >= 70:   exit_signal = 'STRONG EXIT'
    elif sell_score >= 50: exit_signal = 'EXIT'
    elif sell_score >= 30: exit_signal = 'WATCH'
    else:                  exit_signal = ''

    return {'buy_score': buy_score, 'sell_score': sell_score, 'exit_signal': exit_signal}


# ====== Dashboard — หน้าแสดง Watchlist พร้อมราคาและ RSI แบบ Real-time ======

@login_required
def dashboard(request):
    """
    แสดงรายการ Watchlist ของผู้ใช้พร้อมราคาปัจจุบัน, % เปลี่ยนแปลง
    และค่า RSI 14 วัน คำนวณแบบ Real-time ผ่าน yfinance
    """
    watchlist = Watchlist.objects.filter(user=request.user)
    items = []
    import pandas_ta as ta
    from .utils import analyze_momentum_technical
    for item in watchlist:
        try:
            t = yf.Ticker(item.symbol)
            hist = t.history(period="1y")

            # Fallback: try alternate symbol if empty
            if hist.empty:
                alt_sym = f"{item.symbol}.BK" if ".BK" not in item.symbol else item.symbol.replace(".BK", "")
                t = yf.Ticker(alt_sym)
                hist = t.history(period="1y")

            current = None
            change = 0
            if not hist.empty:
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = [col[0] for col in hist.columns]
                hist = hist.loc[:, ~hist.columns.duplicated()]
                current = float(hist['Close'].iloc[-1])
                if len(hist) >= 2:
                    prev = float(hist['Close'].iloc[-2])
                    change = ((current - prev) / prev * 100) if prev else 0
            if not current:
                try:
                    info = t.info
                    if isinstance(info, dict):
                        current = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
                        change = info.get('regularMarketChangePercent', 0)
                except:
                    pass

            rsi_val = None
            rsi_status = "Neutral"
            if not hist.empty and len(hist) >= 14:
                rsi_series = ta.rsi(hist['Close'], length=14)
                if not rsi_series.empty:
                    rsi_val = rsi_series.iloc[-1]
                    if rsi_val < 30: rsi_status = "Oversold"
                    elif rsi_val > 70: rsi_status = "Overbought"

            # ดึงข้อมูลจาก PrecisionScanCandidate ก่อน (ตรงกับ Scanner ทุกค่า)
            clean_symbol = item.symbol.split('.')[0].upper()
            from .models import PrecisionScanCandidate
            prec_data = (PrecisionScanCandidate.objects
                         .filter(user=request.user, symbol=clean_symbol)
                         .order_by('-scan_run').first())

            if prec_data:
                class QuickMom: pass
                mom_data = QuickMom()
                mom_data.technical_score      = prec_data.technical_score
                mom_data.rvol                 = prec_data.rvol
                mom_data.rvol_bullish         = prec_data.rvol_bullish
                mom_data.adx                  = prec_data.adx
                mom_data.rsi                  = prec_data.rsi
                mom_data.erc_volume_confirmed = prec_data.erc_volume_confirmed
                mom_data.risk_reward_ratio    = prec_data.risk_reward_ratio
                mom_data.demand_zone_start    = prec_data.demand_zone_start
                mom_data.demand_zone_end      = prec_data.demand_zone_end
                mom_data.supply_zone_start    = prec_data.supply_zone_start
                mom_data.stop_loss            = prec_data.stop_loss
                mom_data.zone_proximity       = prec_data.zone_proximity
                mom_data.year_high            = prec_data.year_high
                mom_data.price_pattern        = prec_data.price_pattern
                mom_data.price_pattern_score  = prec_data.price_pattern_score
                mom_data.rel_momentum_1m      = prec_data.rel_momentum_1m
                mom_data.rel_momentum_3m      = prec_data.rel_momentum_3m
            else:
                # Fallback: คำนวณ on-the-fly ด้วย v2
                from .utils import analyze_momentum_technical_v2
                mom_data = None
                if not hist.empty:
                    tech_analysis = analyze_momentum_technical_v2(hist)
                    if tech_analysis and tech_analysis.get('score', 0) > 0:
                        class QuickMom: pass
                        mom_data = QuickMom()
                        mom_data.technical_score      = tech_analysis['score']
                        mom_data.rvol                 = tech_analysis.get('rvol', 1.0)
                        mom_data.rvol_bullish         = tech_analysis.get('rvol_bullish', True)
                        mom_data.adx                  = 0
                        mom_data.rsi                  = float(rsi_val or 0)
                        mom_data.erc_volume_confirmed = False
                        mom_data.year_high            = 0
                        mom_data.price_pattern        = ''
                        mom_data.price_pattern_score  = 0
                        mom_data.rel_momentum_1m      = 0.0
                        mom_data.rel_momentum_3m      = 0.0
                        sd = tech_analysis.get('sd_zone')
                        if sd and sd.get('start') and sd['start'] > 0:
                            mom_data.risk_reward_ratio = sd.get('rr_ratio', 0)
                            mom_data.demand_zone_start = sd['start']
                            mom_data.demand_zone_end   = sd.get('end', 0)
                            mom_data.supply_zone_start = sd.get('target', 0)
                            mom_data.stop_loss         = sd.get('stop_loss', None)
                            mom_data.zone_proximity    = 0 if (current and current <= sd['start']) else ((float(current or 0) - sd['start']) / sd['start']) * 100
                        else:
                            mom_data.risk_reward_ratio = 0
                            mom_data.demand_zone_start = 0
                            mom_data.demand_zone_end   = 0
                            mom_data.supply_zone_start = 0
                            mom_data.stop_loss         = None
                            mom_data.zone_proximity    = 999

            signals = _compute_signals(mom_data, current) if mom_data else {'buy_score': 0, 'sell_score': 0, 'exit_signal': ''}

            items.append({
                'obj': item,
                'price': current,
                'change': change,
                'rsi': rsi_val,
                'rsi_status': rsi_status,
                'mom_data': mom_data,
                'buy_score': signals['buy_score'],
                'sell_score': signals['sell_score'],
                'exit_signal': signals['exit_signal'],
            })
        except:
            items.append({'obj': item, 'price': 'Error', 'change': 0, 'rsi': None, 'rsi_status': 'Error', 'mom_data': None})

    return render(request, 'stocks/dashboard.html', {'items': items, 'categories': AssetCategory.choices})

# ====== Analyze — วิเคราะห์หุ้นรายตัวด้วย AI (Gemini) ======

@login_required
def analyze(request, symbol):
    """
    ดึงข้อมูลหุ้นจาก yfinance + yahooquery และส่งให้ Gemini AI วิเคราะห์
    ผลการวิเคราะห์จะถูกแคชไว้ใน AnalysisCache เพื่อใช้ซ้ำได้
    แสดงกราฟราคา 90 วัน, ข่าวล่าสุด, และข้อมูลพื้นฐาน
    """
    try:
        # Stop passing custom session, let yfinance handle its internal logic
        ticker = yf.Ticker(symbol)
        # ดึงข้อมูลหุ้นทั้งหมดผ่าน utility function
        data = get_stock_data(symbol)
        # ====== Fetch Extra Context from Cache (Value Stock data) ======
        extra_ctx = ""
        cached_lists = ['THAI_REC_ALL', 'US_REC_ALL']
        for list_sym in cached_lists:
            c = AnalysisCache.objects.filter(user=request.user, symbol=list_sym).first()
            if c:
                try:
                    s_list = json.loads(c.analysis_data)
                    match = next((s for s in s_list if s['symbol'] == symbol), None)
                    if match:
                        extra_ctx = f"Legendary Score: {match.get('value_score')}\n"
                        extra_ctx += f"Pillars: {match.get('legendary')}\n"
                        extra_ctx += f"Fair Value (Estimated): {match.get('fair_value')}\n"
                        extra_ctx += f"Upside (%): {match.get('upside')}\n"
                        break
                except: pass

        # ====== Fetch Extra Context from Momentum Scanner (Technical data) ======
        mom = MomentumCandidate.objects.filter(user=request.user, symbol_bk=symbol).first()
        if not mom:
            # ลองค้นหาด้วย symbol แบบไม่มี .BK
            clean_sym = symbol.replace('.BK', '')
            mom = MomentumCandidate.objects.filter(user=request.user, symbol=clean_sym).first()
        
        if mom:
            extra_ctx += f"\n[Technical Momentum Analysis]:\n"
            extra_ctx += f"Momentum Score: {mom.technical_score}/100\n"
            extra_ctx += f"RVOL: {mom.rvol}x, ADX: {mom.adx}, MFI: {mom.mfi}\n"
            if mom.entry_strategy:
                extra_ctx += f"Entry Strategy: {mom.entry_strategy}\n"
                extra_ctx += f"Demand Zone: {mom.demand_zone_start} - {mom.demand_zone_end}\n"
                extra_ctx += f"Target (Supply): {mom.supply_zone_start}\n"
                extra_ctx += f"Stop Loss: {mom.stop_loss}\n"
                extra_ctx += f"RR Ratio: {mom.risk_reward_ratio}\n"

        # ====== Pre-fetch macro data & compute signal for commodities ======
        # Done BEFORE AI call so we can pass signal into the prompt
        history = data.get('history', pd.DataFrame())
        is_commodity = _is_commodity(symbol)
        macro_data   = {}
        macro_signal = None
        if is_commodity:
            macro_data = _fetch_commodity_macro()
            _ema200 = float(history['EMA_200'].iloc[-1]) if 'EMA_200' in history.columns and not history.empty else None
            _rsi    = history['RSI'].iloc[-1]             if 'RSI'     in history.columns and not history.empty else None
            _price  = float(history['Close'].iloc[-1])    if not history.empty else 0
            macro_signal = _score_commodity_signal(symbol, _price, _ema200, _rsi, macro_data)
            # Stash raw macro inside signal so AI function can re-use without double-fetching
            macro_signal['_raw_macro'] = macro_data

        # ส่งข้อมูลให้ AI วิเคราะห์และรับผลเป็น Markdown
        analysis_text = analyze_with_ai(symbol, data, extra_context=extra_ctx, macro_signal=macro_signal)

        # ====== เตรียมข้อมูลกราฟราคาและวอลลุ่ม ======
        # Prepare Chart Data (Price & Volume)
        chart_labels = []
        chart_values = []
        chart_volumes = []
        if not history.empty:
            # แสดงเฉพาะ 90 วันล่าสุด
            history_subset = history.tail(90)
            chart_labels = [d.strftime('%Y-%m-%d') for d in history_subset.index]
            chart_values = [round(float(v), 2) for v in history_subset['Close'].values]
            chart_volumes = [int(v) for v in history_subset['Volume'].values]

        # ====== เตรียมข้อมูลข่าว — แปลง timestamp ให้อ่านได้ ======
        # Prepare News Data (Convert timestamp to readable)
        from datetime import datetime
        news_list = data.get('news', [])
        for n in news_list:
            if 'providerPublishTime' in n:
                try:
                    # รองรับทั้ง string (ISO format) และ int (Unix timestamp)
                    if isinstance(n['providerPublishTime'], str):
                        n['display_time'] = datetime.fromisoformat(n['providerPublishTime'].replace('Z', '+00:00'))
                    else:
                        n['display_time'] = datetime.fromtimestamp(n['providerPublishTime'])
                except Exception:
                    n['display_time'] = n['providerPublishTime']

        # ====== บันทึกผลวิเคราะห์ลงใน cache ของแต่ละ user ======
        # Cache it per user
        AnalysisCache.objects.update_or_create(
            user=request.user,
            symbol=symbol,
            defaults={'analysis_data': analysis_text}
        )

        # ====== คำนวณค่า RSI ล่าสุดเพื่อแสดงใน header ======
        # Prepare RSI
        current_rsi = history['RSI'].iloc[-1] if 'RSI' in history.columns and not history.empty else None
        rsi_status = "Neutral"
        if current_rsi:
            if current_rsi < 30: rsi_status = "Oversold"
            elif current_rsi > 70: rsi_status = "Overbought"

        # ====== เตรียมข้อมูลพื้นฐานการเงิน ======
        info = data.get('info') or {}
        if not isinstance(info, dict):
            info = {}

        # ทำ copy เพื่อไม่แก้ไข dict ต้นฉบับ
        info = info.copy() # Safe copy
        # แปลงค่าสัดส่วนพื้นฐาน (ROE, Dividend Yield, NPM) จากทศนิยมเป็นเปอร์เซ็นต์ (เฉพาะถ้าเป็นทศนิยม < 1)
        for key in ['returnOnEquity', 'dividendYield', 'profitMargins']:
            val = info.get(key)
            if isinstance(val, (int, float)):
                if abs(val) < 1.0:
                    info[key] = val * 100
                else:
                    info[key] = val

        # ====== คำนวณ D/E Ratio จาก Balance Sheet ======
        bs = data.get('balance_sheet')
        de_calculated = None
        if bs is not None and not bs.empty:
            try:
                col = bs.columns[0]
                # พยายามดึง Total Liabilities จากหลายชื่อ field ที่ yfinance อาจใช้
                tot_liab = bs.loc['Total Liabilities Net Minority Interest', col] if 'Total Liabilities Net Minority Interest' in bs.index else bs.loc['Total Liabilities', col]
                tot_eq = bs.loc['Stockholders Equity', col] if 'Stockholders Equity' in bs.index else bs.loc['Total Equity Gross Minority Interest', col]
                de_calculated = tot_liab / tot_eq
            except Exception:
                pass

        # อัปเดต D/E ใน info dict (ใช้ค่าจาก balance sheet ถ้ามี หรือ fallback เป็นค่าจาก yfinance)
        if de_calculated is not None:
            info['debtToEquity'] = de_calculated
        elif isinstance(info.get('debtToEquity'), (int, float)) if isinstance(info, dict) else False:
            # yfinance ส่งค่า D/E เป็น % (คูณ 100 มาแล้ว) ต้องหาร 100 กลับ
            info['debtToEquity'] = info['debtToEquity'] / 100

        # ====== คำนวณ Breakout / Resistance Levels ======
        fifty_two_week_high = history['High'].max() if not history.empty and 'High' in history.columns else None
        # แนวต้านย่อยในช่วง 20 วันล่าสุด
        recent_resistance = history['High'].tail(20).max() if not history.empty and 'High' in history.columns else None
        # แนวรับ/จุดตัดขาดทุนในช่วง 20 วันล่าสุด
        recent_support = history['Low'].tail(20).min() if not history.empty and 'Low' in history.columns else None
        curr_price = history['Close'].iloc[-1] if not history.empty and 'Close' in history.columns else info.get('currentPrice', 0)
        # ตรวจสอบว่าราคาปัจจุบันทะลุ 52-Week High หรือไม่ (Breakout Signal)
        is_breakout = (curr_price >= fifty_two_week_high) if (fifty_two_week_high and curr_price) else False

        context = {
            'symbol': symbol,
            'info': info,
            'analysis': analysis_text,
            'chart_labels': chart_labels,
            'chart_values': chart_values,
            'chart_volumes': chart_volumes,
            'fifty_two_week_high': fifty_two_week_high,
            'recent_resistance': recent_resistance,
            'recent_support': recent_support,
            'is_breakout': is_breakout,
            'current_rsi': current_rsi,
            'rsi_status': rsi_status,
            'news': news_list,
            'title': f"AI Analysis: {symbol}",
            'is_commodity': is_commodity,
            'macro_data': macro_data,
            'macro_signal': macro_signal,
        }
        return render(request, 'stocks/analysis.html', context)
    except Exception as e:
        messages.error(request, f"Error analyzing {symbol}: {str(e)}")
        return redirect('stocks:dashboard')

@login_required
def crew_analyze(request, symbol):
    """
    หน้าแสดงผลการวิเคราะห์เจาะลึกด้วย CrewAI Multi-Agent System.
    ใช้เวลาในการประมวลผลนานกว่าปกติเพราะ Agent มีการโต้ตอบกัน.
    """
    try:
        crew = MomentumCrew(symbol)
        result = crew.run_analysis()
        
        # ดึงข้อมูลเบื้องต้นเพื่อใช้ในหัวข่าว
        data = get_stock_data(symbol)
        
        context = {
            'symbol': symbol,
            'crew_result': result,
            'info': data.get('info', {}),
            'title': f'CrewAI Deep Analysis: {symbol}'
        }
        return render(request, 'stocks/crew_result.html', context)
    except Exception as e:
        messages.error(request, f"CrewAI Analysis Error: {str(e)}")
        return redirect('stocks:analyze', symbol=symbol)

# ====== Watchlist Management — เพิ่ม/ลบ รายการ Watchlist ======

@login_required
def add_to_watchlist(request):
    """รับ POST form เพิ่ม symbol เข้า Watchlist ของ user ปัจจุบัน"""
    if request.method == 'POST':
        symbol = request.POST.get('symbol').upper()
        category = request.POST.get('category', AssetCategory.STOCK)
        name = request.POST.get('name', '')

        if symbol:
            # get_or_create ป้องกันการเพิ่ม symbol ซ้ำ
            Watchlist.objects.get_or_create(
                user=request.user,
                symbol=symbol,
                defaults={'name': name, 'category': category}
            )
            messages.success(request, f"เพิ่ม {symbol} เข้าใน Watchlist แล้ว")

    return redirect('stocks:dashboard')

@login_required
def delete_from_watchlist(request, pk):
    """ลบรายการ Watchlist ตาม pk (เฉพาะของ user ปัจจุบันเท่านั้น)"""
    item = get_object_or_404(Watchlist, pk=pk, user=request.user)
    symbol = item.symbol
    item.delete()
    messages.success(request, f"ลบ {symbol} ออกจาก Watchlist แล้ว")
    return redirect('stocks:dashboard')

# ====== Portfolio — แสดงพอร์ตการลงทุนพร้อมวิเคราะห์ AI ======

@login_required
def portfolio_list(request):
    """
    แสดงรายการสินทรัพย์ในพอร์ต พร้อม:
    - ราคาปัจจุบัน, P/L, Market Value
    - RSI 14 วัน
    - Trailing Stop (3% จาก High)
    - Supply & Demand Zone
    - AI Portfolio Analysis (PyPortfolioOpt + Gemini)
      เมื่อผู้ใช้กดปุ่ม Analyze (?analyze=true)
    """
    portfolio_items = Portfolio.objects.filter(user=request.user)
    items = []
    total_market_value = 0
    total_gain_loss = 0
    print(f"DEBUG: Portfolio Scan Started for {getattr(request.user, 'username', 'Anonymous')}")

    for item in portfolio_items:
        try:
            symbol = item.symbol
            print(f"DEBUG: Processing {symbol}")

            # ====== ดึงข้อมูลราคาจาก yfinance ======
            # Data fetch
            t = yf.Ticker(symbol)
            hist = t.history(period="1y")

            # ถ้าไม่มีข้อมูล ลองเพิ่ม/ลบ .BK suffix (รองรับหุ้นไทย)
            if hist.empty:
                alt_sym = f"{symbol}.BK" if ".BK" not in symbol else symbol.replace(".BK", "")
                print(f"DEBUG: {symbol} empty, trying {alt_sym}")
                t = yf.Ticker(alt_sym)
                hist = t.history(period="1y")

            current_price = 0
            rsi_val = None

            if not hist.empty:
                # จัดการ MultiIndex columns ที่อาจเกิดขึ้นเมื่อ yfinance ส่งข้อมูลหลาย ticker
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = [col[0] for col in hist.columns]
                hist = hist.loc[:, ~hist.columns.duplicated()]

                current_price = float(hist['Close'].iloc[-1])

                # ตรวจสอบซ้ำอีกรอบเพื่อกรณีที่ Close เป็น NaN
                # Double check price
                if not current_price or pd.isna(current_price):
                    try:
                        info = t.info
                        if isinstance(info, dict):
                            current_price = info.get('currentPrice') or info.get('regularMarketPrice') or 0
                    except: pass

                current_price = float(current_price or 0)

                # คำนวณ RSI 14 วัน จากข้อมูลราคาปิด
                # RSI
                rsi_series = ta.rsi(hist['Close'], length=14)
                rsi_val = rsi_series.iloc[-1] if (rsi_series is not None and not rsi_series.empty) else None
                print(f"DEBUG: {symbol} Success Price={current_price}")
            else:
                print(f"DEBUG: {symbol} FAILED - No data")

            # คำนวณ % เปลี่ยนแปลงวันนี้ vs เมื่อวาน
            day_change = 0
            if not hist.empty and len(hist) >= 2:
                prev_close = float(hist['Close'].iloc[-2])
                day_change = ((current_price - prev_close) / prev_close * 100) if prev_close else 0

            # ====== คำนวณ P/L และ Market Value ======
            # Calculations
            market_value = float(item.quantity) * float(current_price)
            cost_basis = float(item.quantity) * float(item.entry_price or 0)
            gain_loss = market_value - cost_basis
            gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis > 0 else 0

            # ====== คำนวณ ATR Trailing Stop ======
            from .utils import calculate_atr_trailing_stop
            atr_ts = calculate_atr_trailing_stop(
                df=hist if not hist.empty else None,
                entry_price=float(item.entry_price or 0),
                highest_price_db=float(item.highest_price or 0),
                multiplier=float(item.trail_multiplier or 2.5),
            ) if current_price > 0 else None

            # อัปเดต highest_price และ ATR ใน DB ถ้าสูงขึ้น
            if atr_ts and current_price > 0:
                new_high = atr_ts['highest']
                update_fields = []
                if float(item.highest_price or 0) < new_high:
                    item.highest_price = new_high
                    update_fields.append('highest_price')
                if abs(float(item.atr or 0) - atr_ts['atr']) > 0.0001:
                    item.atr = atr_ts['atr']
                    update_fields.append('atr')
                if update_fields:
                    item.save(update_fields=update_fields)

            ts_data = atr_ts  # ยังคง key เดิมใน template

            # ====== ดึง/คำนวณ Zone Data — ใช้ PrecisionScanCandidate (v2) เสมอ ======
            clean_symbol = item.symbol.split('.')[0].upper()
            from .utils import analyze_momentum_technical_v2
            from .models import PrecisionScanCandidate

            # 1. ลองหาผล Precision Scan ล่าสุดก่อน (ตรงกับ Precision Scanner ทุกค่า)
            prec_data = (PrecisionScanCandidate.objects
                         .filter(user=request.user, symbol=clean_symbol)
                         .order_by('-scan_run').first())

            if prec_data and not request.GET.get('refresh') == 'true':
                # ใช้ข้อมูลจาก Precision Scanner โดยตรง
                class QuickMom: pass
                mom_data = QuickMom()
                mom_data.technical_score   = prec_data.technical_score
                mom_data.rvol              = prec_data.rvol
                mom_data.rvol_bullish      = prec_data.rvol_bullish
                mom_data.adx               = prec_data.adx
                mom_data.rsi               = prec_data.rsi
                mom_data.erc_volume_confirmed = prec_data.erc_volume_confirmed
                mom_data.risk_reward_ratio = prec_data.risk_reward_ratio
                mom_data.demand_zone_start = prec_data.demand_zone_start
                mom_data.demand_zone_end   = prec_data.demand_zone_end
                mom_data.supply_zone_start = prec_data.supply_zone_start
                mom_data.stop_loss         = prec_data.stop_loss
                mom_data.zone_proximity    = prec_data.zone_proximity
                mom_data.year_high         = prec_data.year_high
                mom_data.price_pattern     = prec_data.price_pattern
                mom_data.price_pattern_score = prec_data.price_pattern_score
                mom_data.rel_momentum_1m   = prec_data.rel_momentum_1m
                mom_data.rel_momentum_3m   = prec_data.rel_momentum_3m
                mom_data.macd_histogram    = prec_data.macd_histogram
                mom_data.macd_crossover    = prec_data.macd_crossover
                mom_data.bb_squeeze        = prec_data.bb_squeeze
                mom_data.ema20_aligned     = prec_data.ema20_aligned
                mom_data.rs_rating         = prec_data.rs_rating
                mom_data.ema20_rising      = prec_data.ema20_rising
                mom_data.hh_hl_structure   = prec_data.hh_hl_structure
                mom_data.cmf               = prec_data.cmf
                mom_data.is_52w_breakout   = prec_data.is_52w_breakout
            else:
                # 2. คำนวณ on-the-fly ด้วย v2 (ตรงกับ Precision Scanner)
                tech_analysis = analyze_momentum_technical_v2(hist) if not hist.empty else None
                class QuickMom: pass
                mom_data = QuickMom()
                if tech_analysis:
                    mom_data.technical_score = tech_analysis['score']
                    mom_data.rvol = tech_analysis['rvol']
                    sd = tech_analysis.get('sd_zone')
                    if sd and sd.get('start') and sd['start'] > 0:
                        mom_data.risk_reward_ratio = sd.get('rr_ratio', 0)
                        mom_data.demand_zone_start = sd['start']
                        mom_data.demand_zone_end = sd.get('end', 0)
                        mom_data.supply_zone_start = sd.get('target', 0)
                        mom_data.stop_loss = sd.get('stop_loss', None)
                        mom_data.zone_proximity = 0 if current_price <= sd['start'] else ((float(current_price) - sd['start']) / sd['start']) * 100
                    else:
                        mom_data.risk_reward_ratio = 0
                        mom_data.demand_zone_start = 0
                        mom_data.stop_loss = None
                        mom_data.zone_proximity = 999
                else:
                    mom_data.technical_score = 0
                    mom_data.rvol = 0
                    mom_data.risk_reward_ratio = 0
                    mom_data.demand_zone_start = 0
                    mom_data.stop_loss = None
                    mom_data.zone_proximity = 999

            total_market_value += market_value
            total_gain_loss += gain_loss

            signals = _compute_signals(mom_data, current_price) if mom_data else {'buy_score': 0, 'sell_score': 0, 'exit_signal': ''}

            items.append({
                'obj': item,
                'current_price': current_price,
                'day_change': day_change,
                'market_value': market_value,
                'gain_loss': gain_loss,
                'gain_loss_pct': gain_loss_pct,
                'rsi': rsi_val,
                'trailing_stop_data': ts_data,
                'mom_data': mom_data,
                'buy_score': signals['buy_score'],
                'sell_score': signals['sell_score'],
                'exit_signal': signals['exit_signal'],
                'in_scan': prec_data is not None,
                'scan_score': prec_data.technical_score if prec_data else None,
            })
        except Exception as e:
            print(f"DEBUG: ERROR for {item.symbol}: {e}")
            traceback.print_exc()
            # ถ้า error ใส่ข้อมูลเปล่าเพื่อแสดง error state ใน template
            items.append({
                'obj': item, 'current_price': 0, 'day_change': 0, 'market_value': 0,
                'gain_loss': 0, 'gain_loss_pct': 0, 'rsi': None,
                'trailing_stop_data': None, 'mom_data': None
            })

    # ====== AI Portfolio Analysis ด้วย Gemini + PyPortfolioOpt ======
    ai_analysis = None
    if request.GET.get('analyze') == 'true' and items:
        # เลือก Gemini model ที่ดีที่สุดที่ตอบสนองได้
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        model_name_to_use = 'gemini-2.5-flash'

        # สร้าง string สรุปพอร์ตสำหรับส่งให้ AI
        port_data = []
        for it in items:
            mom_info = ""
            if it.get('mom_data'):
                m = it['mom_data']
                rvol = m.rvol if hasattr(m, 'rvol') else 0
                rs = getattr(m, 'rs_rating', 0)
                adx = m.adx if hasattr(m, 'adx') else 0
                score = m.technical_score if hasattr(m, 'technical_score') else 0
                buy_sc = it.get('buy_score', 0)
                exit_sig = it.get('exit_signal', '')
                mom_info = f", Score(0-100): {score}, BUY Score: {buy_sc}, RS(0-99): {rs}, RVOL: {rvol:.1f}x, ADX: {adx:.1f}, Exit Signal: '{exit_sig}'"
            port_data.append(f"{it['obj'].symbol}: {it['obj'].quantity} units @ {it['obj'].entry_price} (Current: {it['current_price']}, P/L: {it['gain_loss_pct']:.2f}%, RSI: {it['rsi']}{mom_info})")
        port_str = "\n".join(port_data)

        # ====== PyPortfolioOpt — คำนวณ Efficient Frontier / Max Sharpe ======
        # --- PyPortfolioOpt Integration ---
        # Get historical data for all symbols to calculate correlation & efficient frontier
        symbols = [it['obj'].symbol for it in items if it['obj'].quantity > 0]
        ppo_advice = ""
        if len(symbols) > 1:
            try:
                from pypfopt import expected_returns, risk_models
                from pypfopt.efficient_frontier import EfficientFrontier

                # ดึงราคาปิดย้อนหลัง 1 ปีสำหรับทุก symbol พร้อมกัน
                # Fetch 1 yr of closing prices for correlation
                data = yf.download(symbols, period="1y")

                # แปลง MultiIndex columns ให้เหลือแค่ 'Close' level
                if isinstance(data.columns, pd.MultiIndex):
                    data = data['Close']
                elif 'Close' in data:
                    data = data[['Close']]
                else:
                    data = pd.DataFrame() # Fallback

                # จัดการ missing values ด้วย forward-fill และ backward-fill
                # Deal with missing values
                data = data.dropna(how="all")
                data = data.ffill().bfill()

                # ตรวจสอบว่ามีข้อมูลเพียงพอสำหรับการคำนวณ
                # Make sure data is not flat (in case of single symbol fallback bug, though handled by len(symbols) > 1)
                if data.empty or len(data.columns) < 2:
                    raise ValueError("Not enough overlapping price data to calculate correlation.")

                # คำนวณ Expected Return และ Covariance Matrix
                mu = expected_returns.mean_historical_return(data)
                S = risk_models.sample_cov(data)

                ef = EfficientFrontier(mu, S)

                # หา Portfolio ที่ Max Sharpe Ratio (ผลตอบแทนดีที่สุดเมื่อเทียบกับความเสี่ยง)
                # Optimise for maximal Sharpe ratio
                try:
                    raw_weights = ef.max_sharpe()
                except Exception as ef_e:
                    # Fallback: กรณีที่ max_sharpe ไม่ converge ใช้ equal weight แทน
                    # Fallback to equal weighting if max_sharpe fails (e.g. non-convex/all negative returns)
                    raw_weights = {sym: 1.0/len(symbols) for sym in symbols}

                cleaned_weights = ef.clean_weights()

                # เปรียบเทียบน้ำหนักปัจจุบันกับน้ำหนักที่เหมาะสม
                # Compare current weights to optimal weights
                portfolio_total = sum(it['market_value'] for it in items)
                current_weights = {it['obj'].symbol: (it['market_value'] / portfolio_total if portfolio_total > 0 else 0) for it in items}

                ppo_advice += "\n[PyPortfolioOpt Portfolio Optimization (Max Sharpe)]\n"
                for sym in symbols:
                    c_weight = current_weights.get(sym, 0) * 100
                    o_weight = cleaned_weights.get(sym, 0) * 100
                    action = "Hold"
                    # คำแนะนำ: Buy เมื่อน้ำหนักปัจจุบันต่ำกว่า optimal > 5%
                    if o_weight > c_weight + 5: action = "Buy/Increase Weight"
                    elif o_weight < c_weight - 5: action = "Sell/Reduce Weight"
                    ppo_advice += f"- {sym}: Current Weight = {c_weight:.1f}%, Optimal Weight = {o_weight:.1f}% -> Model says: {action}\n"

                # แสดงผลการวิเคราะห์ประสิทธิภาพของ Portfolio ที่เหมาะสม
                try:
                    perf = ef.portfolio_performance(verbose=False)
                    ppo_advice += f"\nOptimal Expected Annual Return: {perf[0]*100:.2f}%\n"
                    ppo_advice += f"Optimal Annual Volatility: {perf[1]*100:.2f}%\n"
                    ppo_advice += f"Optimal Sharpe Ratio: {perf[2]:.2f}\n"
                except:
                    pass

            except ImportError:
                ppo_advice = f"\n[PyPortfolioOpt] Unable to optimize portfolio: PyPortfolioOpt is not installed.\n"
            except Exception as e:
                ppo_advice = f"\n[PyPortfolioOpt] Unable to optimize portfolio due to an error: {str(e)}\n"

        # ====== สร้าง Prompt สำหรับ AI วิเคราะห์พอร์ต ======
        prompt = f"""
        You are an expert Stock Portfolio Analyst specializing in "Precision Momentum Trading" (similar to Mark Minervini and CANSLIM).
        The user has the following assets in their portfolio (with Entry Price, Current Price, and Profit/Loss, along with Momentum metrics):
        {port_str}

        {ppo_advice}

        Please analyze this portfolio and provide:
        2. A brief analysis and clear recommendation for EACH individual asset (e.g., Hold, Buy More, Take Profit, Cut Loss).
           - CRITICAL RULE: In your analysis, you MUST heavily weigh the Momentum metrics (Score, BUY Score, RS, RVOL, ADX, and Exit Signal).
           - Do NOT immediately suggest cutting a loss JUST because P/L is slightly negative or RSI is > 70.
           - **Consider Entry Price:** If a stock's price is below its technical Stop Loss but still above the Entry Price (in profit), suggest "Locking Profit" (ล็อกกำไร) or "Trailing Exit" instead of a harsh "Cut Loss".
           - If a stock has High RS (e.g. > 75), strong RVOL (> 1.5x) or a high BUY Score/Score, it indicates it is a "Market Leader" and in a strong uptrend. In such cases, suggest "Holding" to ride the momentum as long as the Exit Signal is not triggered, even if P/L is temporarily negative.
           - Acknowledge the strength of the momentum. E.g., "แม้จะขาดทุน -2.35% แต่หุ้นมี RS แข็งแกร่งถึง 88 และ RVOL สูง บ่งบอกถึงแรงซื้อที่ยังมีอยู่ แนะนำให้ถือเพื่อรอจังหวะเด้งกลับ"
        3. Actionable strategic advice on what sectors or types of assets to consider adding next to balance the portfolio.

        Format your response beautifully in Markdown using Thai Language (Sarabun professional tone).
        IMPORTANT RULES:
        1. DO NOT include any conversational preamble or outro (e.g. "Here is the analysis...", "Explanation of Choices:").
        2. Output ONLY the raw markdown text.
        3. DO NOT wrap the output in ```markdown code blocks. Start immediately with the analysis headings.
        """
        try:
            response = client.models.generate_content(
                model=model_name_to_use,
                contents=prompt
            )
            ai_analysis = response.text

            # ลบ markdown code block wrapper ถ้า AI ไม่ปฏิบัติตาม prompt
            # Strip any residual markdown blocks if AI disobeys
            if ai_analysis.startswith("```markdown"):
                ai_analysis = ai_analysis[len("```markdown"):].strip()
            if ai_analysis.endswith("```"):
                ai_analysis = ai_analysis[:-3].strip()
        except Exception as e:
            ai_analysis = f"ไม่สามารถวิเคราะห์พอร์ตได้ในขณะนี้: {str(e)}"

    # ====== เตรียมข้อมูลสำหรับกราฟประวัติกำไร/ขาดทุน (Realized P/L) ======
    sold_stocks = SoldStock.objects.filter(user=request.user).order_by('sold_at')
    chart_labels = []
    chart_data = []
    running_pl = 0
    for s in sold_stocks:
        running_pl += float(s.profit_loss)
        chart_labels.append(s.sold_at.strftime('%Y-%m-%d %H:%M'))
        chart_data.append(running_pl)

    # ====== เตรียมข้อมูลตารางสรุปรายเดือน (Monthly Summary) ======
    from collections import defaultdict
    monthly_summary_dict = defaultdict(lambda: {'items': [], 'total_pl': 0})
    for s in sold_stocks:
        month_key = s.sold_at.strftime('%B %Y') # e.g. March 2024
        monthly_summary_dict[month_key]['items'].append(s)
        monthly_summary_dict[month_key]['total_pl'] += float(s.profit_loss)
    
    # แปลงเป็น list และเรียงลำดับเดือน (ล่าสุดขึ้นก่อน)
    # หมายเหตุ: การเรียงลำดับตามชื่อเดือนอาจจะเพี้ยน ต้องใช้ key ที่เป็นตัวเลข หรือเรียงจาก sold_at แทน
    # ดังนั้นจะดึงเดือนล่าสุดจาก sold_stocks ที่เรียงมาแล้ว
    monthly_summary = []
    unique_months = []
    for s in sold_stocks[::-1]: # วนย้อนกลับจากล่าสุด
        m_key = s.sold_at.strftime('%B %Y')
        if m_key not in unique_months:
            unique_months.append(m_key)
            monthly_summary.append({
                'month_name': m_key,
                'items': monthly_summary_dict[m_key]['items'],
                'total_pl': monthly_summary_dict[m_key]['total_pl']
            })

    context = {
        'items': items,
        'total_market_value': total_market_value,
        'total_gain_loss': total_gain_loss,
        'categories': AssetCategory.choices,
        'title': 'My Portfolio',
        'ai_analysis': ai_analysis,
        'sold_stocks': sold_stocks,
        'monthly_summary': monthly_summary,
        'chart_labels': json.dumps(chart_labels),
        'chart_data': json.dumps(chart_data),
    }
    return render(request, 'stocks/portfolio.html', context)


# ====== Portfolio Exit Plan — แผนออกหุ้นแต่ละตัว เรียงตามความเร่งด่วน ======

@login_required
def portfolio_exit_plan(request):
    """
    แสดงแผนออกจากหุ้นแต่ละตัวในพอร์ต พร้อม:
    - Progress bar: SL → Entry → Current → TP
    - Action recommendation ชัดเจน (ออกทันที / ทยอยขาย / เฝ้า / ถือต่อ)
    - สัญญาณออกที่ active อยู่
    - เรียงตาม SELL Score สูงสุดก่อน (urgent first)
    """
    portfolio_items = Portfolio.objects.filter(user=request.user)
    items = []

    for item in portfolio_items:
        try:
            symbol = item.symbol
            t = yf.Ticker(symbol)
            hist = t.history(period="1y")
            if hist.empty:
                alt = f"{symbol}.BK" if ".BK" not in symbol else symbol.replace(".BK", "")
                hist = yf.Ticker(alt).history(period="1y")
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = [col[0] for col in hist.columns]
            hist = hist.loc[:, ~hist.columns.duplicated()]

            current_price = float(hist['Close'].iloc[-1]) if not hist.empty else 0
            day_change = 0
            if not hist.empty and len(hist) >= 2:
                prev = float(hist['Close'].iloc[-2])
                day_change = ((current_price - prev) / prev * 100) if prev else 0

            entry_price  = float(item.entry_price or 0)
            quantity     = float(item.quantity or 0)
            gain_loss_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0

            # days held
            from datetime import date
            days_held = (date.today() - item.added_at.date()).days if item.added_at else 0

            # ดึง PrecisionScanCandidate
            clean_symbol = symbol.split('.')[0].upper()
            from .models import PrecisionScanCandidate
            prec_data = (PrecisionScanCandidate.objects
                         .filter(user=request.user, symbol=clean_symbol)
                         .order_by('-scan_run').first())

            sl_price = tp_price = rsi_val = adx_val = None
            price_pattern = ''
            price_pattern_score = 0
            rel_1m = rel_3m = 0.0
            rvol_bullish = True
            rvol = 1.0
            supply_zone_start = year_high = 0
            cmf_val = None

            if prec_data:
                sl_price    = prec_data.stop_loss
                tp_price    = prec_data.supply_zone_start
                rsi_val     = prec_data.rsi
                adx_val     = prec_data.adx
                price_pattern       = prec_data.price_pattern
                price_pattern_score = prec_data.price_pattern_score
                rel_1m      = prec_data.rel_momentum_1m
                rel_3m      = prec_data.rel_momentum_3m
                rvol_bullish = prec_data.rvol_bullish
                rvol        = prec_data.rvol
                supply_zone_start = prec_data.supply_zone_start or 0
                year_high   = prec_data.year_high or 0
                cmf_val     = prec_data.cmf

            signals = _compute_signals(prec_data, current_price) if prec_data else {'buy_score': 0, 'sell_score': 0, 'exit_signal': ''}
            sell_score   = signals['sell_score']
            exit_signal  = signals['exit_signal']

            # ====== Progress Bar: SL → Entry → Current → TP ======
            progress_pct   = None
            current_pct    = None
            entry_pct      = None
            sl_hit         = False
            tp_hit         = False

            if sl_price and tp_price and tp_price > sl_price:
                total_range    = tp_price - sl_price
                sl_hit         = current_price <= sl_price
                tp_hit         = current_price >= tp_price
                current_pct    = min(100, max(0, (current_price - sl_price) / total_range * 100))
                entry_pct      = min(100, max(0, (entry_price - sl_price) / total_range * 100))

            # ====== Momentum Classification ======
            # หุ้นผู้นำ (Leader) = Momentum แข็งแกร่งกว่าตลาดมาก
            is_leader = (rel_3m and rel_3m > 10) or (rel_1m and rel_1m > 5) or (adx_val and adx_val > 30)
            # หุ้นล้าหลัง (Laggard) = Momentum อ่อนแอกว่าตลาด
            is_laggard = (rel_3m and rel_3m < -5) or (adx_val and adx_val < 18)

            # ====== Action Recommendation (Momentum-Aware) ======
            if exit_signal == 'STRONG EXIT':
                if is_leader:
                    action       = 'ทยอยขาย (Leader)'
                    action_style = 'warning'
                    action_detail = f"สัญญาณขายแรง แต่หุ้นยังเป็นผู้นำ (RS สูง) — ขาย 70% เก็บ 30% เผื่อเด้งแรง"
                else:
                    action       = 'ออกทันที'
                    action_style = 'danger'
                    action_detail = f"ขายทั้งหมด {quantity:.0f} หุ้น — สัญญาณเทคนิคขาลงชัดเจนและหุ้นเริ่มล้าหลัง"
            
            elif sl_hit:
                if entry_price > 0 and current_price < entry_price:
                    if is_leader:
                        action       = 'เฝ้าจุดเด้ง (Cut?)'
                        action_style = 'warning'
                        action_detail = "หลุด SL แต่เป็นหุ้นผู้นำ — รอดูการดึงกลับที่เส้นค่าเฉลี่ย ถ้าไม่เด้งต้องคัท"
                    else:
                        action       = 'ตัดขาดทุน (Cut Loss)'
                        action_style = 'danger'
                        action_detail = f"ราคาหลุด SL และหุ้นอ่อนแอกว่าตลาด — แนะนำขายทันทีเพื่อปกป้องเงินทุน"
                else:
                    action       = 'ล็อกกำไร (Trailing)'
                    action_style = 'warning'
                    action_detail = f"ราคาหลุดจุดเฝ้าระวัง (SL) — กำไรยังเหลือ {gain_loss_pct:.1f}% แนะนำขายล็อกกำไร"

            elif exit_signal == 'EXIT':
                if is_leader:
                    action       = 'ถือต่อ (Leader)'
                    action_style = 'success'
                    action_detail = "มีสัญญาณขายบ้าง แต่ momentum แข็งแกร่งมาก — ถือต่อเพื่อรันเทรน"
                else:
                    action       = 'ทยอยขาย 50%'
                    action_style = 'warning'
                    action_detail = f"หุ้นเริ่มหมดแรงและไม่ใช่ผู้นำ — ขายครึ่งหนึ่งเก็บกำไรไว้ก่อน"

            elif is_laggard and gain_loss_pct < 0:
                action       = 'พิจารณาเปลี่ยนตัว'
                action_style = 'warning-soft'
                action_detail = "หุ้นเคลื่อนไหวช้ากว่าตลาด (Laggard) — แนะนำพิจารณาเปลี่ยนไปถือหุ้นผู้นำตัวอื่น"

            elif tp_price and current_price >= tp_price * 0.95:
                action       = 'ใกล้ TP'
                action_style = 'info'
                action_detail = f"ราคาใกล้เป้าหมายแล้ว — เตรียมทยอยรับทรัพย์"

            else:
                action       = 'ถือต่อ'
                action_style = 'success'
                action_detail = "ยังไม่มีสัญญาณออก และโครงสร้างราคายังดี — ถือรันเทรนต่อไป"

            # ====== Active Exit Triggers ======
            triggers = []
            if sl_hit:
                triggers.append({'label': 'SL HIT — หลุด Stop Loss', 'level': 'danger'})
            if tp_hit:
                triggers.append({'label': f'TP Hit — ถึงเป้า ฿{tp_price:.2f}', 'level': 'danger'})
            if rsi_val and rsi_val > 78:
                triggers.append({'label': f'RSI {rsi_val:.0f} — overbought มาก', 'level': 'danger'})
            elif rsi_val and rsi_val > 72:
                triggers.append({'label': f'RSI {rsi_val:.0f} — เริ่ม overbought', 'level': 'warning'})
            if not rvol_bullish and rvol >= 1.5:
                triggers.append({'label': f'RVOL {rvol:.1f}x Bear — แรงขายเข้ามา', 'level': 'danger'})
            elif not rvol_bullish:
                triggers.append({'label': 'RVOL Bear — volume หันขาลง', 'level': 'warning'})
            if rel_1m < -5:
                triggers.append({'label': f'Rel Mom 1m {rel_1m:.1f}% — แพ้ SET มาก', 'level': 'warning'})
            elif rel_1m < 0:
                triggers.append({'label': f'Rel Mom 1m {rel_1m:.1f}% — เริ่มแพ้ SET', 'level': 'info'})
            if price_pattern_score < -5:
                triggers.append({'label': f'Pattern: {price_pattern} — สัญญาณขาย', 'level': 'danger'})
            elif price_pattern_score < 0:
                triggers.append({'label': f'Pattern: {price_pattern}', 'level': 'warning'})
            if adx_val and adx_val < 20:
                triggers.append({'label': f'ADX {adx_val:.0f} — เทรนด์อ่อนแรง', 'level': 'warning'})
            if cmf_val is not None:
                if cmf_val < -0.1:
                    triggers.append({'label': f'CMF {cmf_val:.2f} — Distribution ชัดเจน เงินไหลออก', 'level': 'danger'})
                elif cmf_val < -0.05:
                    triggers.append({'label': f'CMF {cmf_val:.2f} — เริ่มมีแรงขายสุทธิ', 'level': 'warning'})
            if not triggers and exit_signal == '':
                triggers.append({'label': 'ไม่มีสัญญาณออก — ถือต่อได้', 'level': 'success'})

            items.append({
                'obj':          item,
                'current_price': current_price,
                'day_change':   day_change,
                'entry_price':  entry_price,
                'gain_loss_pct': gain_loss_pct,
                'quantity':     quantity,
                'days_held':    days_held,
                'sl_price':     sl_price,
                'tp_price':     tp_price,
                'rsi':          rsi_val,
                'adx':          adx_val,
                'price_pattern': price_pattern,
                'price_pattern_score': price_pattern_score,
                'rel_1m':       rel_1m,
                'rel_3m':       rel_3m,
                'rvol':         rvol,
                'rvol_bullish': rvol_bullish,
                'sell_score':   sell_score,
                'exit_signal':  exit_signal,
                'current_pct':  current_pct,
                'entry_pct':    entry_pct,
                'sl_hit':       sl_hit,
                'tp_hit':       tp_hit,
                'action':       action,
                'action_style': action_style,
                'action_detail': action_detail,
                'triggers':     triggers,
                'is_leader':    is_leader,
                'is_laggard':   is_laggard,
                'cmf':          cmf_val,
            })
        except Exception as e:
            print(f"[ExitPlan] Error {item.symbol}: {e}")
            continue

    # เรียงตาม SELL Score สูงสุดก่อน
    items.sort(key=lambda x: x['sell_score'], reverse=True)

    # ====== Portfolio Health Summary ======
    urgent_count   = sum(1 for i in items if i['exit_signal'] in ('STRONG EXIT',) or i['sl_hit'])
    warning_count  = sum(1 for i in items if i['exit_signal'] == 'EXIT')
    watch_count    = sum(1 for i in items if i['exit_signal'] == 'WATCH')
    healthy_count  = sum(1 for i in items if not i['exit_signal'] and not i['sl_hit'])
    total_count    = len(items)
    avg_sell_score = round(sum(i['sell_score'] for i in items) / total_count, 1) if total_count else 0

    # Market Condition
    market_condition = {'phase': 'UNKNOWN', 'label': 'ไม่มีข้อมูล', 'color': 'secondary', 'score': 0}
    try:
        from datetime import datetime as _mcdt, timedelta as _mctd
        import pytz as _mcpytz
        _mc_bkk   = _mcpytz.timezone('Asia/Bangkok')
        _mc_now   = _mcdt.now(_mc_bkk)
        _mc_end   = _mc_now.date().strftime('%Y-%m-%d')
        _mc_start = (_mc_now.date() - _mctd(days=430)).strftime('%Y-%m-%d')
        _mc_df = yf.download("^SET", start=_mc_start, end=_mc_end, interval="1d", progress=False)
        if _mc_df is not None and not _mc_df.empty:
            if isinstance(_mc_df.columns, pd.MultiIndex):
                _mc_df.columns = _mc_df.columns.droplevel(1)
            market_condition = _get_market_condition(_mc_df)
    except Exception:
        pass

    return render(request, 'stocks/portfolio_exit_plan.html', {
        'items': items,
        'urgent_count':  urgent_count,
        'warning_count': warning_count,
        'watch_count':   watch_count,
        'healthy_count': healthy_count,
        'total_count':   total_count,
        'avg_sell_score': avg_sell_score,
        'market_condition': market_condition,
    })


# ====== Portfolio Management — เพิ่ม/ลบ รายการพอร์ต ======

@login_required
def add_to_portfolio(request):
    """
    รับ POST form เพิ่มหรืออัปเดต position ในพอร์ต
    ใช้ update_or_create เพื่อรองรับการแก้ไขข้อมูล (เช่น เพิ่ม quantity)
    """
    if request.method == 'POST':
        symbol = request.POST.get('symbol').upper()
        name = request.POST.get('name', '')
        quantity = request.POST.get('quantity', 0)
        entry_price = request.POST.get('entry_price', 0)
        category = request.POST.get('category', AssetCategory.STOCK)

        if symbol:
            # update_or_create: สร้างใหม่ หรืออัปเดตถ้ามี symbol นั้นอยู่แล้ว
            Portfolio.objects.update_or_create(
                user=request.user,
                symbol=symbol,
                defaults={
                    'name': name,
                    'quantity': quantity,
                    'entry_price': entry_price,
                    'category': category
                }
            )
            messages.success(request, f"เพิ่ม {symbol} เข้าพอร์ตเรียบร้อยแล้ว")
    return redirect('stocks:portfolio_list')

@login_required
def delete_from_portfolio(request, pk):
    """ลบรายการจากพอร์ต (เฉพาะ object ของ user ปัจจุบันเท่านั้น)"""
    item = get_object_or_404(Portfolio, pk=pk, user=request.user)
    symbol = item.symbol
    item.delete()
    messages.success(request, f"ลบ {symbol} ออกจากพอร์ตแล้ว")
    return redirect('stocks:portfolio_list')

@login_required
def sell_stock(request, pk):
    """
    จัดการการขายหุ้นพร้อมคำนวณกำไร/ขาดทุน
    """
    portfolio_item = get_object_or_404(Portfolio, pk=pk, user=request.user)
    
    if request.method == 'POST':
        try:
            qty_str = request.POST.get('quantity', '0')
            price_str = request.POST.get('sell_price', '0')
            
            sell_quantity = Decimal(qty_str)
            sell_price = Decimal(price_str)
            
            if sell_quantity <= 0 or sell_quantity > portfolio_item.quantity:
                messages.error(request, f"จำนวนหุ้นไม่ถูกต้อง (มีอยู่ {portfolio_item.quantity} หุ้น)")
                return redirect('stocks:portfolio_list')
            
            # คำนวณกำไร/ขาดทุน
            cost_of_sold_shares = sell_quantity * portfolio_item.entry_price
            sell_revenue = sell_quantity * sell_price
            profit_loss = sell_revenue - cost_of_sold_shares
            profit_loss_pct = (profit_loss / cost_of_sold_shares * 100) if cost_of_sold_shares > 0 else 0
            
            # บันทึกประวัติการขาย
            SoldStock.objects.create(
                user=request.user,
                symbol=portfolio_item.symbol,
                quantity=sell_quantity,
                buy_price=portfolio_item.entry_price,
                sell_price=sell_price,
                profit_loss=profit_loss,
                profit_loss_pct=profit_loss_pct
            )
            
            # อัปเดตพอร์ต
            portfolio_item.quantity -= sell_quantity
            if portfolio_item.quantity <= 0:
                portfolio_item.delete()
                messages.success(request, f"ขาย {portfolio_item.symbol} เรียบร้อยแล้ว (ปิดสถานะ)")
            else:
                portfolio_item.save()
                messages.success(request, f"ขาย {portfolio_item.symbol} จำนวน {sell_quantity} หุ้น เรียบร้อยแล้ว")
                
        except (ValueError, Exception) as e:
            messages.error(request, f"เกิดข้อผิดพลาด: {str(e)}")
            
    return redirect('stocks:portfolio_list')

# ====== Recommendations — คำแนะนำหุ้นรายวันจาก AI ======

@login_required
def recommendations(request):
    """
    Thai Stock Recommendations with Legendary 5-Pillar Scoring.
    Implements Manual Scan and Persistence (AnalysisCache).
    """
    import random
    import json
    from datetime import datetime
    import pandas as pd
    import pandas_ta as ta
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor

    def process_single_stock(sym):
        try:
            t = yf.Ticker(sym)
            try:
                inf = t.info
                if not isinstance(inf, dict): inf = {}
            except:
                inf = {}
            
            hist_short = t.history(period="6mo")
            
            # If sym without .BK fails, try with .BK
            if (not inf or hist_short.empty) and ".BK" not in sym:
                try:
                    alt_t = yf.Ticker(f"{sym}.BK")
                    alt_inf = alt_t.info
                    alt_hist = alt_t.history(period="6mo")
                    if isinstance(alt_inf, dict) and alt_inf:
                        t = alt_t
                        inf = alt_inf
                        hist_short = alt_hist
                except: pass

            rsi_val = 'N/A'
            rvol = 1.0
            if not hist_short.empty:
                rsi_series = ta.rsi(hist_short['Close'], length=14)
                if rsi_series is not None and not rsi_series.empty:
                    rsi_val = float(rsi_series.iloc[-1])
                current_vol = float(hist_short['Volume'].iloc[-1])
                avg_vol_20 = float(hist_short['Volume'].tail(20).mean())
                rvol = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

            de = 'N/A'
            try:
                bs = t.quarterly_balance_sheet if not t.quarterly_balance_sheet.empty else t.balance_sheet
                if not bs.empty:
                    col = bs.columns[0]
                    tot_liab = bs.loc['Total Liabilities Net Minority Interest', col] if 'Total Liabilities Net Minority Interest' in bs.index else bs.loc['Total Liabilities', col]
                    tot_eq = bs.loc['Stockholders Equity', col] if 'Stockholders Equity' in bs.index else bs.loc['Total Equity Gross Minority Interest', col]
                    de = tot_liab / tot_eq
            except: pass

            if de == 'N/A' or pd.isna(de):
                de = inf.get('debtToEquity', 'N/A')
                if isinstance(de, (int, float)): de = de / 100

            def scale_to_percent(val):
                if not isinstance(val, (int, float)): return val
                if abs(val) < 1.0: return val * 100
                return val

            pe = inf.get('trailingPE')
            pb = inf.get('priceToBook')
            peg = inf.get('pegRatio')
            roe = scale_to_percent(inf.get('returnOnEquity'))
            dy = scale_to_percent(inf.get('dividendYield'))
            npm = scale_to_percent(inf.get('profitMargins'))
            bv = inf.get('bookValue')
            price = inf.get('currentPrice') or inf.get('regularMarketPrice')

            p_graham = 0; p_buffett = 0; p_lynch = 0; p_greenblatt = 0; p_templeton = 0
            if isinstance(pe, (int, float)) and pe < 15: p_graham += 7
            if isinstance(pb, (int, float)) and pb < 1.2: p_graham += 7
            if isinstance(de, (int, float)) and de < 1.0: p_graham += 6
            fcf = inf.get('freeCashflow')
            if isinstance(roe, (int, float)) and roe > 18: p_buffett += 8
            if isinstance(fcf, (int, float)) and fcf > 0: p_buffett += 7
            if isinstance(npm, (int, float)) and npm > 10: p_buffett += 5
            eg = inf.get('earningsGrowth')
            if isinstance(peg, (int, float)) and 0 < peg < 1.0: p_lynch += 12
            elif isinstance(peg, (int, float)) and 0 < peg < 1.5: p_lynch += 8
            if isinstance(eg, (int, float)) and eg > 0.20: p_lynch += 8
            ev = inf.get('enterpriseValue'); ebitda = inf.get('ebitda')
            if ev and ebitda:
                ey = ebitda / ev
                if ey > 0.12: p_greenblatt += 10
            if isinstance(roe, (int, float)) and roe > 15: p_greenblatt += 10
            if isinstance(pe, (int, float)) and pe < 10: p_templeton += 10

            final_score = (p_graham * 0.75) + (p_buffett * 0.75) + (p_lynch * 2.0) + (p_greenblatt * 1.0) + (p_templeton * 0.5)
            momentum_bonus = 0
            if isinstance(rsi_val, (int, float)) and 30 <= rsi_val <= 50: momentum_bonus += 5
            if rvol > 1.2: momentum_bonus += 5
            final_score = min(100, final_score + momentum_bonus)

            ev_spread = (roe - 10.0) if isinstance(roe, (int, float)) else None
            
            # ====== ENHANCED VALUATION FRAMEWORK (Thai Market) ======
            # วิธีที่ใช้: 3 วิธีผสมกันแบบ Weighted Average
            #   1. Graham Number       — พื้นฐานราคาตามทรัพย์สิน
            #   2. Graham Revised      — คำนึงถึง Growth + Bond Yield (สูตรทองของ Graham)
            #   3. DCF (FCF-based)     — มูลค่าจากกระแสเงินสดอิสระ (multiplier ปรับตาม Growth)
            v_graham = None; v_graham_rev = None; v_dcf = None
            fair_value = None; upside = None; mos_price = None

            # ใช้ Forward EPS ก่อน (มองไปข้างหน้า) ถ้าไม่มีให้ใช้ Trailing EPS
            eps = inf.get('forwardEps') or inf.get('trailingEps') or (price / pe if pe and pe > 0 and price else 0)
            bv = inf.get('bookValue') or 0
            # เฉลี่ย Earnings Growth + Revenue Growth เพื่อลด noise
            eg = inf.get('earningsGrowth') or 0
            rg = inf.get('revenueGrowth') or 0
            raw_growth = ((eg + rg) / 2) if eg and rg else (eg or rg or 0.10)
            fcf = inf.get('freeCashflow')
            shares = inf.get('sharesOutstanding')

            # Bond Yield ของไทย (ใช้ค่าประมาณ Thai 10-yr Govt Bond)
            THAI_BOND_YIELD = 3.0

            import math
            try:
                # 1. Graham Number: √(22.5 × EPS × Book Value)
                #    เหมาะกับหุ้นที่มีทรัพย์สินมาก (Banks, Property, Industrial)
                if isinstance(eps, (int, float)) and eps > 0 and isinstance(bv, (int, float)) and bv > 0:
                    v_graham = math.sqrt(22.5 * eps * bv)

                # 2. Graham Revised: EPS × (8.5 + 2g) × (4.4 / bond_yield)
                #    สูตรดั้งเดิมของ Graham ที่ปรับด้วย Bond Yield เพื่อสะท้อนสภาพดอกเบี้ย
                g_rate = min(25, max(3, raw_growth * 100 if raw_growth < 1 else raw_growth))
                bond_adj = 4.4 / THAI_BOND_YIELD  # ปรับตามดอกเบี้ย (สูงกว่า 1.0 เมื่อ yield ต่ำ)
                if isinstance(eps, (int, float)) and eps > 0:
                    v_graham_rev = eps * (8.5 + 2 * g_rate) * bond_adj

                # 3. FCF-based DCF: (FCF/Share) × Multiplier
                #    Multiplier ปรับตาม Growth Rate (growth สูง = มูลค่าในอนาคตสูงกว่า)
                if fcf and shares and shares > 0:
                    fcf_per_share = fcf / shares
                    if fcf_per_share > 0:
                        fcf_multiple = 20 if g_rate > 15 else (15 if g_rate >= 7 else 12)
                        v_dcf = fcf_per_share * fcf_multiple

                # รวม 3 วิธีด้วย Weighted Average (Graham Rev มีน้ำหนักมากสุด)
                weighted_sum = 0.0; total_weight = 0.0
                if v_graham and v_graham > 0:
                    weighted_sum += v_graham * 1.0; total_weight += 1.0
                if v_graham_rev and v_graham_rev > 0:
                    weighted_sum += v_graham_rev * 2.0; total_weight += 2.0
                if v_dcf and v_dcf > 0:
                    weighted_sum += v_dcf * 1.5; total_weight += 1.5

                if total_weight > 0:
                    fair_value = weighted_sum / total_weight
                elif bv > 0:
                    fair_value = bv * 0.9  # Fallback: 90% ของ Book Value

                if fair_value and price and price > 0:
                    fair_value = min(fair_value, price * 3.0)  # Cap ที่ 200% upside
                    upside = ((fair_value / price) - 1) * 100
                    mos_price = fair_value * 0.75  # ราคาที่ควรซื้อ = Fair Value - 25% Margin of Safety
            except: pass

            return {
                'symbol': sym, 'name': inf.get('longName', sym),
                'pe': pe, 'pb': pb, 'roe': roe, 'dy': dy, 'npm': npm, 'de': de,
                'rsi': rsi_val, 'peg': peg, 'price': price, 'rvol': round(rvol, 2),
                'ev_spread': ev_spread,
                'fair_value': round(fair_value, 2) if fair_value else None,
                'mos_price': round(mos_price, 2) if mos_price else None,
                'upside': round(upside, 1) if upside else None,
                'value_score': round(final_score, 1),
                'legendary': {'graham': p_graham, 'buffett': p_buffett, 'lynch': p_lynch, 'greenblatt': p_greenblatt, 'templeton': p_templeton}
            }
        except: return None

    cache_symbol = 'THAI_REC_ALL'
    cached_data = AnalysisCache.objects.filter(user=request.user, symbol=cache_symbol).first()
    
    stock_previews = []
    last_scanned = None
    if cached_data:
        try:
            stock_previews = json.loads(cached_data.analysis_data)
            last_scanned = cached_data.last_updated
        except: pass

    # If manual scan is requested
    if request.GET.get('scan') == 'true':
        set100_pool = [
            'ADVANC.BK', 'AOT.BK', 'AWC.BK', 'BANPU.BK', 'BBL.BK', 'BDMS.BK', 'BEM.BK', 'BGRIM.BK', 'BH.BK', 'BJC.BK',
            'BTS.BK', 'CBG.BK', 'CENTEL.BK', 'COM7.BK', 'CPALL.BK', 'CPAXT.BK', 'CPF.BK', 'CPN.BK', 'CRC.BK', 'DELTA.BK',
            'EA.BK', 'EGCO.BK', 'GLOBAL.BK', 'GPSC.BK', 'GULF.BK', 'HMPRO.BK', 'INTUCH.BK', 'IRPC.BK', 'IVL.BK', 'JMART.BK',
            'JMT.BK', 'KBANK.BK', 'KCE.BK', 'KKP.BK', 'KTB.BK', 'KTC.BK', 'LH.BK', 'MINT.BK', 'MTC.BK', 'OR.BK',
            'OSP.BK', 'PTT.BK', 'PTTEP.BK', 'PTTGC.BK', 'RATCH.BK', 'SCB.BK', 'SCC.BK', 'SCGP.BK', 'TISCO.BK', 'TOP.BK',
            'TRUE.BK', 'TTB.BK', 'TU.BK', 'WHA.BK', 'AMATA.BK', 'AP.BK', 'BAM.BK', 'BCH.BK', 'BCP.BK', 'BCPG.BK',
            'BLA.BK', 'BPP.BK', 'CHG.BK', 'CK.BK', 'CKP.BK', 'DOHOME.BK', 'ERW.BK', 'FORTH.BK', 'GUNKUL.BK', 'HANA.BK',
            'ICHI.BK', 'ITC.BK', 'M.BK', 'MBK.BK', 'MEGA.BK', 'ORI.BK', 'PLANB.BK', 'PRM.BK', 'PSL.BK', 'PTG.BK',
            'QH.BK', 'RCL.BK', 'ROJNA.BK', 'RS.BK', 'SABINA.BK', 'SAWAD.BK', 'SINGER.BK', 'SIRI.BK', 'SPALI.BK', 'SPRC.BK',
            'STA.BK', 'STEC.BK', 'STGT.BK', 'SUPER.BK', 'TASCO.BK', 'TCAP.BK', 'THANI.BK', 'THCOM.BK', 'THG.BK', 'TIDLOR.BK',
            'TKN.BK', 'TLI.BK', 'TOA.BK', 'TPIPL.BK', 'TPIPP.BK', 'TQM.BK', 'TTA.BK', 'VGI.BK', 'WHAUP.BK'
        ]
        mai_pool = [
            'SPA.BK', 'AU.BK', 'D.BK', 'CHAYO.BK', 'YGG.BK', 'BE8.BK', 'BBIK.BK', 'SNNP.BK', 'TNP.BK', 'TACC.BK',
            'SICT.BK', 'ADD.BK', 'ABM.BK', 'CHO.BK', 'PSTC.BK', 'TVDH.BK', 'NDR.BK', 'BOL.BK', 'IP.BK', 'PLANET.BK'
        ]
        full_pool = set100_pool + mai_pool
        candidate_symbols = random.sample(full_pool, min(100, len(full_pool))) # Limit to 100 for speed
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            scanned_list = list(filter(None, executor.map(process_single_stock, candidate_symbols)))
        
        # Save to Cache
        scanned_list = sorted(scanned_list, key=lambda x: x['value_score'], reverse=True)
        AnalysisCache.objects.update_or_create(
            user=request.user, symbol=cache_symbol,
            defaults={'analysis_data': json.dumps(scanned_list)}
        )
        stock_previews = scanned_list
        last_scanned = datetime.now()


    # Generate Report
    report_text = None
    if request.GET.get('analyze') == 'true' and stock_previews:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        data_str = "\n".join([f"{s['symbol']} Price:{s['price']} Score:{s['value_score']} PEG:{s['peg']}" for s in stock_previews[:30]])
        prompt = f"""คุณคือนักวิเคราะห์หุ้นที่เน้น Maximum Returns ในปี 2026 โดยใช้สไตล์ Peter Lynch (GARP) และ Greenblatt (Magic Formula) เป็นหลัก
        นี่คือข้อมูลหุ้น 30 อันดับแรก:
        {data_str}
        โปรดวิเคราะห์หุ้นที่น่าเข้าซื้อที่สุดสำหรับปี 2026 ภายใต้ธีม AI และ พลังงานสะอาด เขียนรายงานภาษาไทยแบบมืออาชีพ เจาะลึกรายตัวท็อป 10"""
        try:
            response = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
            report_text = response.text
            if report_text.startswith("```markdown"): report_text = report_text[11:].strip()
            if report_text.endswith("```"): report_text = report_text[:-3].strip()
        except Exception as e: report_text = f"Error: {e}"

    context = {
        'title': 'AI Thai Stock Recommendations',
        'report': report_text,
        'stocks': stock_previews,
        'market': 'thai',
        'last_scanned': last_scanned
    }
    return render(request, 'stocks/recommendations.html', context)


@login_required
def us_recommendations(request):
    """
    US Stock Recommendations with Manual Scan and Persistence.
    """
    import random
    import json
    from datetime import datetime
    import pandas as pd
    import pandas_ta as ta

    cache_symbol = 'US_REC_ALL'
    cached_data = AnalysisCache.objects.filter(user=request.user, symbol=cache_symbol).first()
    
    stock_previews = []
    last_scanned = None
    if cached_data:
        try:
            stock_previews = json.loads(cached_data.analysis_data)
            last_scanned = cached_data.last_updated
        except: pass

    if request.GET.get('scan') == 'true':
        full_pool = [
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B', 'UNH', 'JNJ',
            'XOM', 'JPM', 'V', 'PG', 'MA', 'CVX', 'HD', 'PFE', 'ABBV', 'KO',
            'PEP', 'COST', 'MCD', 'WMT', 'DIS', 'ADBE', 'CRM', 'NFLX', 'AMD', 'INTC',
            'QCOM', 'TXN', 'AMAT', 'MU', 'LRCX', 'AVGO', 'NKE', 'TMUS', 'SBUX', 'LOW',
            'UPS', 'CAT', 'GE', 'HON', 'DE', 'MMM', 'LMT', 'BA', 'RTX', 'T'
        ]
        candidate_symbols = random.sample(full_pool, min(50, len(full_pool)))
        
        scanned_list = []
        for sym in candidate_symbols:
            try:
                t = yf.Ticker(sym)
                inf = t.info
                hist = t.history(period="6mo")
                if hist.empty: continue
                
                rsi_series = ta.rsi(hist['Close'], length=14)
                rsi_val = float(rsi_series.iloc[-1]) if rsi_series is not None and not rsi_series.empty else None
                current_vol = float(hist['Volume'].iloc[-1])
                avg_vol_20 = float(hist['Volume'].tail(20).mean())
                rvol = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

                def scale_to_percent(val):
                    if not isinstance(val, (int, float)): return val
                    if abs(val) < 1.0: return val * 100
                    return val

                pe = inf.get('trailingPE')
                pb = inf.get('priceToBook')
                peg = inf.get('pegRatio')
                roe = scale_to_percent(inf.get('returnOnEquity'))
                dy = scale_to_percent(inf.get('dividendYield'))
                npm = scale_to_percent(inf.get('profitMargins'))
                price = inf.get('currentPrice') or inf.get('regularMarketPrice')
                de = inf.get('debtToEquity')
                if isinstance(de, (int, float)) and de > 5: de = de / 100

                # 5 PILLARS v2 (US Focus)
                p_graham = 0; p_buffett = 0; p_lynch = 0; p_greenblatt = 0; p_templeton = 0
                
                if isinstance(pe, (int, float)) and pe < 18: p_graham += 7
                if isinstance(de, (int, float)) and de < 1.0: p_graham += 6
                
                fcf = inf.get('freeCashflow')
                if isinstance(roe, (int, float)) and roe > 20: p_buffett += 8
                if isinstance(fcf, (int, float)) and fcf > 0: p_buffett += 7
                
                eg = inf.get('earningsGrowth')
                if isinstance(peg, (int, float)) and 0 < peg < 1.0: p_lynch += 12
                if isinstance(eg, (int, float)) and eg > 0.15: p_lynch += 8
                
                ev = inf.get('enterpriseValue'); ebitda = inf.get('ebitda')
                if ev and ebitda:
                    ey = ebitda / ev
                    if ey > 0.10: p_greenblatt += 10
                if isinstance(roe, (int, float)) and roe > 15: p_greenblatt += 10
                
                if isinstance(pe, (int, float)) and pe < 12: p_templeton += 10
                if isinstance(pb, (int, float)) and pb < 1.2: p_templeton += 10

                final_score = (p_graham * 0.75) + (p_buffett * 0.75) + (p_lynch * 2.0) + (p_greenblatt * 1.0) + (p_templeton * 0.5)
                final_score = min(100, final_score + 5 if rvol > 1.2 else final_score)

                # Economic Profit (ROE - CoE 10%)
                ev_spread = None
                if isinstance(roe, (int, float)):
                    ev_spread = roe - 10.0

                # ====== ENHANCED VALUATION FRAMEWORK (US Market) ======
                # ใช้ 3 วิธีเหมือน Thai Framework แต่ Bond Yield อิง US 10-yr Treasury
                fair_value = None; upside = None; mos_price = None
                v_graham = None; v_graham_rev = None; v_dcf = None

                eps = inf.get('forwardEps') or inf.get('trailingEps') or (price / pe if pe and pe > 0 and price else 0)
                bv = inf.get('bookValue') or 0
                eg = inf.get('earningsGrowth') or 0
                rg = inf.get('revenueGrowth') or 0
                raw_growth = ((eg + rg) / 2) if eg and rg else (eg or rg or 0.10)
                fcf_us = inf.get('freeCashflow')
                shares_us = inf.get('sharesOutstanding')

                # Bond Yield ของสหรัฐฯ (US 10-yr Treasury — ประมาณ 4.4%)
                US_BOND_YIELD = 4.4

                if isinstance(eps, (int, float)):
                    import math
                    try:
                        g_rate = min(25, max(3, raw_growth * 100 if raw_growth < 1 else raw_growth))
                        bond_adj = 4.4 / US_BOND_YIELD  # ≈ 1.0 เมื่อ yield ปกติ

                        # 1. Graham Number
                        if eps > 0 and isinstance(bv, (int, float)) and bv > 0:
                            v_graham = math.sqrt(22.5 * eps * bv)

                        # 2. Graham Revised + Bond Yield adjustment
                        if eps > 0:
                            v_graham_rev = eps * (8.5 + 2 * g_rate) * bond_adj

                        # 3. DCF (FCF-based, dynamic multiplier)
                        if fcf_us and shares_us and shares_us > 0:
                            fcf_ps = fcf_us / shares_us
                            if fcf_ps > 0:
                                fcf_multiple = 20 if g_rate > 15 else (15 if g_rate >= 7 else 12)
                                v_dcf = fcf_ps * fcf_multiple

                        # Weighted Average (Graham Rev: น้ำหนัก 2, DCF: 1.5, Graham No.: 1)
                        ws = 0.0; tw = 0.0
                        if v_graham and v_graham > 0: ws += v_graham * 1.0; tw += 1.0
                        if v_graham_rev and v_graham_rev > 0: ws += v_graham_rev * 2.0; tw += 2.0
                        if v_dcf and v_dcf > 0: ws += v_dcf * 1.5; tw += 1.5

                        if tw > 0:
                            fair_value = ws / tw
                        elif bv > 0:
                            fair_value = bv * 0.7  # Fallback: 70% ของ Book Value

                        if fair_value and price and price > 0:
                            fair_value = min(fair_value, price * 3.0)  # Cap ที่ 200% upside
                            upside = ((fair_value / price) - 1) * 100
                            mos_price = fair_value * 0.75  # ราคาที่ควรซื้อ (25% Margin of Safety)
                    except: pass

                scanned_list.append({
                    'symbol': sym, 'name': inf.get('shortName', sym),
                    'pe': pe, 'pb': pb, 'roe': roe, 'dy': dy, 'npm': npm, 'de': de,
                    'rsi': rsi_val, 'peg': peg, 'price': price, 'rvol': round(rvol, 2),
                    'ev_spread': ev_spread,
                    'fair_value': round(fair_value, 2) if fair_value else None,
                    'mos_price': round(mos_price, 2) if mos_price else None,
                    'upside': round(upside, 1) if upside else None,
                    'value_score': round(final_score, 1),
                    'legendary': {'graham': p_graham, 'buffett': p_buffett, 'lynch': p_lynch, 'greenblatt': p_greenblatt, 'templeton': p_templeton}
                })
            except: continue
            
        scanned_list = sorted(scanned_list, key=lambda x: x['value_score'], reverse=True)
        AnalysisCache.objects.update_or_create(
            user=request.user, symbol=cache_symbol,
            defaults={'analysis_data': json.dumps(scanned_list)}
        )
        stock_previews = scanned_list
        last_scanned = datetime.now()

    report_text = None
    if request.GET.get('analyze') == 'true' and stock_previews:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        data_str = "\n".join([f"{s['symbol']} Price:{s['price']} Score:{s['value_score']} PEG:{s['peg']}" for s in stock_previews[:20]])
        prompt = f"คุณคือนักวิเคราะห์หุ้นอเมริกัน เน้น Maximum Returns ปี 2026 โดยใช้ Lynch และ Greenblatt สแกนหุ้น {data_str} โปรดสรุปตัวท็อปในธีม AI/Semiconductor/Energy ภาษาไทย"
        try:
            response = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
            report_text = response.text
        except: report_text = "Analysis service unavailable."

    context = {
        'title': 'AI US Stock Recommendations',
        'report': report_text,
        'stocks': stock_previews,
        'market': 'us',
        'last_scanned': last_scanned
    }
    return render(request, 'stocks/recommendations.html', context)



# ====== Macro Economy — ภาพรวมเศรษฐกิจมหภาคและสินค้าโภคภัณฑ์ ======

@login_required
def macro_economy(request):
    """
    ดึงข้อมูล SET Index, USD/THB, ทองคำ, น้ำมัน WTI/Brent
    แสดงกราฟย้อนหลัง 3 เดือน และวิเคราะห์ด้วย AI ตามคำขอ
    """
    # รายการข้อมูลมหภาคที่ต้องดึงพร้อม symbol Yahoo Finance
    macro_items = [
        {'id': 'set', 'name': 'SET Index (ดัชนีหุ้นไทย)', 'symbol': '^SET', 'unit': 'Points', 'desc': 'ดัชนีตลาดหลักทรัพย์แห่งประเทศไทย บ่งบอกสภาวะตลาดโดยรวม'},
        {'id': 'spx', 'name': 'S&P 500 (ตลาดหุ้นสหรัฐฯ)', 'symbol': '^GSPC', 'unit': 'Points', 'desc': 'ดัชนีหุ้นใหญ่ 500 ตัวของสหรัฐฯ สะท้อนภาพรวมตลาดโลก'},
        {'id': 'usdthb', 'name': 'USD/THB (อัตราแลกเปลี่ยน)', 'symbol': 'USDTHB=X', 'unit': 'THB', 'desc': 'ค่าเงินบาทเทียบดอลลาร์สิงคโปร์/สหรัฐฯ'},
        {'id': 'dxy', 'name': 'Dollar Index (DXY)', 'symbol': 'DX-Y.NYB', 'unit': 'Points', 'desc': 'ดัชนีดอลลาร์สหรัฐ บ่งบอกถึงกระแสเงินทุน (Fund Flow)'},
        {'id': 'us10y', 'name': 'US 10Y Bond Yield', 'symbol': '^TNX', 'unit': '%', 'desc': 'อัตราดอกเบี้ยพันธบัตรฯ 10 ปี สหรัฐฯ'},
        {'id': 'gold', 'name': 'Gold (ทองคำโลก)', 'symbol': 'GC=F', 'unit': 'USD/oz', 'desc': 'สินทรัพย์ปลอดภัยและตัววัดเงินเฟ้อ'},
        {'id': 'btc', 'name': 'Bitcoin (BTC-USD)', 'symbol': 'BTC-USD', 'unit': 'USD', 'desc': 'สินทรัพย์ดิจิทัล (Crypto) สะท้อนความกล้าเสี่ยง (Risk-on) ของตลาด'},
        {'id': 'wti', 'name': 'WTI Crude Oil (น้ำมันดิบ)', 'symbol': 'CL=F', 'unit': 'USD/bbl', 'desc': 'ต้นทุนพลังงานและเศรษฐกิจโลก'}
    ]

    data = []
    charts = {}

    # วนดึงข้อมูลราคาปัจจุบันและ % เปลี่ยนแปลงของแต่ละตัวชี้วัด
    for item in macro_items:
        try:
            t = yf.Ticker(item['symbol'])
            hist = t.history(period='3mo')
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
                prev_price = hist['Close'].iloc[-2]
                pct_change = ((current_price - prev_price) / prev_price) * 100

                # Chart data
                dates = [d.strftime('%Y-%m-%d') for d in hist.index]
                prices = [float(p) for p in hist['Close'].tolist()]

                charts[item['id']] = {
                    'labels': dates,
                    'values': prices
                }

                data.append({
                    'id': item['id'],
                    'name': item['name'],
                    'price': current_price,
                    'change': pct_change,
                    'is_up': pct_change >= 0,
                    'unit': item['unit'],
                    'desc': item['desc'],
                })
        except Exception:
            continue

    # ====== AI Macro Analysis — วิเคราะห์ภาพรวมเศรษฐกิจด้วย Gemini ======
    _MACRO_CACHE_KEY = 'MACRO_ECONOMY_V2'
    analysis_text = None
    analysis_last_updated = None

    # Load cached analysis on every page visit
    _cached = AnalysisCache.objects.filter(user=request.user, symbol=_MACRO_CACHE_KEY).first()
    if _cached:
        analysis_text = _cached.analysis_data
        analysis_last_updated = _cached.last_updated

    if request.GET.get('analyze') == 'true' and data:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        model_name_to_use = 'gemini-2.5-flash'

        # สร้าง string สรุปข้อมูลมหภาคเพื่อส่งให้ AI
        data_str = "\n".join([f"{d['name']}: {d['price']:.2f} ({d['change']:+.2f}%) - {d['desc']}" for d in data])
        prompt = f"""
        คุณคือผู้เชี่ยวชาญด้านเศรษฐศาสตร์มหาภาค (Senior Economist) และนักกลยุทธ์การลงทุนระดับโลก (Global Investment Strategist) 
        จงวิเคราะห์ข้อมูลตลาดปัจจุบันด้านล่างนี้ และสรุปภาพรวมเศรษฐกิจและการลงทุนให้มีความลุ่มลึกระดับสถาบัน:
        
        [Market Data Summary]:
        {data_str}

        โปรดเขียนรายงาน "Global Investment Outlook & Asset Allocation" เป็นภาษาไทย โดยมีหัวข้อดังนี้:
        1. **Fund Flow & Risk Appetite**: วิเคราะห์ความสัมพันธ์ของ DXY, Bond Yield เเละ Bitcoin ตอนนี้ตลาดอยู่ในภาวะ Risk-on (กล้าเสี่ยง) หรือ Risk-off (กลัว) เงินกำลังไหลออกจากตลาดหุ้นไปสู่หลุมหลบภัย (Gold) หรือไหลเข้าสู่ระบบใหม่ (Crypto)?
        2. **US vs Thai Market Direction**: วิเคราะห์เปรียบเทียบตลาดหุ้นสหรัฐฯ (S&P 500) และไทย (SET) ทิศทางเป็นอย่างไร? มีปัจจัยอะไรที่สวนทางกันหรือไม่?
        3. **Asset Allocation (การจัดพอร์ตแนะนำ)**: แนะนำสัดส่วนการลงทุนที่เหมาะสมใน 'ตอนนี้' (เช่น หุ้นกี่ %, ทองคำกี่ %, คริปโตกี่ %, เงินสดกี่ %) โดยอ้างอิงจากความเสี่ยงเศรษฐกิจมหาภาค
        4. **Deep Dive: Gold & Crypto**: เจาะลึกทองคำและบิทคอยน์ในฐานะสินทรัพย์ทางเลือก (Alternative Assets) ในสภาวะปัจจุบันควรสะสม, ถือเฉยๆ หรือหาจังหวะขาย?
        5. **Sector Strategy (US & Thai)**: เจาะกลุ่มอุตสาหกรรมโดดเด่น:
           - **US Sectors**: แนะนำกลุ่มที่น่าสนใจในตลาดสหรัฐฯ (เช่น Tech, Healthcare, Energy) พร้อมตัวอย่างบริษัทยักษ์ใหญ่
           - **Thai Sectors**: แนะนำกลุ่ม Winner ในไทย (เช่น Tourism, Export, Banking) พร้อมระบุรายชื่อหุ้น 3-5 ตัว
        6. **Strategic Summary (1-3 Months Outlook)**: สรุปกลยุทธ์สั้นๆ 1-3 เดือนข้างหน้าว่าควรโฟกัสที่จุดใดมากที่สุด

        ข้อกำหนดการตอบ:
        - ใช้โทนเสียงระดับมืออาชีพ น่าเชื่อถือ (Institutional Tone)
        - ใช้ Markdown จัดรูปแบบให้สวยงาม (ใช้ตารางเเนะนำ Asset Allocation จะดีมาก)
        - ห้ามมีคำเกริ่นนำหรือคำส่งท้าย
        - ส่งออกมาเป็น Raw Markdown เท่านั้น
        """

        try:
            response = client.models.generate_content(
                model=model_name_to_use,
                contents=prompt
            )
            analysis_text = response.text or ""

            # ลบ markdown block wrapper ถ้า AI ไม่ปฏิบัติตาม prompt
            # Strip any residual markdown blocks if AI disobeys
            if analysis_text.startswith("```markdown"):
                analysis_text = analysis_text[len("```markdown"):].strip()
            if analysis_text.endswith("```"):
                analysis_text = analysis_text[:-3].strip()
            if not analysis_text:
                analysis_text = "ไม่สามารถรับผลจาก AI ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง"

            # Save to cache so user can read it on next visit
            obj, _ = AnalysisCache.objects.update_or_create(
                user=request.user,
                symbol=_MACRO_CACHE_KEY,
                defaults={'analysis_data': analysis_text}
            )
            analysis_last_updated = obj.last_updated

        except Exception as e:
            analysis_text = f"ไม่สามารถสร้างบทวิเคราะห์ได้ในขณะนี้: {str(e)}"

    context = {
        'title': 'Macro Economy & Commodities',
        'data': data,
        'analysis': analysis_text,
        'analysis_last_updated': analysis_last_updated,
        # ส่ง charts data เป็น JSON string สำหรับ JavaScript
        'charts_json': json.dumps(charts)
    }
    return render(request, 'stocks/macro.html', context)

# ====== Momentum Scanner — สแกนหาหุ้น SET100+MAI ตามเกณฑ์ Trend Template ======

@login_required
def momentum_scanner(request):
    """
    Globally scans SET100 roughly matching Mark Minervini Trend Template.
    Requires significant processing time, might be better offloaded in prod,
    but done synchronously here for demonstration.

    เกณฑ์การคัดกรอง:
    1. ราคาต้องยืนเหนือ EMA200 (Long Term Uptrend)
    2. ราคาต้องอยู่ภายใน 40% ของ 52-Week High (Near High Filter)
    3. คำนวณ Technical Score รวม RSI, RVOL, EMA alignment
    4. หา Supply & Demand Zone สำหรับ Sniper Entry
    """
    # โหลดรายชื่อหุ้นที่จะสแกนจาก database
    # Load symbols from database
    scan_symbols = ScannableSymbol.objects.filter(is_active=True).values_list('symbol', flat=True)

    # ถ้า DB ว่างเปล่า ให้ refresh รายชื่อหุ้นอัตโนมัติ (Self-healing)
    # If DB is empty, trigger a refresh immediately (Self-healing)
    if not scan_symbols:
        refresh_set100_symbols()
        scan_symbols = ScannableSymbol.objects.filter(is_active=True).values_list('symbol', flat=True)

    candidates = []

    # สแกนเฉพาะเมื่อผู้ใช้กด POST หรือส่ง ?scan=true เพื่อลด load server
    # We only scan if requested to avoid huge load on every page visit
    if request.method == "POST" or request.GET.get('scan') == 'true':
        # ลบผลสแกนเก่าของ user นี้ก่อนเริ่มสแกนใหม่
        # Clear previous results for this user ONLY
        MomentumCandidate.objects.filter(user=request.user).delete()

        import pandas_ta as ta
        for symbol in scan_symbols:
            try:
                # Let yfinance handle internal auth
                print(f"Scanning {symbol}...")
                # ดึงข้อมูลราคา 1 ปีจาก yfinance (ต้องการอย่างน้อย 200 วัน สำหรับ EMA200)
                df = yf.download(f"{symbol}.BK", period="1y", interval="1d", progress=False)

                # ถ้า yfinance ล้มเหลว ลองใช้ yahooquery เป็น fallback
                if df is None or df.empty:
                    print(f"yfinance failed for {symbol}, trying yahooquery...")
                    try:
                        yq = YQTicker(f"{symbol}.BK")
                        df = yq.history(period="1y", interval="1d")
                        if isinstance(df, pd.DataFrame) and not df.empty:
                            # yahooquery returns a dataframe with [symbol, date] index.
                            df = df.reset_index()
                            if 'date' in df.columns:
                                df.set_index('date', inplace=True)
                            if 'symbol' in df.columns:
                                df.drop(columns=['symbol'], inplace=True)
                            # แปลงชื่อ columns ให้ตรงกับ yfinance (ตัวพิมพ์ใหญ่)
                            # Map columns to match yfinance (Capitalized)
                            df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
                            print(f"Successfully recovered {symbol} via yahooquery")
                    except Exception as yqe:
                        print(f"yahooquery also failed for {symbol}: {yqe}")

                if df is None or df.empty:
                    continue

                # จัดการ MultiIndex columns (เกิดขึ้นเมื่อ yfinance download หลาย ticker)
                if isinstance(df.columns, pd.MultiIndex):
                    # Flatten the columns by dropping the ticker level
                    df.columns = df.columns.droplevel(1)

                # กรองแถวที่ขาด Close หรือ High
                df = df.dropna(subset=['Close', 'High'])
                # ต้องการข้อมูลอย่างน้อย 150 วันสำหรับ EMA150
                if len(df) < 150:
                    continue

                # ====== คำนวณ Technical Indicators ======
                df['EMA50'] = ta.ema(df['Close'], length=50)
                df['EMA150'] = ta.ema(df['Close'], length=150)
                df['EMA200'] = ta.ema(df['Close'], length=200)
                df['RSI'] = ta.rsi(df['Close'], length=14)

                # คำนวณ ADX (Average Directional Index) — วัดความแรงของเทรนด์
                # ADX Calculation
                adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                if adx_df is not None and not adx_df.empty:
                    df = pd.concat([df, adx_df], axis=1)

                # คำนวณ MFI (Money Flow Index) — วัดแรงซื้อ/ขายตามวอลลุ่ม
                # Money Flow Index (MFI)
                mfi = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                df['MFI'] = mfi

                # คำนวณ Relative Volume (RVOL) — วอลลุ่มปัจจุบันเทียบค่าเฉลี่ย 20 วัน
                # Relative Volume (RVOL) - Current Volume vs 20-day Average
                avg_vol_20 = df['Volume'].rolling(window=20).mean()
                df['RVOL'] = df['Volume'] / avg_vol_20

                # ดึงค่าล่าสุดของทุก indicator
                # Extract last values
                last_row = df.iloc[-1]

                # ใช้ centralized utility function เพื่อความสม่ำเสมอระหว่าง scanner และ portfolio
                # Use centralized utility for consistent results across all pages
                from .utils import analyze_momentum_technical
                tech = analyze_momentum_technical(df)

                current_price = float(df['Close'].iloc[-1])
                # ราคาสูงสุดใน 252 วัน (ประมาณ 1 ปีทำการ)
                year_high = float(df['High'].tail(252).max())

                integrated_score = tech['score']
                rvol = tech['rvol']
                rsi = tech['rsi']
                ema200 = tech['ema200']

                # ดึงค่า MFI และ ADX จาก DataFrame โดยตรง (scanner-specific)
                # Scanner-specific indicators
                mfi_val = float(df['MFI'].iloc[-1]) if 'MFI' in df.columns and pd.notna(df['MFI'].iloc[-1]) else 0
                adx = float(df['ADX_14'].iloc[-1]) if 'ADX_14' in df.columns and pd.notna(df['ADX_14'].iloc[-1]) else 0
                gap_to_high = ((year_high - current_price) / current_price) * 100

                # ====== เกณฑ์กรองหุ้น (Relaxed Trend Template) ======
                # Base filter (Relaxed Trend Template)
                # 1. Price above EMA200 (Essential for long term uptrend)
                # 2. Within 40% of 52-week high
                is_uptrend = (current_price > ema200)
                near_high = (current_price >= year_high * 0.60)

                if is_uptrend and near_high:
                    print(f"MATCH FOUND: {symbol} (Score: {integrated_score})")
                    # ดึง sector และ fundamental เฉพาะหุ้นที่ผ่านเกณฑ์เพื่อประหยัดเวลา
                    # Fetching sector & fundamentals only for candidates to save time
                    sector = "Unknown"
                    eps_growth = 0.0
                    rev_growth = 0.0
                    fund_bonus = 0

                    try:
                        ticker = yf.Ticker(f"{symbol}.BK")
                        info = ticker.info
                        if isinstance(info, dict) and len(info) >= 5:
                            sector = info.get('sector', 'Other')

                            # ดึงการเติบโตของ EPS และรายได้ (แปลงเป็น %)
                            eps_growth = float(info.get('earningsQuarterlyGrowth', 0) or 0) * 100
                            rev_growth = float(info.get('revenueGrowth', 0) or 0) * 100
                        else:
                            sector = "N/A"
                            eps_growth = 0
                            rev_growth = 0

                        # บวกคะแนน bonus ตามเกณฑ์ CAN SLIM
                        # Fundamental Bonus (CAN SLIM Criteria)
                        if eps_growth >= 20: fund_bonus += 10  # EPS Growth > 20%
                        if rev_growth >= 10: fund_bonus += 10  # Revenue Growth > 10%
                    except Exception as e:
                        print(f"Fundamental fetch error for {symbol}: {e}")
                        pass

                    # ====== Supply & Demand Analysis (Sniper Entry) ======
                    sd_zone = find_supply_demand_zones(df)
                    entry_strat = ""
                    dz_start = None
                    dz_end = None
                    sz_start = None
                    sz_end = None
                    sl_price = None
                    rr_val = None

                    if sd_zone:
                        entry_strat = sd_zone['type']
                        dz_start = sd_zone['start']
                        dz_end = sd_zone['end']
                        sz_start = sd_zone['target']
                        sz_end = sd_zone['target'] * 1.02 # เพิ่ม 2% สำหรับ visual buffer
                        sl_price = sd_zone['stop_loss']
                        rr_val = sd_zone['rr_ratio']

                    # คำนวณ % ห่างจากราคาปัจจุบันถึงขอบบน Demand Zone
                    # Calculate Proximity to Zone
                    prox_val = 999.0
                    if dz_start:
                        if current_price <= dz_start:
                            prox_val = 0.0  # ราคาอยู่ใน Zone แล้ว
                        else:
                            prox_val = ((current_price - dz_start) / dz_start) * 100

                    # บันทึกผลการสแกนลง database
                    obj = MomentumCandidate.objects.create(
                        user=request.user,
                        symbol=symbol,
                        symbol_bk=f"{symbol}.BK",
                        sector=sector,
                        price=round(current_price, 2),
                        rsi=round(rsi, 2),
                        adx=round(adx, 2),
                        mfi=round(mfi_val, 2),
                        rvol=round(rvol, 2),
                        eps_growth=round(eps_growth, 2),
                        rev_growth=round(rev_growth, 2),
                        technical_score=int(integrated_score + fund_bonus),

                        entry_strategy=entry_strat,
                        demand_zone_start=dz_start,
                        demand_zone_end=dz_end,
                        supply_zone_start=sz_start,
                        supply_zone_end=sz_end,
                        stop_loss=sl_price,
                        risk_reward_ratio=rr_val,

                        year_high=round(year_high, 2),
                        upside_to_high=round(gap_to_high, 2),
                        zone_proximity=round(prox_val, 2)
                    )
                    candidates.append(obj)
            except Exception as e:
                import traceback
                print(f"!!! Error scanning {symbol}: {str(e)}")
                # traceback.print_exc()
                continue

    # ====== จัดเรียงผลการสแกนตาม parameter ที่ผู้ใช้เลือก ======
    # Define Sorting Logic
    sort_by = request.GET.get('sort', 'score')
    valid_sorts = {
        'symbol': 'symbol',
        'score': '-technical_score',
        'price': '-price',
        'rsi': '-rsi',
        'rvol': '-rvol',
        'eps': '-eps_growth',
        'rev': '-rev_growth',
        'gap': 'upside_to_high',
        'prox': 'zone_proximity',       # เรียงตามระยะห่างจาก Zone (น้อยสุดก่อน = ใกล้โซนสุด)
        'round_rr': '-risk_reward_ratio' # เรียงตาม RR Ratio (มากสุดก่อน)
    }
    order_field = valid_sorts.get(sort_by, '-technical_score')

    # ดึงผลสแกนล่าสุดของ user นี้จาก database
    candidates = MomentumCandidate.objects.filter(user=request.user).order_by(order_field)

    # หาเวลาสแกนล่าสุด
    # Get last scan time from the first candidate if available
    last_scan = MomentumCandidate.objects.filter(user=request.user).order_by('-scanned_at').first()
    scanned_at = last_scan.scanned_at if last_scan else None

    # ====== AI Insight — คัด Superperformance Stocks จากรายชื่อที่ผ่านเกณฑ์ ======
    ai_analysis = None
    if candidates and request.GET.get('analyze') == 'true':
        symbols_list = [c.symbol for c in candidates]
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            model_name_to_use = 'gemini-2.5-flash'

            # Prompt ให้ AI วิเคราะห์ข่าวและ Sentiment แล้วคัดหุ้น Superperformance
            prompt = f"""จากรายชื่อหุ้นใน SET ที่ผ่านเกณฑ์ Momentum ขาขึ้น (Trend Template) ณ ขณะนี้ ได้แก่:
{', '.join(symbols_list)}

ช่วยวิเคราะห์ข่าวล่าสุด แนวโน้มอุตสาหกรรม และ Sentiment ของตลาดไทยในสัปดาห์นี้
เพื่อคัดกรองว่าตัวไหนในกลุ่มนี้มีโอกาสเป็น 'Superperformance Stocks' (สไตล์ Mark Minervini) มากที่สุด
พร้อมอธิบายเหตุผลประกอบสั้นๆ และเน้นย้ำเรื่องจุดเสี่ยงที่ต้องระวัง

เขียนเป็นภาษาไทย รูปแบบ Markdown ที่เป็นทางการและสวยงาม สไตล์นักวิเคราะห์หุ้น المحترف
ไม่ต้องเกริ่นนำ ไม่ต้องลงท้าย
"""
            response = client.models.generate_content(
                model=model_name_to_use,
                contents=prompt
            )
            ai_analysis = response.text
            # ลบ markdown block wrapper ถ้า AI ไม่ปฏิบัติตาม prompt
            if ai_analysis.startswith("```markdown"):
                ai_analysis = ai_analysis[11:].strip()
            if ai_analysis.endswith("```"):
                ai_analysis = ai_analysis[:-3].strip()
        except Exception as e:
            ai_analysis = f"AI Error: {str(e)}"

    context = {
        'title': 'Global Momentum Scanner (CAN SLIM)',
        'candidates': candidates,
        'ai_analysis': ai_analysis,
        'scanned_at': scanned_at,
        'current_sort': sort_by,
        # has_scanned: แสดงตารางผลเมื่อมีการสแกน หรือมีข้อมูลเก่าอยู่แล้ว
        'has_scanned': request.method == "POST" or request.GET.get('scan') == 'true' or candidates.exists()
    }
    return render(request, 'stocks/momentum.html', context)


# ====== Market Condition Analyzer — วิเคราะห์สภาวะตลาด SET Index ======

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
        phase, color, label = 'UPTREND',    'success', 'ตลาดขาขึ้น — เหมาะสำหรับ Swing Buy'
    elif score >= 4:
        phase, color, label = 'RECOVERY',   'info',    'ตลาดฟื้นตัว — คัดเฉพาะหุ้นแข็งแกร่ง'
    elif score >= 1:
        phase, color, label = 'MIXED',      'warning', 'ตลาดผสม — เน้น Watchlist และ Risk Management'
    elif score >= -2:
        phase, color, label = 'CORRECTION', 'warning', 'ตลาดพักฐาน — ระวังสูง ลดขนาด Position'
    else:
        phase, color, label = 'DOWNTREND',  'danger',  'ตลาดขาลง — หลีกเลี่ยงการซื้อใหม่'

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

@login_required
def watchlist_item_toggle(request):
    """AJAX POST — เพิ่ม/ลบหุ้นออกจาก ScanWatchlistItem และส่งไปที่ Market Watchlist (สำหรับรับ Alert เข้า Telegram)"""
    import json
    from django.http import JsonResponse
    from .models import ScanWatchlistItem, Watchlist
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    try:
        data = json.loads(request.body)
    except (ValueError, KeyError):
        return JsonResponse({'error': 'invalid JSON'}, status=400)
    symbol = data.get('symbol', '').strip().upper()
    sector = data.get('sector', 'Unknown')
    if not symbol:
        return JsonResponse({'error': 'symbol required'}, status=400)
        
    obj, created = ScanWatchlistItem.objects.get_or_create(
        user=request.user, symbol=symbol,
        defaults={'sector': sector}
    )
    
    if not created:
        # ถ้ามีอยู่แล้ว สั่งลบออก (Un-toggle)
        obj.delete()
        # อนุโลมให้ลบออกจาก Market Watchlist ไปด้วยเลยเพื่อความสะดวก
        Watchlist.objects.filter(user=request.user, symbol=symbol).delete()
        return JsonResponse({'status': 'removed', 'symbol': symbol})
        
    # ถ้ายังไม่มี สั่งให้เพิ่มเข้าไปที่ฝั่ง Market Watchlist ด้วย (เพื่อให้ระบบ Telegram ส่องเป้าหมาย)
    Watchlist.objects.get_or_create(user=request.user, symbol=symbol)
    
    return JsonResponse({'status': 'added', 'symbol': symbol})


@login_required
def scan_watchlist_view(request):
    """แสดง Scan Watchlist พร้อม score ปัจจุบัน / รอบก่อน / delta / alert"""
    from .models import ScanWatchlistItem, PrecisionScanCandidate
    items = ScanWatchlistItem.objects.filter(user=request.user)

    runs = list(
        PrecisionScanCandidate.objects
        .filter(user=request.user)
        .values_list('scan_run', flat=True)
        .order_by('-scan_run')
        .distinct()[:2]
    )
    latest_run = runs[0] if len(runs) >= 1 else None
    prev_run   = runs[1] if len(runs) >= 2 else None

    latest_map = {c.symbol: c for c in PrecisionScanCandidate.objects.filter(user=request.user, scan_run=latest_run)} if latest_run else {}
    prev_map   = {c.symbol: c for c in PrecisionScanCandidate.objects.filter(user=request.user, scan_run=prev_run)}   if prev_run   else {}

    enriched = []
    for item in items:
        latest = latest_map.get(item.symbol)
        prev   = prev_map.get(item.symbol)
        cur_score  = latest.technical_score if latest else None
        prev_score = prev.technical_score   if prev   else None
        delta = (cur_score - prev_score) if (cur_score is not None and prev_score is not None) else None
        enriched.append({
            'watchlist':   item,
            'scan_data':   latest,
            'delta':       delta,
            'triggered':   cur_score is not None and cur_score >= item.alert_threshold,
        })

    return render(request, 'stocks/scan_watchlist.html', {
        'items':       enriched,
        'latest_run':  latest_run,
    })


# ====== Precision Momentum Scanner — เวอร์ชันกรองคุณภาพสูง ======

@login_required
def precision_momentum_scanner(request):
    """
    Precision Momentum Scanner — กรองคุณภาพสูงกว่า momentum_scanner
    ปรับปรุงจาก momentum_scanner:
    1. ERC ต้องมี Body + Volume > 1.5x avg (ทั้งสองเงื่อนไข)
    2. ADX >= 20 (กรองเทรนด์แข็งแกร่งเท่านั้น)
    3. Liquidity filter: avg 20d volume >= 500,000 หุ้น
    4. Supply target = 52-week high เสมอ
    5. ATR-based stop loss
    6. Direction-aware RVOL scoring
    7. เก็บประวัติ scan 3 รอบล่าสุด
    8. is_new_entry flag (หุ้นใหม่ vs ยังอยู่จากรอบก่อน)
    """
    from .models import PrecisionScanCandidate
    from .utils import analyze_momentum_technical_v2
    from django.utils import timezone as tz
    from yahooquery import Ticker as YQTicker

    scan_symbols = list(ScannableSymbol.objects.filter(is_active=True).values_list('symbol', flat=True))
    if not scan_symbols:
        refresh_set100_symbols()
        scan_symbols = list(ScannableSymbol.objects.filter(is_active=True).values_list('symbol', flat=True))

    # ====== AJAX Status Poll ======
    if request.GET.get('scan_status') == '1':
        from django.core.cache import cache as _cp
        from django.http import JsonResponse as _JR
        _key = f'precision_scan_{request.user.id}'
        _st = _cp.get(_key, {'state': 'idle'})
        if _st.get('state') == 'done':
            _cp.delete(_key)
        return _JR(_st)

    if request.method == "POST" and request.POST.get('action') == 'scan':
        from django.core.cache import cache as _cache_bg
        import threading

        user_id   = request.user.id
        cache_key = f'precision_scan_{user_id}'

        _cur = _cache_bg.get(cache_key, {})
        if _cur.get('state') == 'running':
            return redirect('stocks:precision_momentum_scanner')

        _cache_bg.set(cache_key, {'state': 'running', 'progress': 0, 'total': 0, 'phase': 'เตรียมข้อมูล…'}, timeout=900)

        def _run_precision_bg(uid, ckey, sym_list):
            try:
                import django
                django.setup()
                import pandas_ta as ta
                from datetime import datetime as _dt, timedelta as _td, time as _dtime
                import pytz as _pytz
                import concurrent.futures
                from django.contrib.auth import get_user_model
                from django.core.cache import cache as _cache
                from django.utils import timezone as tz
                from yahooquery import Ticker as YQTicker
                from .models import PrecisionScanCandidate
                from .utils import analyze_momentum_technical_v2

                User = get_user_model()
                user = User.objects.get(pk=uid)
                scan_run_time = tz.now()

                # ====== Pin Scan Date ======
                _bkk_tz = _pytz.timezone('Asia/Bangkok')
                _now_bkk = _dt.now(_bkk_tz)
                _t = _now_bkk.time()
                _morning_session   = _dtime(10,  0) <= _t <= _dtime(12, 30)
                _midday_break      = _dtime(12, 30) <  _t <  _dtime(14, 30)
                _afternoon_session = _dtime(14, 30) <= _t <= _dtime(16, 30)
                _pre_market        = _t < _dtime(10, 0)
                _market_day = (
                    _now_bkk.weekday() < 5 and
                    (_pre_market or _morning_session or _midday_break or _afternoon_session)
                )
                scan_end_date = (
                    (_now_bkk.date() - _td(days=1)) if _market_day else _now_bkk.date()
                )
                scan_end_str   = scan_end_date.strftime('%Y-%m-%d')
                scan_start_str = (scan_end_date - _td(days=400)).strftime('%Y-%m-%d')
                set_start_str  = (scan_end_date - _td(days=185)).strftime('%Y-%m-%d')

                # ดึง symbols รอบก่อนหน้า (is_new_entry)
                prev_run = (
                    PrecisionScanCandidate.objects
                    .filter(user=user)
                    .values_list('scan_run', flat=True)
                    .order_by('-scan_run')
                    .distinct()
                    .first()
                )
                prev_symbols = set()
                if prev_run:
                    prev_symbols = set(
                        PrecisionScanCandidate.objects
                        .filter(user=user, scan_run=prev_run)
                        .values_list('symbol', flat=True)
                    )

                # ====== SET Index ======
                set_1m_return = 0.0
                set_3m_return = 0.0
                try:
                    set_df = yf.download("^SET", start=set_start_str, end=scan_end_str, interval="1d", progress=False)
                    if set_df is not None and not set_df.empty:
                        if isinstance(set_df.columns, pd.MultiIndex):
                            set_df.columns = set_df.columns.droplevel(1)
                        set_close = set_df['Close'].dropna()
                        if len(set_close) >= 66:
                            set_1m_return = float((set_close.iloc[-1] - set_close.iloc[-22]) / set_close.iloc[-22] * 100)
                            set_3m_return = float((set_close.iloc[-1] - set_close.iloc[-66]) / set_close.iloc[-66] * 100)
                    import logging; logging.getLogger('stocks').info(f"[Precision] SET Index: 1m={set_1m_return:.2f}% 3m={set_3m_return:.2f}%")
                except Exception as e:
                    import logging; logging.getLogger('stocks').warning(f"[Precision] SET Index fetch failed: {e}")

                # ====== Pre-compute RS Rating ======
                _cache.set(ckey, {'state': 'running', 'progress': 0, 'total': len(sym_list), 'phase': 'คำนวณ RS Rating…'}, timeout=900)

                def _fetch_rs_return(sym):
                    try:
                        _df = yf.Ticker(f"{sym}.BK").history(start=scan_start_str, end=scan_end_str, interval="1d")
                        if _df is None or _df.empty:
                            return sym, None
                        if isinstance(_df.columns, pd.MultiIndex):
                            _df.columns = _df.columns.droplevel(1)
                        _close = _df['Close'].dropna()
                        n = len(_close)
                        if n >= 252:
                            q1 = float((_close.iloc[-1]   - _close.iloc[-64])  / abs(_close.iloc[-64])  * 100)
                            q2 = float((_close.iloc[-64]  - _close.iloc[-127]) / abs(_close.iloc[-127]) * 100)
                            q3 = float((_close.iloc[-127] - _close.iloc[-190]) / abs(_close.iloc[-190]) * 100)
                            q4 = float((_close.iloc[-190] - _close.iloc[-253]) / abs(_close.iloc[-253]) * 100)
                            return sym, q1 * 0.4 + q2 * 0.2 + q3 * 0.2 + q4 * 0.2
                        elif n >= 66:
                            return sym, float((_close.iloc[-1] - _close.iloc[-66]) / abs(_close.iloc[-66]) * 100)
                        return sym, None
                    except Exception:
                        return sym, None

                rs_returns_all = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as _ex:
                    _futs = {_ex.submit(_fetch_rs_return, s): s for s in sym_list}
                    for _f in concurrent.futures.as_completed(_futs):
                        _sym, _ret = _f.result()
                        if _ret is not None:
                            rs_returns_all[_sym] = _ret

                rs_ratings_map = {}
                if rs_returns_all:
                    _rs_ser = pd.Series(rs_returns_all)
                    rs_ratings_map = (_rs_ser.rank(pct=True) * 99).clip(0, 99).astype(int).to_dict()

                _cache.set(ckey, {'state': 'running', 'progress': 0, 'total': len(sym_list), 'phase': 'สแกนหุ้น…'}, timeout=900)

                def _process_precision_scan(symbol):
                    try:
                        # ใช้ yf.Ticker().history() แทน yf.download() เพราะ yf.download() 
                        # มีบั๊ก Thread-safety กรองข้อมูลข้าม Symbol กันเมื่อรันใน ThreadPool 
                        ticker_obj = yf.Ticker(f"{symbol}.BK")
                        df = ticker_obj.history(start=scan_start_str, end=scan_end_str, interval="1d")

                        if df is None or df.empty:
                            try:
                                yq = YQTicker(f"{symbol}.BK")
                                df = yq.history(start=scan_start_str, end=scan_end_str, interval="1d")
                                if isinstance(df, pd.DataFrame) and not df.empty:
                                    df = df.reset_index()
                                    if 'date' in df.columns:
                                        df.set_index('date', inplace=True)
                                    if 'symbol' in df.columns:
                                        df.drop(columns=['symbol'], inplace=True)
                                    df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low',
                                                       'close': 'Close', 'volume': 'Volume'}, inplace=True)
                            except Exception:
                                pass

                        if df is None or df.empty:
                            return None

                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(1)

                        df = df.dropna(subset=['Close', 'High'])
                        if len(df) < 200:
                            return None

                        # ====== Liquidity & Quality Filters (Institutional Grade) ======
                        avg_vol_20 = float(df['Volume'].tail(20).mean())
                        avg_close_20 = float(df['Close'].tail(20).mean())
                        avg_turnover_20 = avg_vol_20 * avg_close_20
                
                        # 1. Turnover >= 15M THB (ตัดหุ้นปั่นสภาพคล่องต่ำที่รายใหญ่เข้าลงทุนไม่ได้)
                        if avg_turnover_20 < 15_000_000:
                            return None
                    
                        # 2. Minimum Price >= 1.00 (ตัดหุ้น Penny Stocks ต่ำกว่า 1 บาท)
                        current_price = float(df['Close'].iloc[-1])
                        if current_price < 1.00:
                            return None
                    
                        # 3. RS Rating >= 70 (ต้องแข็งแกร่งกว่าหุ้น 70% ในตลาด)
                        rs_val = rs_ratings_map.get(symbol, 0)
                        if rs_val < 70:
                            return None

                        # ====== คำนวณ Indicators ======
                        df['EMA200'] = ta.ema(df['Close'], length=200)
                        df['EMA50'] = ta.ema(df['Close'], length=50)
                        df['RSI'] = ta.rsi(df['Close'], length=14)
                        adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                        if adx_df is not None and not adx_df.empty:
                            df = pd.concat([df, adx_df], axis=1)
                        mfi_series = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                        df['MFI'] = mfi_series

                        last_row = df.iloc[-1]
                        current_price = float(last_row['Close'])
                        ema200 = float(df['EMA200'].iloc[-1]) if pd.notna(df['EMA200'].iloc[-1]) else current_price
                        year_high = float(df['High'].tail(252).max())

                        # ====== ADX Filter (ผ่อนปรนให้หุ้นเพิ่งเริ่มเทรนด์) ======
                        adx_val = float(df['ADX_14'].iloc[-1]) if 'ADX_14' in df.columns and pd.notna(df['ADX_14'].iloc[-1]) else 0
                        if adx_val < 15:
                            # skipped (ADX < 15)
                            return None

                        # ====== Trend Template Filter ======
                        # รับหุ้นที่อยู่ไม่ต่ำกว่า 35% จาก 52w High — กรองขยะออก แต่ยังเปิดรับ reversal
                        near_high  = current_price >= year_high * 0.65
                        if not near_high:
                            return None

                        import logging; logger = logging.getLogger('stocks')
                        logger.debug(f"[Precision] MATCH: {symbol} (ADX:{adx_val:.1f})")

                        # ====== Precision Technical Analysis (v3) ======
                        tech = analyze_momentum_technical_v2(df)
                        integrated_score = tech['score']
                        rvol         = tech['rvol']
                        rsi          = tech['rsi']
                        rvol_bullish = tech['rvol_bullish']
                        sd_zone      = tech['sd_zone']
                        ema20_aligned_flag = tech.get('ema20_aligned', False)
                        ema20_slope_val    = tech.get('ema20_slope', 0.0)
                        ema20_rising_flag  = tech.get('ema20_rising', False)
                        hh_hl_flag         = tech.get('hh_hl_structure', False)

                        mfi_val = float(df['MFI'].iloc[-1]) if 'MFI' in df.columns and pd.notna(df['MFI'].iloc[-1]) else 0

                        # ====== MACD (12,26,9) — histogram + bullish crossover detection ======
                        macd_hist_val  = None
                        macd_cross_val = False
                        try:
                            macd_df = ta.macd(df['Close'], fast=12, slow=26, signal=9)
                            if macd_df is not None and not macd_df.empty:
                                hist_col = [c for c in macd_df.columns if 'h' in c.lower() or 'hist' in c.lower()]
                                macd_col = [c for c in macd_df.columns if c.lower().startswith('macd_')]
                                sig_col  = [c for c in macd_df.columns if 'macds' in c.lower() or 'signal' in c.lower()]
                                if hist_col:
                                    macd_hist_val = float(macd_df[hist_col[0]].iloc[-1]) if pd.notna(macd_df[hist_col[0]].iloc[-1]) else None
                                # Bullish crossover = MACD line crosses above signal line in last 3 bars
                                if macd_col and sig_col:
                                    m_ser = macd_df[macd_col[0]].dropna()
                                    s_ser = macd_df[sig_col[0]].dropna()
                                    if len(m_ser) >= 4 and len(s_ser) >= 4:
                                        # Check if MACD crossed above signal in last 3 candles
                                        for i in range(-3, 0):
                                            if m_ser.iloc[i-1] <= s_ser.iloc[i-1] and m_ser.iloc[i] > s_ser.iloc[i]:
                                                macd_cross_val = True
                                                break
                        except Exception:
                            pass

                        # ====== Bollinger Bands Squeeze — bandwidth in bottom 20th pct (pending breakout) ======
                        bb_squeeze_flag = False
                        try:
                            bb_df = ta.bbands(df['Close'], length=20, std=2)
                            if bb_df is not None and not bb_df.empty:
                                upper_col = [c for c in bb_df.columns if 'BBU' in c or 'upper' in c.lower()]
                                lower_col = [c for c in bb_df.columns if 'BBL' in c or 'lower' in c.lower()]
                                mid_col   = [c for c in bb_df.columns if 'BBM' in c or 'mid' in c.lower()]
                                if upper_col and lower_col and mid_col:
                                    bbu = bb_df[upper_col[0]].dropna()
                                    bbl = bb_df[lower_col[0]].dropna()
                                    bbm = bb_df[mid_col[0]].dropna()
                                    if len(bbu) >= 20:
                                        bw = (bbu - bbl) / bbm  # bandwidth ratio
                                        pct20 = bw.quantile(0.20)
                                        if float(bw.iloc[-1]) <= float(pct20):
                                            bb_squeeze_flag = True
                        except Exception:
                            pass

                        # ====== Stage 2 (Weinstein): price > SMA150 AND SMA150 rising ======
                        # Stage 2 = markup phase — หุ้นที่ผ่าน filter นี้อยู่ในช่วงที่ดีที่สุดสำหรับการซื้อ
                        stage2_flag = False
                        try:
                            sma150 = ta.sma(df['Close'], length=150)
                            if sma150 is not None:
                                sma150_clean = sma150.dropna()
                                if len(sma150_clean) >= 20:
                                    sma150_cur = float(sma150_clean.iloc[-1])
                                    sma150_4w  = float(sma150_clean.iloc[-20])  # ~4 สัปดาห์ก่อน
                                    stage2_flag = (current_price > sma150_cur) and (sma150_cur > sma150_4w)
                        except Exception:
                            pass

                        # ====== Fundamental Data (bulk-fetched after all threads complete) ======
                        # ตัวแปรเหล่านี้ไม่ถูกใช้ใน thread — bulk enrichment เป็นตัวทำใน step 2

                        # ====== Supply & Demand Zone ======
                        entry_strat = ""
                        dz_start = None
                        dz_end = None
                        sz_start = None
                        sz_end = None
                        sl_price = None
                        rr_val = None
                        erc_vol_confirmed = False
                        zone_target_src = '52w'

                        if sd_zone:
                            entry_strat = sd_zone['type']
                            dz_start = sd_zone['start']
                            dz_end = sd_zone['end']
                            sz_start = sd_zone['target']
                            sz_end = sd_zone['target'] * 1.02
                            sl_price = sd_zone['stop_loss']
                            rr_val = sd_zone['rr_ratio']
                            erc_vol_confirmed = sd_zone.get('erc_volume_confirmed', False)
                            zone_target_src = sd_zone.get('zone_target_source', '52w')

                        prox_val = 999.0
                        if dz_start:
                            if current_price <= dz_start:
                                prox_val = 0.0
                            else:
                                prox_val = ((current_price - dz_start) / dz_start) * 100

                        gap_to_high = ((year_high - current_price) / current_price) * 100

                        # ====== Pocket Pivot (Morales & Kacher) ======
                        # Up-day volume > highest down-day volume in prior 10 sessions
                        pocket_pivot_flag = False
                        try:
                            if len(df) >= 14:
                                closes = df['Close'].values
                                volumes = df['Volume'].values
                                for _i in [-1, -2]:
                                    if float(closes[_i]) <= float(closes[_i - 1]):
                                        continue  # not an up day
                                    _start = len(volumes) + _i - 10
                                    _end   = len(volumes) + _i
                                    if _start < 1:
                                        continue
                                    _prior_c = closes[_start:_end]
                                    _prior_v = volumes[_start:_end]
                                    _prior_prev_c = closes[_start - 1:_end - 1]
                                    _down_mask = _prior_c < _prior_prev_c
                                    if not _down_mask.any():
                                        continue
                                    _max_down_vol = float(_prior_v[_down_mask].max())
                                    if float(volumes[_i]) > _max_down_vol and _max_down_vol > 0:
                                        pocket_pivot_flag = True
                                        break
                        except Exception:
                            pass

                        # ====== Volume Dry-Up (VDU): เงียบสะสม — volume ลด 3 วันติด + ต่ำกว่า avg 70% ======
                        vdu_flag = False
                        try:
                            if len(df) >= 4:
                                _vols = df['Volume'].tail(4).values.astype(float)
                                _avg20 = float(df['Volume'].tail(20).mean())
                                _declining = (_vols[-1] < _vols[-2]) and (_vols[-2] < _vols[-3])
                                _quiet     = _vols[-1] < _avg20 * 0.7
                                vdu_flag   = _declining and _quiet
                        except Exception:
                            pass

                        # Price Pattern detection (ใช้ df ที่มีอยู่แล้ว)
                        pattern_result = detect_price_pattern(df)
                        pattern_name  = pattern_result['name']
                        pattern_score = pattern_result['score']

                        close_series = df['Close'].dropna()
                        rel_1m = rel_3m = 0.0
                        stock_3m_ret = 0.0
                        if len(close_series) >= 66:
                            stock_1m = float((close_series.iloc[-1] - close_series.iloc[-22]) / close_series.iloc[-22] * 100)
                            stock_3m = float((close_series.iloc[-1] - close_series.iloc[-66]) / close_series.iloc[-66] * 100)
                            stock_3m_ret = stock_3m
                            rel_1m = round(stock_1m - set_1m_return, 2)
                            rel_3m = round(stock_3m - set_3m_return, 2)
                        elif len(close_series) >= 22:
                            stock_1m = float((close_series.iloc[-1] - close_series.iloc[-22]) / close_series.iloc[-22] * 100)
                            rel_1m = round(stock_1m - set_1m_return, 2)

                        # Return dict instead of model to allow bulk fundamental enrichment and RS Ranking
                        return {
                            'symbol': symbol,
                            'price': round(current_price, 2),
                            'rsi': round(rsi, 2),
                            'adx': round(adx_val, 2),
                            'mfi': round(mfi_val, 2),
                            'rvol': round(rvol, 2),
                            'technical_score': int(integrated_score),
                            'avg_volume_20d': round(avg_vol_20, 0),
                            'rvol_bullish': rvol_bullish,
                            'erc_volume_confirmed': erc_vol_confirmed,
                            'zone_target_src': zone_target_src,
                            'entry_strat': entry_strat,
                            'dz_start': dz_start,
                            'dz_end': dz_end,
                            'sz_start': sz_start,
                            'sz_end': sz_end,
                            'sl_price': sl_price,
                            'rr_val': rr_val,
                            'year_high': round(year_high, 2),
                            'upside_to_high': round(gap_to_high, 2),
                            'prox_val': round(prox_val, 2),
                            'pattern_name': pattern_name,
                            'pattern_score': pattern_score,
                            'rel_1m': rel_1m,
                            'rel_3m': rel_3m,
                            'macd_histogram': round(macd_hist_val, 4) if macd_hist_val is not None else None,
                            'macd_crossover': macd_cross_val,
                            'bb_squeeze': bb_squeeze_flag,
                            'ema20_aligned': ema20_aligned_flag,
                            'ema20_slope': round(ema20_slope_val, 3),
                            'ema20_rising': ema20_rising_flag,
                            'hh_hl_structure': hh_hl_flag,
                            'stock_3m_ret': stock_3m_ret,
                            'rs_rating': rs_ratings_map.get(symbol, 0),
                            'stage2': stage2_flag,
                            'pocket_pivot': pocket_pivot_flag,
                            'vdu_near_zone': vdu_flag,
                            'cmf': tech.get('cmf', 0.0),
                            'is_52w_breakout': tech.get('is_52w_breakout', False),
                            'volume_surge': tech.get('volume_surge', 1.0),
                            'is_volume_surge': tech.get('is_volume_surge', False),
                        }

                    except Exception as e:
                        import logging
                        logging.getLogger('stocks').exception(f"[Precision] Error scanning {symbol}: {e}")
                        return None

                # ====== Scan all symbols with progress tracking ======
                results = []
                done_count = 0
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    futures = [executor.submit(_process_precision_scan, sym) for sym in sym_list]
                    for future in concurrent.futures.as_completed(futures):
                        res = future.result()
                        if res:
                            results.append(res)
                        done_count += 1
                        _cache.set(ckey, {
                            'state': 'running', 'progress': done_count,
                            'total': len(sym_list), 'phase': 'สแกนหุ้น…'
                        }, timeout=900)

                if results:
                    scan_df = pd.DataFrame(results)
                    if 'rs_rating' not in scan_df.columns:
                        scan_df['rs_rating'] = 0

                    _cache.set(ckey, {'state': 'running', 'progress': done_count, 'total': len(sym_list), 'phase': 'ดึงข้อมูล Fundamental…'}, timeout=900)

                    # ====== Bulk Fundamental Enrichment ======
                    matched_symbols = [r['symbol'] for r in results]
                    symbols_bk = [f"{s}.BK" for s in matched_symbols]
                    fund_data = {}
                    try:
                        yq_all = YQTicker(symbols_bk)
                        modules = yq_all.get_modules('financialData summaryProfile')
                        for sym_bk, data in modules.items():
                            if not isinstance(data, dict):
                                continue
                            clean_sym = sym_bk.replace('.BK', '')
                            profile  = data.get('summaryProfile', {})
                            fin_data = data.get('financialData', {})
                            sector   = (
                                profile.get('sector')
                                or data.get('assetProfile', {}).get('sector')
                                or 'Unknown'
                            )
                            eps_growth = float(fin_data.get('earningsQuarterlyGrowth', 0) or 0) * 100
                            rev_growth = float(fin_data.get('revenueGrowth', 0) or 0) * 100
                            fund_data[clean_sym] = {'sector': sector, 'eps_growth': eps_growth, 'rev_growth': rev_growth}
                    except Exception as e:
                        print(f"[Precision] Bulk Fundamental fetch failed: {e}")

                    # ====== Bulk Create ======
                    bulk_candidates = []
                    for r in scan_df.to_dict('records'):
                        sym = r['symbol']
                        f = fund_data.get(sym, {'sector': 'N/A', 'eps_growth': 0.0, 'rev_growth': 0.0})
                        bulk_candidates.append(PrecisionScanCandidate(
                            user=user,
                            scan_run=scan_run_time,
                            symbol=sym,
                            symbol_bk=f"{sym}.BK",
                            sector=f.get('sector') or 'Unknown',
                            price=r['price'],
                            rsi=r['rsi'],
                            adx=r['adx'],
                            mfi=r['mfi'],
                            rvol=r['rvol'],
                            eps_growth=round(f.get('eps_growth', 0), 2),
                            rev_growth=round(f.get('rev_growth', 0), 2),
                            technical_score=r['technical_score'],
                            rs_rating=r['rs_rating'],
                            avg_volume_20d=r['avg_volume_20d'],
                            rvol_bullish=r['rvol_bullish'],
                            erc_volume_confirmed=r['erc_volume_confirmed'],
                            zone_target_source=r['zone_target_src'],
                            is_new_entry=(sym not in prev_symbols),
                            entry_strategy=r['entry_strat'],
                            demand_zone_start=r['dz_start'],
                            demand_zone_end=r['dz_end'],
                            supply_zone_start=r['sz_start'],
                            supply_zone_end=r['sz_end'],
                            stop_loss=r['sl_price'],
                            risk_reward_ratio=r['rr_val'],
                            year_high=r['year_high'],
                            upside_to_high=r['upside_to_high'],
                            zone_proximity=r['prox_val'],
                            price_pattern=r['pattern_name'],
                            price_pattern_score=r['pattern_score'],
                            rel_momentum_1m=r['rel_1m'],
                            rel_momentum_3m=r['rel_3m'],
                            macd_histogram=r['macd_histogram'],
                            macd_crossover=r['macd_crossover'],
                            bb_squeeze=r['bb_squeeze'],
                            ema20_aligned=r['ema20_aligned'],
                            ema20_slope=r.get('ema20_slope', 0.0),
                            ema20_rising=r.get('ema20_rising', False),
                            hh_hl_structure=r.get('hh_hl_structure', False),
                            stage2=r.get('stage2', False),
                            pocket_pivot=r.get('pocket_pivot', False),
                            vdu_near_zone=r.get('vdu_near_zone', False),
                            cmf=r.get('cmf', None),
                            is_52w_breakout=r.get('is_52w_breakout', False),
                            volume_surge=r.get('volume_surge', 1.0),
                            is_volume_surge=r.get('is_volume_surge', False),
                        ))

                    if bulk_candidates:
                        PrecisionScanCandidate.objects.bulk_create(bulk_candidates)

                # เก็บ 3 รอบล่าสุด
                distinct_runs = (
                    PrecisionScanCandidate.objects
                    .filter(user=user)
                    .values_list('scan_run', flat=True)
                    .order_by('-scan_run')
                    .distinct()
                )
                runs_list = list(distinct_runs)
                if len(runs_list) > 3:
                    old_runs = runs_list[3:]
                    PrecisionScanCandidate.objects.filter(user=user, scan_run__in=old_runs).delete()

                _cache.set(ckey, {'state': 'done', 'count': len(results)}, timeout=300)

            except Exception as _bg_err:
                import logging
                logging.getLogger('stocks').exception(f"[PrecisionBG] Error: {_bg_err}")
                from django.core.cache import cache as _ec
                _ec.set(ckey, {'state': 'idle'}, timeout=60)

        # เปิด background thread แล้ว return ทันที
        _t = threading.Thread(
            target=_run_precision_bg,
            args=(user_id, cache_key, scan_symbols),
            daemon=True
        )
        _t.start()
        return redirect('stocks:precision_momentum_scanner')

    # ====== จัดเรียงผลลัพธ์ ======
    sort_by = request.GET.get('sort', 'score')
    valid_db_sorts = {
        'symbol': 'symbol',
        'score': '-technical_score',
        'price': '-price',
        'rsi': '-rsi',
        'rvol': '-rvol',
        'adx': '-adx',
        'prox': 'zone_proximity',
        'round_rr': '-risk_reward_ratio',
        'rs': '-rs_rating',          # RS Rating (Minervini Relative Strength)
    }
    use_db_sort = sort_by in valid_db_sorts
    order_field = valid_db_sorts.get(sort_by, '-technical_score')

    # รายชื่อ scan runs ทั้งหมด (index 0 = ล่าสุด)
    all_runs = list(
        PrecisionScanCandidate.objects
        .filter(user=request.user)
        .values_list('scan_run', flat=True)
        .order_by('-scan_run')
        .distinct()
    )

    # เลือกรอบสแกนตาม ?run_idx= (0 = ล่าสุด, 1 = ก่อนหน้า, ...)
    try:
        run_idx = int(request.GET.get('run_idx', 0))
    except (ValueError, TypeError):
        run_idx = 0
    run_idx = max(0, min(run_idx, len(all_runs) - 1)) if all_runs else 0

    candidates = []
    scanned_at = None
    if all_runs:
        selected_run = all_runs[run_idx]
        qs = PrecisionScanCandidate.objects.filter(user=request.user, scan_run=selected_run)
        if use_db_sort:
            qs = qs.order_by(order_field)
        candidates = list(qs)
        scanned_at = selected_run

        # ====== Live Price Fetch (ถ้าตลาดเปิด) — แสดงราคาปัจจุบันคู่กับราคา close เมื่อวาน ======
        # Indicator ยังคำนวณจาก settled close (คงที่), live price ใช้แสดงเท่านั้น
        import pytz as _lpytz
        from datetime import datetime as _ldt, time as _ldtime
        _lbkk = _lpytz.timezone('Asia/Bangkok')
        _lnow = _ldt.now(_lbkk)
        _lt = _lnow.time()
        # Live price: เฉพาะช่วงที่ตลาด SET ซื้อขายจริง (ไม่รวม midday break 12:30-14:30)
        _lmarket_open = (
            _lnow.weekday() < 5 and
            (_ldtime(10, 0) <= _lt <= _ldtime(12, 30) or
             _ldtime(14, 30) <= _lt <= _ldtime(16, 30))
        )
        live_prices = {}
        live_mcaps  = {}
        if candidates:
            try:
                import concurrent.futures as _lcf
                def _get_live(sym):
                    try:
                        fi = yf.Ticker(f"{sym}.BK").fast_info
                        p  = getattr(fi, 'last_price', None)
                        mc = getattr(fi, 'market_cap', None)
                        return sym, (float(p) if p else None), (round(float(mc)/1e9, 2) if mc else None)
                    except Exception:
                        return sym, None, None
                with _lcf.ThreadPoolExecutor(max_workers=12) as _lex:
                    for _sym, _p, _mc in _lex.map(_get_live, [c.symbol for c in candidates]):
                        if _p:  live_prices[_sym] = _p
                        if _mc: live_mcaps[_sym]  = _mc
            except Exception:
                pass

        for c in candidates:
            lp = live_prices.get(c.symbol)
            c.live_price      = lp
            c.live_market_cap = live_mcaps.get(c.symbol)
            c.is_live         = _lmarket_open and lp is not None
            if lp and c.demand_zone_start and c.demand_zone_start > 0:
                c.live_zone_prox = 0.0 if lp <= c.demand_zone_start else round(((lp - c.demand_zone_start) / c.demand_zone_start) * 100, 1)
            else:
                c.live_zone_prox = None
            if lp and c.price and c.price > 0:
                c.live_change_pct = round(((lp - c.price) / c.price) * 100, 2)
            else:
                c.live_change_pct = None

        # ====== คำนวณ BUY/SELL Score ด้วย _compute_signals() เดียวกับ Dashboard/Watchlist ======
        for c in candidates:
            sigs = _compute_signals(c)
            c.buy_score  = sigs['buy_score']
            c.sell_score = sigs['sell_score']
            c.exit_signal = sigs['exit_signal']

        # ====== BUY Score Delta เทียบกับรอบก่อนหน้า ======
        prev_buy_scores = {}
        if len(all_runs) > run_idx + 1:
            for _p in PrecisionScanCandidate.objects.filter(
                    user=request.user, scan_run=all_runs[run_idx + 1]):
                _ps = _compute_signals(_p)
                prev_buy_scores[_p.symbol] = _ps['buy_score']
        for c in candidates:
            _prev = prev_buy_scores.get(c.symbol)
            c.buy_score_delta = (c.buy_score - _prev) if _prev is not None else None

        # เรียงตาม BUY/SELL/RS score ด้วย Python (fallback ถ้าไม่ใช่ DB sort)
        if sort_by == 'buy':
            candidates.sort(key=lambda x: x.buy_score, reverse=True)
        elif sort_by == 'sell':
            candidates.sort(key=lambda x: x.sell_score, reverse=True)
        elif sort_by == 'rs':
            candidates.sort(key=lambda x: getattr(x, 'rs_rating', 0), reverse=True)

        # ====== Top 5 หุ้นแนะนำซื้อ (BUY score สูง) ======
        # เงื่อนไข: RVOL Bull ≥ 1.0x (มีแรงซื้อจริง) + RSI ไม่ overbought
        def _top5_filter(min_rvol, max_rsi=85):
            # max_rsi=85 สอดคล้องกับ _compute_signals ที่ยังให้ +2 กับ RSI 80-85
            return sorted(
                [c for c in candidates
                 if c.buy_score >= 50
                 and c.rvol_bullish
                 and c.rvol >= min_rvol
                 and c.rsi <= max_rsi],
                key=lambda x: x.buy_score, reverse=True
            )[:5]

        top5_buy = _top5_filter(1.0)
        if len(top5_buy) < 5:
            top5_buy = _top5_filter(0.7)
        if len(top5_buy) < 3:
            top5_buy = _top5_filter(0.0)

        # ====== Top 5 หุ้นที่ "ผ่านเกณฑ์ครบทุกข้อ" ======
        # ผ่อนปรนเกณฑ์ ADX 20 (เดิม 25) และ RSI ขยายเพื่อให้มีตัวเลือกมากขึ้น 
        def _is_fully_qualified(c):
            rr = c.risk_reward_ratio or 0
            in_zone = (c.demand_zone_start and c.demand_zone_end and
                       c.price <= c.demand_zone_start and c.price >= c.demand_zone_end)
            near_zone = in_zone or (c.zone_proximity <= 30)
            # ตัดหุ้นที่ราคาวิ่งขึ้นเกือบถึง/เกิน target (supply_zone_start ≈ 52w high) แล้ว
            # ถ้า upside เหลือน้อยกว่า 8% ไม่คุ้มค่าที่จะแนะนำอีกต่อไป
            target = c.supply_zone_start or 0
            upside_pct = ((target - c.price) / c.price * 100) if (target > 0 and c.price > 0) else 999
            price_near_target = target > 0 and upside_pct < 8
            return (
                c.buy_score >= 65
                and rr >= 1.5
                and c.adx >= 20
                and 45 <= c.rsi <= 82
                and c.rvol_bullish
                and c.rvol >= 0.8
                and near_zone
                and not price_near_target      # กรอง: ราคาใกล้ target แล้ว → ไม่แนะนำ
                and (c.sell_score or 0) < 50
                and getattr(c, 'rs_rating', 0) >= 60
            )

        top5_qualified = sorted(
            [c for c in candidates if _is_fully_qualified(c)],
            key=lambda x: x.buy_score, reverse=True
        )

        for c in top5_buy:
            reasons = []
            in_zone = (c.demand_zone_start and c.demand_zone_end and
                       c.price <= c.demand_zone_start and c.price >= c.demand_zone_end)
            if in_zone:
                reasons.append("อยู่ใน Entry Zone แล้ว")
            elif c.zone_proximity <= 10:
                reasons.append(f"ห่างโซนแค่ {c.zone_proximity:.0f}%")
            elif c.zone_proximity <= 30:
                reasons.append(f"ใกล้โซน {c.zone_proximity:.0f}%")

            if c.rvol_bullish and c.rvol >= 1.5:
                reasons.append(f"RVOL {c.rvol:.1f}x Bull แรง")
            elif c.rvol_bullish and c.rvol >= 1.0:
                reasons.append(f"RVOL {c.rvol:.1f}x Bull ยืนยัน")

            rr = c.risk_reward_ratio or 0
            if rr >= 3:
                reasons.append(f"RR 1:{rr:.1f} ดีเยี่ยม")
            elif rr >= 2:
                reasons.append(f"RR 1:{rr:.1f} ดี")

            if c.adx >= 30:
                reasons.append(f"ADX {c.adx:.0f} เทรนด์แข็ง")
            elif c.adx >= 25:
                reasons.append(f"ADX {c.adx:.0f} มีเทรนด์")

            if c.technical_score >= 85:
                reasons.append(f"Precision {c.technical_score} สูงมาก")
            elif c.technical_score >= 75:
                reasons.append(f"Precision {c.technical_score} ดี")

            if c.erc_volume_confirmed:
                reasons.append("ERC ยืนยันแล้ว")

            if 55 <= c.rsi <= 70:
                reasons.append(f"RSI {c.rsi:.0f} จุดหวาน")

            if c.price_pattern and c.price_pattern_score > 0:
                reasons.append(f"Pattern: {c.price_pattern}")

            rel = c.rel_momentum_3m if c.rel_momentum_3m != 0.0 else c.rel_momentum_1m
            if rel >= 8:
                reasons.append(f"ชนะ SET +{rel:.1f}% (3m)")
            elif rel >= 3:
                reasons.append(f"ชนะ SET +{rel:.1f}%")

            rs = getattr(c, 'rs_rating', 0)
            if rs >= 85:
                reasons.insert(1, f"RS {rs} — ผู้นำตลาด")   # สอดในตำแหน่ง 2 เสมอ
            elif rs >= 70:
                reasons.insert(1, f"RS {rs} — แข็งแกร่ง")

            c.top_reasons = reasons[:4]

        # เพิ่ม reasons ให้ top5_qualified ด้วย (บางตัวอาจซ้ำกับ top5_buy)
        for c in top5_qualified:
            if not hasattr(c, 'top_reasons'):
                reasons = []
                in_zone = (c.demand_zone_start and c.demand_zone_end and
                           c.price <= c.demand_zone_start and c.price >= c.demand_zone_end)
                if in_zone:
                    reasons.append("อยู่ใน Entry Zone แล้ว")
                elif c.zone_proximity <= 10:
                    reasons.append(f"ห่างโซนแค่ {c.zone_proximity:.0f}%")
                else:
                    reasons.append(f"ใกล้โซน {c.zone_proximity:.0f}%")
                rr = c.risk_reward_ratio or 0
                reasons.append(f"RR 1:{rr:.1f} ✓")
                reasons.append(f"ADX {c.adx:.0f} ✓")
                rs = getattr(c, 'rs_rating', 0)
                if rs >= 85:
                    reasons.insert(1, f"RS {rs} — ผู้นำตลาด")
                elif rs >= 70:
                    reasons.insert(1, f"RS {rs} — แข็งแกร่ง")
                if c.rvol >= 1.5:
                    reasons.append(f"RVOL {c.rvol:.1f}x Bull ✓")
                c.top_reasons = reasons[:4]

        # ====== Leading Sectors Analysis (v3) ======
        # นับจำนวนหุ้นที่ 'แข็งแกร่ง' (buy_score >= 65) ในแต่ละ sector เพื่อหาผู้นำกลุ่ม
        sector_counts = {}
        for c in candidates:
            if c.buy_score >= 65:
                sec = c.sector or 'Unknown'
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
        
        # เรียงลำดับกลุ่มที่แข็งแกร่งที่สุด 5 อันดับแรก
        top_sectors = sorted(
            [{'name': k, 'count': v} for k, v in sector_counts.items()],
            key=lambda x: x['count'], reverse=True
        )[:5]

        # ====== Automated AI Insights (คำอธิบายวิเคราะห์ผลสแกน) ======
        scan_insights = []
        if top5_qualified:
            best_setup = top5_qualified[0]
            rr_val = best_setup.risk_reward_ratio or 0
            rs_val = getattr(best_setup, "rs_rating", 0)
            target_val = best_setup.supply_zone_start or 0
            upside_left = ((target_val - best_setup.price) / best_setup.price * 100) if (target_val > 0 and best_setup.price > 0) else 0
            scan_insights.append({
                'icon': '🏆',
                'title': f'โฟกัสหลัก: {best_setup.symbol} (หน้าเทรดคุ้มค่า ปลอดภัยสูง)',
                'desc': f'ถือเป็นหน้าเทรด Swing Trade ที่สมบูรณ์แบบที่สุดในรอบนี้ เพราะมีความแข็งแกร่ง (RS {rs_val}) เทรนด์ทำมุมสวยงาม แต่ราคาปัจจุบันกลับอยู่ใกล้จุดเข้าซื้อ ทำให้มีความคุ้มค่ากับความเสี่ยงสูง (RR 1:{rr_val:.1f}) Upside เหลืออีก {upside_left:.1f}% ถึง Target ซื้อแล้วมีโอกาสชนะสูง'
            })
        
        # หาหุ้นซิ่งที่สุดแต่เสี่ยงสูง (RS > 90 แต่ RR < 1.0)
        high_risk_momentum = [c for c in top5_buy if getattr(c, 'rs_rating', 0) >= 90 and (c.risk_reward_ratio or 0) < 1.5]
        if high_risk_momentum:
            hm = high_risk_momentum[0]
            if not top5_qualified or hm.symbol != top5_qualified[0].symbol:
                scan_insights.append({
                    'icon': '🚀',
                    'title': f'สายซิ่ง (เสี่ยงสูง): {hm.symbol} (แรงทะลุกราฟ)',
                    'desc': f'นี่คือ "หุ้นโคตรโมเมนตัม" วิ่งแรงชนะตลาดถึง {getattr(hm, "rs_rating", 0)}% วอลุ่มเข้าหนัก แต่อัตราคุ้มทุน (RR) ณ ราคานี้ได้เพียง 1:{hm.risk_reward_ratio or 0:.1f} แปลว่าราคาลอยขึ้นมาพอสมควรแล้ว "อย่าเพิ่งไล่ราคา (Market Buy) แนะนำให้เอาเข้า Watchlist แล้วรอซื้อตอนย่อตัวพักฐาน"'
                })

        # หาหุ้นเพิ่งเริ่มกลับตัว (MACD crossover)
        reversal_stocks = [c for c in top5_buy if any('MACD' in str(r) for r in (c.top_reasons or []))]
        if reversal_stocks and len(scan_insights) < 3:
            rev = reversal_stocks[0]
            skip = False
            if top5_qualified and rev.symbol == top5_qualified[0].symbol: skip = True
            if high_risk_momentum and rev.symbol == high_risk_momentum[0].symbol: skip = True
            if not skip:
                scan_insights.append({
                    'icon': '🥈',
                    'title': f'สัญญาณกลับตัว: {rev.symbol} (ต้นเทรนด์)',
                    'desc': f'หุ้นตัวนี้มีสัญญาณเชิงบวกคือเกิด MACD Crossover (ตัดเส้น Signal ขึ้นมา) มักใช้ระบุจุดเริ่มต้นของรอบขาขึ้นชุดใหม่ น่าเก็บสะสมที่บริเวณแนวรับปัจจุบัน'
                })
        
        # ถ้าระบบยังไม่มีคำแนะนำเลย
        if not scan_insights and top5_buy:
            top = top5_buy[0]
            scan_insights.append({
                'icon': '💡',
                'title': f'น่าปั้นเทรนด์: {top.symbol}',
                'desc': f'ได้คะแนนเข้าซื้อสูงสุดในรอบนี้ มีโครงสร้างทางเทคนิคโดยรวมเฉลี่ยดีที่สุด เหมาะเป็นหุ้นน่าจับตามอง'
            })

    else:
        top5_buy = []
        top5_qualified = []
        top_sectors = []
        scan_insights = []

    # ====== Market Condition — ดึงข้อมูล SET Index สำหรับแสดงผล (GET + POST) ======
    market_condition = {'phase': 'UNKNOWN', 'label': 'ไม่มีข้อมูล', 'color': 'secondary', 'score': 0}
    try:
        from datetime import datetime as _mcdt, timedelta as _mctd
        import pytz as _mcpytz
        _mc_bkk   = _mcpytz.timezone('Asia/Bangkok')
        _mc_now   = _mcdt.now(_mc_bkk)
        _mc_end   = _mc_now.date().strftime('%Y-%m-%d')
        _mc_start = (_mc_now.date() - _mctd(days=430)).strftime('%Y-%m-%d')
        _mc_df = yf.download("^SET", start=_mc_start, end=_mc_end, interval="1d", progress=False)
        if _mc_df is not None and not _mc_df.empty:
            if isinstance(_mc_df.columns, pd.MultiIndex):
                _mc_df.columns = _mc_df.columns.droplevel(1)
            market_condition = _get_market_condition(_mc_df)
    except Exception:
        pass

    context = {
        'title': 'Precision Momentum Scanner — กรองคุณภาพ',
        'candidates': candidates,
        'scanned_at': scanned_at,
        'current_sort': sort_by,
        'all_runs': all_runs,
        'selected_run_idx': run_idx,
        'has_scanned': request.method == "POST" or request.GET.get('scan') == 'true' or bool(all_runs),
        'top5_buy': top5_buy,
        'top5_qualified': top5_qualified,
        'scan_total': len(scan_symbols),
        'scan_passed': len(candidates),
        'top_sectors': top_sectors,
        'scan_insights': scan_insights,
        'scan_data_date': None,  # คำนวณด้านล่าง
        'market_condition': market_condition,
    }
    # คำนวณ scan_data_date จาก scanned_at — ถ้า scan ทำหลัง 16:30 BKK ข้อมูลคือวันเดียวกัน
    # ถ้า scan ทำระหว่าง 10:00-16:30 (ตลาดเปิด) ข้อมูลจะเป็นวันก่อนหน้า
    if scanned_at:
        import pytz as _sddtz
        _bkk = _sddtz.timezone('Asia/Bangkok')
        _st = scanned_at.astimezone(_bkk) if hasattr(scanned_at, 'astimezone') else scanned_at
        from datetime import time as _t, timedelta as _tdd
        # scan_data_date: midday break ยังถือว่า candle ของวันนั้นยังไม่ settle
        _in_mkt = (
            _st.weekday() < 5 and (
                _t(10, 0) <= _st.time() <= _t(12, 30) or
                _t(12, 30) < _st.time() < _t(14, 30) or
                _t(14, 30) <= _st.time() <= _t(16, 30)
            )
        )
        context['scan_data_date'] = (_st.date() - _tdd(days=1)) if _in_mkt else _st.date()

    # Build AI scan JSON for Gemini analysis button
    import json as _scan_json
    def _ser_c(c):
        return {
            "symbol": c.symbol,
            "price": c.price,
            "buy_score": getattr(c, 'buy_score', 0),
            "rs_rating": getattr(c, 'rs_rating', 0),
            "rsi": round(c.rsi, 1),
            "adx": round(c.adx, 1),
            "rvol": round(c.rvol, 2),
            "rvol_bullish": c.rvol_bullish,
            "risk_reward_ratio": c.risk_reward_ratio,
            "zone_proximity": round(c.zone_proximity, 1) if c.zone_proximity else None,
            "macd_crossover": getattr(c, 'macd_crossover', False),
            "ema20_aligned": getattr(c, 'ema20_aligned', False),
            "ema20_rising": getattr(c, 'ema20_rising', False),
            "hh_hl_structure": getattr(c, 'hh_hl_structure', False),
            "bb_squeeze": getattr(c, 'bb_squeeze', False),
            "rel_momentum_3m": getattr(c, 'rel_momentum_3m', 0),
            "sector": c.sector,
            "exit_signal": getattr(c, 'exit_signal', ''),
            "top_reasons": getattr(c, 'top_reasons', []),
        }
    _ai_data = {
        "scan_date": str(context.get('scan_data_date', '')),
        "qualified_stocks": [_ser_c(c) for c in top5_qualified],
        "top_buy_stocks": [_ser_c(c) for c in top5_buy],
        "total_passed": len(candidates),
        "top_sectors": [{"name": s["name"], "count": s["count"]} for s in top_sectors],
    }
    context['ai_scan_json'] = _scan_json.dumps(_ai_data, ensure_ascii=False, default=str)

    # Watchlist symbols for toggle button state
    from .models import ScanWatchlistItem
    context['watchlist_symbols'] = set(
        ScanWatchlistItem.objects.filter(user=request.user).values_list('symbol', flat=True)
    )

    return render(request, 'stocks/precision_scan.html', context)


# ====== Portfolio Momentum Scan — สแกนเฉพาะหุ้นใน Portfolio ======

@login_required
def portfolio_scan(request):
    """
    สแกน Momentum เฉพาะหุ้นที่อยู่ใน Portfolio ของผู้ใช้
    ใช้ Logic เดียวกันกับ momentum_scanner() แต่เปลี่ยน Input จาก SET100+MAI เป็นหุ้นใน Portfolio
    """
    from .utils import analyze_momentum_technical, find_supply_demand_zones
    from types import SimpleNamespace

    portfolio_items = Portfolio.objects.filter(user=request.user, category='STOCK')

    candidates = []
    scanned_at = None

    if request.method == "POST" or request.GET.get('scan') == 'true':
        import pandas_ta as ta
        import datetime

        for item in portfolio_items:
            symbol = item.symbol.upper().replace('.BK', '')
            try:
                print(f"[PortfolioScan] Scanning {symbol}...")
                df = yf.download(f"{symbol}.BK", period="1y", interval="1d", progress=False)

                if df is None or df.empty:
                    try:
                        yq = YQTicker(f"{symbol}.BK")
                        df = yq.history(period="1y", interval="1d")
                        if isinstance(df, pd.DataFrame) and not df.empty:
                            df = df.reset_index()
                            if 'date' in df.columns:
                                df.set_index('date', inplace=True)
                            if 'symbol' in df.columns:
                                df.drop(columns=['symbol'], inplace=True)
                            df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low',
                                               'close': 'Close', 'volume': 'Volume'}, inplace=True)
                    except Exception:
                        pass

                if df is None or df.empty:
                    continue

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)

                df = df.dropna(subset=['Close', 'High'])
                if len(df) < 150:
                    continue

                # ====== คำนวณ Technical Indicators (เหมือน momentum_scanner) ======
                df['EMA50'] = ta.ema(df['Close'], length=50)
                df['EMA150'] = ta.ema(df['Close'], length=150)
                df['EMA200'] = ta.ema(df['Close'], length=200)

                adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                if adx_df is not None and not adx_df.empty:
                    df = pd.concat([df, adx_df], axis=1)

                mfi = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                df['MFI'] = mfi

                avg_vol_20 = df['Volume'].rolling(window=20).mean()
                df['RVOL'] = df['Volume'] / avg_vol_20

                tech = analyze_momentum_technical(df)

                current_price = float(df['Close'].iloc[-1])
                year_high = float(df['High'].tail(252).max())

                integrated_score = tech['score']
                rvol = tech['rvol']
                rsi = tech['rsi']
                ema200 = tech['ema200']

                mfi_val = float(df['MFI'].iloc[-1]) if 'MFI' in df.columns and pd.notna(df['MFI'].iloc[-1]) else 0
                adx = float(df['ADX_14'].iloc[-1]) if 'ADX_14' in df.columns and pd.notna(df['ADX_14'].iloc[-1]) else 0
                gap_to_high = ((year_high - current_price) / current_price) * 100

                # ====== เกณฑ์กรอง Trend Template (เหมือน momentum_scanner) ======
                is_uptrend = (current_price > ema200)
                near_high = (current_price >= year_high * 0.60)

                if is_uptrend and near_high:
                    sector = "Unknown"
                    eps_growth = 0.0
                    rev_growth = 0.0
                    fund_bonus = 0

                    try:
                        ticker_yf = yf.Ticker(f"{symbol}.BK")
                        info = ticker_yf.info
                        if isinstance(info, dict) and len(info) >= 5:
                            sector = info.get('sector', 'Other')
                            eps_growth = float(info.get('earningsQuarterlyGrowth', 0) or 0) * 100
                            rev_growth = float(info.get('revenueGrowth', 0) or 0) * 100
                        else:
                            sector = "N/A"
                    except Exception:
                        pass

                    if eps_growth >= 20:
                        fund_bonus += 10
                    if rev_growth >= 10:
                        fund_bonus += 10

                    sd_zone = find_supply_demand_zones(df)
                    dz_start = dz_end = sz_start = sz_end = sl_price = rr_val = None
                    entry_strat = ""
                    prox_val = 999.0

                    if sd_zone:
                        entry_strat = sd_zone['type']
                        dz_start = sd_zone['start']
                        dz_end = sd_zone['end']
                        sz_start = sd_zone['target']
                        sz_end = sd_zone['target'] * 1.02
                        sl_price = sd_zone['stop_loss']
                        rr_val = sd_zone['rr_ratio']

                    if dz_start:
                        prox_val = 0.0 if current_price <= dz_start else ((current_price - dz_start) / dz_start) * 100

                    candidates.append(SimpleNamespace(
                        symbol=symbol,
                        symbol_bk=f"{symbol}.BK",
                        sector=sector,
                        price=round(current_price, 2),
                        rsi=round(rsi, 2),
                        adx=round(adx, 2),
                        mfi=round(mfi_val, 2),
                        rvol=round(rvol, 2),
                        eps_growth=round(eps_growth, 2),
                        rev_growth=round(rev_growth, 2),
                        technical_score=int(integrated_score + fund_bonus),
                        entry_strategy=entry_strat,
                        demand_zone_start=dz_start,
                        demand_zone_end=dz_end,
                        supply_zone_start=sz_start,
                        supply_zone_end=sz_end,
                        stop_loss=sl_price,
                        risk_reward_ratio=rr_val,
                        year_high=round(year_high, 2),
                        upside_to_high=round(gap_to_high, 2),
                        zone_proximity=round(prox_val, 2),
                        portfolio_name=item.name,
                    ))

            except Exception as e:
                print(f"!!! [PortfolioScan] Error scanning {symbol}: {str(e)}")
                continue

        candidates.sort(key=lambda x: x.technical_score, reverse=True)
        scanned_at = datetime.datetime.now()

    context = {
        'title': 'Portfolio Momentum Scan',
        'candidates': candidates,
        'portfolio_count': portfolio_items.count(),
        'scanned_at': scanned_at,
        'has_scanned': request.method == "POST" or request.GET.get('scan') == 'true',
    }
    return render(request, 'stocks/portfolio_scan.html', context)


# ====== Entry Finder — กราฟ Sniper Entry พร้อม Supply & Demand Zone ======

@login_required
def entry_finder(request, symbol):
    """
    Detailed view for Supply & Demand / Sniper Entry zone for a specific symbol.
    แสดงกราฟ 120 วันพร้อม:
    - Demand Zone (โซนเข้าซื้อ)
    - Supply Zone / Target (โซนขาย)
    - Stop Loss Line
    - EMA50 และ EMA200
    """
    # ถ้า market=US ไม่ต้องเติม .BK (US stocks ใช้ ticker เดิม)
    market = request.GET.get('market', 'SET')
    if market == 'US':
        full_symbol = symbol
    else:
        full_symbol = f"{symbol}.BK" if not symbol.endswith(".BK") else symbol

    try:
        # ใช้ scan_end_date เดียวกับ Precision Scanner เพื่อให้ Zone ตรงกัน
        from datetime import datetime as _efdt, timedelta as _eftd, time as _efdtime
        import pytz as _efpytz
        _ef_bkk = _efpytz.timezone('Asia/Bangkok')
        _ef_now = _efdt.now(_ef_bkk)
        _ef_t   = _ef_now.time()
        _ef_market_day = (
            _ef_now.weekday() < 5 and
            (
                _ef_t < _efdtime(10, 0) or                                      # ก่อนเปิด
                (_efdtime(10, 0) <= _ef_t <= _efdtime(12, 30)) or               # เช้า
                (_efdtime(12, 30) < _ef_t < _efdtime(14, 30)) or               # พัก
                (_efdtime(14, 30) <= _ef_t <= _efdtime(16, 30))                 # บ่าย
            )
        )
        _ef_end_date  = (_ef_now.date() - _eftd(days=1)) if _ef_market_day else _ef_now.date()
        _ef_end_str   = _ef_end_date.strftime('%Y-%m-%d')
        _ef_start_str = (_ef_end_date - _eftd(days=400)).strftime('%Y-%m-%d')

        df = yf.download(full_symbol, start=_ef_start_str, end=_ef_end_str,
                         interval="1d", progress=False)
        if df.empty:
            messages.error(request, f"ไม่พบข้อมูลสำหรับ {symbol}")
            if market == 'US':
                return redirect('stocks:us_precision_scanner')
            return redirect('stocks:momentum_scanner')

        # แก้ไข MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # คำนวณ Supply & Demand Zone ด้วย v2 (ใช้ข้อมูลชุดเดียวกับ Precision Scanner)
        sd_zone = find_supply_demand_zones_v2(df)

        # เตรียมข้อมูลกราฟ 120 วันล่าสุด
        history_subset = df.tail(120).copy()
        chart_labels = [d.strftime('%Y-%m-%d') for d in history_subset.index]
        chart_values = [round(float(v), 2) for v in history_subset['Close'].values]

        # คำนวณ EMA50 และ EMA200 สำหรับแสดงในกราฟ
        import pandas_ta as ta
        history_subset['EMA50'] = ta.ema(history_subset['Close'], length=50)
        history_subset['EMA200'] = ta.ema(history_subset['Close'], length=200)
        ema50_vals = [round(float(v), 2) if pd.notna(v) else None for v in history_subset['EMA50'].values]
        ema200_vals = [round(float(v), 2) if pd.notna(v) else None for v in history_subset['EMA200'].values]

        # แปลงข้อมูล chart เป็น JSON สำหรับ JavaScript
        chart_labels_json = json.dumps(chart_labels)
        chart_values_json = json.dumps(chart_values)
        ema50_vals_json = json.dumps(ema50_vals)
        ema200_vals_json = json.dumps(ema200_vals)
        sd_zone_json = json.dumps(sd_zone)

        # ราคาปิดวันสุดท้ายของ historical data (ใช้คำนวณ zone เท่านั้น)
        hist_close = float(df['Close'].iloc[-1])

        # Live price จาก fast_info (ตรงกับ momentum card)
        try:
            _live_fi = yf.Ticker(full_symbol).fast_info
            _live_p  = getattr(_live_fi, 'last_price', None)
            curr_price = float(_live_p) if _live_p else hist_close
        except Exception:
            curr_price = hist_close

        # ถ้า live price ต่างจาก hist_close → เพิ่มเป็น data point สุดท้ายในกราฟ
        if abs(curr_price - hist_close) > 0.001:
            _today_str = _ef_now.strftime('%Y-%m-%d')
            chart_labels.append(_today_str)
            chart_values.append(round(curr_price, 2))
            ema50_vals.append(None)
            ema200_vals.append(None)
            chart_labels_json = json.dumps(chart_labels)
            chart_values_json = json.dumps(chart_values)
            ema50_vals_json   = json.dumps(ema50_vals)
            ema200_vals_json  = json.dumps(ema200_vals)

        # คำนวณ zone_proximity ให้ตรงกับที่ precision scanner แสดง
        ef_zone_prox = None
        if sd_zone and sd_zone.get('start'):
            dz_top = sd_zone['start']
            if curr_price <= dz_top:
                ef_zone_prox = 0.0
            else:
                ef_zone_prox = round(((curr_price - dz_top) / dz_top) * 100, 1)

        context = {
            'symbol': symbol,
            'full_symbol': full_symbol,
            'sd_zone': sd_zone,
            'sd_zone_json': sd_zone_json,
            'curr_price': round(curr_price, 2),
            'zone_proximity': ef_zone_prox,
            'scan_end_date': _ef_end_str,
            'chart_labels': chart_labels_json,
            'chart_values': chart_values_json,
            'ema50_vals': ema50_vals_json,
            'ema200_vals': ema200_vals_json,
            'title': f"Sniper Entry: {symbol}"
        }
        return render(request, 'stocks/entry_finder.html', context)
    except Exception as e:
        messages.error(request, f"Error finding zones for {symbol}: {str(e)}")
        return redirect('stocks:momentum_scanner')

# ====== Signup — สมัครสมาชิกใหม่ ======

def signup(request):
    """
    หน้าสมัครสมาชิก ใช้ Django built-in UserCreationForm
    เมื่อสมัครสำเร็จจะ login อัตโนมัติและ redirect ไปหน้า dashboard
    """
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Login อัตโนมัติหลังจากสมัครสำเร็จ
            login(request, user)
            messages.success(request, f"ยินดีต้อนรับคุณ {user.username}! ระบบของคุณพร้อมใช้งานแล้ว")
            return redirect('stocks:dashboard')
    else:
        form = UserCreationForm()
    return render(request, 'registration/signup.html', {'form': form})


# ====== Multi-Factor Scoring Scanner ======

@login_required
def multi_factor_scanner(request):
    """
    สแกนหุ้นด้วยระบบ Multi-Factor Super Score
    รวม 4 ปัจจัย: Momentum(40) + Volume/Flow(30) + Sentiment AI(20) + Fundamental(10)
    """
    # ====== SCAN STATUS POLL (AJAX) ======
    if request.GET.get('scan_status') == '1':
        from django.core.cache import cache
        from django.http import JsonResponse as _JsonResponse
        key = f'multifactor_scan_{request.user.id}'
        status = cache.get(key, {'state': 'idle'})
        # เมื่อ done ถูก poll แล้ว ให้ reset เป็น idle ทันที ป้องกัน reload loop
        if status.get('state') == 'done':
            cache.delete(key)
        return _JsonResponse(status)

    # ====== SCAN (POST — ทำ background เพื่อไม่ให้ nginx timeout) ======
    if request.method == "POST" and request.POST.get('action') == 'scan':
        from django.core.cache import cache
        import threading

        user_id  = request.user.id
        cache_key = f'multifactor_scan_{user_id}'

        # ป้องกันการสแกนซ้ำถ้ายังรันอยู่
        current = cache.get(cache_key, {})
        if current.get('state') == 'running':
            return redirect('stocks:multi_factor_scanner')

        cache.set(cache_key, {'state': 'running', 'progress': 0, 'total': 0}, timeout=600)

        def _run_scan(user_id, cache_key):
            import django
            django.setup()
            import pandas_ta as ta
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from django.contrib.auth import get_user_model
            from django.core.cache import cache as _cache

            User = get_user_model()
            user = User.objects.get(pk=user_id)

            scan_symbols = ScannableSymbol.objects.filter(
                is_active=True
            ).values_list('symbol', flat=True).distinct()
            if not scan_symbols:
                refresh_set100_symbols()
                scan_symbols = ScannableSymbol.objects.filter(
                    is_active=True
                ).values_list('symbol', flat=True).distinct()

            MultiFactorCandidate.objects.filter(user=user).delete()
            # deduplicate while preserving order
            seen = set()
            sym_list = [s for s in scan_symbols if not (s in seen or seen.add(s))]

            _cache.set(cache_key, {'state': 'running', 'progress': 0, 'total': len(sym_list)}, timeout=600)

            # โหลด sector cache จาก DB ครั้งเดียว
            sector_cache = {
                s.symbol: s.sector
                for s in ScannableSymbol.objects.filter(
                    is_active=True
                ).only('symbol', 'sector')
            }

            # Phase 1: Batch download
            tickers_str = " ".join(f"{s}.BK" for s in sym_list)
            try:
                batch_df = yf.download(
                    tickers_str, period="1y", interval="1d",
                    group_by='ticker', progress=False, threads=True,
                )
            except Exception as e:
                print(f"[MultiFactorScan] Batch download failed: {e}")
                batch_df = None

            def _get_df(symbol):
                sym_bk = f"{symbol}.BK"
                df = None
                if batch_df is not None and not batch_df.empty:
                    try:
                        df = batch_df[sym_bk].copy() if len(sym_list) > 1 else batch_df.copy()
                    except Exception:
                        df = None
                if df is None or (hasattr(df, 'empty') and df.empty):
                    try:
                        df = yf.download(sym_bk, period="1y", interval="1d", progress=False)
                    except Exception:
                        return None
                return df

            def process_one(symbol):
                try:
                    df = _get_df(symbol)
                    if df is None or df.empty:
                        return None
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.droplevel(1)
                    df = df.dropna(subset=['Close', 'High'])
                    if len(df) < 60:
                        return None
                    df = df.copy()
                    df['EMA50']  = ta.ema(df['Close'], length=50)
                    df['EMA200'] = ta.ema(df['Close'], length=200)
                    df['RSI']    = ta.rsi(df['Close'], length=14)
                    adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                    if adx_df is not None and not adx_df.empty:
                        df = pd.concat([df, adx_df], axis=1)
                    df['MFI']  = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                    df['RVOL'] = df['Volume'] / df['Volume'].rolling(20).mean()
                    last    = df.iloc[-1]
                    price   = float(df['Close'].iloc[-1])
                    rsi     = float(last.get('RSI')    or 0) if pd.notna(last.get('RSI'))    else 0
                    adx_val = float(last.get('ADX_14') or 0) if 'ADX_14' in df.columns and pd.notna(last.get('ADX_14')) else 0
                    mfi_val = float(last.get('MFI')    or 0) if pd.notna(last.get('MFI'))    else 0
                    rvol    = float(last.get('RVOL')   or 1) if pd.notna(last.get('RVOL'))   else 1.0
                    ema50   = float(last.get('EMA50')  or 0) if pd.notna(last.get('EMA50'))  else 0
                    ema200  = float(last.get('EMA200') or 0) if pd.notna(last.get('EMA200')) else 0
                    above_ema200 = bool(price > ema200) if ema200 else False
                    above_ema50  = bool(price > ema50)  if ema50  else False
                    mom = 0
                    if above_ema200:                        mom += 15
                    if above_ema50:                         mom += 5
                    if 55 <= rsi <= 72:                     mom += 15
                    elif 45 <= rsi < 55 or 72 < rsi <= 80: mom += 7
                    if adx_val >= 30:                       mom += 5
                    vol = 0
                    if rvol >= 3.0:     vol += 15
                    elif rvol >= 2.0:   vol += 12
                    elif rvol >= 1.5:   vol += 8
                    elif rvol >= 1.0:   vol += 4
                    if mfi_val >= 70:   vol += 15
                    elif mfi_val >= 60: vol += 10
                    elif mfi_val >= 50: vol += 5
                    sector = sector_cache.get(symbol, 'Unknown')
                    vol_score = min(vol, 30)
                    return dict(
                        symbol=symbol, sector=sector, price=round(price, 2),
                        momentum_score=mom, volume_score=vol_score,
                        sentiment_score=0, fundamental_score=0,
                        super_score=mom + vol_score,
                        rsi=round(rsi, 2), adx=round(adx_val, 2),
                        mfi=round(mfi_val, 2), rvol=round(rvol, 2),
                        eps_growth=0.0, rev_growth=0.0,
                        above_ema200=above_ema200, above_ema50=above_ema50,
                    )
                except Exception as e:
                    print(f"[MultiFactorScan] {symbol}: {e}")
                    return None

            # Phase 2: รันขนาน + update progress
            raw_results = []
            done = 0
            with ThreadPoolExecutor(max_workers=12) as executor:
                futures = {executor.submit(process_one, s): s for s in sym_list}
                for future in as_completed(futures):
                    r = future.result()
                    if r:
                        raw_results.append(r)
                    done += 1
                    _cache.set(cache_key, {'state': 'running', 'progress': done, 'total': len(sym_list)}, timeout=600)

            # Phase 3: Bulk create
            MultiFactorCandidate.objects.bulk_create([
                MultiFactorCandidate(user=user, **r) for r in raw_results
            ])
            _cache.set(cache_key, {'state': 'done', 'count': len(raw_results)}, timeout=300)

        # เปิด background thread แล้ว return ทันที — ไม่ block nginx
        t = threading.Thread(target=_run_scan, args=(user_id, cache_key), daemon=True)
        t.start()
        return redirect('stocks:multi_factor_scanner')

    # ====== AI SENTIMENT (batch) ======
    if request.GET.get('sentiment') == 'true':
        candidates_qs = MultiFactorCandidate.objects.filter(user=request.user).order_by('-super_score')[:30]
        symbols_list  = [c.symbol for c in candidates_qs]
        if symbols_list:
            try:
                client     = genai.Client(api_key=settings.GEMINI_API_KEY)
                prompt = f"""วิเคราะห์ข่าวและ Sentiment ล่าสุดสำหรับหุ้นไทยเหล่านี้ในตลาด SET:
{', '.join(symbols_list)}

ตอบเป็น JSON array เท่านั้น ไม่มีข้อความอื่นนอก array:
[{{"symbol":"PTT","score":15,"label":"บวก","reason":"สรุปเหตุผล 1 ประโยค"}}]

score: 0-20 (20=บวกมาก, 10=กลาง, 0=ลบมาก)
label: "บวก" หรือ "กลาง" หรือ "ลบ"
reason: ภาษาไทย ไม่เกิน 60 ตัวอักษร"""
                resp = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                import json, re
                raw = resp.text.strip()
                raw = re.sub(r'^```(?:json)?\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw)
                data = json.loads(raw)
                for item in data:
                    sym   = item.get('symbol','').upper()
                    score = int(item.get('score', 0))
                    label = item.get('label', '')
                    reason= item.get('reason', '')
                    MultiFactorCandidate.objects.filter(
                        user=request.user, symbol=sym
                    ).update(
                        sentiment_score=score,
                        sentiment_label=label,
                        sentiment_reason=reason,
                    )
                # recalculate super_score for updated records
                for c in MultiFactorCandidate.objects.filter(user=request.user):
                    c.super_score = c.momentum_score + c.volume_score + c.sentiment_score + c.fundamental_score
                    c.save(update_fields=['super_score'])
            except Exception as e:
                messages.warning(request, f"AI Sentiment Error: {e}")
        return redirect('stocks:multi_factor_scanner')

    # ====== Sort & Render ======
    sort_by = request.GET.get('sort', 'super')
    valid_sorts = {
        'super': '-super_score',
        'momentum': '-momentum_score',
        'volume': '-volume_score',
        'sentiment': '-sentiment_score',
        'fundamental': '-fundamental_score',
        'rsi': '-rsi',
        'rvol': '-rvol',
        'symbol': 'symbol',
    }
    order_field = valid_sorts.get(sort_by, '-super_score')
    candidates  = MultiFactorCandidate.objects.filter(user=request.user).order_by(order_field)
    last_scan   = candidates.first()

    context = {
        'candidates':    candidates,
        'current_sort':  sort_by,
        'has_scanned':   candidates.exists(),
        'scanned_at':    last_scan.scanned_at if last_scan else None,
        'has_sentiment': candidates.filter(sentiment_score__gt=0).exists(),
    }
    return render(request, 'stocks/multi_factor.html', context)

@login_required
def realized_pl_report(request):
    """
    รายงานกำไรขาดทุนสะสมที่เกิดขึ้นจริง (Realized P/L)
    พร้อมตัวกรอง รายวัน รายเดือน รายปี และช่วงเวลา
    """
    import json
    from collections import defaultdict
    
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    group_by = request.GET.get('group_by', 'month') # day, month, year

    sold_stocks = SoldStock.objects.filter(user=request.user).order_by('sold_at')

    if start_date:
        sold_stocks = sold_stocks.filter(sold_at__date__gte=start_date)
    if end_date:
        sold_stocks = sold_stocks.filter(sold_at__date__lte=end_date)

    # Grouping logic
    summary_dict = defaultdict(lambda: {'items': [], 'total_pl': 0})
    
    chart_labels = []
    chart_data = []
    running_pl = 0
    
    for s in sold_stocks:
        if group_by == 'day':
            key = s.sold_at.strftime('%Y-%m-%d')
        elif group_by == 'year':
            key = s.sold_at.strftime('%Y')
        else: # month
            key = s.sold_at.strftime('%Y-%m')
            
        summary_dict[key]['items'].append(s)
        summary_dict[key]['total_pl'] += float(s.profit_loss)
        
        # สำหรับกราฟเส้น (Performance)
        running_pl += float(s.profit_loss)
        chart_labels.append(s.sold_at.strftime('%Y-%m-%d %H:%M'))
        chart_data.append(running_pl)

    # เตรียมข้อมูลสรุปสำหรับตาราง (Sorted รายการล่าสุดขึ้นก่อน)
    summary_list = []
    sorted_keys = sorted(summary_dict.keys(), reverse=True)
    for k in sorted_keys:
        summary_list.append({
            'period': k,
            'items': summary_dict[k]['items'],
            'total_pl': summary_dict[k]['total_pl'],
            'count': len(summary_dict[k]['items'])
        })

    context = {
        'summary_list': summary_list,
        'sold_stocks': sold_stocks,
        'chart_labels': json.dumps(chart_labels),
        'chart_data': json.dumps(chart_data),
        'start_date': start_date,
        'end_date': end_date,
        'group_by': group_by,
        'title': 'Realized P/L Report',
    }
    return render(request, 'stocks/realized_pl_report.html', context)


# ======================================================================
# PRECISION SCAN AI ANALYSIS
# ======================================================================

@login_required
def precision_scan_ai_analysis(request):
    import json as _json_lib
    from django.http import JsonResponse
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        body = _json_lib.loads(request.body)
        scan_data = body.get("scan_data", {})
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return JsonResponse({"error": "ไม่พบ GEMINI_API_KEY"}, status=500)

    qualified = scan_data.get("qualified_stocks", [])
    top_buy = scan_data.get("top_buy_stocks", [])
    scan_date = scan_data.get("scan_date", "ไม่ระบุ")
    total_passed = scan_data.get("total_passed", 0)
    top_sectors = scan_data.get("top_sectors", [])

    def _fmt_stock(s):
        lines = [
            "  - {sym}: ราคา {price} | BUY {buy} | RS {rs}".format(
                sym=s["symbol"], price=s["price"], buy=s["buy_score"], rs=s["rs_rating"]),
            "    RSI {rsi} | ADX {adx} | RVOL {rvol}x {dir} | RR 1:{rr}".format(
                rsi=s["rsi"], adx=s["adx"], rvol=s["rvol"],
                dir="Bull ▲" if s.get("rvol_bullish") else "Bear ▼",
                rr=s.get("risk_reward_ratio", "-")),
            "    Zone {z}% | {sec} | RelMom3m {rm}%".format(
                z=s.get("zone_proximity", "-"), sec=s.get("sector", "-"),
                rm=s.get("rel_momentum_3m", 0)),
            "    Signals: {m}{e}{h}{b}{a}".format(
                m="MACD✕ " if s.get("macd_crossover") else "",
                e="EMA↑ " if s.get("ema20_rising") else "",
                h="HH/HL " if s.get("hh_hl_structure") else "",
                b="BB Squeeze " if s.get("bb_squeeze") else "",
                a="EMA20 Aligned " if s.get("ema20_aligned") else ""),
        ]
        if s.get("top_reasons"):
            lines.append("    เหตุผล: {r}".format(r=", ".join(s["top_reasons"])))
        return "\n".join(lines)

    q_text = "\n".join([_fmt_stock(s) for s in qualified]) if qualified else "  (ไม่มีหุ้นผ่านเกณฑ์ครบ)"
    b_text = "\n".join([_fmt_stock(s) for s in top_buy]) if top_buy else "  (ไม่มีข้อมูล)"
    sec_text = ", ".join(["{n}({c})".format(n=s["name"], c=s["count"]) for s in top_sectors]) if top_sectors else "ไม่ระบุ"

    prompt = (
        "คุณคือผู้เชี่ยวชาญด้านหุ้น SET"
        " ที่ใช้ Precision Momentum (สไตล์ Mark Minervini + William O'Neil)\n"
        "เชี่ยวชาญ Stage Analysis, RS Rating, Supply/Demand Zone,"
        " RVOL Bull/Bear, MACD Crossover, EMA Alignment, Trend Following (HH/HL)\n\n"
        "ผล Precision Scan วันที่ {sd} (ผ่านเกณฑ์ {tp} ตัว)"
        " | Leading Sectors: {sec}\n\n"
        "=== หุ้นผ่านเกณฑ์ครบทุกข้อ (Fully Qualified) ===\n{q}\n\n"
        "=== Top หุ้นแนะนำซื้อ (BUY Score) ===\n{b}\n\n"
        "วิเคราะห์ในหัวข้อต่อไปนี้:\n\n"
        "## 1. ✨ ภาพรวมตลาดวันนี้\n"
        "- บรรยากาศตลาด (Bullish/Mixed/Bearish), Sector นำตลาด\n\n"
        "## 2. ✅ วิเคราะห์หุ้นผ่านเกณฑ์ครบทุกข้อ\n"
        "- แต่ละตัว: จุดเด่น, ความเสี่ยง, โอกาสวิ่ง, ลำดับน่าสนใจ\n\n"
        "## 3. 🏆 วิเคราะห์ Top BUY Score\n"
        "- ตัวที่น่าสนใจที่สุด และทำไม | ระวังอะไร\n\n"
        "## 4. ⚡ กลยุทธ์แนะนำ\n"
        "- ลำดับซื้อ: ตัวไหนก่อน หลัง หรือรอ | Entry Zone ที่เหมาะสม\n\n"
        "## 5. ⚠ ข้อควรระวัง\n"
        "- RSI/RVOL/Zone น่าเป็นห่วง, Stop Loss discipline\n\n"
        "ตอบภาษาไทย กระชับ เป็นมืออาชีพ"
        " จัดรูปแบบ Markdown"
        " เน้น Actionable Insights"
    ).format(sd=scan_date, tp=total_passed, sec=sec_text, q=q_text, b=b_text)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        if not response.text:
            return JsonResponse({"error": "AI ไม่ตอบกลับ"}, status=500)
        return JsonResponse({"status": "success", "analysis": response.text})
    except Exception as e:
        err = str(e)
        if "API_KEY_INVALID" in err:
            return JsonResponse({"error": "GEMINI_API_KEY ไม่ถูกต้อง"}, status=500)
        return JsonResponse({"error": "Gemini error: {}".format(err)}, status=500)


# ====== tithe_report — รายงานทศางค์ 10% จากกำไรหุ้นรายเดือน ======

@login_required
def tithe_report(request):
    """
    แสดงกำไร/ขาดทุนรายเดือนจากการขายหุ้น
    คำนวณทศางค์ 10% จากเดือนที่มีกำไร พร้อม track การจ่าย
    """
    from django.db.models import Sum
    from django.db.models.functions import TruncMonth
    import calendar

    monthly_qs = (
        SoldStock.objects
        .filter(user=request.user)
        .annotate(month_trunc=TruncMonth('sold_at'))
        .values('month_trunc')
        .annotate(total_pl=Sum('profit_loss'))
        .order_by('-month_trunc')
    )

    tithe_map = {
        (t.year, t.month): t
        for t in TitheRecord.objects.filter(user=request.user)
    }

    months = []
    total_profit = Decimal('0')
    total_tithe_owed = Decimal('0')
    total_tithe_paid = Decimal('0')

    for entry in monthly_qs:
        dt = entry['month_trunc']
        yr, mo = dt.year, dt.month
        pl = Decimal(str(entry['total_pl'] or 0))
        tithe = (pl * Decimal('0.10')).quantize(Decimal('0.01')) if pl > 0 else Decimal('0')

        rec = tithe_map.get((yr, mo))
        is_paid = rec.is_paid if rec else False
        paid_at = rec.paid_at if rec else None

        if pl > 0:
            total_profit += pl
            total_tithe_owed += tithe
            if is_paid:
                total_tithe_paid += tithe

        months.append({
            'year': yr,
            'month': mo,
            'month_name': calendar.month_abbr[mo],
            'pl': pl,
            'tithe': tithe,
            'is_paid': is_paid,
            'paid_at': paid_at,
        })

    # Build chart data (chronological order = reversed from newest-first list)
    chart_months = list(reversed(months))
    chart_data = json.dumps({
        'labels':  [f"{m['month_name']} {m['year']}" for m in chart_months],
        'profit':  [float(m['pl'])    for m in chart_months],
        'tithe':   [float(m['tithe']) for m in chart_months],
    }, ensure_ascii=False)

    context = {
        'months': months,
        'total_profit': total_profit,
        'total_tithe_owed': total_tithe_owed,
        'total_tithe_paid': total_tithe_paid,
        'total_tithe_remaining': total_tithe_owed - total_tithe_paid,
        'chart_json': chart_data,
    }
    return render(request, 'stocks/tithe_report.html', context)


@login_required
def tithe_mark_paid(request):
    """Toggle paid/unpaid status for a tithe month via AJAX POST."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    from django.utils import timezone

    try:
        yr = int(request.POST.get('year', 0))
        mo = int(request.POST.get('month', 0))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid year/month'}, status=400)

    rec, _ = TitheRecord.objects.get_or_create(
        user=request.user, year=yr, month=mo,
        defaults={'is_paid': False}
    )
    rec.is_paid = not rec.is_paid
    rec.paid_at = timezone.now() if rec.is_paid else None
    rec.save()

    return JsonResponse({
        'is_paid': rec.is_paid,
        'paid_at': rec.paid_at.strftime('%d %b %Y %H:%M') if rec.paid_at else None,
    })


# ======================================================================
# US PRECISION MOMENTUM SCANNER — Nasdaq & S&P 500
# ======================================================================

def _seed_us_symbols():
    """Seed curated US stock universe (~220 symbols, Nasdaq & S&P 500) into ScannableSymbol."""
    US_SYMBOLS = [
        # ── Mega-cap Tech ──────────────────────────────────────────────
        "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA", "AVGO", "ORCL",
        "AMD", "ARM", "DELL", "HPE", "WDC",
        # ── Semiconductor ──────────────────────────────────────────────
        "TSM", "QCOM", "INTC", "MU", "AMAT", "LRCX", "KLAC", "MRVL", "ON", "TXN",
        "SMCI", "ASML", "NXPI", "MPWR", "WOLF",
        # ── Cloud / Software ──────────────────────────────────────────
        "CRM", "NOW", "SNOW", "PLTR", "PANW", "CRWD", "ZS", "NET", "DDOG", "MDB",
        "ADBE", "INTU", "ANSS", "CDNS", "SNPS", "FTNT", "OKTA", "HUBS", "TWLO",
        "TTD", "BILL", "GTLB", "DOCN", "ZM",
        # ── Financials ────────────────────────────────────────────────
        "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "V", "MA",
        "COF", "DFS", "SYF", "USB", "TFC", "KEY", "RF", "FITB",
        "CB", "PGR", "ALL", "TRV", "MET", "PRU",
        # ── Healthcare / Biotech ──────────────────────────────────────
        "UNH", "LLY", "JNJ", "ABBV", "MRK", "PFE", "ABT", "TMO", "AMGN", "ISRG",
        "DXCM", "IDXX", "ILMN", "MRNA", "REGN", "VRTX", "BIIB", "GILD", "BMY",
        "CVS", "CI", "HUM", "MDT", "SYK", "BSX", "EW",
        # ── Consumer Staples ──────────────────────────────────────────
        "COST", "WMT", "TGT", "KR", "PG", "KO", "PEP", "CL", "MDLZ", "MO",
        # ── Consumer Discretionary ────────────────────────────────────
        "HD", "LOW", "NKE", "LULU", "DECK", "ONON", "RH",
        "SBUX", "MCD", "YUM", "CMG", "DPZ",
        "NFLX", "ABNB", "UBER", "DASH", "LYFT", "ETSY", "EBAY",
        "BABA", "JD", "PDD",
        # ── Energy ────────────────────────────────────────────────────
        "XOM", "CVX", "COP", "EOG", "SLB", "PSX", "MPC", "VLO", "OXY", "HAL",
        "DVN", "FANG", "APA", "MRO", "WMB", "KMI",
        # ── Industrials / Aerospace ───────────────────────────────────
        "CAT", "DE", "HON", "GE", "RTX", "LMT", "BA", "UPS", "FDX", "CSX",
        "ITW", "EMR", "ETN", "PH", "ROK", "AME", "TT", "DHR", "NOC", "GD",
        # ── FinTech / Payments ────────────────────────────────────────
        "SPOT", "RBLX", "COIN", "SQ", "PYPL", "MSTR",
        # ── REIT / Utilities ──────────────────────────────────────────
        "AMT", "PLD", "CCI", "EQIX", "O", "WELL", "VICI", "PSA",
        "NEE", "DUK", "SO", "AEP", "EXC",
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


@login_required
def us_precision_scanner(request):
    """
    US Precision Momentum Scanner — Nasdaq & S&P 500
    Same logic as precision_momentum_scanner but for US stocks:
    - No .BK suffix
    - Benchmark: SPY
    - Market hours: 09:30-16:00 ET (America/New_York)
    - Liquidity: avg 20d volume >= 1,000,000
    - market='US' filter on all DB queries
    """
    from .models import PrecisionScanCandidate
    from .utils import analyze_momentum_technical_v2
    from django.utils import timezone as tz
    from yahooquery import Ticker as YQTicker

    scan_symbols = list(
        ScannableSymbol.objects.filter(is_active=True, market='US').values_list('symbol', flat=True)
    )
    if not scan_symbols:
        _seed_us_symbols()
        scan_symbols = list(
            ScannableSymbol.objects.filter(is_active=True, market='US').values_list('symbol', flat=True)
        )

    if request.method == "POST" or request.GET.get('scan') == 'true':
        import pandas_ta as ta
        from datetime import datetime as _dt, timedelta as _td, time as _dtime
        import pytz as _pytz

        scan_run_time = tz.now()

        # ====== Pin Scan Date — NYSE/Nasdaq 09:30-16:00 ET ======
        _ny_tz = _pytz.timezone('America/New_York')
        _now_ny = _dt.now(_ny_tz)
        _t = _now_ny.time()
        _market_trading = (
            _now_ny.weekday() < 5 and
            _dtime(9, 30) <= _t <= _dtime(16, 0)
        )
        scan_end_date  = (_now_ny.date() - _td(days=1)) if _market_trading else _now_ny.date()
        scan_end_str   = scan_end_date.strftime('%Y-%m-%d')
        scan_start_str = (scan_end_date - _td(days=400)).strftime('%Y-%m-%d')
        spy_start_str  = (scan_end_date - _td(days=185)).strftime('%Y-%m-%d')

        # ดึง symbols รอบก่อน (is_new_entry flag)
        prev_run = (
            PrecisionScanCandidate.objects
            .filter(user=request.user, market='US')
            .values_list('scan_run', flat=True)
            .order_by('-scan_run').distinct().first()
        )
        prev_symbols = set()
        if prev_run:
            prev_symbols = set(
                PrecisionScanCandidate.objects
                .filter(user=request.user, market='US', scan_run=prev_run)
                .values_list('symbol', flat=True)
            )

        # ====== SPY Benchmark Returns ======
        spy_1m_return = 0.0
        spy_3m_return = 0.0
        try:
            spy_df = yf.download("SPY", start=spy_start_str, end=scan_end_str, interval="1d", progress=False)
            if spy_df is not None and not spy_df.empty:
                if isinstance(spy_df.columns, pd.MultiIndex):
                    spy_df.columns = spy_df.columns.droplevel(1)
                spy_close = spy_df['Close'].dropna()
                if len(spy_close) >= 66:
                    spy_1m_return = float((spy_close.iloc[-1] - spy_close.iloc[-22]) / spy_close.iloc[-22] * 100)
                    spy_3m_return = float((spy_close.iloc[-1] - spy_close.iloc[-66]) / spy_close.iloc[-66] * 100)
            import logging; logging.getLogger('stocks').info(
                f"[US Precision] SPY: 1m={spy_1m_return:.2f}% 3m={spy_3m_return:.2f}%")
        except Exception as e:
            import logging; logging.getLogger('stocks').warning(f"[US Precision] SPY fetch failed: {e}")

        import concurrent.futures

        # ====== Pre-compute RS Ratings from full universe ======
        # Minervini Weighted RS: Q1×40% + Q2×20% + Q3×20% + Q4×20%
        def _fetch_rs_return_us(sym):
            try:
                _df = yf.Ticker(sym).history(start=scan_start_str, end=scan_end_str, interval="1d")
                if _df is None or _df.empty:
                    return sym, None
                if isinstance(_df.columns, pd.MultiIndex):
                    _df.columns = _df.columns.droplevel(1)
                _close = _df['Close'].dropna()
                n = len(_close)
                if n >= 252:
                    q1 = float((_close.iloc[-1]   - _close.iloc[-64])  / abs(_close.iloc[-64])  * 100)
                    q2 = float((_close.iloc[-64]  - _close.iloc[-127]) / abs(_close.iloc[-127]) * 100)
                    q3 = float((_close.iloc[-127] - _close.iloc[-190]) / abs(_close.iloc[-190]) * 100)
                    q4 = float((_close.iloc[-190] - _close.iloc[-253]) / abs(_close.iloc[-253]) * 100)
                    return sym, q1 * 0.4 + q2 * 0.2 + q3 * 0.2 + q4 * 0.2
                elif n >= 66:
                    return sym, float((_close.iloc[-1] - _close.iloc[-66]) / abs(_close.iloc[-66]) * 100)
                return sym, None
            except Exception:
                return sym, None

        rs_returns_all = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as _ex:
            _futs = {_ex.submit(_fetch_rs_return_us, s): s for s in scan_symbols}
            for _f in concurrent.futures.as_completed(_futs):
                _sym, _ret = _f.result()
                if _ret is not None:
                    rs_returns_all[_sym] = _ret

        rs_ratings_map = {}
        if rs_returns_all:
            _rs_ser = pd.Series(rs_returns_all)
            rs_ratings_map = (_rs_ser.rank(pct=True) * 99).clip(0, 99).astype(int).to_dict()

        def _process_us_scan(symbol):
            try:
                ticker_obj = yf.Ticker(symbol)
                df = ticker_obj.history(start=scan_start_str, end=scan_end_str, interval="1d")

                if df is None or df.empty:
                    try:
                        yq = YQTicker(symbol)
                        df = yq.history(start=scan_start_str, end=scan_end_str, interval="1d")
                        if isinstance(df, pd.DataFrame) and not df.empty:
                            df = df.reset_index()
                            if 'date' in df.columns:
                                df.set_index('date', inplace=True)
                            if 'symbol' in df.columns:
                                df.drop(columns=['symbol'], inplace=True)
                            df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low',
                                               'close': 'Close', 'volume': 'Volume'}, inplace=True)
                    except Exception:
                        pass

                if df is None or df.empty:
                    return None

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)

                df = df.dropna(subset=['Close', 'High'])
                if len(df) < 200:
                    return None

                # ====== Liquidity: avg 20d vol >= 1,000,000 ======
                avg_vol_20 = float(df['Volume'].tail(20).mean())
                if avg_vol_20 < 1_000_000:
                    return None

                # ====== Indicators ======
                df['EMA200'] = ta.ema(df['Close'], length=200)
                df['EMA50']  = ta.ema(df['Close'], length=50)
                df['RSI']    = ta.rsi(df['Close'], length=14)
                adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                if adx_df is not None and not adx_df.empty:
                    df = pd.concat([df, adx_df], axis=1)
                mfi_series = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                df['MFI'] = mfi_series

                current_price = float(df['Close'].iloc[-1])
                year_high = float(df['High'].tail(252).max())

                adx_val = float(df['ADX_14'].iloc[-1]) if 'ADX_14' in df.columns and pd.notna(df['ADX_14'].iloc[-1]) else 0
                if adx_val < 15:
                    return None

                near_high = current_price >= year_high * 0.65
                if not near_high:
                    return None

                tech = analyze_momentum_technical_v2(df)
                integrated_score = tech['score']
                rvol             = tech['rvol']
                rsi              = tech['rsi']
                rvol_bullish     = tech['rvol_bullish']
                sd_zone          = tech['sd_zone']
                ema20_aligned_flag = tech.get('ema20_aligned', False)
                ema20_slope_val    = tech.get('ema20_slope', 0.0)
                ema20_rising_flag  = tech.get('ema20_rising', False)
                hh_hl_flag         = tech.get('hh_hl_structure', False)

                mfi_val = float(df['MFI'].iloc[-1]) if 'MFI' in df.columns and pd.notna(df['MFI'].iloc[-1]) else 0

                # ====== MACD ======
                macd_hist_val  = None
                macd_cross_val = False
                try:
                    macd_df = ta.macd(df['Close'], fast=12, slow=26, signal=9)
                    if macd_df is not None and not macd_df.empty:
                        hist_col = [c for c in macd_df.columns if 'h' in c.lower() or 'hist' in c.lower()]
                        macd_col = [c for c in macd_df.columns if c.lower().startswith('macd_')]
                        sig_col  = [c for c in macd_df.columns if 'macds' in c.lower() or 'signal' in c.lower()]
                        if hist_col:
                            macd_hist_val = float(macd_df[hist_col[0]].iloc[-1]) if pd.notna(macd_df[hist_col[0]].iloc[-1]) else None
                        if macd_col and sig_col:
                            m_ser = macd_df[macd_col[0]].dropna()
                            s_ser = macd_df[sig_col[0]].dropna()
                            if len(m_ser) >= 4 and len(s_ser) >= 4:
                                for i in range(-3, 0):
                                    if m_ser.iloc[i-1] <= s_ser.iloc[i-1] and m_ser.iloc[i] > s_ser.iloc[i]:
                                        macd_cross_val = True
                                        break
                except Exception:
                    pass

                # ====== BB Squeeze ======
                bb_squeeze_flag = False
                try:
                    bb_df = ta.bbands(df['Close'], length=20, std=2)
                    if bb_df is not None and not bb_df.empty:
                        upper_col = [c for c in bb_df.columns if 'BBU' in c or 'upper' in c.lower()]
                        lower_col = [c for c in bb_df.columns if 'BBL' in c or 'lower' in c.lower()]
                        mid_col   = [c for c in bb_df.columns if 'BBM' in c or 'mid' in c.lower()]
                        if upper_col and lower_col and mid_col:
                            bbu = bb_df[upper_col[0]].dropna()
                            bbl = bb_df[lower_col[0]].dropna()
                            bbm = bb_df[mid_col[0]].dropna()
                            if len(bbu) >= 20:
                                bw = (bbu - bbl) / bbm
                                pct20 = bw.quantile(0.20)
                                if float(bw.iloc[-1]) <= float(pct20):
                                    bb_squeeze_flag = True
                except Exception:
                    pass

                # ====== Stage 2 (Weinstein): price > SMA150 AND SMA150 rising ======
                stage2_flag = False
                try:
                    sma150 = ta.sma(df['Close'], length=150)
                    if sma150 is not None:
                        sma150_clean = sma150.dropna()
                        if len(sma150_clean) >= 20:
                            sma150_cur = float(sma150_clean.iloc[-1])
                            sma150_4w  = float(sma150_clean.iloc[-20])
                            stage2_flag = (current_price > sma150_cur) and (sma150_cur > sma150_4w)
                except Exception:
                    pass

                # ====== Earnings Warning (US): earnings within 14 days ======
                earnings_soon_flag = False
                try:
                    _earn_dates = yf.Ticker(symbol).earnings_dates
                    if _earn_dates is not None and not _earn_dates.empty:
                        from datetime import date as _date_cls
                        _future = [
                            d.date() if hasattr(d, 'date') else d
                            for d in _earn_dates.index
                            if (hasattr(d, 'date') and d.date() >= scan_end_date)
                            or (isinstance(d, _date_cls) and d >= scan_end_date)
                        ]
                        if _future:
                            _days_to = (min(_future) - scan_end_date).days
                            earnings_soon_flag = _days_to <= 14
                except Exception:
                    pass

                # ====== Supply & Demand Zone ======
                entry_strat = ""
                dz_start = dz_end = sz_start = sz_end = sl_price = rr_val = None
                erc_vol_confirmed = False
                zone_target_src   = '52w'

                if sd_zone:
                    entry_strat       = sd_zone['type']
                    dz_start          = sd_zone['start']
                    dz_end            = sd_zone['end']
                    sz_start          = sd_zone['target']
                    sz_end            = sd_zone['target'] * 1.02
                    sl_price          = sd_zone['stop_loss']
                    rr_val            = sd_zone['rr_ratio']
                    erc_vol_confirmed = sd_zone.get('erc_volume_confirmed', False)
                    zone_target_src   = sd_zone.get('zone_target_source', '52w')

                prox_val = 999.0
                if dz_start:
                    prox_val = 0.0 if current_price <= dz_start else ((current_price - dz_start) / dz_start) * 100

                gap_to_high = ((year_high - current_price) / current_price) * 100

                # ====== Pocket Pivot ======
                pocket_pivot_flag = False
                try:
                    if len(df) >= 14:
                        closes  = df['Close'].values
                        volumes = df['Volume'].values
                        for _i in [-1, -2]:
                            if float(closes[_i]) <= float(closes[_i - 1]):
                                continue
                            _start = len(volumes) + _i - 10
                            _end   = len(volumes) + _i
                            if _start < 1:
                                continue
                            _prior_c = closes[_start:_end]
                            _prior_v = volumes[_start:_end]
                            _prior_prev_c = closes[_start - 1:_end - 1]
                            _down_mask = _prior_c < _prior_prev_c
                            if not _down_mask.any():
                                continue
                            _max_down_vol = float(_prior_v[_down_mask].max())
                            if float(volumes[_i]) > _max_down_vol and _max_down_vol > 0:
                                pocket_pivot_flag = True
                                break
                except Exception:
                    pass

                # ====== Volume Dry-Up (VDU) ======
                vdu_flag = False
                try:
                    if len(df) >= 4:
                        _vols  = df['Volume'].tail(4).values.astype(float)
                        _avg20 = float(df['Volume'].tail(20).mean())
                        _declining = (_vols[-1] < _vols[-2]) and (_vols[-2] < _vols[-3])
                        _quiet     = _vols[-1] < _avg20 * 0.7
                        vdu_flag   = _declining and _quiet
                except Exception:
                    pass

                pattern_result = detect_price_pattern(df)
                pattern_name   = pattern_result['name']
                pattern_score  = pattern_result['score']

                close_series = df['Close'].dropna()
                rel_1m = rel_3m = stock_3m_ret = 0.0
                if len(close_series) >= 66:
                    stock_1m    = float((close_series.iloc[-1] - close_series.iloc[-22]) / close_series.iloc[-22] * 100)
                    stock_3m    = float((close_series.iloc[-1] - close_series.iloc[-66]) / close_series.iloc[-66] * 100)
                    stock_3m_ret = stock_3m
                    rel_1m      = round(stock_1m - spy_1m_return, 2)
                    rel_3m      = round(stock_3m - spy_3m_return, 2)
                elif len(close_series) >= 22:
                    stock_1m = float((close_series.iloc[-1] - close_series.iloc[-22]) / close_series.iloc[-22] * 100)
                    rel_1m   = round(stock_1m - spy_1m_return, 2)

                return {
                    'symbol': symbol, 'price': round(current_price, 2),
                    'rsi': round(rsi, 2), 'adx': round(adx_val, 2), 'mfi': round(mfi_val, 2),
                    'rvol': round(rvol, 2), 'technical_score': int(integrated_score),
                    'avg_volume_20d': round(avg_vol_20, 0), 'rvol_bullish': rvol_bullish,
                    'erc_volume_confirmed': erc_vol_confirmed, 'zone_target_src': zone_target_src,
                    'entry_strat': entry_strat, 'dz_start': dz_start, 'dz_end': dz_end,
                    'sz_start': sz_start, 'sz_end': sz_end, 'sl_price': sl_price, 'rr_val': rr_val,
                    'year_high': round(year_high, 2), 'upside_to_high': round(gap_to_high, 2),
                    'prox_val': round(prox_val, 2), 'pattern_name': pattern_name, 'pattern_score': pattern_score,
                    'rel_1m': rel_1m, 'rel_3m': rel_3m,
                    'macd_histogram': round(macd_hist_val, 4) if macd_hist_val is not None else None,
                    'macd_crossover': macd_cross_val, 'bb_squeeze': bb_squeeze_flag,
                    'ema20_aligned': ema20_aligned_flag, 'ema20_slope': round(ema20_slope_val, 3),
                    'ema20_rising': ema20_rising_flag, 'hh_hl_structure': hh_hl_flag,
                    'stock_3m_ret': stock_3m_ret, 'rs_rating': rs_ratings_map.get(symbol, 0),
                    'stage2': stage2_flag,
                    'earnings_soon': earnings_soon_flag,
                    'pocket_pivot': pocket_pivot_flag,
                    'vdu_near_zone': vdu_flag,
                }

            except Exception as e:
                import logging
                logging.getLogger('stocks').exception(f"[US Precision] Error scanning {symbol}: {e}")
                return None

        # ====== Concurrent Scan ======
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_process_us_scan, sym) for sym in scan_symbols]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    results.append(res)

        if results:
            scan_df = pd.DataFrame(results)
            if 'rs_rating' not in scan_df.columns:
                scan_df['rs_rating'] = 0

            # ====== Bulk Fundamental Enrichment ======
            matched_symbols = [r['symbol'] for r in results]
            fund_data = {}
            try:
                yq_all = YQTicker(matched_symbols)
                modules = yq_all.get_modules('financialData summaryProfile')
                for sym_key, data in modules.items():
                    if not isinstance(data, dict):
                        continue
                    profile  = data.get('summaryProfile', {})
                    fin_data = data.get('financialData', {})
                    sector = (
                        profile.get('sector')
                        or data.get('assetProfile', {}).get('sector')
                        or 'Unknown'
                    )
                    eps_growth = float(fin_data.get('earningsQuarterlyGrowth', 0) or 0) * 100
                    rev_growth = float(fin_data.get('revenueGrowth', 0) or 0) * 100
                    fund_data[sym_key.upper()] = {
                        'sector': sector, 'eps_growth': eps_growth, 'rev_growth': rev_growth,
                    }
            except Exception as e:
                print(f"[US Precision] Bulk Fundamental fetch failed: {e}")

            # ====== Bulk Create ======
            bulk_candidates = []
            for r in scan_df.to_dict('records'):
                sym = r['symbol']
                f = fund_data.get(sym.upper(), {'sector': 'N/A', 'eps_growth': 0.0, 'rev_growth': 0.0})
                bulk_candidates.append(PrecisionScanCandidate(
                    user=request.user, market='US', scan_run=scan_run_time,
                    symbol=sym, symbol_bk=sym,
                    sector=f.get('sector') or 'Unknown',
                    price=r['price'], rsi=r['rsi'], adx=r['adx'], mfi=r['mfi'], rvol=r['rvol'],
                    eps_growth=round(f.get('eps_growth', 0), 2),
                    rev_growth=round(f.get('rev_growth', 0), 2),
                    technical_score=r['technical_score'], rs_rating=r['rs_rating'],
                    avg_volume_20d=r['avg_volume_20d'], rvol_bullish=r['rvol_bullish'],
                    erc_volume_confirmed=r['erc_volume_confirmed'],
                    zone_target_source=r['zone_target_src'],
                    is_new_entry=(sym not in prev_symbols),
                    entry_strategy=r['entry_strat'],
                    demand_zone_start=r['dz_start'], demand_zone_end=r['dz_end'],
                    supply_zone_start=r['sz_start'], supply_zone_end=r['sz_end'],
                    stop_loss=r['sl_price'], risk_reward_ratio=r['rr_val'],
                    year_high=r['year_high'], upside_to_high=r['upside_to_high'],
                    zone_proximity=r['prox_val'], price_pattern=r['pattern_name'],
                    price_pattern_score=r['pattern_score'],
                    rel_momentum_1m=r['rel_1m'], rel_momentum_3m=r['rel_3m'],
                    macd_histogram=r['macd_histogram'], macd_crossover=r['macd_crossover'],
                    bb_squeeze=r['bb_squeeze'], ema20_aligned=r['ema20_aligned'],
                    ema20_slope=r.get('ema20_slope', 0.0),
                    ema20_rising=r.get('ema20_rising', False),
                    hh_hl_structure=r.get('hh_hl_structure', False),
                    stage2=r.get('stage2', False),
                    earnings_soon=r.get('earnings_soon', False),
                    pocket_pivot=r.get('pocket_pivot', False),
                    vdu_near_zone=r.get('vdu_near_zone', False),
                ))

            if bulk_candidates:
                PrecisionScanCandidate.objects.bulk_create(bulk_candidates)

        # เก็บ 3 รอบล่าสุด
        distinct_runs = (
            PrecisionScanCandidate.objects
            .filter(user=request.user, market='US')
            .values_list('scan_run', flat=True)
            .order_by('-scan_run').distinct()
        )
        runs_list = list(distinct_runs)
        if len(runs_list) > 3:
            PrecisionScanCandidate.objects.filter(
                user=request.user, market='US', scan_run__in=runs_list[3:]
            ).delete()

    # ====== Sort & Display ======
    sort_by = request.GET.get('sort', 'score')
    valid_db_sorts = {
        'symbol': 'symbol', 'score': '-technical_score', 'price': '-price',
        'rsi': '-rsi', 'rvol': '-rvol', 'adx': '-adx',
        'prox': 'zone_proximity', 'round_rr': '-risk_reward_ratio', 'rs': '-rs_rating',
    }
    use_db_sort  = sort_by in valid_db_sorts
    order_field  = valid_db_sorts.get(sort_by, '-technical_score')

    all_runs = list(
        PrecisionScanCandidate.objects
        .filter(user=request.user, market='US')
        .values_list('scan_run', flat=True)
        .order_by('-scan_run').distinct()
    )

    try:
        run_idx = int(request.GET.get('run_idx', 0))
    except (ValueError, TypeError):
        run_idx = 0
    run_idx = max(0, min(run_idx, len(all_runs) - 1)) if all_runs else 0

    candidates = []
    scanned_at = None
    if all_runs:
        selected_run = all_runs[run_idx]
        qs = PrecisionScanCandidate.objects.filter(user=request.user, market='US', scan_run=selected_run)
        if use_db_sort:
            qs = qs.order_by(order_field)
        candidates = list(qs)
        scanned_at = selected_run

        # ====== Live Price (NYSE hours) ======
        import pytz as _lpytz
        from datetime import datetime as _ldt, time as _ldtime
        _lny = _lpytz.timezone('America/New_York')
        _lnow = _ldt.now(_lny)
        _lt   = _lnow.time()
        _lmarket_open = (
            _lnow.weekday() < 5 and
            _ldtime(9, 30) <= _lt <= _ldtime(16, 0)
        )
        live_prices = {}
        live_mcaps  = {}
        if candidates:
            try:
                import concurrent.futures as _lcf
                def _get_live_us(sym):
                    try:
                        fi = yf.Ticker(sym).fast_info
                        p  = getattr(fi, 'last_price', None)
                        mc = getattr(fi, 'market_cap', None)
                        return sym, (float(p) if p else None), (round(float(mc)/1e9, 2) if mc else None)
                    except Exception:
                        return sym, None, None
                with _lcf.ThreadPoolExecutor(max_workers=12) as _lex:
                    for _sym, _p, _mc in _lex.map(_get_live_us, [c.symbol for c in candidates]):
                        if _p:  live_prices[_sym] = _p
                        if _mc: live_mcaps[_sym]  = _mc
            except Exception:
                pass

        for c in candidates:
            lp = live_prices.get(c.symbol)
            c.live_price      = lp
            c.live_market_cap = live_mcaps.get(c.symbol)
            c.is_live         = _lmarket_open and lp is not None
            if lp and c.demand_zone_start and c.demand_zone_start > 0:
                c.live_zone_prox = 0.0 if lp <= c.demand_zone_start else round(((lp - c.demand_zone_start) / c.demand_zone_start) * 100, 1)
            else:
                c.live_zone_prox = None
            if lp and c.price and c.price > 0:
                c.live_change_pct = round(((lp - c.price) / c.price) * 100, 2)
            else:
                c.live_change_pct = None

        # ====== BUY/SELL Signals ======
        for c in candidates:
            sigs = _compute_signals(c)
            c.buy_score   = sigs['buy_score']
            c.sell_score  = sigs['sell_score']
            c.exit_signal = sigs['exit_signal']

        # ====== BUY Score Delta vs previous run ======
        prev_buy_scores_us = {}
        if len(all_runs) > run_idx + 1:
            for _p in PrecisionScanCandidate.objects.filter(
                    user=request.user, market='US', scan_run=all_runs[run_idx + 1]):
                _ps = _compute_signals(_p)
                prev_buy_scores_us[_p.symbol] = _ps['buy_score']
        for c in candidates:
            _prev = prev_buy_scores_us.get(c.symbol)
            c.buy_score_delta = (c.buy_score - _prev) if _prev is not None else None

        if sort_by == 'buy':
            candidates.sort(key=lambda x: x.buy_score, reverse=True)
        elif sort_by == 'sell':
            candidates.sort(key=lambda x: x.sell_score, reverse=True)
        elif sort_by == 'rs':
            candidates.sort(key=lambda x: getattr(x, 'rs_rating', 0), reverse=True)

        # ====== Top 5 BUY ======
        def _top5_us(min_rvol, max_rsi=85):
            return sorted(
                [c for c in candidates
                 if c.buy_score >= 50 and c.rvol_bullish
                 and c.rvol >= min_rvol and c.rsi <= max_rsi],
                key=lambda x: x.buy_score, reverse=True
            )[:5]

        top5_buy = _top5_us(1.0)
        if len(top5_buy) < 5:
            top5_buy = _top5_us(0.7)
        if len(top5_buy) < 3:
            top5_buy = _top5_us(0.0)

        # ====== Top 5 Qualified ======
        def _qualified_us(c):
            rr = c.risk_reward_ratio or 0
            in_zone   = (c.demand_zone_start and c.demand_zone_end and
                         c.price <= c.demand_zone_start and c.price >= c.demand_zone_end)
            near_zone = in_zone or (c.zone_proximity <= 30)
            return (
                c.buy_score >= 65 and rr >= 1.5 and c.adx >= 20 and
                45 <= c.rsi <= 82 and c.rvol_bullish and c.rvol >= 0.8 and
                near_zone and (c.sell_score or 0) < 50 and
                getattr(c, 'rs_rating', 0) >= 60
            )

        top5_qualified = sorted(
            [c for c in candidates if _qualified_us(c)],
            key=lambda x: x.buy_score, reverse=True
        )

        for c in top5_buy:
            reasons = []
            in_zone = (c.demand_zone_start and c.demand_zone_end and
                       c.price <= c.demand_zone_start and c.price >= c.demand_zone_end)
            if in_zone:
                reasons.append("In Entry Zone")
            elif c.zone_proximity <= 10:
                reasons.append(f"Near Zone {c.zone_proximity:.0f}%")
            elif c.zone_proximity <= 30:
                reasons.append(f"Approaching Zone {c.zone_proximity:.0f}%")
            if c.rvol_bullish and c.rvol >= 1.5:
                reasons.append(f"RVOL {c.rvol:.1f}x Bull Strong")
            elif c.rvol_bullish and c.rvol >= 1.0:
                reasons.append(f"RVOL {c.rvol:.1f}x Bull")
            rr = c.risk_reward_ratio or 0
            if rr >= 3:
                reasons.append(f"RR 1:{rr:.1f} Excellent")
            elif rr >= 2:
                reasons.append(f"RR 1:{rr:.1f} Good")
            if c.adx >= 30:
                reasons.append(f"ADX {c.adx:.0f} Strong")
            elif c.adx >= 25:
                reasons.append(f"ADX {c.adx:.0f} Trending")
            if c.technical_score >= 85:
                reasons.append(f"Precision {c.technical_score} High")
            elif c.technical_score >= 75:
                reasons.append(f"Precision {c.technical_score}")
            if c.erc_volume_confirmed:
                reasons.append("ERC Confirmed")
            if 55 <= c.rsi <= 70:
                reasons.append(f"RSI {c.rsi:.0f} Sweet Spot")
            if c.price_pattern and c.price_pattern_score > 0:
                reasons.append(f"Pattern: {c.price_pattern}")
            rel = c.rel_momentum_3m if c.rel_momentum_3m != 0.0 else c.rel_momentum_1m
            if rel >= 8:
                reasons.append(f"Beats SPY +{rel:.1f}% (3m)")
            elif rel >= 3:
                reasons.append(f"Beats SPY +{rel:.1f}%")
            rs = getattr(c, 'rs_rating', 0)
            if rs >= 85:
                reasons.insert(1, f"RS {rs} — Market Leader")
            elif rs >= 70:
                reasons.insert(1, f"RS {rs} — Strong")
            c.top_reasons = reasons[:4]

        for c in top5_qualified:
            if not hasattr(c, 'top_reasons'):
                reasons = []
                in_zone = (c.demand_zone_start and c.demand_zone_end and
                           c.price <= c.demand_zone_start and c.price >= c.demand_zone_end)
                if in_zone:
                    reasons.append("In Entry Zone")
                elif c.zone_proximity <= 10:
                    reasons.append(f"Near Zone {c.zone_proximity:.0f}%")
                else:
                    reasons.append(f"Zone Dist {c.zone_proximity:.0f}%")
                rr = c.risk_reward_ratio or 0
                reasons.append(f"RR 1:{rr:.1f} ✓")
                reasons.append(f"ADX {c.adx:.0f} ✓")
                rs = getattr(c, 'rs_rating', 0)
                if rs >= 85:
                    reasons.insert(1, f"RS {rs} — Leader")
                elif rs >= 70:
                    reasons.insert(1, f"RS {rs} — Strong")
                if c.rvol >= 1.5:
                    reasons.append(f"RVOL {c.rvol:.1f}x Bull ✓")
                c.top_reasons = reasons[:4]

        # ====== Leading Sectors ======
        sector_counts = {}
        for c in candidates:
            if c.buy_score >= 65:
                sec = c.sector or 'Unknown'
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
        top_sectors = sorted(
            [{'name': k, 'count': v} for k, v in sector_counts.items()],
            key=lambda x: x['count'], reverse=True
        )[:5]

        # ====== AI Insights ======
        scan_insights = []
        if top5_qualified:
            best = top5_qualified[0]
            rr_val = best.risk_reward_ratio or 0
            rs_val = getattr(best, 'rs_rating', 0)
            scan_insights.append({
                'icon': '🏆',
                'title': f'Best Setup: {best.symbol} (High Reward/Risk)',
                'desc': (f'Top-ranked US play this scan. RS {rs_val}, strong trend, '
                         f'price near entry zone. RR 1:{rr_val:.1f} — favorable reward-to-risk.'),
            })
        high_risk_mo = [c for c in top5_buy if getattr(c, 'rs_rating', 0) >= 90 and (c.risk_reward_ratio or 0) < 1.5]
        if high_risk_mo:
            hm = high_risk_mo[0]
            if not top5_qualified or hm.symbol != top5_qualified[0].symbol:
                scan_insights.append({
                    'icon': '🚀',
                    'title': f'Momentum Leader: {hm.symbol} (Extended)',
                    'desc': (f'RS {getattr(hm, "rs_rating", 0)}, heavy volume. '
                             f'RR 1:{hm.risk_reward_ratio or 0:.1f} — price extended. Watch for pullback entry.'),
                })
        if not scan_insights and top5_buy:
            top = top5_buy[0]
            scan_insights.append({
                'icon': '💡',
                'title': f'Watchlist: {top.symbol}',
                'desc': 'Highest BUY score this scan. Monitor for entry near demand zone.',
            })

    else:
        top5_buy = []
        top5_qualified = []
        top_sectors = []
        scan_insights = []

    context = {
        'title': 'US Precision Momentum Scanner — Nasdaq & S&P 500',
        'candidates': candidates,
        'scanned_at': scanned_at,
        'current_sort': sort_by,
        'all_runs': all_runs,
        'selected_run_idx': run_idx,
        'has_scanned': request.method == "POST" or request.GET.get('scan') == 'true' or bool(all_runs),
        'top5_buy': top5_buy,
        'top5_qualified': top5_qualified,
        'scan_total': len(scan_symbols),
        'scan_passed': len(candidates),
        'top_sectors': top_sectors,
        'scan_insights': scan_insights,
        'scan_data_date': None,
    }

    if scanned_at:
        import pytz as _sddtz
        _ny = _sddtz.timezone('America/New_York')
        _st = scanned_at.astimezone(_ny) if hasattr(scanned_at, 'astimezone') else scanned_at
        from datetime import time as _t, timedelta as _tdd
        _in_mkt = (_st.weekday() < 5 and _t(9, 30) <= _st.time() <= _t(16, 0))
        context['scan_data_date'] = (_st.date() - _tdd(days=1)) if _in_mkt else _st.date()

    import json as _scan_json
    def _ser_c_us(c):
        return {
            "symbol": c.symbol, "price": c.price,
            "buy_score": getattr(c, 'buy_score', 0), "rs_rating": getattr(c, 'rs_rating', 0),
            "rsi": round(c.rsi, 1), "adx": round(c.adx, 1), "rvol": round(c.rvol, 2),
            "rvol_bullish": c.rvol_bullish, "risk_reward_ratio": c.risk_reward_ratio,
            "zone_proximity": round(c.zone_proximity, 1) if c.zone_proximity else None,
            "macd_crossover": getattr(c, 'macd_crossover', False),
            "ema20_aligned": getattr(c, 'ema20_aligned', False),
            "ema20_rising": getattr(c, 'ema20_rising', False),
            "hh_hl_structure": getattr(c, 'hh_hl_structure', False),
            "bb_squeeze": getattr(c, 'bb_squeeze', False),
            "rel_momentum_3m": getattr(c, 'rel_momentum_3m', 0),
            "sector": c.sector, "exit_signal": getattr(c, 'exit_signal', ''),
            "top_reasons": getattr(c, 'top_reasons', []),
        }
    _ai_data = {
        "scan_date": str(context.get('scan_data_date', '')),
        "qualified_stocks": [_ser_c_us(c) for c in top5_qualified],
        "top_buy_stocks": [_ser_c_us(c) for c in top5_buy],
        "total_passed": len(candidates),
        "top_sectors": [{"name": s["name"], "count": s["count"]} for s in top_sectors],
    }
    context['ai_scan_json'] = _scan_json.dumps(_ai_data, ensure_ascii=False, default=str)
    return render(request, 'stocks/us_precision_scan.html', context)


# ======================================================================
# US PRECISION SCAN AI ANALYSIS
# ======================================================================

@login_required
def us_precision_scan_ai_analysis(request):
    import json as _json_lib
    from django.http import JsonResponse
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        body = _json_lib.loads(request.body)
        scan_data = body.get("scan_data", {})
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return JsonResponse({"error": "No GEMINI_API_KEY configured"}, status=500)

    qualified    = scan_data.get("qualified_stocks", [])
    top_buy      = scan_data.get("top_buy_stocks", [])
    scan_date    = scan_data.get("scan_date", "N/A")
    total_passed = scan_data.get("total_passed", 0)
    top_sectors  = scan_data.get("top_sectors", [])

    def _fmt_stock(s):
        lines = [
            "  - {sym}: Price ${price} | BUY {buy} | RS {rs}".format(
                sym=s["symbol"], price=s["price"], buy=s["buy_score"], rs=s["rs_rating"]),
            "    RSI {rsi} | ADX {adx} | RVOL {rvol}x {dir} | RR 1:{rr}".format(
                rsi=s["rsi"], adx=s["adx"], rvol=s["rvol"],
                dir="Bull ▲" if s.get("rvol_bullish") else "Bear ▼",
                rr=s.get("risk_reward_ratio", "-")),
            "    Zone {z}% | {sec} | RelMom3m vs SPY {rm}%".format(
                z=s.get("zone_proximity", "-"), sec=s.get("sector", "-"),
                rm=s.get("rel_momentum_3m", 0)),
            "    Signals: {m}{e}{h}{b}{a}".format(
                m="MACD✕ " if s.get("macd_crossover") else "",
                e="EMA↑ " if s.get("ema20_rising") else "",
                h="HH/HL " if s.get("hh_hl_structure") else "",
                b="BB Squeeze " if s.get("bb_squeeze") else "",
                a="EMA20 Aligned " if s.get("ema20_aligned") else ""),
        ]
        if s.get("top_reasons"):
            lines.append("    Reasons: {r}".format(r=", ".join(s["top_reasons"])))
        return "\n".join(lines)

    q_text   = "\n".join([_fmt_stock(s) for s in qualified]) if qualified else "  (No fully qualified stocks)"
    b_text   = "\n".join([_fmt_stock(s) for s in top_buy]) if top_buy else "  (No data)"
    sec_text = ", ".join(["{n}({c})".format(n=s["name"], c=s["count"]) for s in top_sectors]) if top_sectors else "N/A"

    prompt = (
        "You are an expert US equity analyst specializing in Precision Momentum trading"
        " (Mark Minervini SEPA + William O'Neil CAN SLIM methodology).\n"
        "Expert in Stage Analysis, RS Rating, Supply/Demand Zone,"
        " RVOL Bull/Bear, MACD Crossover, EMA Alignment, Trend Following (HH/HL).\n\n"
        "US Precision Scan Date: {sd} | Stocks Passed Filter: {tp}"
        " | Leading Sectors: {sec}\n\n"
        "=== Fully Qualified Stocks (All Criteria Met) ===\n{q}\n\n"
        "=== Top BUY Score Stocks ===\n{b}\n\n"
        "Analyze the following:\n\n"
        "## 1. 📊 US Market Overview\n"
        "- Market sentiment (Bullish/Mixed/Bearish), Leading sectors, SPY context\n\n"
        "## 2. ✅ Fully Qualified Setups\n"
        "- Each stock: Key strengths, risks, upside potential, priority ranking\n\n"
        "## 3. 🏆 Top BUY Score Analysis\n"
        "- Most attractive setup and why | What to watch out for\n\n"
        "## 4. ⚡ Trading Strategy\n"
        "- Entry order: Which first, which to wait | Optimal entry zones\n\n"
        "## 5. ⚠ Risk Warnings\n"
        "- RSI/RVOL/Zone concerns | Stop Loss discipline | Macro risks\n\n"
        "Reply in English. Be concise and professional."
        " Format as Markdown. Focus on Actionable Insights."
    ).format(sd=scan_date, tp=total_passed, sec=sec_text, q=q_text, b=b_text)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        if not response.text:
            return JsonResponse({"error": "AI did not respond"}, status=500)
        return JsonResponse({"status": "success", "analysis": response.text})
    except Exception as e:
        err = str(e)
        if "API_KEY_INVALID" in err:
            return JsonResponse({"error": "GEMINI_API_KEY is invalid"}, status=500)
        return JsonResponse({"error": "Gemini error: {}".format(err)}, status=500)


# ============================================================
# US VALUE SCANNER
# ============================================================

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

            # RSI — underowned zone
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


@login_required
def us_value_scanner(request):
    """
    US Value Stock Scanner — fundamental quality + cheap valuation.
    P/E < 25 across all sectors (Financials, Energy, Healthcare, Tech, etc.)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import datetime as _dt, timezone as _tz
    import pandas_ta as ta

    run_scan = request.GET.get('scan') == 'true'
    current_sort = request.GET.get('sort', 'score')

    sort_map = {
        'score': '-total_score', 'val': '-valuation_score',
        'qual': '-quality_score', 'pe': 'pe_ratio',
        'pb': 'pb_ratio',        'div': '-dividend_yield',
        'roe': '-roe',           'symbol': 'symbol',
        'price': '-price',       'rsi': 'rsi',
    }

    # ── Load from DB (display mode) ───────────────────────
    if not run_scan:
        all_runs = list(
            ValueScanCandidate.objects
            .filter(user=request.user)
            .values_list('scan_run', flat=True)
            .order_by('-scan_run').distinct()
        )
        has_scanned = bool(all_runs)
        candidates = []
        scanned_at = None

        try:
            run_idx = int(request.GET.get('run_idx', 0))
        except (ValueError, TypeError):
            run_idx = 0
        run_idx = max(0, min(run_idx, len(all_runs) - 1)) if all_runs else 0

        if has_scanned:
            selected_run = all_runs[run_idx]
            scanned_at   = selected_run
            qs = (ValueScanCandidate.objects
                  .filter(user=request.user, scan_run=selected_run)
                  .order_by(sort_map.get(current_sort, '-total_score')))
            candidates = list(qs)

            # Live prices (fast_info)
            live_prices = {}
            try:
                import concurrent.futures as _lcf
                def _get_live_val(sym):
                    try:
                        fi = yf.Ticker(sym).fast_info
                        p = getattr(fi, 'last_price', None)
                        return sym, round(float(p), 2) if p else None
                    except Exception:
                        return sym, None
                with _lcf.ThreadPoolExecutor(max_workers=12) as ex:
                    for sym, p in ex.map(_get_live_val, [c.symbol for c in candidates]):
                        if p:
                            live_prices[sym] = p
            except Exception:
                pass
            for c in candidates:
                c.live_price = live_prices.get(c.symbol)

        return render(request, 'stocks/us_value_scan.html', {
            'candidates':       candidates,
            'has_scanned':      has_scanned,
            'scanned_at':       scanned_at,
            'all_runs':         all_runs,
            'selected_run_idx': run_idx,
            'current_sort':     current_sort,
        })

    # ── RUN SCAN ──────────────────────────────────────────
    symbols = _seed_value_symbols()
    scan_time = _dt.now(_tz.utc)
    results = []

    def _process_value_symbol(sym):
        try:
            ticker = yf.Ticker(sym)
            info   = ticker.info or {}

            price = info.get('regularMarketPrice') or info.get('currentPrice') or 0
            if not price:
                fi = getattr(ticker, 'fast_info', None)
                price = getattr(fi, 'last_price', 0) or 0
            if not price or price <= 0:
                return None

            # P/E filter — skip pure growth stocks (P/E > 30)
            pe = info.get('trailingPE') or info.get('forwardPE')
            if pe and pe > 30:
                return None

            # Market cap filter — at least $2B (mid/large cap)
            mkt_cap = (info.get('marketCap') or 0) / 1e9
            if mkt_cap < 2:
                return None

            # Download 1-year price history for technical indicators
            df = yf.download(sym, period='1y', progress=False, auto_adjust=True)
            if df is None or len(df) < 50:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)

            val_score, qual_score, price_score, total = _score_value_candidate(info, df)

            # Minimum quality threshold
            if total < 20:
                return None

            # Compute additional price stats
            close = df['Close']
            rsi14  = ta.rsi(close, length=14)
            rsi_val = float(rsi14.dropna().iloc[-1]) if rsi14 is not None and not rsi14.dropna().empty else 50
            y_high = float(df['High'].max())
            y_low  = float(df['Low'].min())
            pct_from_high = ((y_high - float(close.iloc[-1])) / y_high * 100) if y_high > 0 else 0

            ema200 = ta.ema(close, length=200)
            above_ema200 = False
            if ema200 is not None and not ema200.dropna().empty:
                above_ema200 = float(close.iloc[-1]) > float(ema200.dropna().iloc[-1])

            div = (info.get('dividendYield') or 0) * 100
            roe = (info.get('returnOnEquity') or 0) * 100
            margin = (info.get('profitMargins') or 0) * 100
            de_raw = info.get('debtToEquity')
            de  = (de_raw / 100) if de_raw is not None else None
            fcf_raw = info.get('freeCashflow') or 0
            fcf_yield = (fcf_raw / (info.get('marketCap') or 1)) * 100 if fcf_raw and mkt_cap > 0 else 0

            return {
                'symbol':       sym,
                'name':         info.get('longName') or info.get('shortName') or sym,
                'sector':       info.get('sector') or 'Unknown',
                'price':        round(float(price), 2),
                'market_cap':   round(mkt_cap, 2),
                'pe_ratio':     round(float(pe), 2) if pe and pe > 0 else None,
                'forward_pe':   round(float(info.get('forwardPE') or 0), 2) or None,
                'pb_ratio':     round(float(info.get('priceToBook') or 0), 2) or None,
                'peg_ratio':    round(float(info.get('pegRatio') or 0), 2) or None,
                'ps_ratio':     round(float(info.get('priceToSalesTrailing12Months') or 0), 2) or None,
                'dividend_yield': round(div, 2),
                'roe':          round(roe, 1) if roe else None,
                'profit_margin': round(margin, 1) if margin else None,
                'debt_equity':  round(de, 2) if de is not None else None,
                'current_ratio': round(float(info.get('currentRatio') or 0), 2) or None,
                'revenue_growth': round((info.get('revenueGrowth') or 0) * 100, 1),
                'fcf_yield':    round(fcf_yield, 1),
                'rsi':          round(rsi_val, 1),
                'year_high':    round(y_high, 2),
                'year_low':     round(y_low, 2),
                'pct_from_high': round(pct_from_high, 1),
                'above_ema200': above_ema200,
                'valuation_score':    val_score,
                'quality_score':      qual_score,
                'price_action_score': price_score,
                'total_score':        total,
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_process_value_symbol, sym): sym for sym in symbols}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)

    results.sort(key=lambda x: -x['total_score'])

    # Fetch previous symbols for new-entry flag
    prev_run_q = (ValueScanCandidate.objects
                  .filter(user=request.user)
                  .order_by('-scan_run')
                  .values_list('scan_run', flat=True)
                  .distinct()[:1])
    prev_symbols = set()
    if prev_run_q:
        prev_symbols = set(
            ValueScanCandidate.objects.filter(user=request.user, scan_run=prev_run_q[0])
            .values_list('symbol', flat=True)
        )

    # Save new results FIRST
    to_create = []
    for r in results:
        to_create.append(ValueScanCandidate(
            user=request.user, scan_run=scan_time,
            symbol=r['symbol'], name=r['name'], sector=r['sector'],
            price=r['price'], market_cap=r['market_cap'],
            pe_ratio=r['pe_ratio'], forward_pe=r['forward_pe'],
            pb_ratio=r['pb_ratio'], peg_ratio=r['peg_ratio'],
            ps_ratio=r['ps_ratio'], dividend_yield=r['dividend_yield'],
            roe=r['roe'], profit_margin=r['profit_margin'],
            debt_equity=r['debt_equity'], current_ratio=r['current_ratio'],
            revenue_growth=r['revenue_growth'], fcf_yield=r['fcf_yield'],
            rsi=r['rsi'], year_high=r['year_high'], year_low=r['year_low'],
            pct_from_high=r['pct_from_high'], above_ema200=r['above_ema200'],
            valuation_score=r['valuation_score'],
            quality_score=r['quality_score'],
            price_action_score=r['price_action_score'],
            total_score=r['total_score'],
            is_new_entry=(r['symbol'] not in prev_symbols),
        ))
    ValueScanCandidate.objects.bulk_create(to_create)

    # THEN delete old runs (keep last 3)
    distinct_runs = list(
        ValueScanCandidate.objects
        .filter(user=request.user)
        .values_list('scan_run', flat=True)
        .order_by('-scan_run').distinct()
    )
    if len(distinct_runs) > 3:
        ValueScanCandidate.objects.filter(
            user=request.user, scan_run__in=distinct_runs[3:]
        ).delete()

    return redirect(f'/stocks/value/us-value/?sort={current_sort}&run_idx=0')
@login_required
def crew_analyze(request, symbol):
    """
    หน้าแสดงผลการวิเคราะห์เจาะลึกด้วย CrewAI Multi-Agent System.
    ใช้เวลาในการประมวลผลนานกว่าปกติเพราะ Agent มีการโต้ตอบกัน.
    """
    try:
        crew = MomentumCrew(symbol)
        result = crew.run_analysis()
        
        # ดึงข้อมูลเบื้องต้นเพื่อใช้ในหัวข่าว
        data = get_stock_data(symbol)
        
        context = {
            'symbol': symbol,
            'crew_result': result,
            'info': data.get('info', {}),
            'title': f'CrewAI Deep Analysis: {symbol}'
        }
        return render(request, 'stocks/crew_result.html', context)
    except Exception as e:
        messages.error(request, f"CrewAI Analysis Error: {str(e)}")
        return redirect('stocks:analyze', symbol=symbol)
