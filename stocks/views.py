from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib import messages
from django.conf import settings
import google.generativeai as genai
from .models import Watchlist, AnalysisCache, AssetCategory, Portfolio
from .utils import get_stock_data, analyze_with_ai
import yfinance as yf
import pandas as pd

def admin_only(user):
    return user.is_authenticated and user.is_staff

@user_passes_test(admin_only)
def dashboard(request):
    watchlist = Watchlist.objects.all()
    # Briefly get current price for each
    items = []
    import pandas_ta as ta
    for item in watchlist:
        try:
            t = yf.Ticker(item.symbol)
            # Fetch at least 30 days to calculate 14-day RSI
            hist = t.history(period="1mo")
            current = t.info.get('currentPrice') or t.info.get('regularMarketPrice') or t.info.get('previousClose')
            change = t.info.get('regularMarketChangePercent', 0)
            
            rsi_val = None
            rsi_status = "Neutral"
            if not hist.empty and len(hist) >= 14:
                rsi_series = ta.rsi(hist['Close'], length=14)
                if not rsi_series.empty:
                    rsi_val = rsi_series.iloc[-1]
                    if rsi_val < 30: rsi_status = "Oversold"
                    elif rsi_val > 70: rsi_status = "Overbought"

            items.append({
                'obj': item,
                'price': current,
                'change': change,
                'rsi': rsi_val,
                'rsi_status': rsi_status
            })
        except:
            items.append({'obj': item, 'price': 'Error', 'change': 0, 'rsi': None, 'rsi_status': 'Error'})
            
    return render(request, 'stocks/dashboard.html', {'items': items, 'categories': AssetCategory.choices})

@user_passes_test(admin_only)
def analyze(request, symbol):
    try:
        data = get_stock_data(symbol)
        analysis_text = analyze_with_ai(symbol, data)
        
        # Prepare Chart Data (Price & Volume)
        history = data.get('history', pd.DataFrame())
        chart_labels = []
        chart_values = []
        chart_volumes = []
        if not history.empty:
            history_subset = history.tail(90)
            chart_labels = [d.strftime('%Y-%m-%d') for d in history_subset.index]
            chart_values = [round(float(v), 2) for v in history_subset['Close'].values]
            chart_volumes = [int(v) for v in history_subset['Volume'].values]

        # Prepare News Data (Convert timestamp to readable)
        from datetime import datetime
        news_list = data.get('news', [])
        for n in news_list:
            if 'providerPublishTime' in n:
                n['display_time'] = datetime.fromtimestamp(n['providerPublishTime'])

        # Cache it? 
        AnalysisCache.objects.update_or_create(
            symbol=symbol,
            defaults={'analysis_data': analysis_text}
        )
        
        # Prepare RSI
        current_rsi = history['RSI'].iloc[-1] if 'RSI' in history.columns and not history.empty else None
        rsi_status = "Neutral"
        if current_rsi:
            if current_rsi < 30: rsi_status = "Oversold"
            elif current_rsi > 70: rsi_status = "Overbought"

        info = data['info'].copy()
        for key in ['returnOnEquity', 'dividendYield', 'profitMargins']:
            if isinstance(info.get(key), (int, float)):
                info[key] = info[key] * 100

        context = {
            'symbol': symbol,
            'info': info,
            'analysis': analysis_text,
            'chart_labels': chart_labels,
            'chart_values': chart_values,
            'chart_volumes': chart_volumes,
            'current_rsi': current_rsi,
            'rsi_status': rsi_status,
            'news': news_list,
            'title': f"AI Analysis: {symbol}"
        }
        return render(request, 'stocks/analysis.html', context)
    except Exception as e:
        messages.error(request, f"Error analyzing {symbol}: {str(e)}")
        return redirect('stocks:dashboard')

