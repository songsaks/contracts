import yfinance as yf
import google.generativeai as genai
from django.conf import settings
from yahooquery import Ticker as YQTicker
import pandas_ta as ta
import pandas as pd

def get_stock_data(symbol):
    """
    Fetch comprehensive data for a symbol using yfinance and yahooquery.
    """
    ticker = yf.Ticker(symbol)
    yq_ticker = YQTicker(symbol)
    
    # yfinance data
    info = ticker.info
    history = ticker.history(period="1y")
    financials = ticker.financials
    try:
        balance_sheet = ticker.quarterly_balance_sheet if not ticker.quarterly_balance_sheet.empty else ticker.balance_sheet
    except Exception:
        balance_sheet = None
    
    # Calculate Technical Indicators (RSI, MACD, etc.) using pandas_ta
    if not history.empty:
        history['RSI'] = ta.rsi(history['Close'], length=14)
        macd = ta.macd(history['Close'])
        if macd is not None:
            history = pd.concat([history, macd], axis=1)
    
    # yahooquery data (for deeper fundamentals)
    yq_summary = yq_ticker.summary_detail.get(symbol, {})
    yq_profile = yq_ticker.asset_profile.get(symbol, {})
    yq_stats = yq_ticker.key_stats.get(symbol, {})
    yq_recommendations = yq_ticker.recommendation_trend.get(symbol, pd.DataFrame())
    
    return {
        'info': info,
        'history': history,
        'financials': financials,
        'balance_sheet': balance_sheet,
        'news': ticker.news,
        'yq_data': {
            'summary': yq_summary,
            'profile': yq_profile,
            'stats': yq_stats,
            'recommendations': yq_recommendations
        }
    }

