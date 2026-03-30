import pandas as pd
import requests
import yfinance as yf
from google import genai
from django.conf import settings
from yahooquery import Ticker as YQTicker
import pandas_ta as ta

# ======================================================================
# stocks/utils.py — ฟังก์ชันหลักสำหรับวิเคราะห์หุ้นและดึงข้อมูลตลาด
# ======================================================================


# ----------------------------------------------------------------------
# calculate_trailing_stop — คำนวณ Trailing Stop Loss
# ใช้ป้องกันความเสี่ยงหลังจากซื้อหุ้น โดยตั้ง stop loss ตาม %
# ของราคาสูงสุดที่เคยทำได้นับตั้งแต่ซื้อ
# ----------------------------------------------------------------------
def calculate_trailing_stop(symbol, current_price, entry_price, highest_price_since_buy=None, percent_trail=3.0):
    # คำนวณราคาสูงสุดตั้งแต่ซื้อ (ใช้ราคาปัจจุบันและต้นทุนเป็น fallback)
    if highest_price_since_buy is None:
        highest_price_since_buy = max(current_price, entry_price)
    else:
        highest_price_since_buy = max(current_price, entry_price, highest_price_since_buy)

    # คำนวณราคา stop loss = ราคาสูงสุด × (1 - %)
    stop_loss_price = highest_price_since_buy * (1 - (percent_trail / 100))

    # กำหนดสถานะเริ่มต้น
    status_code = "HOLD"
    color_code = "success"

    # ตรวจสอบว่าราคาปัจจุบันแตะ stop loss หรือใกล้แล้วหรือยัง
    if current_price <= stop_loss_price:
        status_code = "SELL (STOP LOSS)"
        color_code = "danger"
    elif current_price <= stop_loss_price * 1.01:
        # อยู่ในช่วง 1% ใกล้ stop loss — แจ้งเตือน
        status_code = "WARNING (NEAR STOP LOSS)"
        color_code = "warning"

    return {
        'symbol': symbol,
        'current_price': current_price,
        'stop_loss_price': round(stop_loss_price, 2),
        'highest_price_since_buy': highest_price_since_buy,
        'status': status_code,
        'color': color_code
    }


# ----------------------------------------------------------------------
# get_stock_data — ดึงข้อมูลหุ้นจาก yfinance + yahooquery
# ครอบคลุม: ราคา, งบการเงิน, Indicator (RSI/MACD), ข่าว, โปรไฟล์บริษัท
# ----------------------------------------------------------------------
def get_stock_data(symbol):
    # สร้าง ticker object จากทั้งสอง library
    ticker = yf.Ticker(symbol)
    yq_ticker = YQTicker(symbol)

    # ดึงข้อมูลพื้นฐาน, ราคาย้อนหลัง 1 ปี, งบการเงิน, และงบดุล
    try:
        info = ticker.info
        if not info or not isinstance(info, dict) or len(info) < 5:
            # Try .BK suffix for potential Thai stocks
            if ".BK" not in symbol:
                alt_t = yf.Ticker(f"{symbol}.BK")
                alt_info = alt_t.info
                if alt_info and isinstance(alt_info, dict) and len(alt_info) > 5:
                    ticker = alt_t
                    info = alt_info
            if not info or not isinstance(info, dict):
                info = {}
    except Exception as e:
        print(f"DEBUG: yfinance info fetch failed for {symbol}: {e}")
        # Fallback to fast_info for basic price data if info fails
        try:
            fast = ticker.fast_info
            info = {
                'currentPrice': fast.get('last_price'),
                'currency': fast.get('currency'),
                'exchange': fast.get('exchange'),
                'quoteType': fast.get('quote_type')
            }
        except:
            info = {}

    history = ticker.history(period="1y")
    financials = ticker.financials
    try:
        # ใช้งบดุลรายไตรมาสก่อน ถ้าไม่มีให้ใช้รายปี
        balance_sheet = ticker.quarterly_balance_sheet if not ticker.quarterly_balance_sheet.empty else ticker.balance_sheet
    except Exception:
        balance_sheet = None

    # คำนวณ Indicator ทางเทคนิค: RSI(14) และ MACD(12,26,9)
    if not history.empty:
        history['RSI'] = ta.rsi(history['Close'], length=14)
        macd = ta.macd(history['Close'])
        if macd is not None and not macd.empty:
            history = pd.concat([history, macd], axis=1)

    # ดึงข้อมูลเพิ่มเติมจาก yahooquery: สรุปข้อมูล, โปรไฟล์, สถิติ, คำแนะนำนักวิเคราะห์
    def get_yq_item(prop, sym):
        try:
            val = getattr(yq_ticker, prop)
            if isinstance(val, dict) and sym in val:
                return val[sym]
            return {}
        except:
            return {}

    yq_summary = get_yq_item('summary_detail', symbol)
    yq_profile = get_yq_item('asset_profile', symbol)
    yq_stats = get_yq_item('key_stats', symbol)
    
    # Handle recommendations which might be a DataFrame or Dict
    try:
        yq_recommendations = yq_ticker.recommendation_trend
        if isinstance(yq_recommendations, dict) and symbol in yq_recommendations:
            yq_recommendations = yq_recommendations[symbol]
        elif not isinstance(yq_recommendations, pd.DataFrame):
            yq_recommendations = pd.DataFrame()
    except:
        yq_recommendations = pd.DataFrame()

    # แปลงโครงสร้างข่าวล่าสุดให้เป็นรูปแบบมาตรฐาน
    raw_news = ticker.news
    normalized_news = []
    if raw_news:
        for n in raw_news:
            if n.get('content'):
                # รูปแบบข่าวใหม่ของ yfinance — อยู่ใน key 'content'
                c = n['content']
                normalized_news.append({
                    'title': c.get('title', ''),
                    'link': (c.get('clickThroughUrl') or {}).get('url', ''),
                    'publisher': (c.get('provider') or {}).get('displayName', ''),
                    'providerPublishTime': c.get('pubDate', ''),
                })
            else:
                # รูปแบบข่าวเก่า — ใช้โดยตรง
                normalized_news.append(n)

    return {
        'info': info,
        'history': history,
        'financials': financials,
        'balance_sheet': balance_sheet,
        'news': normalized_news,
        'yq_data': {
            'summary': yq_summary,
            'profile': yq_profile,
            'stats': yq_stats,
            'recommendations': yq_recommendations
        }
    }


# ----------------------------------------------------------------------
# Commodity / Futures helpers
# ----------------------------------------------------------------------
_COMMODITY_NAME_MAP = {
    'GC=F': 'Gold Futures (COMEX)',
    'SI=F': 'Silver Futures',
    'PL=F': 'Platinum Futures',
    'HG=F': 'Copper Futures',
    'CL=F': 'Crude Oil WTI Futures',
    'BZ=F': 'Crude Oil Brent Futures',
    'NG=F': 'Natural Gas Futures',
    'ZC=F': 'Corn Futures',
    'ZS=F': 'Soybeans Futures',
    'ZW=F': 'Wheat Futures',
    'BTC-USD': 'Bitcoin (Crypto)',
    'ETH-USD': 'Ethereum (Crypto)',
}

def _is_commodity(symbol: str) -> bool:
    """Returns True for futures and crypto — assets with no stock fundamentals."""
    return symbol.endswith('=F') or symbol.endswith('-USD') or symbol.endswith('-USDT')


