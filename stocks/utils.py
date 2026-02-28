import pandas as pd
import requests
import yfinance as yf
from google import genai
from django.conf import settings
from yahooquery import Ticker as YQTicker
import pandas_ta as ta

# Removed custom session for yfinance to let it handle curl_cffi internally

def calculate_trailing_stop(symbol, current_price, entry_price, highest_price_since_buy=None, percent_trail=3.0):
    if highest_price_since_buy is None:
        highest_price_since_buy = max(current_price, entry_price) 
    else:
        highest_price_since_buy = max(current_price, entry_price, highest_price_since_buy)
        
    stop_loss_price = highest_price_since_buy * (1 - (percent_trail / 100))
    
    status_code = "HOLD"
    color_code = "success" 
    
    if current_price <= stop_loss_price:
        status_code = "SELL (STOP LOSS)"
        color_code = "danger"
    elif current_price <= stop_loss_price * 1.01:
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

def get_stock_data(symbol):
    ticker = yf.Ticker(symbol)
    yq_ticker = YQTicker(symbol)
    
    info = ticker.info
    history = ticker.history(period="1y")
    financials = ticker.financials
    try:
        balance_sheet = ticker.quarterly_balance_sheet if not ticker.quarterly_balance_sheet.empty else ticker.balance_sheet
    except Exception:
        balance_sheet = None
    
    if not history.empty:
        history['RSI'] = ta.rsi(history['Close'], length=14)
        macd = ta.macd(history['Close'])
        if macd is not None and not macd.empty:
            history = pd.concat([history, macd], axis=1)
    
    yq_summary = yq_ticker.summary_detail.get(symbol, {}) if (yq_ticker.summary_detail and isinstance(yq_ticker.summary_detail, dict) and yq_ticker.summary_detail.get(symbol)) else {}
    yq_profile = yq_ticker.asset_profile.get(symbol, {}) if (yq_ticker.asset_profile and isinstance(yq_ticker.asset_profile, dict) and yq_ticker.asset_profile.get(symbol)) else {}
    yq_stats = yq_ticker.key_stats.get(symbol, {}) if (yq_ticker.key_stats and isinstance(yq_ticker.key_stats, dict) and yq_ticker.key_stats.get(symbol)) else {}
    yq_recommendations = yq_ticker.recommendation_trend.get(symbol, pd.DataFrame()) if (yq_ticker.recommendation_trend is not None and not isinstance(yq_ticker.recommendation_trend, dict)) else pd.DataFrame()
    if isinstance(yq_ticker.recommendation_trend, dict):
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
    info = data.get('info', {})
    yq = data.get('yq_data', {})
    history = data.get('history', pd.DataFrame())
    news = data.get('news', [])
    
    pe_ratio = info.get('trailingPE', 'N/A')
    pb_ratio = info.get('priceToBook', 'N/A')
    roe = f"{(info.get('returnOnEquity', 0) or 0) * 100:.2f}%" if info.get('returnOnEquity') else 'N/A'
    npm = f"{(info.get('profitMargins', 0) or 0) * 100:.2f}%" if info.get('profitMargins') else 'N/A'
    
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
    except: pass
    
    free_float = info.get('floatShares', 'N/A')
    
    yq_summary_dict = yq.get('summary', {}) if isinstance(yq, dict) else {}
    if not isinstance(yq_summary_dict, dict): yq_summary_dict = {}
    div_yield = yq_summary_dict.get('dividendYield', info.get('dividendYield', 'N/A'))
    
    thaifin_data = ""
    if symbol.endswith('.BK'):
        clean_symbol = symbol.replace('.BK', '')
        try:
            from thaifin import Stock
            tf_stock = Stock(clean_symbol)
            tf_info = tf_stock.info if hasattr(tf_stock, 'info') else {}
            if isinstance(tf_info, dict):
                thaifin_data = f"\n    [Thaifin Local Data] PE: {tf_info.get('pe', 'N/A')}, PBV: {tf_info.get('pbv', 'N/A')}, DivYield: {tf_info.get('dividend_yield', 'N/A')}, Industry PE: {tf_info.get('industry_pe', 'N/A')}"
        except: pass

    yq_stats_dict = yq.get('stats', {}) if isinstance(yq, dict) else {}
    if not isinstance(yq_stats_dict, dict): yq_stats_dict = {}
    peg_ratio = yq_stats_dict.get('pegRatio', 'N/A')
    
    rec_summary = "N/A"
    try:
        yq_recommendations = yq.get('recommendations', pd.DataFrame())
        if isinstance(yq_recommendations, pd.DataFrame) and not yq_recommendations.empty:
            latest_rec = yq_recommendations.iloc[-1]
            rec_summary = f"Strong Buy: {latest_rec.get('strongBuy', 0)}, Buy: {latest_rec.get('buy', 0)}, Hold: {latest_rec.get('hold', 0)}, Sell: {latest_rec.get('sell', 0)}"
    except: pass

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
    except: pass

    fin_context = f"""
    - P/E Ratio: {pe_ratio}
    - P/BV Ratio: {pb_ratio}
    - ROE: {roe}
    - Net Profit Margin: {npm}
    - D/E Ratio: {de_ratio}
    - Free Float: {free_float}
    - Dividend Yield: {div_yield}{thaifin_data}
    """
    
    last_price = history['Close'].iloc[-1] if not history.empty else 0
    price_change = ((last_price - history['Close'].iloc[-2]) / history['Close'].iloc[-2] * 100) if not history.empty and len(history) > 1 else 0
    last_volume = history['Volume'].iloc[-1] if not history.empty else 0
    avg_volume = history['Volume'].mean() if not history.empty else 1
    vol_ratio = last_volume / avg_volume
    
    rsi = history['RSI'].iloc[-1] if 'RSI' in history.columns else 'N/A'
    macd_val = history['MACD_12_26_9'].iloc[-1] if 'MACD_12_26_9' in history.columns else 'N/A'
    macd_sig = history['MACDs_12_26_9'].iloc[-1] if 'MACDs_12_26_9' in history.columns else 'N/A'
    
    news_content = "\nRecent Headlines:\n"
    for n in news[:5]:
        news_content += f"- {n.get('title')} ({n.get('publisher')})\n"
    
    prompt = f"""
    Analyze the stock {symbol} for an investor using the following data:
    
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
    2. Deep Fundamental & Valuation: วิเคราะห์ความคุ้มค่า
    3. Advanced Technicals: วิเคราะห์แนวโน้มราคา
    4. Sentiment Analysis: วิเคราะห์ทิศทางข่าวสาร
    5. Strategic Action Plan: คำแนะนำ Buy/Hold/Sell
    
    Format in Markdown for professional web report. Output ONLY raw markdown.
    """
    
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(model='gemini-2.0-flash', contents=prompt)
        clean_text = response.text
        if clean_text.startswith("```markdown"): clean_text = clean_text[len("```markdown"):].strip()
        if clean_text.endswith("```"): clean_text = clean_text[:-3].strip()
        return clean_text
    except Exception as e:
        return f"Error analyzing data with AI: {str(e)}"

def refresh_set100_symbols():
    """
    Refreshes the ScannableSymbol database with current SET100 and MAI stocks.
    """
    from .models import ScannableSymbol
    
    # Seed/Fallback list (Current SET100 + popular MAI)
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

        "AU", "SPA", "DITTO", "BE8", "BBIK", "IIG", "SABUY", "SECURE", "JDF", "PROEN",
        "ZIGA", "XPG", "SMD", "TACC", "TMC", "TPCH", "FPI", "FSMART", "NDR",
        "NETBAY", "BIZ", "BROOK", "COLOR", "CHO", "D", "KUN", "MVP", "SE", "UKEM"
    ]
    
    # Update Database: ensures these exist in the database for the scanner to pull from
    for sym in default_symbols:
        ScannableSymbol.objects.update_or_create(
            symbol=sym,
            defaults={'index_name': 'SET100+MAI', 'is_active': True}
        )
    
    print(f"Refreshed {len(default_symbols)} scannable symbols in database.")