def analyze_with_ai(symbol, data):
    """
    Use Gemini to analyze the collected data.
    """
    genai.configure(api_key=settings.GEMINI_API_KEY)
    
    # Model Selection Logic (Based on available models in the environment)
    model_names = [
        'gemini-2.0-flash', 
        'gemini-flash-latest', 
        'gemini-pro-latest', 
        'gemini-1.5-flash', 
        'gemini-pro'
    ]
    model = None
    last_err = ""
    for m_name in model_names:
        try:
            temp_model = genai.GenerativeModel(m_name)
            # Try a very simple call to verify availability
            temp_model.generate_content("ping", generation_config={"max_output_tokens": 1})
            model = temp_model
            break
        except Exception as e:
            last_err = str(e)
            continue
    
    if not model:
        # Final fallback
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
        except:
            model = genai.GenerativeModel('gemini-pro')
    
    # Prepare data summary
    info = data['info']
    history = data['history']
    yq = data.get('yq_data', {})
    
    current_price = info.get('currentPrice') or info.get('regularMarketPrice')
    
    # Technical Summary
    last_close = history['Close'].iloc[-1] if not history.empty else 0
    sma_50 = history['Close'].rolling(window=50).mean().iloc[-1] if len(history) >= 50 else 0
    sma_200 = history['Close'].rolling(window=200).mean().iloc[-1] if len(history) >= 200 else 0
    
    # Volume Analysis
    avg_volume = history['Volume'].tail(20).mean() if len(history) >= 20 else 0
    last_volume = history['Volume'].iloc[-1] if not history.empty else 0
    vol_ratio = last_volume / avg_volume if avg_volume > 0 else 1
    
    # RSI Analysis
    current_rsi = history['RSI'].iloc[-1] if 'RSI' in history.columns and len(history) > 0 else 0
    rsi_status = "Neutral"
    if current_rsi < 30: rsi_status = "Oversold (RSI < 30)"
    elif current_rsi > 70: rsi_status = "Overbought (RSI > 70)"

    # Resistance & Breakout Analysis
    fifty_two_week_high = history['High'].max() if not history.empty and 'High' in history.columns else "N/A"
    recent_resistance = history['High'].tail(20).max() if not history.empty and 'High' in history.columns else "N/A"
    recent_support = history['Low'].tail(20).min() if not history.empty and 'Low' in history.columns else "N/A"
    is_breakout = (last_close >= fifty_two_week_high) if isinstance(fifty_two_week_high, (int, float)) else False

    # Fundamental Metrics Extraction
    pe_ratio = info.get('trailingPE', 'N/A')
    pb_ratio = info.get('priceToBook', 'N/A')
    roe = info.get('returnOnEquity', 'N/A')
    npm = info.get('profitMargins', 'N/A')
    
    bs = data.get('balance_sheet')
    de_ratio = 'N/A'
    if bs is not None and not bs.empty:
        try:
            col = bs.columns[0]
            tot_liab = bs.loc['Total Liabilities Net Minority Interest', col] if 'Total Liabilities Net Minority Interest' in bs.index else bs.loc['Total Liabilities', col]
            tot_eq = bs.loc['Stockholders Equity', col] if 'Stockholders Equity' in bs.index else bs.loc['Total Equity Gross Minority Interest', col]
            de_ratio = tot_liab / tot_eq
        except Exception:
            pass
            
    if de_ratio == 'N/A':
        de_ratio = info.get('debtToEquity', 'N/A')
        if isinstance(de_ratio, (int, float)): de_ratio = de_ratio / 100
    elif isinstance(de_ratio, (int, float)):
        de_ratio = round(de_ratio, 2)
        
    free_float = info.get('floatShares', 'N/A')
    div_yield = yq.get('summary', {}).get('dividendYield', info.get('dividendYield', 'N/A'))
    
    # Optional: thaifin integration for Thai Stocks
    thaifin_data = ""
    if symbol.endswith('.BK'):
        clean_symbol = symbol.replace('.BK', '')
        try:
            from thaifin import Stock
            tf_stock = Stock(clean_symbol)
            tf_info = tf_stock.info if hasattr(tf_stock, 'info') else {}
            tf_pe = tf_info.get('pe', 'N/A')
            tf_pbv = tf_info.get('pbv', 'N/A')
            tf_div = tf_info.get('dividend_yield', 'N/A')
            tf_ind_pe = tf_info.get('industry_pe', 'N/A') # Just as an example assumption of their API
            
            thaifin_data = f"\n    [Thaifin Local Data] PE: {tf_pe}, PBV: {tf_pbv}, DivYield: {tf_div}, Industry PE: {tf_ind_pe} (Use this for precise Thai market comparison if available)"
        except ImportError:
            thaifin_data = "\n    [Thaifin Notice] To get more accurate local Thai data like Industry PE, please install 'thaifin' library."
        except Exception:
            pass

    # YahooQuery Stats for PEG
    yq_stats = yq.get('stats', {})
    peg_ratio = yq_stats.get('pegRatio', 'N/A')
    
    # Analyst Trends
    yq_recommendations = yq.get('recommendations', pd.DataFrame())
    rec_summary = "N/A"
    if isinstance(yq_recommendations, pd.DataFrame) and not yq_recommendations.empty and 'strongBuy' in yq_recommendations.columns:
        latest_rec = yq_recommendations.iloc[-1]
        rec_summary = f"Strong Buy: {latest_rec.get('strongBuy', 0)}, Buy: {latest_rec.get('buy', 0)}, Hold: {latest_rec.get('hold', 0)}, Sell: {latest_rec.get('sell', 0)}"

    # Financial context formatting
    fin_context = f"""
    - P/E Ratio: {pe_ratio}
    - P/BV Ratio: {pb_ratio}
    - ROE: {roe}
    - Net Profit Margin: {npm}
    - D/E Ratio: {de_ratio}
    - Free Float: {free_float}
    - Dividend Yield: {div_yield}{thaifin_data}
    """

    # --- ADVANCED TECHNICALS (Replacing TA-Lib with pandas_ta) ---
    macd_info = "N/A"
    bb_info = "N/A"
    if not history.empty and len(history) >= 26:
        import pandas_ta as ta
        # MACD
        macd = history.ta.macd(fast=12, slow=26, signal=9)
        if macd is not None and not macd.empty:
            m_line = macd.iloc[-1, 0]
            m_hist = macd.iloc[-1, 1]
            m_sig = macd.iloc[-1, 2]
            macd_info = f"MACD={m_line:.2f}, Signal={m_sig:.2f}, Hist={m_hist:.2f} ({'Bullish' if m_hist > 0 else 'Bearish'})"
        
        # Bollinger Bands
        bbands = history.ta.bbands(length=20, std=2)
        if bbands is not None and not bbands.empty:
            lower = bbands.iloc[-1, 0]
            mid = bbands.iloc[-1, 1]
            upper = bbands.iloc[-1, 2]
            bb_info = f"Lower={lower:.2f}, Mid={mid:.2f}, Upper={upper:.2f} (Price vs Upper/Lower reflects overbought/oversold)"

    prompt = f"""
    Analyze the following asset for Trend and Actionable advice: {symbol} ({info.get('longName', 'N/A')})
    
    Financial Metrics (Fundamental):
    {fin_context}

    Market Data Context & Technicals:
    - Current Price: {current_price} {info.get('currency', 'USD')}
    - PEG Ratio: {peg_ratio}
    - Analyst Trends: {rec_summary}
    - Support & Resistance: 52W High={fifty_two_week_high}, 20D Resistance={recent_resistance}, 20D Support (Stop Loss)={recent_support}, Breakout={is_breakout}
    - SMA Trends: Last Close={last_close}, 50 SMA={sma_50}, 200 SMA={sma_200}
    - Momentum: RSI (14)={current_rsi:.2f} ({rsi_status})
    - Trend (MACD): {macd_info}
    - Volatility (Bollinger Bands): {bb_info}
    - Volume: Current={last_volume}, 20-Day Avg={avg_volume:.0f} (Ratio: {vol_ratio:.2f}x)
    
    Business Profile:
    {yq.get('profile', {}).get('longBusinessSummary', 'N/A')[:500]}...
    
    Please provide a professional analysis in Thai language:
    1. Business Quality Review: วิเคราะห์ธุรกิจ โครงสร้างผู้ถือหุ้น (Free Float) และเทียบความถูก-แพงจากข้อมูล (Industry PE ถ้ามี)
    2. Deep Fundamental & Valuation: วิเคราะห์ความคุ้มค่า (PE, PBV, ROE, NPM, DE) และกำไรส่วนเกิน
    3. Advanced Technicals: วิเคราะห์แนวโน้มราคาด้วย MACD, Bollinger Bands, สัญญาณ Breakout, แนวรับ-แนวต้าน และจุดกลับตัว
    4. Strategic Action Plan: คำแนะนำ Buy/Hold/Sell พร้อมเป้าหมายกำไรและจุดตัดขาดทุน
    
    Format in Markdown using 'Sarabun' style tone, professional and concise.
    IMPORTANT RULES:
    1. DO NOT include any conversational preamble or outro (e.g. "Here is the analysis...", "Explanation of Choices:"). 
    2. Output ONLY the raw markdown text.
    3. DO NOT wrap the output in ```markdown code blocks. Start immediately with the analysis headings.
    """
    
    response = model.generate_content(prompt)
    
    # Strip any residual markdown blocks if AI disobeys
    clean_text = response.text
    if clean_text.startswith("```markdown"):
        clean_text = clean_text[len("```markdown"):].strip()
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3].strip()
        
    return clean_text