def _fetch_commodity_macro() -> dict:
    """Fetch real-time macro indicators + GLD ETF fund-flow data."""
    from concurrent.futures import ThreadPoolExecutor

    macro = {}

    def _fast(ticker_sym, key):
        try:
            v = getattr(yf.Ticker(ticker_sym).fast_info, 'last_price', None)
            if v: macro[key] = round(float(v), 2)
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=3) as ex:
        ex.submit(_fast, "DX-Y.NYB", 'dxy')
        ex.submit(_fast, "^TNX",     'tnx')
        ex.submit(_fast, "^VIX",     'vix')

    # GLD ETF — institutional fund-flow proxy for precious metals
    try:
        gld = yf.Ticker("GLD").history(period="1mo", auto_adjust=True)
        if len(gld) >= 10:
            avg_v = float(gld['Volume'].mean())
            last_v = float(gld['Volume'].iloc[-1])
            macro['gld_vol_ratio'] = round(last_v / max(avg_v, 1), 2)
            if len(gld) >= 6:
                macro['gld_5d_chg'] = round(
                    (float(gld['Close'].iloc[-1]) - float(gld['Close'].iloc[-6]))
                    / float(gld['Close'].iloc[-6]) * 100, 2
                )
            # net flow direction: count up vs down days in last 5 sessions
            last5 = gld['Close'].diff().iloc[-5:]
            macro['gld_net_flow'] = 'inflow' if (last5 > 0).sum() >= 3 else 'outflow'
    except Exception:
        pass

    return macro


def _score_commodity_signal(symbol: str, last_price: float, ema200, rsi, macro: dict) -> dict:
    """
    Compute a 0-100 macro+technical buy/wait signal for a commodity/futures.
    Returns dict with score, recommendation, signals list ready for template rendering.
    """
    score = 0
    max_pts = 0
    signals = []

    dxy           = macro.get('dxy')
    tnx           = macro.get('tnx')
    vix           = macro.get('vix')
    gld_vol_ratio = macro.get('gld_vol_ratio')
    gld_5d_chg    = macro.get('gld_5d_chg')
    gld_net_flow  = macro.get('gld_net_flow')

    is_precious = symbol in ('GC=F', 'SI=F', 'PL=F', 'HG=F')
    is_energy   = symbol in ('CL=F', 'BZ=F', 'NG=F')

    # ── Factor 1: USD Index (DXY) — 25 pts ────────────────────────────
    if dxy is not None:
        max_pts += 25
        if is_precious:
            if dxy < 99:      pts, icon = 25, '✅'
            elif dxy < 101:   pts, icon = 20, '✅'
            elif dxy < 103:   pts, icon = 13, '⚠️'
            elif dxy < 105:   pts, icon =  5, '⚠️'
            else:              pts, icon =  0, '❌'
            strength = 'อ่อนมาก → บวกมากต่อทอง' if pts >= 20 else ('อ่อน → บวกต่อทอง' if pts >= 13 else ('แข็ง → กดดันทอง' if pts <= 5 else 'เป็นกลาง'))
            note = f'USD Index (DXY) = {dxy} ({strength})'
        else:
            if dxy < 101:   pts, icon = 18, '✅'; note = f'DXY {dxy} (ดอลลาร์อ่อน → สนับสนุน commodity)'
            elif dxy < 104: pts, icon = 10, '⚠️'; note = f'DXY {dxy} (เป็นกลาง)'
            else:            pts, icon =  2, '❌'; note = f'DXY {dxy} (ดอลลาร์แข็ง → แรงกดดัน)'
        score += pts
        signals.append({'text': note, 'positive': pts >= 13, 'icon': icon, 'pts': pts, 'max': 25,
                         'badge': 'success' if pts >= 20 else ('warning' if pts >= 8 else 'danger')})

    # ── Factor 2: 10-Year Treasury Yield (TNX) — 25 pts (precious only) ─
    if tnx is not None and is_precious:
        max_pts += 25
        if tnx < 3.5:   pts, icon = 25, '✅'; note = f'10yr Yield = {tnx}% (ต่ำมาก → ต้นทุนโอกาสน้อย → บวกมากต่อทอง)'
        elif tnx < 4.0: pts, icon = 18, '✅'; note = f'10yr Yield = {tnx}% (พอรับได้ → สนับสนุนทอง)'
        elif tnx < 4.5: pts, icon = 10, '⚠️'; note = f'10yr Yield = {tnx}% (ปานกลาง → กดดันบ้าง)'
        elif tnx < 5.0: pts, icon =  4, '⚠️'; note = f'10yr Yield = {tnx}% (สูง → ต้นทุนโอกาสสูงขึ้น)'
        else:            pts, icon =  0, '❌'; note = f'10yr Yield = {tnx}% (สูงมาก → ลบต่อทอง)'
        score += pts
        signals.append({'text': note, 'positive': pts >= 18, 'icon': icon, 'pts': pts, 'max': 25,
                         'badge': 'success' if pts >= 18 else ('warning' if pts >= 8 else 'danger')})

    # ── Factor 3: VIX — Safe-haven / Risk sentiment — 20 pts ──────────
    if vix is not None:
        max_pts += 20
        if vix > 30:   pts, icon = 20, '✅'; note = f'VIX = {vix} (ตลาดหวาดกลัวมาก → อุปสงค์ safe-haven พุ่งสูง)'
        elif vix > 25: pts, icon = 16, '✅'; note = f'VIX = {vix} (ความผันผวนสูง → อุปสงค์ safe-haven เพิ่ม)'
        elif vix > 20: pts, icon = 11, '⚠️'; note = f'VIX = {vix} (ความผันผวนปานกลาง)'
        elif vix > 15: pts, icon =  6, '⚠️'; note = f'VIX = {vix} (ตลาดค่อนข้างสงบ → อุปสงค์ safe-haven ต่ำ)'
        else:           pts, icon =  3, '⚠️'; note = f'VIX = {vix} (ตลาดสงบมาก → demand ทองลดลง)'
        score += pts
        signals.append({'text': note, 'positive': pts >= 11, 'icon': icon, 'pts': pts, 'max': 20,
                         'badge': 'success' if pts >= 16 else ('warning' if pts >= 6 else 'secondary')})

    # ── Factor 4: Trend (EMA200) — 10 pts ─────────────────────────────
    if ema200 and last_price:
        max_pts += 10
        if last_price > float(ema200):
            pts, icon = 10, '✅'; note = f'Trend: ราคา ({last_price:,.0f}) อยู่เหนือ EMA200 ({float(ema200):,.0f}) — Uptrend'
        else:
            pts, icon =  2, '❌'; note = f'Trend: ราคา ({last_price:,.0f}) ต่ำกว่า EMA200 ({float(ema200):,.0f}) — Downtrend'
        score += pts
        signals.append({'text': note, 'positive': pts >= 10, 'icon': icon, 'pts': pts, 'max': 10,
                         'badge': 'success' if pts >= 10 else 'danger'})

    # ── Factor 5: RSI — Momentum / Oversold — 12 pts ──────────────────
    if isinstance(rsi, (int, float)):
        max_pts += 12
        r = float(rsi)
        if r < 30:    pts, icon = 12, '✅'; note = f'RSI {r:.0f} — Oversold (โอกาสซื้อที่ดีมาก)'
        elif r < 45:  pts, icon = 10, '✅'; note = f'RSI {r:.0f} — Underowned (จังหวะสะสมดี)'
        elif r < 60:  pts, icon =  7, '⚠️'; note = f'RSI {r:.0f} — Neutral (รอจังหวะถอยก่อนซื้อ)'
        elif r < 70:  pts, icon =  3, '⚠️'; note = f'RSI {r:.0f} — เริ่มร้อนแรง (ระวังซื้อแพง)'
        else:          pts, icon =  0, '❌'; note = f'RSI {r:.0f} — Overbought (หลีกเลี่ยง)'
        score += pts
        signals.append({'text': note, 'positive': pts >= 10, 'icon': icon, 'pts': pts, 'max': 12,
                         'badge': 'success' if pts >= 10 else ('warning' if pts >= 7 else 'danger')})

    # ── Factor 6: GLD ETF Fund Flow — 8 pts (precious metals only) ────
    if gld_vol_ratio is not None and is_precious:
        max_pts += 8
        if gld_vol_ratio > 2.0:    pts, icon = 8, '✅'
        elif gld_vol_ratio > 1.5:  pts, icon = 6, '✅'
        elif gld_vol_ratio > 1.0:  pts, icon = 4, '⚠️'
        else:                       pts, icon = 2, '⚠️'
        flow_label = 'Inflow (เงินไหลเข้าทอง)' if gld_net_flow == 'inflow' else 'Outflow (เงินไหลออกจากทอง)'
        chg_str = f', 5d: {"↑" if gld_5d_chg and gld_5d_chg > 0 else "↓"}{abs(gld_5d_chg):.1f}%' if gld_5d_chg is not None else ''
        note = f'GLD ETF Fund Flow: Volume {gld_vol_ratio:.1f}x avg, {flow_label}{chg_str}'
        score += pts
        signals.append({'text': note, 'positive': pts >= 6, 'icon': icon, 'pts': pts, 'max': 8,
                         'badge': 'success' if pts >= 6 else 'secondary'})

    # ── Normalize to 100 and determine recommendation ─────────────────
    pct = round(score / max_pts * 100) if max_pts > 0 else 0
    pct = min(pct, 100)

    if pct >= 70:   rec, rec_th, rec_color = 'BUY',        'ซื้อ / เข้าลงทุน',   'success'
    elif pct >= 55: rec, rec_th, rec_color = 'ACCUMULATE', 'ทยอยสะสม',           'info'
    elif pct >= 40: rec, rec_th, rec_color = 'WAIT',       'รอจังหวะที่ดีกว่า',  'warning'
    else:           rec, rec_th, rec_color = 'AVOID',      'หลีกเลี่ยง',         'danger'

    return {
        'score': pct,
        'recommendation': rec,
        'recommendation_th': rec_th,
        'rec_color': rec_color,
        'signals': signals,
    }