@user_passes_test(admin_only)
def add_to_watchlist(request):
    if request.method == 'POST':
        symbol = request.POST.get('symbol').upper()
        category = request.POST.get('category', AssetCategory.STOCK)
        name = request.POST.get('name', '')
        
        if symbol:
            Watchlist.objects.get_or_create(
                symbol=symbol,
                defaults={'name': name, 'category': category}
            )
            messages.success(request, f"เพิ่ม {symbol} เข้าใน Watchlist แล้ว")
            
    return redirect('stocks:dashboard')

@user_passes_test(admin_only)
def delete_from_watchlist(request, pk):
    item = get_object_or_404(Watchlist, pk=pk)
    symbol = item.symbol
    item.delete()
    messages.success(request, f"ลบ {symbol} ออกจาก Watchlist แล้ว")
    return redirect('stocks:dashboard')

@user_passes_test(admin_only)
def portfolio_list(request):
    portfolio_items = Portfolio.objects.all()
    items = []
    import pandas_ta as ta
    
    total_market_value = 0
    total_gain_loss = 0
    
    for item in portfolio_items:
        try:
            t = yf.Ticker(item.symbol)
            hist = t.history(period="1mo")
            current_price = t.info.get('currentPrice') or t.info.get('regularMarketPrice') or t.info.get('previousClose')
            
            # RSI Calculation
            rsi_val = None
            if not hist.empty and len(hist) >= 14:
                rsi_series = ta.rsi(hist['Close'], length=14)
                if not rsi_series.empty:
                    rsi_val = rsi_series.iloc[-1]

            market_value = float(item.quantity) * float(current_price)
            cost_basis = float(item.quantity) * float(item.entry_price)
            gain_loss = market_value - cost_basis
            gain_loss_pct = (gain_loss / cost_basis * 100) if cost_basis > 0 else 0
            
            total_market_value += market_value
            total_gain_loss += gain_loss

            items.append({
                'obj': item,
                'current_price': current_price,
                'market_value': market_value,
                'gain_loss': gain_loss,
                'gain_loss_pct': gain_loss_pct,
                'rsi': rsi_val,
            })
        except:
            items.append({'obj': item, 'current_price': 'Error', 'market_value': 0, 'gain_loss': 0, 'gain_loss_pct': 0, 'rsi': None})

    context = {
        'items': items,
        'total_market_value': total_market_value,
        'total_gain_loss': total_gain_loss,
        'categories': AssetCategory.choices,
        'title': 'My Portfolio'
    }
    return render(request, 'stocks/portfolio.html', context)

