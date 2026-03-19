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
            if 'content' in n:
                # รูปแบบข่าวใหม่ของ yfinance — อยู่ใน key 'content'
                c = n['content']
                normalized_news.append({
                    'title': c.get('title', ''),
                    'link': c.get('clickThroughUrl', {}).get('url', ''),
                    'publisher': c.get('provider', {}).get('displayName', ''),
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
# analyze_with_ai — วิเคราะห์หุ้นด้วย Gemini AI
# รวมข้อมูลพื้นฐาน + เทคนิค + ข่าว แล้วส่งให้ AI สรุปเป็นภาษาไทย
# ----------------------------------------------------------------------
def analyze_with_ai(symbol, data, extra_context=None):
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
        return {'score': 0, 'rvol': 0, 'rsi': 0, 'ema200': 0, 'ema50': 0,
                'rvol_bullish': True, 'avg_volume_20d': 0, 'sd_zone': None}

    import pandas_ta as ta
    df = df.copy()

    df['EMA200'] = ta.ema(df['Close'], length=200)
    df['EMA50'] = ta.ema(df['Close'], length=50)
    df['EMA20'] = ta.ema(df['Close'], length=20)
    df['RSI'] = ta.rsi(df['Close'], length=14)

    current_price = df['Close'].iloc[-1]
    last_open = df['Open'].iloc[-1]
    rsi = float(df['RSI'].iloc[-1]) if pd.notna(df['RSI'].iloc[-1]) else 50.0
    ema200 = float(df['EMA200'].iloc[-1]) if pd.notna(df['EMA200'].iloc[-1]) else current_price
    ema50 = float(df['EMA50'].iloc[-1]) if pd.notna(df['EMA50'].iloc[-1]) else current_price

    score = 0

    # 1. Trend Score (สูงสุด 40 คะแนน)
    if current_price > ema200:
        score += 15
    if current_price > ema50:
        score += 15
    if ema50 > ema200:
        score += 10

    # 2. RSI Score (สูงสุด 25 คะแนน — เพิ่มจาก 20)
    year_high = df['High'].tail(252).max()
    if 55 <= rsi <= 75:
        score += 15   # RSI อยู่ใน momentum zone
    elif 45 <= rsi < 55:
        score += 7    # RSI อยู่ในโซนกลาง
    if current_price >= year_high * 0.85:
        score += 10   # ราคาใกล้ 52-week high

    # 3. Direction-aware RVOL Score (สูงสุด 25 คะแนน — ลดจาก 30)
    avg_vol = df['Volume'].tail(20).mean()
    last_vol = df['Volume'].iloc[-1]
    rvol = last_vol / avg_vol if avg_vol > 0 else 1.0
    rvol_bullish = current_price >= last_open  # True = วันขาขึ้น

    if rvol_bullish:
        # วันขาขึ้น: ให้คะแนนเต็ม
        if rvol >= 2.0:
            score += 25
        elif rvol >= 1.5:
            score += 18
        elif rvol >= 1.0:
            score += 10
    else:
        # วันขาลง: ให้ครึ่งคะแนน (volume ที่เพิ่มขึ้นในวันลงเป็นสัญญาณแรงขาย)
        if rvol >= 2.0:
            score += 12
        elif rvol >= 1.5:
            score += 9
        elif rvol >= 1.0:
            score += 5

    # 4. Supply/Demand Zone (สูงสุด 10 คะแนน)
    sd = find_supply_demand_zones_v2(df)
    if sd and sd['is_retesting']:
        score += 10

    return {
        'score': min(score, 100),
        'rvol': round(rvol, 2),
        'rsi': round(rsi, 2),
        'ema200': ema200,
        'ema50': ema50,
        'rvol_bullish': rvol_bullish,
        'avg_volume_20d': round(avg_vol, 0),
        'sd_zone': sd,
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