def _analyze_commodity_with_ai(symbol: str, data: dict, macro_signal: dict = None) -> str:
    """Specialized AI analysis for commodity futures and crypto (GC=F, CL=F, BTC-USD…)."""
    history = data.get('history', pd.DataFrame())
    news    = data.get('news', [])

    # ── Technical indicators ──────────────────────────────────────────
    last_price   = float(history['Close'].iloc[-1])  if not history.empty else 0
    price_change = ((last_price - float(history['Close'].iloc[-2])) / float(history['Close'].iloc[-2]) * 100) if len(history) > 1 else 0
    last_volume  = int(history['Volume'].iloc[-1])    if not history.empty else 0
    avg_volume   = float(history['Volume'].mean())    if not history.empty else 1
    vol_ratio    = last_volume / max(avg_volume, 1)

    rsi      = history['RSI'].iloc[-1]           if 'RSI'          in history.columns else 'N/A'
    macd_val = history['MACD_12_26_9'].iloc[-1]  if 'MACD_12_26_9' in history.columns else 'N/A'
    macd_sig = history['MACDs_12_26_9'].iloc[-1] if 'MACDs_12_26_9' in history.columns else 'N/A'
    ema200   = history['EMA_200'].iloc[-1]        if 'EMA_200'      in history.columns else None
    ema50    = history['EMA_50'].iloc[-1]         if 'EMA_50'       in history.columns else None

    year_high     = float(history['High'].max())  if not history.empty else None
    year_low      = float(history['Low'].min())   if not history.empty else None
    pct_from_high = ((last_price - year_high) / year_high * 100) if year_high else None

    trend_note = ""
    if ema200:
        trend_note += f"{'ABOVE' if last_price > ema200 else 'BELOW'} EMA200 ({ema200:.2f})"
    if ema50:
        trend_note += f", {'ABOVE' if last_price > ema50 else 'BELOW'} EMA50 ({ema50:.2f})"

    fmt_rsi  = f"{rsi:.1f}"      if isinstance(rsi,      float) else str(rsi)
    fmt_macd = f"{macd_val:.2f}" if isinstance(macd_val, float) else str(macd_val)
    fmt_sig  = f"{macd_sig:.2f}" if isinstance(macd_sig, float) else str(macd_sig)
    fmt_high = f"{year_high:.2f}" if year_high else 'N/A'
    fmt_low  = f"{year_low:.2f}"  if year_low  else 'N/A'
    fmt_pct  = f"{pct_from_high:.1f}" if pct_from_high is not None else 'N/A'

    # ── Macro data (passed in from caller to avoid double-fetch) ────────
    if macro_signal and macro_signal.get('_raw_macro'):
        macro = macro_signal['_raw_macro']
    else:
        macro = _fetch_commodity_macro()
    dxy   = macro.get('dxy', 'N/A')
    tnx   = macro.get('tnx', 'N/A')
    vix   = macro.get('vix', 'N/A')

    # ── News ──────────────────────────────────────────────────────────
    news_content = "\nRecent Headlines:\n"
    for n in news[:5]:
        news_content += f"- {n.get('title', '')} ({n.get('publisher', '')})\n"

    # ── Commodity type branching ──────────────────────────────────────
    commodity_name = _COMMODITY_NAME_MAP.get(symbol, f'{symbol} (Futures/Crypto)')
    is_precious_metal = symbol in ('GC=F', 'SI=F', 'PL=F')
    is_energy         = symbol in ('CL=F', 'BZ=F', 'NG=F')
    is_crypto         = symbol.endswith('-USD') or symbol.endswith('-USDT')

    if is_precious_metal:
        macro_context = f"""Macro Environment (Key Drivers for Precious Metals):
- USD Index (DXY): {dxy}  ← ↑DXY = headwind for gold; ↓DXY = tailwind
- 10-Year Treasury Yield (^TNX): {tnx}%  ← ↑real yields = opportunity cost rises = bearish gold
- VIX Fear Index: {vix}  ← ↑VIX = safe-haven demand spike = bullish gold
- Approximate Real Yield = TNX - inflation expectations (~2.5%); negative real yields = very bullish gold"""
        analysis_sections = """Please provide a professional analysis in Thai language covering:
1. **Macro & Monetary Policy Impact**: วิเคราะห์ผลกระทบ DXY, อัตราดอกเบี้ยแท้จริง (Real Yield = TNX - inflation), นโยบาย Fed และเงินเฟ้อต่อทิศทางราคา
2. **Technical Analysis**: วิเคราะห์แนวโน้ม (EMA200/EMA50 trend), แนวรับ-แนวต้านสำคัญ, RSI momentum และสัญญาณ MACD
3. **Safe-Haven & Geopolitical Demand**: ความเสี่ยงภูมิรัฐศาสตร์, VIX สูง, ความไม่แน่นอนทางการเงินและการเมืองโลก
4. **Structural Gold Drivers**: ธนาคารกลางทั่วโลกสะสมทอง (Central Bank buying), กระแส de-dollarization, ETF Gold Flows (GLD/IAU), อุปสงค์เครื่องประดับจีน-อินเดีย, ฤดูกาล
5. **Strategic Action Plan**: คำแนะนำ Buy/Hold/Sell พร้อม Entry Zone, Target Price และ Stop Loss ที่ชัดเจน สำหรับนักลงทุนรายย่อยไทย"""
    elif is_energy:
        macro_context = f"""Macro Environment (Key Drivers for Energy):
- USD Index (DXY): {dxy}  ← dollar-denominated commodity correlation
- 10-Year Treasury Yield (^TNX): {tnx}%  ← proxy for economic growth expectations
- VIX Fear Index: {vix}  ← risk-off = demand concerns = bearish"""
        analysis_sections = """Please provide a professional analysis in Thai language covering:
1. **Supply & Demand Dynamics**: OPEC+ production policy, US shale output, global demand outlook (China, India, OECD)
2. **Technical Analysis**: แนวโน้ม EMA, แนวรับ-แนวต้าน RSI และ MACD
3. **Macro & Currency Impact**: DXY, ดัชนีเศรษฐกิจโลก, ความเชื่อมั่นนักลงทุน
4. **Geopolitical Risk Premium**: ความเสี่ยงตะวันออกกลาง, รัสเซีย-ยูเครน, LNG trade flows
5. **Strategic Action Plan**: คำแนะนำ Buy/Hold/Sell พร้อม Entry Zone, Target และ Stop Loss"""
    elif is_crypto:
        macro_context = f"""Macro Environment (Crypto Correlation Factors):
- USD Index (DXY): {dxy}  ← inverse correlation with crypto
- 10-Year Treasury Yield (^TNX): {tnx}%  ← risk appetite indicator
- VIX Fear Index: {vix}  ← ↑VIX = risk-off = crypto weakness"""
        analysis_sections = """Please provide a professional analysis in Thai language covering:
1. **Macro & Liquidity Environment**: Fed policy, risk appetite, Bitcoin halving cycle, institutional adoption
2. **Technical Analysis**: แนวโน้ม EMA200, แนวรับ-แนวต้านสำคัญ, RSI, MACD, on-chain signals
3. **Market Sentiment**: Fear & Greed cycle, whale activity, exchange flows
4. **Crypto-Specific Drivers**: Regulatory developments, network metrics, DeFi activity
5. **Strategic Action Plan**: คำแนะนำ Buy/Hold/Sell พร้อม Entry Zone, Target และ Stop Loss"""
    else:
        macro_context = f"""Macro Environment:
- USD Index (DXY): {dxy}
- 10-Year Treasury Yield (^TNX): {tnx}%
- VIX: {vix}"""
        analysis_sections = """Please provide a professional analysis in Thai language covering:
1. **Macro Environment**: ผลกระทบ DXY, อัตราดอกเบี้ย, ความเชื่อมั่นนักลงทุน
2. **Technical Analysis**: แนวโน้ม EMA, RSI, MACD, แนวรับ-แนวต้าน
3. **Supply & Demand**: ปัจจัยอุปสงค์อุปทานของ commodity นี้
4. **Strategic Action Plan**: คำแนะนำ Buy/Hold/Sell พร้อม Target และ Stop Loss"""

    # ── Macro signal context for AI (if computed) ────────────────────
    signal_context = ""
    if macro_signal:
        signal_context = f"""
Quantitative Macro Signal: {macro_signal['score']}/100 → {macro_signal['recommendation']} ({macro_signal['recommendation_th']})
Signal Breakdown:
"""
        for sig in macro_signal.get('signals', []):
            signal_context += f"  {sig['icon']} {sig['text']}  [{sig['pts']}/{sig['max']}]\n"
        signal_context += "\nUse the signal score above as the basis for your final recommendation in section 5.\n"

    prompt = f"""Analyze the commodity/futures contract {symbol} ({commodity_name}) for a trader/investor:

{macro_context}
{signal_context}
Technical Snapshot:
- Current Price: {last_price:.2f} USD ({price_change:+.2f}%)
- 52-Week High: {fmt_high} | 52-Week Low: {fmt_low}
- Distance from 52w High: {fmt_pct}%
- Trend: {trend_note if trend_note else 'N/A'}
- RSI(14): {fmt_rsi}
- MACD: {fmt_macd} (Signal: {fmt_sig})
- Volume Ratio vs 20-day avg: {vol_ratio:.2f}x
{news_content}

{analysis_sections}

Format in Markdown for a professional web report. Output ONLY raw markdown."""

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
        clean_text = response.text
        if clean_text.startswith("```markdown"):
            clean_text = clean_text[len("```markdown"):].strip()
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3].strip()
        return clean_text
    except Exception as e:
        return f"**Error generating commodity analysis:** {str(e)}"