@user_passes_test(admin_only)
def add_to_portfolio(request):
    if request.method == 'POST':
        symbol = request.POST.get('symbol').upper()
        name = request.POST.get('name', '')
        quantity = request.POST.get('quantity', 0)
        entry_price = request.POST.get('entry_price', 0)
        category = request.POST.get('category', AssetCategory.STOCK)
        
        if symbol:
            Portfolio.objects.update_or_create(
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

@user_passes_test(admin_only)
def delete_from_portfolio(request, pk):
    item = get_object_or_404(Portfolio, pk=pk)
    symbol = item.symbol
    item.delete()
    messages.success(request, f"ลบ {symbol} ออกจากพอร์ตแล้ว")
    return redirect('stocks:portfolio_list')
@user_passes_test(admin_only)
def recommendations(request):
    # List of high-quality Thai stocks to analyze for recommendations
    # Focusing on SET50/Dividend leaders for accuracy
    candidate_symbols = [
        # Large Caps (15)
        'PTT.BK', 'AOT.BK', 'CPALL.BK', 'ADVANC.BK', 'KBANK.BK', 
        'SCB.BK', 'SCC.BK', 'BDMS.BK', 'GULF.BK', 'INTUCH.BK',
        'CPN.BK', 'PTTEP.BK', 'TRUE.BK', 'HMPRO.BK', 'MINT.BK',
        # Mid Caps (15)
        'TISCO.BK', 'AP.BK', 'SIRI.BK', 'WHA.BK', 'AMATA.BK',
        'TASCO.BK', 'COM7.BK', 'MEGA.BK', 'TU.BK', 'CBG.BK',
        'OSP.BK', 'BCH.BK', 'JMT.BK', 'KCE.BK', 'HANA.BK'
    ]
    
    # We will pick a handful to show detailed metrics for the AI to pick from
    stock_previews = []
    
    # Selection logic: We'll fetch basic data for these and let AI decide the top 10
    # To keep it fast, we'll only fetch the most critical ones
    for sym in candidate_symbols[:30]:
        try:
            t = yf.Ticker(sym)
            inf = t.info
            roe = inf.get('returnOnEquity', 'N/A')
            dy = inf.get('dividendYield', 'N/A')
            npm = inf.get('profitMargins', 'N/A')
            vol = inf.get('volume', 'N/A')
            avg_vol = inf.get('averageVolume', 'N/A')
            
            if isinstance(roe, (int, float)): roe = roe * 100
            if isinstance(dy, (int, float)): dy = dy * 100
            if isinstance(npm, (int, float)): npm = npm * 100

            stock_previews.append({
                'symbol': sym,
                'name': inf.get('longName', sym),
                'pe': inf.get('trailingPE', 'N/A'),
                'pb': inf.get('priceToBook', 'N/A'),
                'roe': roe,
                'dy': dy,
                'npm': npm,
                'de': inf.get('debtToEquity', 'N/A'),
                'volume': vol,
                'avg_volume': avg_vol
            })
        except:
            continue

    # Generate the recommendation report using Gemini
    genai.configure(api_key=settings.GEMINI_API_KEY)
    
    # Dynamic Model Selection (Based on available models in the environment)
    model_names = [
        'gemini-2.0-flash', 
        'gemini-flash-latest', 
        'gemini-pro-latest', 
        'gemini-1.5-flash', 
        'gemini-pro'
    ]
    model = None
    for m_name in model_names:
        try:
            temp_model = genai.GenerativeModel(m_name)
            temp_model.generate_content("ping", generation_config={"max_output_tokens": 1})
            model = temp_model
            break
        except Exception:
            continue
    
    if not model:
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
        except:
            model = genai.GenerativeModel('gemini-pro')
    
    data_str = "\n".join([str(s) for s in stock_previews])
    
    prompt = f"""
    You are a professional Thai Stock Analyst. Based on the following data of Thai stocks (Large Cap and Mid Cap):
    {data_str}
    
    Please provide TWO separate rankings in your report (in Thai language):

    Part 1: 10 อันดับหุ้นไทยขนาดใหญ่แนะนำ (Top 10 Large Cap Thai Stock Recommendations)
    Part 2: 10 อันดับหุ้นไทยขนาดกลางแนะนำ (Top 10 Mid Cap Thai Stock Recommendations)

    For BOTH lists:
    1. Select the top 10 stocks based on Fundamental Strength (ROE, NPM) and Valuation (PE, PBV, Dividend).
    2. Specifically mention which ones have potential for 'Economic Profits' (High ROE vs typical cost of capital).
    3. **CRITICAL**: Include a deep 'Volume Analysis' for each selected stock (compare its 'volume' to 'avg_volume', interpreting buying/selling pressure or momentum).
    4. Provide a brief 'Why this stock?' reason, highlighting its cap size context and its current Volume trend.
    
    Format in beautiful Markdown for a professional web report. Use Sarabun style tone. Add an introductory section explaining the methodology.
    """
    
    try:
        response = model.generate_content(prompt)
        report_text = response.text
    except Exception as e:
        report_text = f"ไม่สามารถสร้างรายงานได้ในขณะนี้: {str(e)}"

    context = {
        'title': 'AI Stock Recommendations',
        'report': report_text,
        'stocks': stock_previews
    }
    return render(request, 'stocks/recommendations.html', context)

@login_required
def macro_economy(request):
    import json
    
    macro_items = [
        {'id': 'set', 'name': 'SET Index (ดัชนีหุ้นไทย)', 'symbol': '^SET', 'unit': 'Points', 'desc': 'ดัชนีตลาดหลักทรัพย์แห่งประเทศไทย บ่งบอกสภาวะตลาดโดยรวม ถ้าเพิ่มขึ้นแปลว่าเศรษฐกิจ/ตลาดหุ้นไทยดีขึ้น'},
        {'id': 'usdthb', 'name': 'USD/THB (อัตราแลกเปลี่ยนดอลลาร์/บาท)', 'symbol': 'USDTHB=X', 'unit': 'THB', 'desc': 'บาทอ่อนชงดีต่อภาคส่งออกและการท่องเที่ยว แต่อาจทำให้เงินทุนต่างชาติไหลออก'},
        {'id': 'gold', 'name': 'Gold (ราคาทองคำโลก GC=F)', 'symbol': 'GC=F', 'unit': 'USD/oz', 'desc': 'ทองคำเป็นสินทรัพย์ปลอดภัย (Safe Haven) มักจะขึ้นเมื่อเงินเฟ้อสูงหรือเศรษฐกิจมีความเสี่ยง'},
        {'id': 'wti', 'name': 'WTI Crude Oil (น้ำมันดิบ WTI)', 'symbol': 'CL=F', 'unit': 'USD/bbl', 'desc': 'ราคาน้ำมันจะกระทบโดยตรงต่อต้นทุนพลังงาน ค่าขนส่ง และอัตราเงินเฟ้อ'},
        {'id': 'brent', 'name': 'Brent Crude Oil (น้ำมันดิบเบรนท์)', 'symbol': 'BZ=F', 'unit': 'USD/bbl', 'desc': 'เป็นมาตรฐานราคาของฝั่งยุโรปและเอเชีย ซึ่งไทยมักมีต้นทุนแปรผันตามราคานี้'}
    ]
    
    data = []
    charts = {}
    
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
            
    # AI Analysis for Macro Economy
    genai.configure(api_key=settings.GEMINI_API_KEY)
    
    # Dynamic Model Selection
    model_names = [
        'gemini-2.0-flash', 
        'gemini-flash-latest', 
        'gemini-pro-latest', 
        'gemini-1.5-flash', 
        'gemini-pro'
    ]
    model = None
    for m_name in model_names:
        try:
            temp_model = genai.GenerativeModel(m_name)
            temp_model.generate_content("ping", generation_config={"max_output_tokens": 1})
            model = temp_model
            break
        except Exception:
            continue
    
    if not model:
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
        except:
            model = genai.GenerativeModel('gemini-pro')

    data_str = "\n".join([f"{d['name']}: {d['price']:.2f} ({d['change']:+.2f}%)" for d in data])
    prompt = f"""
    You are an expert Thai Macroeconomist. Based on the following current market data (which includes SET Index, USD/THB, Gold, and Crude Oil):
    {data_str}
    
    Please provide an 'Economic Overview & Strategy Analysis' report in Thai.
    1. Summarize the current situation based on these specific numbers (e.g. is the Baht strong/weak? is Oil trending up?).
    2. Analyze the impact of these figures on the Thai Economy and Thai Stock Market (SET Index).
    3. What sectors (e.g., Energy, Export, Tourism, Banking) will benefit or be negatively impacted by this current trend?
    4. Provide a brief actionable investment strategy for Thai investors based on this macroeconomic snapshot.
    
    Format in beautiful Markdown for a professional web report. Use Sarabun style tone.
    """
    
    try:
        response = model.generate_content(prompt)
        analysis_text = response.text
    except Exception as e:
        analysis_text = f"ไม่สามารถสร้างบทวิเคราะห์ได้ในขณะนี้: {str(e)}"

    context = {
        'title': 'Macro Economy & Commodities',
        'data': data,
        'analysis': analysis_text,
        'charts_json': json.dumps(charts)
    }
    return render(request, 'stocks/macro.html', context)
