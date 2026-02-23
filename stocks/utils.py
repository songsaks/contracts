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
    history = ticker.history(period="6mo")
    financials = ticker.financials
    
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

    # Fundamental Metrics Extraction
    pe_ratio = info.get('trailingPE', 'N/A')
    pb_ratio = info.get('priceToBook', 'N/A')
    roe = info.get('returnOnEquity', 'N/A')
    npm = info.get('profitMargins', 'N/A')
    de_ratio = info.get('debtToEquity', 'N/A')
    free_float = info.get('floatShares', 'N/A')
    div_yield = yq.get('summary', {}).get('dividendYield', info.get('dividendYield', 'N/A'))
    
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
    - Dividend Yield: {div_yield}
    """

    prompt = f"""
    Analyze the following asset for Trend and Actionable advice: {symbol} ({info.get('longName', 'N/A')})
    
    Financial Metrics (Fundamental):
    {fin_context}

    Market Data Context & Technicals:
    - Current Price: {current_price} {info.get('currency', 'USD')}
    - PEG Ratio: {peg_ratio}
    - Analyst Trends: {rec_summary}
    - SMA Trends: Last Close={last_close}, 50 SMA={sma_50}, 200 SMA={sma_200}
    - Momentum: RSI (14)={current_rsi:.2f} ({rsi_status})
    - Volume: Current={last_volume}, 20-Day Avg={avg_volume:.0f} (Ratio: {vol_ratio:.2f}x)
    
    Business Profile:
    {yq.get('profile', {}).get('longBusinessSummary', 'N/A')[:500]}...
    
    Please provide a professional analysis in Thai language:
    1. Business Quality Review: วิเคราะห์ความแข็งแกร่งของธุรกิจและ Free Float
    2. Deep Fundamental & Valuation: วิเคราะห์ความคุ้มค่าโดยละเอียด (PE, PBV, ROE, NPM, DE) และประเมิน Economic Profits
    3. Technical & Momentum: วิเคราะห์แนวโน้มราคา แรงซื้อขาย (Volume) และจุดกลับตัวจาก RSI
    4. Strategic Action Plan: คำแนะนำ Buy/Hold/Sell พร้อมเป้าหมายกำไรและจุดตัดขาดทุน
    
    Format in Markdown using 'Sarabun' style tone, professional and concise.
    """
    
    response = model.generate_content(prompt)
    return response.text