# ----------------------------------------------------------------------
# analyze_with_ai — วิเคราะห์หุ้นด้วย Gemini AI
# รวมข้อมูลพื้นฐาน + เทคนิค + ข่าว แล้วส่งให้ AI สรุปเป็นภาษาไทย
# ----------------------------------------------------------------------
def analyze_with_ai(symbol, data, extra_context=None, macro_signal=None):
    # Commodity / futures / crypto — use specialized analysis instead
    if _is_commodity(symbol):
        return _analyze_commodity_with_ai(symbol, data, macro_signal=macro_signal)

    info = data.get('info', {})
    yq = data.get('yq_data', {})
    history = data.get('history', pd.DataFrame())
    news = data.get('news', [])

    # --- ดึงอัตราส่วนทางการเงินพื้นฐาน ---
    pe_ratio = info.get('trailingPE', 'N/A')
    pb_ratio = info.get('priceToBook', 'N/A')
    roe = f"{(info.get('returnOnEquity', 0) or 0) * 100:.2f}%" if info.get('returnOnEquity') else 'N/A'
    npm = f"{(info.get('profitMargins', 0) or 0) * 100:.2f}%" if info.get('profitMargins') else 'N/A'

    # คำนวณ D/E Ratio จากงบดุล (หนี้สิน / ส่วนผู้ถือหุ้น)
    de_ratio = 'N/A'
    try:
        bs = data.get('balance_sheet')
        if bs is not None and not bs.empty:
            if isinstance(bs.columns, pd.MultiIndex):
                bs.columns = bs.columns.droplevel(1)
            latest_bs = bs.iloc[:, 0]
            total_debt = latest_bs.get('Total Debt', latest_bs.get('Long Term Debt', 0))
            equity = latest_bs.get('Total Stockholder Equity', latest_bs.get('Common Stock Equity', 0))
            if equity and equity != 0:
                de_ratio = round(total_debt / equity, 2)
    except:
        pass

    free_float = info.get('floatShares', 'N/A')

    # ดึง Dividend Yield จาก yahooquery ก่อน ถ้าไม่มีให้ใช้ yfinance
    yq_summary_dict = yq.get('summary', {}) if isinstance(yq, dict) else {}
    if not isinstance(yq_summary_dict, dict):
        yq_summary_dict = {}
    div_yield = yq_summary_dict.get('dividendYield', info.get('dividendYield', 'N/A'))

    # เพิ่มข้อมูลจาก thaifin สำหรับหุ้นไทย (ลงท้ายด้วย .BK)
    thaifin_data = ""
    if symbol.endswith('.BK'):
        clean_symbol = symbol.replace('.BK', '')
        try:
            from thaifin import Stock
            tf_stock = Stock(clean_symbol)
            tf_info = tf_stock.info if hasattr(tf_stock, 'info') else {}
            if isinstance(tf_info, dict):
                thaifin_data = f"\n    [Thaifin Local Data] PE: {tf_info.get('pe', 'N/A')}, PBV: {tf_info.get('pbv', 'N/A')}, DivYield: {tf_info.get('dividend_yield', 'N/A')}, Industry PE: {tf_info.get('industry_pe', 'N/A')}"
        except:
            pass

    # ดึง PEG Ratio และสรุปคำแนะนำนักวิเคราะห์
    yq_stats_dict = yq.get('stats', {}) if isinstance(yq, dict) else {}
    if not isinstance(yq_stats_dict, dict):
        yq_stats_dict = {}
    peg_ratio = yq_stats_dict.get('pegRatio', 'N/A')

    # สรุปมติของนักวิเคราะห์: จำนวน Strong Buy / Buy / Hold / Sell
    rec_summary = "N/A"
    try:
        yq_recommendations = yq.get('recommendations', pd.DataFrame())
        if isinstance(yq_recommendations, pd.DataFrame) and not yq_recommendations.empty:
            latest_rec = yq_recommendations.iloc[-1]
            rec_summary = f"Strong Buy: {latest_rec.get('strongBuy', 0)}, Buy: {latest_rec.get('buy', 0)}, Hold: {latest_rec.get('hold', 0)}, Sell: {latest_rec.get('sell', 0)}"
    except:
        pass

    # ดึงข้อมูลผู้บริหารและ Governance Risk
    management_context = ""
    try:
        officers = info.get('companyOfficers', []) if isinstance(info, dict) else []
        if officers and isinstance(officers, list):
            management_context = "\nKey Executive Officers:\n"
            for off in officers[:5]:
                if isinstance(off, dict):
                    management_context += f"- {off.get('name')} ({off.get('title')})\n"

        audit_risk = info.get('auditRisk', 'N/A') if isinstance(info, dict) else 'N/A'
        board_risk = info.get('boardRisk', 'N/A') if isinstance(info, dict) else 'N/A'
        if audit_risk != 'N/A':
            management_context += f"\nRisk Scores (Governance): Audit Risk={audit_risk}, Board Risk={board_risk} (Scale 1-10)\n"
    except:
        pass

    # รวมตัวชี้วัดพื้นฐานเป็นข้อความสำหรับส่งให้ AI
    fin_context = f"""
    - P/E Ratio: {pe_ratio}
    - P/BV Ratio: {pb_ratio}
    - ROE: {roe}
    - Net Profit Margin: {npm}
    - D/E Ratio: {de_ratio}
    - Free Float: {free_float}
    - Dividend Yield: {div_yield}{thaifin_data}
    """

    # คำนวณข้อมูลเทคนิคจากราคาย้อนหลัง
    last_price = history['Close'].iloc[-1] if not history.empty else 0
    price_change = ((last_price - history['Close'].iloc[-2]) / history['Close'].iloc[-2] * 100) if not history.empty and len(history) > 1 else 0
    last_volume = history['Volume'].iloc[-1] if not history.empty else 0
    avg_volume = history['Volume'].mean() if not history.empty else 1
    vol_ratio = last_volume / avg_volume  # อัตราส่วนปริมาณซื้อขายวันนี้ vs ค่าเฉลี่ย

    rsi = history['RSI'].iloc[-1] if 'RSI' in history.columns else 'N/A'
    macd_val = history['MACD_12_26_9'].iloc[-1] if 'MACD_12_26_9' in history.columns else 'N/A'
    macd_sig = history['MACDs_12_26_9'].iloc[-1] if 'MACDs_12_26_9' in history.columns else 'N/A'

    # รวบรวมหัวข้อข่าวล่าสุด 5 ข้าวสำหรับ sentiment analysis
    news_content = "\nRecent Headlines:\n"
    for n in news[:5]:
        news_content += f"- {n.get('title')} ({n.get('publisher')})\n"

    # บริบทเพิ่มเติมจากการวิเคราะห์เชิงลึก (Legendary Pillars / Valuation)
    valuation_context = ""
    if extra_context:
        valuation_context = f"\n[Specialized Analysis Context (Legendary Pillars & Valuation)]:\n{extra_context}\n"

    # สร้าง prompt ส่งให้ AI วิเคราะห์เป็นภาษาไทยในรูปแบบ Markdown
    prompt = f"""
    Analyze the stock {symbol} for an investor using the following data:
    {valuation_context}
    Financial Metrics:{fin_context}
    Analyst View: {rec_summary}
    PEG Ratio: {peg_ratio}

    Technical Snapshot:
    - Current Price: {last_price:.2f} ({price_change:+.2f}%)
    - RSI(14): {rsi}
    - MACD: {macd_val} (Signal: {macd_sig})
    - Volume: Current={last_volume}, 20-Day Avg={avg_volume:.0f} (Ratio: {vol_ratio:.2f}x)

    Business Profile & Management:
    {yq.get('profile', {}).get('longBusinessSummary', 'N/A')[:500] if (isinstance(yq, dict) and isinstance(yq.get('profile'), dict)) else 'N/A'}...
    {management_context}

    {news_content}

    Please provide a professional analysis in Thai language:
    1. Business Quality & Management Review: วิเคราะห์ธุรกิจ และคุณภาพผู้บริหาร
    2. Deep Fundamental & Valuation: วิเคราะห์ความคุ้มค่า (อ้างอิงจาก Fair Value / Pillar Scores ถ้ามี)
    3. Advanced Technicals: วิเคราะห์แนวโน้มราคา
    4. Sentiment Analysis: วิเคราะห์ทิศทางข่าวสาร
    5. Strategic Action Plan: คำแนะนำ Buy/Hold/Sell

    Format in Markdown for professional web report. Output ONLY raw markdown.
    """

    # ส่ง prompt ไปยัง Gemini API และทำความสะอาด Markdown ที่ได้กลับมา
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
        clean_text = response.text
        # ลบ code fence ที่ AI บางครั้งใส่มาโดยไม่จำเป็น
        if clean_text.startswith("```markdown"):
            clean_text = clean_text[len("```markdown"):].strip()
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3].strip()
        return clean_text
    except Exception as e:
        return f"Error analyzing data with AI: {str(e)}"


