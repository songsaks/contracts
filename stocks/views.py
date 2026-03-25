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
    MomentumCandidate, ScannableSymbol, MultiFactorCandidate, SoldStock
)
from .utils import (
    get_stock_data, analyze_with_ai, calculate_trailing_stop,
    refresh_set100_symbols, find_supply_demand_zones, find_supply_demand_zones_v2,
    detect_price_pattern
)
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
    # ยอดฮิต Minervini Style (max 15 pts) - ให้ความสำคัญกับ RS มากขึ้นเนื่องจากเน้น Momentum ล้วน
    if rs_rat >= 85:   buy += 15
    elif rs_rat >= 70: buy += 8
    elif rs_rat >= 50: buy += 3


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

        # ส่งข้อมูลให้ AI วิเคราะห์และรับผลเป็น Markdown
        analysis_text = analyze_with_ai(symbol, data, extra_context=extra_ctx)

        # ====== เตรียมข้อมูลกราฟราคาและวอลลุ่ม ======
        # Prepare Chart Data (Price & Volume)
        history = data.get('history', pd.DataFrame())
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
            'title': f"AI Analysis: {symbol}"
        }
        return render(request, 'stocks/analysis.html', context)
    except Exception as e:
        messages.error(request, f"Error analyzing {symbol}: {str(e)}")
        return redirect('stocks:dashboard')

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

            # ====== คำนวณ Trailing Stop ======
            # ใช้ราคาสูงสุดใน 1 ปีเป็น highest_price_since_buy
            # Trailing Stop
            recent_high = hist['High'].max() if not hist.empty else None
            ts_data = calculate_trailing_stop(
                symbol=item.symbol,
                current_price=float(current_price),
                entry_price=float(item.entry_price or 0),
                highest_price_since_buy=recent_high,
                percent_trail=3.0  # Trailing 3% จาก High
            ) if current_price > 0 else None

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
            port_data.append(f"{it['obj'].symbol}: {it['obj'].quantity} units @ {it['obj'].entry_price} (Current: {it['current_price']}, P/L: {it['gain_loss_pct']:.2f}%, RSI: {it['rsi']})")
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
        You are an expert Stock Portfolio Analyst. The user has the following assets in their portfolio (with Entry Price, Current Price, and Profit/Loss):
        {port_str}

        {ppo_advice}

        Please analyze this portfolio and provide:
        1. An overall assessment of the portfolio's health, performance, and diversification based on the Efficient Frontier data provided.
        2. A brief analysis and clear recommendation for EACH individual asset (e.g., Hold, Buy More, Take Profit, Cut Loss) based on its current P/L, RSI, and Optimal Weights.
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

            # ====== Action Recommendation ======
            if exit_signal == 'STRONG EXIT' or sl_hit:
                action       = 'ออกทันที'
                action_style = 'danger'
                action_detail = f"ขายทั้งหมด {quantity:.0f} หุ้น — สัญญาณออกแรงมาก"
            elif exit_signal == 'EXIT':
                action       = 'ทยอยขาย 50%'
                action_style = 'warning'
                action_detail = f"ขาย {quantity/2:.0f} หุ้น เก็บกำไรบางส่วน — เฝ้าดูต่อ"
            elif exit_signal == 'WATCH':
                action       = 'เฝ้าระวัง'
                action_style = 'warning-soft'
                action_detail = "ยังถือได้ แต่เริ่มเฝ้าดู — ขันน็อต SL ให้แน่นขึ้น"
            elif tp_price and current_price >= tp_price * 0.95:
                action       = 'ใกล้ TP'
                action_style = 'info'
                action_detail = f"ราคาใกล้ TP แล้ว — เตรียมทยอยขาย"
            else:
                action       = 'ถือต่อ'
                action_style = 'success'
                action_detail = "ยังไม่มีสัญญาณออก — ถือต่อตาม SL เดิม"

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
            })
        except Exception as e:
            print(f"[ExitPlan] Error {item.symbol}: {e}")
            continue

    # เรียงตาม SELL Score สูงสุดก่อน
    items.sort(key=lambda x: x['sell_score'], reverse=True)

    return render(request, 'stocks/portfolio_exit_plan.html', {'items': items})


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
        {'id': 'set', 'name': 'SET Index (ดัชนีหุ้นไทย)', 'symbol': '^SET', 'unit': 'Points', 'desc': 'ดัชนีตลาดหลักทรัพย์แห่งประเทศไทย บ่งบอกสภาวะตลาดโดยรวม ถ้าเพิ่มขึ้นแปลว่าเศรษฐกิจ/ตลาดหุ้นไทยดีขึ้น'},
        {'id': 'usdthb', 'name': 'USD/THB (อัตราแลกเปลี่ยนดอลลาร์/บาท)', 'symbol': 'USDTHB=X', 'unit': 'THB', 'desc': 'บาทอ่อนชงดีต่อภาคส่งออกและการท่องเที่ยว แต่อาจทำให้เงินทุนต่างชาติไหลออก'},
        {'id': 'gold', 'name': 'Gold (ราคาทองคำโลก GC=F)', 'symbol': 'GC=F', 'unit': 'USD/oz', 'desc': 'ทองคำเป็นสินทรัพย์ปลอดภัย (Safe Haven) มักจะขึ้นเมื่อเงินเฟ้อสูงหรือเศรษฐกิจมีความเสี่ยง'},
        {'id': 'wti', 'name': 'WTI Crude Oil (น้ำมันดิบ WTI)', 'symbol': 'CL=F', 'unit': 'USD/bbl', 'desc': 'ราคาน้ำมันจะกระทบโดยตรงต่อต้นทุนพลังงาน ค่าขนส่ง และอัตราเงินเฟ้อ'},
        {'id': 'brent', 'name': 'Brent Crude Oil (น้ำมันดิบเบรนท์)', 'symbol': 'BZ=F', 'unit': 'USD/bbl', 'desc': 'เป็นมาตรฐานราคาของฝั่งยุโรปและเอเชีย ซึ่งไทยมักมีต้นทุนแปรผันตามราคานี้'}
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

                # เตรียมข้อมูล labels และ values สำหรับกราฟ Chart.js
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
    # AI Analysis for Macro Economy
    analysis_text = None
    if request.GET.get('analyze') == 'true' and data:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        model_name_to_use = 'gemini-2.5-flash'

        # สร้าง string สรุปข้อมูลมหภาคเพื่อส่งให้ AI
        data_str = "\n".join([f"{d['name']}: {d['price']:.2f} ({d['change']:+.2f}%)" for d in data])
        prompt = f"""
        You are an expert Thai Macroeconomist and Investment Strategist. Based on the following current market data:
        {data_str}

        Please provide a comprehensive 'Macroeconomic & Sector Strategy' report in Thai.
        1. **Market Overview**: Summarize the current situation (Baht strength, Oil price trend, etc.).
        2. **Economic Impact**: Analyze how these numbers affect the overall Thai economy and SET Index.
        3. **Sectoral Analysis & Target Stocks**: Identify industries (e.g. Energy, Banking, Export, Tourism, Transport) that are impacted.
           - สำหรับแต่ละกลุ่มอุตสาหกรรม ให้ระบุรายชื่อหุ้นไทยอย่างน้อย 5 หุ้นที่ได้รับผลกระทบ (ทั้งบวกหรือลบ)
           - พร้อมอธิบายสั้นๆ ว่าปัจจัยเศรษฐกิจชุดนี้ส่งผลต่อหุ้นกลุ่มนั้นอย่างไร
        4. **Actionable Investment Strategy**: A clear strategy for the current market conditions.

        Format in beautiful Markdown for a professional web report. Use Sarabun style tone.
        IMPORTANT RULES:
        1. DO NOT include any conversational preamble or outro.
        2. Output ONLY the raw markdown text.
        3. DO NOT wrap the output in ```markdown code blocks.
        """

        try:
            response = client.models.generate_content(
                model=model_name_to_use,
                contents=prompt
            )
            analysis_text = response.text

            # ลบ markdown block wrapper ถ้า AI ไม่ปฏิบัติตาม prompt
            # Strip any residual markdown blocks if AI disobeys
            if analysis_text.startswith("```markdown"):
                analysis_text = analysis_text[len("```markdown"):].strip()
            if analysis_text.endswith("```"):
                analysis_text = analysis_text[:-3].strip()
        except Exception as e:
            analysis_text = f"ไม่สามารถสร้างบทวิเคราะห์ได้ในขณะนี้: {str(e)}"

    context = {
        'title': 'Macro Economy & Commodities',
        'data': data,
        'analysis': analysis_text,
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

    if request.method == "POST" or request.GET.get('scan') == 'true':
        import pandas_ta as ta

        scan_run_time = tz.now()

        # ดึง symbols ของรอบสแกนก่อนหน้า (เพื่อ is_new_entry)
        prev_run = (
            PrecisionScanCandidate.objects
            .filter(user=request.user)
            .values_list('scan_run', flat=True)
            .order_by('-scan_run')
            .distinct()
            .first()
        )
        prev_symbols = set()
        if prev_run:
            prev_symbols = set(
                PrecisionScanCandidate.objects
                .filter(user=request.user, scan_run=prev_run)
                .values_list('symbol', flat=True)
            )

        # ====== ดึง SET Index เพื่อคำนวณ Relative Momentum (ทำครั้งเดียวก่อน loop) ======
        set_1m_return = 0.0
        set_3m_return = 0.0
        try:
            set_df = yf.download("^SET", period="6mo", interval="1d", progress=False)
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

        import concurrent.futures

        def _process_precision_scan(symbol):
            try:
                # ใช้ yf.Ticker().history() แทน yf.download() เพราะ yf.download() 
                # มีบั๊ก Thread-safety กรองข้อมูลข้าม Symbol กันเมื่อรันใน ThreadPool 
                ticker_obj = yf.Ticker(f"{symbol}.BK")
                df = ticker_obj.history(period="1y", interval="1d")

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
                    return None

                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)

                df = df.dropna(subset=['Close', 'High'])
                if len(df) < 200:
                    return None

                # ====== Liquidity Filter: avg 20d volume >= 500,000 ======
                avg_vol_20 = float(df['Volume'].tail(20).mean())
                if avg_vol_20 < 500_000:
                    return None   # skipped: low liquidity (logged at DEBUG level only)

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

                # ====== Trend Template Filter (ผ่อนปรนเพื่อรับหุ้น Momentum เล่นรอบ) ======
                # ยกเลิก is_uptrend ทิ้ง เพื่อเปิดโอกาสหุ้นลงแรงที่เพิ่งมีแรงงัดกลับ (Reversal Momentum)
                # และยอมรับหุ้นที่ลงมาไม่เกิน 50% จากจุดสูงสุด 52 สัปดาห์ (เดิม 25% ซึ่งแคบเกินไป)
                near_high  = current_price >= year_high * 0.50
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
                    'stock_3m_ret': stock_3m_ret,
                }

            except Exception as e:
                import logging
                logging.getLogger('stocks').exception(f"[Precision] Error scanning {symbol}: {e}")
                return None

        # ====== 1. RS Rating Ranking (Percentile based on stocks in this scan) ======
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(_process_precision_scan, sym) for sym in scan_symbols]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    results.append(res)

        if results:
            # ใช้ Pandas เพื่อทำ percentile ranking (Minervini style)
            scan_df = pd.DataFrame(results)
            if not scan_df.empty and 'stock_3m_ret' in scan_df.columns:
                # rank(pct=True) → 0.0–1.0, ×99 → 0–99, clip เพื่อป้องกัน edge case
                scan_df['rs_rating'] = (
                    scan_df['stock_3m_ret'].rank(pct=True) * 99
                ).clip(0, 99).fillna(0).astype(int)
            else:
                scan_df['rs_rating'] = 0

            # ====== 2. Bulk Fundamental Enrichment (Yahooquery) ======
            # Fetch for all matched symbols in one go (Sector, EPS Growth, Rev Growth)
            matched_symbols = [r['symbol'] for r in results]
            symbols_bk = [f"{s}.BK" for s in matched_symbols]
            
            fund_data = {}
            try:
                yq_all = YQTicker(symbols_bk)
                # เพิ่ม summaryProfile เพื่อดึง sector (ไม่ใช่ summaryDetail)
                modules = yq_all.get_modules('financialData summaryProfile')

                for sym_bk, data in modules.items():
                    if not isinstance(data, dict):
                        continue
                    clean_sym = sym_bk.replace('.BK', '')
                    profile   = data.get('summaryProfile', {})
                    fin_data  = data.get('financialData', {})

                    # Sector fallback chain: summaryProfile → assetProfile → 'Unknown'
                    sector = (
                        profile.get('sector')
                        or data.get('assetProfile', {}).get('sector')
                        or 'Unknown'
                    )

                    eps_growth = float(fin_data.get('earningsQuarterlyGrowth', 0) or 0) * 100
                    rev_growth = float(fin_data.get('revenueGrowth', 0) or 0) * 100

                    fund_data[clean_sym] = {
                        'sector': sector,
                        'eps_growth': eps_growth,
                        'rev_growth': rev_growth,
                    }
            except Exception as e:
                print(f"[Precision] Bulk Fundamental fetch failed: {e}")

            # ====== 3. Final Model Mapping & Bulk Create ======
            bulk_candidates = []
            for r in scan_df.to_dict('records'):
                sym = r['symbol']
                f = fund_data.get(sym, {'sector': 'N/A', 'eps_growth': 0.0, 'rev_growth': 0.0})
                
                bulk_candidates.append(PrecisionScanCandidate(
                    user=request.user,
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
                ))

            if bulk_candidates:
                PrecisionScanCandidate.objects.bulk_create(bulk_candidates)

        # เก็บไว้เพียง 3 รอบสแกนล่าสุด — ลบรอบเก่าออก
        distinct_runs = (
            PrecisionScanCandidate.objects
            .filter(user=request.user)
            .values_list('scan_run', flat=True)
            .order_by('-scan_run')
            .distinct()
        )
        runs_list = list(distinct_runs)
        if len(runs_list) > 3:
            old_runs = runs_list[3:]
            PrecisionScanCandidate.objects.filter(user=request.user, scan_run__in=old_runs).delete()

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

        # ====== คำนวณ BUY/SELL Score ด้วย _compute_signals() เดียวกับ Dashboard/Watchlist ======
        # ใช้สูตรกลางแทนการ duplicate logic — ทำให้ทุกหน้าแสดง score ที่สอดคล้องกัน
        for c in candidates:
            sigs = _compute_signals(c)
            c.buy_score  = sigs['buy_score']
            c.sell_score = sigs['sell_score']
            c.exit_signal = sigs['exit_signal']

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
            return (
                c.buy_score >= 65            # เดิม 70 (ปรับลดให้ยืดหยุ่นถ้าคะแนนตึงไป)
                and rr >= 1.5                # เดิม 2.0
                and c.adx >= 20              # เดิม 25
                and 45 <= c.rsi <= 82        # เดิม 55 (เปิดรับหุ้นเพิ่งงัดจาก oversold)
                and c.rvol_bullish
                and c.rvol >= 0.8            # เดิม 1.0
                and near_zone
                and (c.sell_score or 0) < 50
                and getattr(c, 'rs_rating', 0) >= 60  # เดิม 70
            )

        top5_qualified = sorted(
            [c for c in candidates if _is_fully_qualified(c)],
            key=lambda x: x.buy_score, reverse=True
        )[:5]

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
            scan_insights.append({
                'icon': '🏆',
                'title': f'โฟกัสหลัก: {best_setup.symbol} (หน้าเทรดคุ้มค่า ปลอดภัยสูง)',
                'desc': f'ถือเป็นหน้าเทรด Swing Trade ที่สมบูรณ์แบบที่สุดในรอบนี้ เพราะมีความแข็งแกร่ง (RS {rs_val}) เทรนด์ทำมุมสวยงาม แต่ราคาปัจจุบันกลับอยู่ใกล้จุดเข้าซื้อ ทำให้มีความคุ้มค่ากับความเสี่ยงสูง (RR 1:{rr_val:.1f}) ซื้อแล้วมีโอกาสชนะสูง'
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
        'scan_total': len(scan_symbols),   # จำนวน symbol ทั้งหมดใน ScannableSymbol (active)
        'scan_passed': len(candidates),    # ผ่านเกณฑ์ในรอบนั้น
        'top_sectors': top_sectors,        # กลุ่มอุตสาหกรรมผู้นำ
        'scan_insights': scan_insights,    # คำอธิบายผลลัพธ์อัตโนมัติ
    }
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
    # เติม .BK suffix สำหรับหุ้นไทยที่ยังไม่มี
    # Force .BK suffix for Thai symbols if not present
    full_symbol = f"{symbol}.BK" if not symbol.endswith(".BK") else symbol

    try:
        df = yf.download(full_symbol, period="1y", interval="1d", progress=False)
        if df.empty:
            messages.error(request, f"ไม่พบข้อมูลสำหรับ {symbol}")
            return redirect('stocks:momentum_scanner')

        # แก้ไข MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # คำนวณ Supply & Demand Zone ด้วย v2 (52w high + ATR-based SL — ตรงกับ Precision Scanner)
        sd_zone = find_supply_demand_zones_v2(df)

        # เตรียมข้อมูลกราฟ 120 วันล่าสุด
        # Chart Data
        history_subset = df.tail(120)
        chart_labels = [d.strftime('%Y-%m-%d') for d in history_subset.index]
        chart_values = [round(float(v), 2) for v in history_subset['Close'].values]

        # คำนวณ EMA50 และ EMA200 สำหรับแสดงในกราฟ
        # Technical Indicators for context
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
        sd_zone_json = json.dumps(sd_zone)  # ส่ง zone data ให้ chartjs-plugin-annotation

        curr_price = df['Close'].iloc[-1]

        context = {
            'symbol': symbol,
            'full_symbol': full_symbol,
            'sd_zone': sd_zone,  # For template logic
            'sd_zone_json': sd_zone_json,  # For JS
            'curr_price': round(curr_price, 2),
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
    # ====== SCAN (POST only — PRG pattern) ======
    if request.method == "POST" and request.POST.get('action') == 'scan':
        # import หนักเฉพาะตอนสแกนจริง ไม่ใช่ทุก request
        import pandas_ta as ta
        from concurrent.futures import ThreadPoolExecutor, as_completed

        scan_symbols = ScannableSymbol.objects.filter(is_active=True).values_list('symbol', flat=True)
        if not scan_symbols:
            refresh_set100_symbols()
            scan_symbols = ScannableSymbol.objects.filter(is_active=True).values_list('symbol', flat=True)

        MultiFactorCandidate.objects.filter(user=request.user).delete()
        sym_list = list(scan_symbols)

        # ──────────────────────────────────────────────────────────────
        # Phase 1: Batch download ราคาทุก symbol ในคำสั่งเดียว
        # yfinance ใช้ threading ภายใน → เร็วกว่าดาวน์โหลดแยกมาก
        # ──────────────────────────────────────────────────────────────
        tickers_str = " ".join(f"{s}.BK" for s in sym_list)
        try:
            batch_df = yf.download(
                tickers_str,
                period="1y", interval="1d",
                group_by='ticker',
                progress=False, threads=True,
            )
        except Exception as e:
            print(f"[MultiFactorScan] Batch download failed: {e}")
            batch_df = None

        # ──────────────────────────────────────────────────────────────
        # Phase 2: ฟังก์ชันประมวลผลต่อหุ้น (รันใน thread)
        # ──────────────────────────────────────────────────────────────
        def _get_df(symbol):
            """ดึง DataFrame ราคาจาก batch หรือ fallback โหลดแยก"""
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

                # คำนวณ indicators
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

                # Momentum Score (max 40)
                mom = 0
                if above_ema200:                   mom += 15
                if above_ema50:                    mom += 5
                if 55 <= rsi <= 72:                mom += 15
                elif 45 <= rsi < 55 or 72 < rsi <= 80: mom += 7
                if adx_val >= 30:                  mom += 5

                # Volume/Flow Score (max 30)
                vol = 0
                if rvol >= 3.0:   vol += 15
                elif rvol >= 2.0: vol += 12
                elif rvol >= 1.5: vol += 8
                elif rvol >= 1.0: vol += 4
                if mfi_val >= 70:   vol += 15
                elif mfi_val >= 60: vol += 10
                elif mfi_val >= 50: vol += 5

                # Fundamental Score (max 10)  — fetch .info ใน thread เดิมเลย
                sector = "Unknown"; eps_g = 0.0; rev_g = 0.0; fund = 0
                try:
                    info = yf.Ticker(f"{symbol}.BK").info or {}
                    # yfinance บางตัวส่ง sparse dict มา (เช่น {'trailingPegRatio': None})
                    # ตรวจว่ามีข้อมูลพอ ก่อนนำไปใช้
                    if isinstance(info, dict) and len(info) >= 5:
                        sector = info.get('sector', 'Other') or 'Other'
                        eps_g  = float(info.get('earningsQuarterlyGrowth') or 0) * 100
                        rev_g  = float(info.get('revenueGrowth') or 0) * 100
                        pe     = float(info.get('trailingPE') or 0)
                        if eps_g >= 20:   fund += 4
                        elif eps_g >= 10: fund += 2
                        if rev_g >= 10:   fund += 3
                        elif rev_g >= 5:  fund += 1
                        if 5 <= pe <= 30: fund += 3
                except Exception:
                    pass

                vol_score = min(vol, 30)
                return dict(
                    symbol=symbol, sector=sector, price=round(price, 2),
                    momentum_score=mom, volume_score=vol_score,
                    sentiment_score=0, fundamental_score=fund,
                    super_score=mom + vol_score + fund,
                    rsi=round(rsi, 2), adx=round(adx_val, 2),
                    mfi=round(mfi_val, 2), rvol=round(rvol, 2),
                    eps_growth=round(eps_g, 2), rev_growth=round(rev_g, 2),
                    above_ema200=above_ema200, above_ema50=above_ema50,
                )
            except Exception as e:
                print(f"[MultiFactorScan] {symbol}: {e}")
                return None

        # ──────────────────────────────────────────────────────────────
        # Phase 3: รันขนาน 12 threads — fundamentals เป็น I/O bound
        # ──────────────────────────────────────────────────────────────
        raw_results = []
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = {executor.submit(process_one, s): s for s in sym_list}
            for future in as_completed(futures):
                r = future.result()
                if r:
                    raw_results.append(r)

        # ──────────────────────────────────────────────────────────────
        # Phase 4: Bulk create — 1 SQL INSERT แทน 100+
        # ──────────────────────────────────────────────────────────────
        MultiFactorCandidate.objects.bulk_create([
            MultiFactorCandidate(user=request.user, **r) for r in raw_results
        ])

        messages.success(request, f"✅ สแกนเสร็จสิ้น — พบ {len(raw_results)} หุ้น")
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
