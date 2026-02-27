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
    
    raw_news = ticker.news
    normalized_news = []
    if raw_news:
        for n in raw_news:
            if 'content' in n:
                c = n['content']
                normalized_news.append({
                    'title': c.get('title', ''),
                    'link': c.get('clickThroughUrl', {}).get('url', ''),
                    'publisher': c.get('provider', {}).get('displayName', ''),
                    'providerPublishTime': c.get('pubDate', ''),
                })
            else:
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

def analyze_with_ai(symbol, data):
    """
    Use Gemini to analyze the collected data.
    """
    genai.configure(api_key=settings.GEMINI_API_KEY)
    
    # Model Selection Logic (Fallback chain)
    model_names = [
        'gemini-2.0-flash', 
        'gemini-1.5-flash', 
        'gemini-1.5-pro',
        'gemini-pro'
    ]
    model = None
    for m_name in model_names:
        try:
            temp_model = genai.GenerativeModel(m_name)
            # Try a very simple call to verify availability
            temp_model.generate_content("ping")
            model = temp_model
            break
        except Exception:
            continue
    
    if not model:
        # Final fallback
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

    # --- NEWS SCRAPING FOR SENTIMENT (BeautifulSoup4) ---
    news_items = data.get('news', [])
    news_content = ""
    if news_items:
        try:
            import requests
            from bs4 import BeautifulSoup
            
            scraped_texts = []
            for n in news_items[:3]: # Limit to top 3 news
                link = n.get('link')
                title = n.get('title', '')
                try:
                    if link:
                        req = requests.get(link, timeout=3, headers={'User-Agent': 'Mozilla/5.0'})
                        if req.status_code == 200:
                            soup = BeautifulSoup(req.text, 'html.parser')
                            # Try to get paragraphs
                            ps = soup.find_all('p')
                            text = ' '.join([p.get_text() for p in ps if len(p.get_text()) > 20])
                            snippet = text[:600] + '...' if len(text) > 600 else text
                            if snippet:
                                scraped_texts.append(f"• Title: {title}\n  Content Snippet: {snippet}")
                            else:
                                scraped_texts.append(f"• Title: {title}")
                except:
                    scraped_texts.append(f"• Title: {title}")
            
            if scraped_texts:
                news_content = "\nNews & Sentiments:\n" + "\n".join(scraped_texts)
        except Exception:
            pass

    # --- ADVANCED TECHNICALS (Replacing TA-Lib with pandas_ta & Custom Patterns) ---
    macd_info = "N/A"
    bb_info = "N/A"
    pattern_info = "None detected recently"
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

        # Candlestick Patterns (TA-Lib Alternative)
        last_3 = history.tail(3)
        patterns_found = []
        if len(last_3) == 3:
            # Current Day
            o_c, c_c, h_c, l_c = last_3['Open'].iloc[-1], last_3['Close'].iloc[-1], last_3['High'].iloc[-1], last_3['Low'].iloc[-1]
            # Previous Day
            o_p, c_p, h_p, l_p = last_3['Open'].iloc[-2], last_3['Close'].iloc[-2], last_3['High'].iloc[-2], last_3['Low'].iloc[-2]
            
            body_c = abs(c_c - o_c)
            range_c = h_c - l_c
            
            # 1. Doji
            if range_c > 0 and (body_c / range_c) < 0.1:
                patterns_found.append("Doji (Indecision/Reversal)")
                
            # 2. Engulfing
            is_bull_engulf = (c_p < o_p) and (c_c > o_c) and (c_c >= o_p) and (o_c <= c_p)
            is_bear_engulf = (c_p > o_p) and (c_c < o_c) and (c_c <= o_p) and (o_c >= c_p)
            if is_bull_engulf: patterns_found.append("Bullish Engulfing (Strong Reversal Up)")
            if is_bear_engulf: patterns_found.append("Bearish Engulfing (Strong Reversal Down)")
                
            # 3. Hammer / Shooting Star
            if range_c > 0:
                lower_wick = min(o_c, c_c) - l_c
                upper_wick = h_c - max(o_c, c_c)
                if body_c > 0:
                    if lower_wick / body_c > 2 and upper_wick / body_c < 0.5:
                        patterns_found.append("Hammer (Potential Bullish Reversal)")
                    elif upper_wick / body_c > 2 and lower_wick / body_c < 0.5:
                        patterns_found.append("Shooting Star (Potential Bearish Reversal)")
                        
        if patterns_found:
            pattern_info = ", ".join(patterns_found)

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
    - Candlestick Patterns: {pattern_info}
    - Volume: Current={last_volume}, 20-Day Avg={avg_volume:.0f} (Ratio: {vol_ratio:.2f}x)
    
    Business Profile:
    {yq.get('profile', {}).get('longBusinessSummary', 'N/A')[:500]}...
    {news_content}
    
    Please provide a professional analysis in Thai language:
    1. Business Quality Review: วิเคราะห์ธุรกิจ โครงสร้างผู้ถือหุ้น (Free Float) และเทียบความถูก-แพงจากข้อมูล (Industry PE ถ้ามี)
    2. Deep Fundamental & Valuation: วิเคราะห์ความคุ้มค่า (PE, PBV, ROE, NPM, DE) และกำไรส่วนเกิน
    3. Advanced Technicals: วิเคราะห์แนวโน้มราคาด้วย MACD, Bollinger Bands, Price Patterns (Candlesticks), สัญญาณ Breakout, แนวรับ-แนวต้าน
    4. Sentiment Analysis: วิเคราะห์ทิศทางข่าวสารว่าส่งผลบวกหรือลบต่อราคาหุ้นในระยะสั้น
    5. Strategic Action Plan: คำแนะนำ Buy/Hold/Sell พร้อมเป้าหมายกำไรและจุดตัดขาดทุน
    
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