# ----------------------------------------------------------------------
# find_supply_demand_zones — ค้นหา Demand Zone แบบ Sniper Entry
# วิธีการ: หา ERC (Extended Range Candle) แล้วย้อนหาฐาน (Base) ก่อนการขึ้น
# แล้วคำนวณ Stop Loss, Target, Risk/Reward และ Confidence Score
# ----------------------------------------------------------------------
def find_supply_demand_zones(df):
    if df is None or len(df) < 50:
        return None

    df = df.copy()

    # Step 1: คำนวณขนาด Body และ Height ของแต่ละแท่งเทียน
    df['Body'] = (df['Close'] - df['Open']).abs()
    df['Height'] = df['High'] - df['Low']
    df['Avg_Body'] = df['Body'].rolling(window=20).mean()  # ค่าเฉลี่ย Body 20 แท่ง

    # หา ERC Bull: แท่งขาขึ้นที่มี Body ใหญ่กว่าค่าเฉลี่ย 1.5 เท่า
    df['is_erc_bull'] = (df['Close'] > df['Open']) & (df['Body'] > df['Avg_Body'] * 1.5)

    erc_bulls = df[df['is_erc_bull']]
    if erc_bulls.empty:
        return None  # ไม่พบ ERC — ไม่มี demand zone ที่น่าเชื่อถือ

    # ใช้ ERC ล่าสุด (ใกล้ปัจจุบันที่สุด)
    last_erc_idx = erc_bulls.index[-1]
    last_erc_pos = df.index.get_loc(last_erc_idx)

    if last_erc_pos < 5:
        return None  # ข้อมูลไม่พอสำหรับการมองย้อนหลัง

    # Step 2: หา Base — 5 แท่งก่อน ERC ที่ราคาวนอยู่ในกรอบแคบ
    base_window = df.iloc[last_erc_pos - 5:last_erc_pos]

    # กำหนดขอบบน-ล่างของ Demand Zone จาก Base
    zone_upper = base_window[['Open', 'Close']].max().max()
    zone_lower = base_window['Low'].min()

    # ปรับให้ละเอียดขึ้น: ใช้แท่งขาลงสุดท้ายใน Base เป็น Zone ที่ Refine แล้ว
    last_bear = base_window[base_window['Close'] < base_window['Open']]
    if not last_bear.empty:
        refined_upper = last_bear['High'].iloc[-1]
        refined_lower = last_bear['Low'].iloc[-1]
        if refined_lower < zone_lower:
            refined_lower = zone_lower
    else:
        refined_upper = zone_upper
        refined_lower = zone_lower

    # Step 3: กำหนด Target (Supply Zone) จากราคาสูงสุด 60 วัน
    target_price = df['High'].tail(60).max()

    # คำนวณ Risk/Reward เบื้องต้น
    entry_price = refined_upper       # เข้าซื้อที่ขอบบนของ zone
    stop_loss = refined_lower * 0.99  # SL อยู่ต่ำกว่า zone เล็กน้อย
    risk = entry_price - stop_loss
    reward = target_price - entry_price

    # ถ้า RR < 1.5 ให้ขยายไปหา Major Supply ที่ 120 วัน
    if (reward / risk if risk > 0 else 0) < 1.5:
        extended_target = df['High'].tail(120).max()
        if extended_target > target_price:
            target_price = extended_target
            reward = target_price - entry_price

    rr_ratio = reward / risk if risk > 0 else 0

    # Step 4: คำนวณ Confidence Score (0–100) จากหลายปัจจัย
    score = 40  # คะแนนพื้นฐานสำหรับการพบ zone

    import pandas_ta as ta
    # คำนวณ EMA และ RSI ถ้ายังไม่มี
    if 'EMA200' not in df.columns:
        df['EMA200'] = ta.ema(df['Close'], length=200)
    if 'EMA50' not in df.columns:
        df['EMA50'] = ta.ema(df['Close'], length=50)
    if 'RSI' not in df.columns:
        df['RSI'] = ta.rsi(df['Close'], length=14)

    last_close = df['Close'].iloc[-1]
    last_ema200 = df['EMA200'].iloc[-1] if not df['EMA200'].empty else last_close
    last_ema50 = df['EMA50'].iloc[-1] if not df['EMA50'].empty else last_close

    # +15 ถ้าราคาอยู่เหนือ EMA200 (Uptrend ระยะยาว)
    if last_close > last_ema200:
        score += 15
    # +10 ถ้า EMA50 อยู่เหนือ EMA200 (Golden Cross)
    if last_ema50 > last_ema200:
        score += 10

    # โบนัสปริมาณซื้อขาย: ERC ที่มี Volume สูงน่าเชื่อถือกว่า
    erc_vol = df.loc[last_erc_idx, 'Volume']
    avg_vol = df['Volume'].tail(20).mean()
    if erc_vol > avg_vol * 2.0:
        score += 15  # Volume สูงมาก
    elif erc_vol > avg_vol * 1.5:
        score += 10  # Volume สูงพอสมควร

    # โบนัส Risk/Reward
    if rr_ratio >= 3:
        score += 15
    elif rr_ratio >= 2:
        score += 10

    # RSI ในโซนที่เหมาะสม (ไม่ overbought)
    rsi_now = df['RSI'].iloc[-1] if not df['RSI'].empty and pd.notna(df['RSI'].iloc[-1]) else 50
    if 40 <= rsi_now <= 70:
        score += 5

    final_score = min(score, 100)

    return {
        'type': 'Sniper (DZ)',
        'start': float(round(refined_upper, 2)),
        'end': float(round(refined_lower, 2)),
        'stop_loss': float(round(stop_loss, 2)),
        'target': float(round(target_price, 2)),
        'rr_ratio': float(round(rr_ratio, 2)),
        'confidence_score': int(final_score),
        # True ถ้าราคาปัจจุบันกลับมา retest zone (±5%)
        'is_retesting': bool(df['Close'].iloc[-1] <= refined_upper * 1.05 and df['Close'].iloc[-1] >= refined_lower * 0.95),
        # ข้อมูลสำหรับวาดบน Chart
        'erc_date': last_erc_idx.strftime('%Y-%m-%d') if hasattr(last_erc_idx, 'strftime') else str(last_erc_idx),
        'base_start': base_window.index[0].strftime('%Y-%m-%d') if hasattr(base_window.index[0], 'strftime') else str(base_window.index[0]),
        'base_end': base_window.index[-1].strftime('%Y-%m-%d') if hasattr(base_window.index[-1], 'strftime') else str(base_window.index[-1]),
    }


# ----------------------------------------------------------------------
# analyze_momentum_technical — วิเคราะห์เทคนิคเชิง Momentum
# ใช้ร่วมกันระหว่าง Scanner และ Portfolio เพื่อให้ผลลัพธ์สอดคล้องกัน
# คืนค่า: Technical Score (0–100) + Indicator หลัก
# ----------------------------------------------------------------------
def analyze_momentum_technical(df):
    if df is None or len(df) < 50:
        return {'score': 0, 'rvol': 0, 'rsi': 0, 'ema200': 0, 'ema50': 0}

    import pandas_ta as ta
    df = df.copy()

    # คำนวณ Indicator ทั้งหมดที่ต้องใช้
    df['EMA200'] = ta.ema(df['Close'], length=200)
    df['EMA50'] = ta.ema(df['Close'], length=50)
    df['EMA20'] = ta.ema(df['Close'], length=20)
    df['RSI'] = ta.rsi(df['Close'], length=14)

    current_price = df['Close'].iloc[-1]
    rsi = df['RSI'].iloc[-1] if not df['RSI'].empty else 50
    ema200 = df['EMA200'].iloc[-1] if not df['EMA200'].empty else current_price
    ema50 = df['EMA50'].iloc[-1] if not df['EMA50'].empty else current_price
    ema20 = df['EMA20'].iloc[-1] if not df['EMA20'].empty else current_price

    score = 0

    # 1. Trend Score (สูงสุด 40 คะแนน) — ราคาอยู่เหนือ EMA หรือไม่
    if current_price > ema200:
        score += 15  # อยู่เหนือเส้นแนวโน้มระยะยาว
    if current_price > ema50:
        score += 15  # อยู่เหนือเส้นแนวโน้มระยะกลาง
    if ema50 > ema200:
        score += 10  # EMA50 อยู่เหนือ EMA200 (Golden Cross)

    # 2. Momentum Score (สูงสุด 20 คะแนน)
    year_high = df['High'].tail(252).max()
    if 55 <= rsi <= 75:
        score += 10  # RSI อยู่ในโซน momentum ที่ดี (ไม่ overbought)
    if current_price >= year_high * 0.85:
        score += 10  # ราคาใกล้ high ปีล่าสุด — Breakout Potential

    # 3. Relative Volume Score (สูงสุด 30 คะแนน)
    avg_vol = df['Volume'].tail(20).mean()
    last_vol = df['Volume'].iloc[-1]
    rvol = last_vol / avg_vol if avg_vol > 0 else 1.0  # อัตราส่วน Volume วันนี้ vs ค่าเฉลี่ย

    if rvol >= 2.0:
        score += 30  # Volume สูงมาก — สัญญาณแข็งแกร่ง
    elif rvol >= 1.5:
        score += 20
    elif rvol >= 1.0:
        score += 10

    # 4. Supply/Demand Zone Alignment (สูงสุด 10 คะแนน)
    sd = find_supply_demand_zones(df)
    if sd and sd['is_retesting']:
        score += 10  # ราคากำลัง retest demand zone — จุดเข้าซื้อที่ดี

    return {
        'score': min(score, 100),
        'rvol': round(rvol, 2),
        'rsi': round(rsi, 2),
        'ema200': ema200,
        'ema50': ema50,
        'sd_zone': sd
    }


# ----------------------------------------------------------------------
# find_supply_demand_zones_v2 — เวอร์ชันปรับปรุง
# ความแตกต่างจาก v1:
#   - ERC ต้องการ Body > 1.5x avg_body AND Volume > 1.5x avg_vol (ทั้งสองเงื่อนไข)
#   - Supply target = 52-week high เสมอ (ไม่ fallback 60/120d)
#   - Stop loss คำนวณจาก ATR: refined_lower - (ATR * 0.5)
#   - คืนค่า erc_volume_confirmed และ zone_target_source
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# detect_price_pattern — ตรวจจับ Price Pattern จาก OHLC (3 แท่งล่าสุด)
#   Bullish patterns  → score > 0 (bonus ใน BUY score)
#   Bearish patterns  → score < 0 (penalty ใน BUY score)
#   No pattern        → score = 0
#   Patterns: Hammer(+10), Bullish Engulfing(+10), Morning Star(+8),
#             Inside Bar Break(+6), Shooting Star(-8), Bearish Engulfing(-10), Doji(-5)
# ----------------------------------------------------------------------
def detect_price_pattern(df):
    if df is None or len(df) < 3:
        return {'name': '', 'score': 0}

    r3 = df.iloc[-3]  # oldest of last 3 candles
    r2 = df.iloc[-2]  # middle candle
    r1 = df.iloc[-1]  # latest candle

    try:
        o3, h3, l3, c3 = float(r3['Open']), float(r3['High']), float(r3['Low']), float(r3['Close'])
        o2, h2, l2, c2 = float(r2['Open']), float(r2['High']), float(r2['Low']), float(r2['Close'])
        o1, h1, l1, c1 = float(r1['Open']), float(r1['High']), float(r1['Low']), float(r1['Close'])
    except (KeyError, TypeError, ValueError):
        return {'name': '', 'score': 0}

    body1 = abs(c1 - o1)
    rng1  = h1 - l1 if h1 > l1 else 0.0001
    upper_wick1 = h1 - max(o1, c1)
    lower_wick1 = min(o1, c1) - l1

    body2 = abs(c2 - o2)
    body3 = abs(c3 - o3)

    # ---- Bearish patterns (penalty) — check first so we don't miss early exit ----

    # Bearish Engulfing: prev bullish → current bearish fully covers it
    if c2 > o2 and c1 < o1 and o1 >= c2 and c1 <= o2:
        return {'name': 'Bearish Engulf', 'score': -10}

    # Shooting Star: long upper wick ≥ 2× body, closes in lower half
    if (rng1 > 0 and upper_wick1 >= 2 * body1 and
            lower_wick1 <= 0.3 * rng1 and c1 <= l1 + rng1 * 0.5):
        return {'name': 'Shooting Star', 'score': -8}

    # Doji: body ≤ 10% of range — indecision / potential reversal
    if rng1 > 0 and body1 <= 0.1 * rng1:
        return {'name': 'Doji', 'score': -5}

    # ---- Bullish patterns (bonus) ----

    # Bullish Engulfing: prev bearish → current bullish fully covers it
    if c2 < o2 and c1 > o1 and o1 <= c2 and c1 >= o2:
        return {'name': 'Bullish Engulf', 'score': 10}

    # Hammer / Pin Bar: long lower wick ≥ 2× body, closes in upper half
    if (rng1 > 0 and lower_wick1 >= 2 * body1 and
            upper_wick1 <= 0.3 * rng1 and c1 >= l1 + rng1 * 0.5):
        return {'name': 'Hammer', 'score': 10}

    # Morning Star (3-candle reversal)
    mid3 = (o3 + c3) / 2
    if (c3 < o3 and body3 > 0 and       # candle-3 bearish
            body2 <= 0.3 * body3 and    # candle-2 small (doji-like)
            c1 > o1 and c1 > mid3):     # candle-1 bullish, closes above midpoint
        return {'name': 'Morning Star', 'score': 8}

    # Inside Bar Breakout: candle-2 inside candle-3, candle-1 breaks above
    if h2 < h3 and l2 > l3 and c1 > h2:
        return {'name': 'Inside Bar↑', 'score': 6}

    return {'name': '', 'score': 0}

# ----------------------------------------------------------------------
# find_supply_demand_zones_v2 — เวอร์ชันปรับปรุง
# ----------------------------------------------------------------------
def find_supply_demand_zones_v2(df):
    if df is None or len(df) < 50:
        return None

    import pandas_ta as ta
    df = df.copy()

    # คำนวณขนาด Body และค่าเฉลี่ย Body/Volume
    df['Body'] = (df['Close'] - df['Open']).abs()
    df['Avg_Body'] = df['Body'].rolling(window=20).mean()
    df['Avg_Vol'] = df['Volume'].rolling(window=20).mean()

    # ATR สำหรับคำนวณ Stop Loss
    atr_series = ta.atr(df['High'], df['Low'], df['Close'], length=14)
    atr = float(atr_series.iloc[-1]) if atr_series is not None and not atr_series.empty else 0

    # ERC Bull: แท่งขาขึ้น + Body > 1.5x avg_body + Volume > 1.5x avg_vol (ต้องครบทั้งสอง)
    df['is_erc_bull'] = (
        (df['Close'] > df['Open']) &
        (df['Body'] > df['Avg_Body'] * 1.5) &
        (df['Volume'] > df['Avg_Vol'] * 1.5)
    )

    erc_bulls = df[df['is_erc_bull']]
    if erc_bulls.empty:
        return None

    last_erc_idx = erc_bulls.index[-1]
    last_erc_pos = df.index.get_loc(last_erc_idx)

    if last_erc_pos < 5:
        return None

    # หา Base: 5 แท่งก่อน ERC
    base_window = df.iloc[last_erc_pos - 5:last_erc_pos]
    zone_upper = base_window[['Open', 'Close']].max().max()
    zone_lower = base_window['Low'].min()

    last_bear = base_window[base_window['Close'] < base_window['Open']]
    if not last_bear.empty:
        refined_upper = last_bear['High'].iloc[-1]
        refined_lower = last_bear['Low'].iloc[-1]
        if refined_lower < zone_lower:
            refined_lower = zone_lower
    else:
        refined_upper = zone_upper
        refined_lower = zone_lower

    # Supply Target = 52-week high เสมอ
    target_price = df['High'].tail(252).max()
    zone_target_source = '52w'

    # ATR-based stop loss
    stop_loss = refined_lower - (atr * 0.5) if atr > 0 else refined_lower * 0.99

    entry_price = refined_upper
    risk = entry_price - stop_loss
    reward = target_price - entry_price
    rr_ratio = reward / risk if risk > 0 else 0

    # Confidence Score
    score = 40
    if 'EMA200' not in df.columns:
        df['EMA200'] = ta.ema(df['Close'], length=200)
    if 'EMA50' not in df.columns:
        df['EMA50'] = ta.ema(df['Close'], length=50)
    if 'RSI' not in df.columns:
        df['RSI'] = ta.rsi(df['Close'], length=14)

    last_close = df['Close'].iloc[-1]
    last_ema200 = df['EMA200'].iloc[-1] if 'EMA200' in df.columns else last_close
    last_ema50 = df['EMA50'].iloc[-1] if 'EMA50' in df.columns else last_close

    if last_close > last_ema200:
        score += 15
    if last_ema50 > last_ema200:
        score += 10

    erc_vol = df.loc[last_erc_idx, 'Volume']
    avg_vol = df['Volume'].tail(20).mean()
    if erc_vol > avg_vol * 2.0:
        score += 15
    elif erc_vol > avg_vol * 1.5:
        score += 10  # ERC volume confirmed เสมอ เพราะผ่าน filter แล้ว

    if rr_ratio >= 3:
        score += 15
    elif rr_ratio >= 2:
        score += 10

    rsi_now = df['RSI'].iloc[-1] if 'RSI' in df.columns and pd.notna(df['RSI'].iloc[-1]) else 50
    if 40 <= rsi_now <= 70:
        score += 5

    final_score = min(score, 100)

    return {
        'type': 'Sniper (DZ)',
        'start': float(round(refined_upper, 2)),
        'end': float(round(refined_lower, 2)),
        'stop_loss': float(round(stop_loss, 2)),
        'target': float(round(target_price, 2)),
        'rr_ratio': float(round(rr_ratio, 2)),
        'confidence_score': int(final_score),
        'erc_volume_confirmed': True,   # ผ่าน filter volume แล้วเสมอ
        'zone_target_source': zone_target_source,
        'is_retesting': bool(
            df['Close'].iloc[-1] <= refined_upper * 1.05 and
            df['Close'].iloc[-1] >= refined_lower * 0.95
        ),
        'erc_date': last_erc_idx.strftime('%Y-%m-%d') if hasattr(last_erc_idx, 'strftime') else str(last_erc_idx),
        'base_start': base_window.index[0].strftime('%Y-%m-%d') if hasattr(base_window.index[0], 'strftime') else str(base_window.index[0]),
        'base_end': base_window.index[-1].strftime('%Y-%m-%d') if hasattr(base_window.index[-1], 'strftime') else str(base_window.index[-1]),
    }


# ----------------------------------------------------------------------
# analyze_momentum_technical_v2 — เวอร์ชันปรับปรุง
# ความแตกต่างจาก v1:
#   - Direction-aware RVOL: วันขาขึ้น → เต็ม pts, วันขาลง → ครึ่ง pts
#   - RVOL max 25 pts (ลดจาก 30)
#   - RSI max 25 pts (เพิ่มจาก 20)
#   - Trend score ยังคงเดิม 40 pts
#   - S/D Zone: 10 pts
#   - ใช้ find_supply_demand_zones_v2 ภายใน
# ----------------------------------------------------------------------
def analyze_momentum_technical_v2(df):
    if df is None or len(df) < 50:
        return {'score': 0, 'rvol': 0, 'rsi': 0, 'ema200': 0, 'ema50': 0, 'ema20': 0,
                'rvol_bullish': True, 'avg_volume_20d': 0, 'sd_zone': None,
                'ema20_aligned': False}

    import pandas_ta as ta
    df = df.copy()

    df['EMA200'] = ta.ema(df['Close'], length=200)
    df['EMA50']  = ta.ema(df['Close'], length=50)
    df['EMA20']  = ta.ema(df['Close'], length=20)
    df['RSI']    = ta.rsi(df['Close'], length=14)

    current_price = float(df['Close'].iloc[-1])
    last_open     = float(df['Open'].iloc[-1])
    rsi    = float(df['RSI'].iloc[-1])    if pd.notna(df['RSI'].iloc[-1])    else 50.0
    ema200 = float(df['EMA200'].iloc[-1]) if pd.notna(df['EMA200'].iloc[-1]) else current_price
    ema50  = float(df['EMA50'].iloc[-1])  if pd.notna(df['EMA50'].iloc[-1])  else current_price
    ema20  = float(df['EMA20'].iloc[-1])  if pd.notna(df['EMA20'].iloc[-1])  else current_price

    score = 0

    # 1. Trend Score (สูงสุด 40 คะแนน)
    #    v3: เพิ่ม EMA20 > EMA50 > EMA200 full alignment (+8) — ลด weight ตัวเดี่ยวลงเล็กน้อย
    ema20_aligned = (current_price > ema20 > ema50 > ema200)  # Full Minervini stack
    if current_price > ema200: score += 12
    if current_price > ema50:  score += 12
    if ema50 > ema200:         score += 8
    if ema20_aligned:          score += 8   # 3-layer confirmation (Minervini full stack)

    # 2. RSI Score (สูงสุด 25 คะแนน)
    #    v3: ย้าย optimal zone เป็น 65-80 (momentum breakout zone) แทน 55-75
    year_high = float(df['High'].tail(252).max())
    if 65 <= rsi <= 80:
        score += 15   # จุดหวาน momentum — ไม่ overbought แต่กำลังวิ่ง
    elif 55 <= rsi < 65:
        score += 10   # momentum กำลังก่อตัว
    elif rsi > 80:
        score += 8    # overbought แต่ trend ยังแรง
    elif 45 <= rsi < 55:
        score += 5    # กลางๆ
    if current_price >= year_high * 0.85:
        score += 10   # ราคาใกล้ 52-week high

    # 3. Direction-aware RVOL Score (สูงสุด 25 คะแนน)
    avg_vol = float(df['Volume'].tail(20).mean())
    last_vol = float(df['Volume'].iloc[-1])
    rvol = last_vol / avg_vol if avg_vol > 0 else 1.0
    rvol_bullish = current_price >= last_open

    if rvol_bullish:
        if rvol >= 2.0:   score += 25
        elif rvol >= 1.5: score += 18
        elif rvol >= 1.0: score += 10
    else:
        if rvol >= 2.0:   score += 12
        elif rvol >= 1.5: score += 9
        elif rvol >= 1.0: score += 5

    # 4. Supply/Demand Zone retest (สูงสุด 10 คะแนน)
    sd = find_supply_demand_zones_v2(df)
    if sd and sd['is_retesting']:
        score += 10

    # 5. Performance returns (for RS Rating in view)
    ret_1m = 0.0
    ret_3m = 0.0
    if len(df) >= 22:
        ret_1m = float((df['Close'].iloc[-1] - df['Close'].iloc[-22]) / df['Close'].iloc[-22] * 100)
    if len(df) >= 66:
        ret_3m = float((df['Close'].iloc[-1] - df['Close'].iloc[-66]) / df['Close'].iloc[-66] * 100)

    # 6. EMA20 Slope — EMA กำลังชี้ขึ้นหรือแบน (Trend Following quality check)
    ema20_slope = 0.0
    ema20_rising = False
    if len(df['EMA20'].dropna()) >= 6:
        ema20_5d_ago = float(df['EMA20'].dropna().iloc[-6])
        if ema20_5d_ago > 0:
            ema20_slope = round((ema20 - ema20_5d_ago) / ema20_5d_ago * 100, 3)
            ema20_rising = ema20_slope > 0.1  # ชี้ขึ้นอย่างมีนัยสำคัญ

    # 7. Higher High / Higher Low structure (20 candles) — เทรนด์โครงสร้างจริง
    hh_hl = False
    if len(df) >= 20:
        window = df.tail(20)
        highs = window['High'].values
        lows  = window['Low'].values
        # หา swing high (ใหญ่กว่า 2 bars รอบข้าง) และ swing low
        swing_highs = [highs[i] for i in range(2, len(highs)-2)
                       if highs[i] > highs[i-1] and highs[i] > highs[i-2]
                       and highs[i] > highs[i+1] and highs[i] > highs[i+2]]
        swing_lows  = [lows[i] for i in range(2, len(lows)-2)
                       if lows[i] < lows[i-1] and lows[i] < lows[i-2]
                       and lows[i] < lows[i+1] and lows[i] < lows[i+2]]
        # HH = swing high ล่าสุด > swing high ก่อนหน้า
        # HL = swing low ล่าสุด > swing low ก่อนหน้า
        has_hh = len(swing_highs) >= 2 and swing_highs[-1] > swing_highs[-2]
        has_hl = len(swing_lows)  >= 2 and swing_lows[-1]  > swing_lows[-2]
        hh_hl = has_hh and has_hl

    return {
        'score': min(score, 100),
        'rvol': round(rvol, 2),
        'rsi': round(rsi, 2),
        'ema200': ema200,
        'ema50': ema50,
        'ema20': ema20,
        'ema20_aligned': ema20_aligned,
        'ema20_slope': ema20_slope,
        'ema20_rising': ema20_rising,
        'hh_hl_structure': hh_hl,
        'rvol_bullish': rvol_bullish,
        'avg_volume_20d': round(avg_vol, 0),
        'sd_zone': sd,
        'stock_1m_return': ret_1m,
        'stock_3m_return': ret_3m,
    }


# ----------------------------------------------------------------------
# refresh_set100_symbols — อัปเดตรายชื่อหุ้น SET100 + MAI ในฐานข้อมูล
# ใช้รันครั้งแรกหรือเมื่อต้องการ refresh รายชื่อหุ้นที่ Scanner ใช้
# ----------------------------------------------------------------------
def refresh_set100_symbols():
    from .models import ScannableSymbol

    # รายชื่อหุ้น SET100 + MAI ที่นิยม (ใช้เป็น seed ถ้ายังไม่มีในฐานข้อมูล)
    default_symbols = [
        "ADVANC", "AOT", "AWC", "BBL", "BDMS", "BEM", "BGRIM", "BH", "BJC", "BTS",
        "CBG", "CENTEL", "CHG", "CK", "CKP", "COM7", "CPALL", "CPF", "CPN", "CRC",
        "DELTA", "EA", "EGCO", "GLOBAL", "GPSC", "GULF", "HMPRO", "IRPC", "IVL",
        "JMART", "JMT", "KBANK", "KCE", "KTB", "KTC", "LH", "MINT", "MTC", "OR",
        "OSP", "PTT", "PTTEP", "PTTGC", "RATCH", "SAWAD", "SCB", "SCC", "SCGP", "SPALI",
        "STA", "STGT", "TCAP", "TISCO", "TOP", "TRUE", "TTB", "TU", "WHA",
        "AMATA", "BAM", "BANPU", "BAY", "BCH", "BLA", "BPP", "DOHOME", "FORTH", "GUNKUL",
        "ICHI", "KEX", "KKP", "MEGA", "ONEE", "PLANB", "PSL", "PTG", "QH", "RBF",
        "RS", "SABINA", "SINGER", "SIRI", "SPRC", "SYNEX", "THANI", "TIDLOR", "TIPH",
        "TKN", "TLI", "TQM", "TSTH", "TTW", "VGI", "BCP", "NYT",

        # หุ้น MAI ที่ได้รับความนิยม
        "AU", "SPA", "DITTO", "BE8", "BBIK", "IIG", "SABUY", "SECURE", "JDF", "PROEN",
        "ZIGA", "XPG", "SMD", "TACC", "TMC", "TPCH", "FPI", "FSMART", "NDR",
        "NETBAY", "BIZ", "BROOK", "COLOR", "CHO", "D", "KUN", "MVP", "SE", "UKEM"
    ]

    # บันทึกหรืออัปเดตรายชื่อในฐานข้อมูล (ไม่ซ้ำ)
    for sym in default_symbols:
        ScannableSymbol.objects.update_or_create(
            symbol=sym,
            defaults={'index_name': 'SET100+MAI', 'is_active': True}
        )

    print(f"Refreshed {len(default_symbols)} scannable symbols in database.")
