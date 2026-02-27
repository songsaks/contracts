from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test, login_required
from django.contrib import messages
from django.conf import settings
from google import genai
from .models import Watchlist, AnalysisCache, AssetCategory, Portfolio
from .utils import get_stock_data, analyze_with_ai, calculate_trailing_stop
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
                try:
                    if isinstance(n['providerPublishTime'], str):
                        n['display_time'] = datetime.fromisoformat(n['providerPublishTime'].replace('Z', '+00:00'))
                    else:
                        n['display_time'] = datetime.fromtimestamp(n['providerPublishTime'])
                except Exception:
                    n['display_time'] = n['providerPublishTime']

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
        
        bs = data.get('balance_sheet')
        de_calculated = None
        if bs is not None and not bs.empty:
            try:
                col = bs.columns[0]
                tot_liab = bs.loc['Total Liabilities Net Minority Interest', col] if 'Total Liabilities Net Minority Interest' in bs.index else bs.loc['Total Liabilities', col]
                tot_eq = bs.loc['Stockholders Equity', col] if 'Stockholders Equity' in bs.index else bs.loc['Total Equity Gross Minority Interest', col]
                de_calculated = tot_liab / tot_eq
            except Exception:
                pass
                
        if de_calculated is not None:
            info['debtToEquity'] = de_calculated
        elif isinstance(info.get('debtToEquity'), (int, float)):
            info['debtToEquity'] = info['debtToEquity'] / 100

        fifty_two_week_high = history['High'].max() if not history.empty and 'High' in history.columns else None
        recent_resistance = history['High'].tail(20).max() if not history.empty and 'High' in history.columns else None
        recent_support = history['Low'].tail(20).min() if not history.empty and 'Low' in history.columns else None
        curr_price = history['Close'].iloc[-1] if not history.empty and 'Close' in history.columns else info.get('currentPrice', 0)
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
            
            # DCA Planner Logic (if loss is > 20%)
            dca_target_cost = None
            dca_qty = None
            dca_amount = None
            if gain_loss_pct <= -20:
                # Target adjusting average cost to just 10% loss
                target_cost = float(current_price) / 0.90
                entry_p = float(item.entry_price)
                if float(current_price) < target_cost < entry_p:
                    if (target_cost - float(current_price)) > 0:
                        dca_qty = float(item.quantity) * (entry_p - target_cost) / (target_cost - float(current_price))
                        dca_amount = dca_qty * float(current_price)
                        dca_target_cost = target_cost

            # Trailing Stop Logic using calculate_trailing_stop
            recent_high = hist['High'].max() if not hist.empty and 'High' in hist.columns else None
            ts_data = calculate_trailing_stop(
                symbol=item.symbol, 
                current_price=float(current_price), 
                entry_price=float(item.entry_price),
                highest_price_since_buy=recent_high,
                percent_trail=3.0
            )

            total_market_value += market_value
            total_gain_loss += gain_loss

            items.append({
                'obj': item,
                'current_price': current_price,
                'market_value': market_value,
                'gain_loss': gain_loss,
                'gain_loss_pct': gain_loss_pct,
                'rsi': rsi_val,
                'dca_target_cost': dca_target_cost,
                'dca_qty': dca_qty,
                'dca_amount': dca_amount,
                'trailing_stop_data': ts_data
            })
        except:
            items.append({
                'obj': item, 'current_price': 'Error', 'market_value': 0, 
                'gain_loss': 0, 'gain_loss_pct': 0, 'rsi': None,
                'dca_target_cost': None, 'dca_qty': None, 'dca_amount': None, 'trailing_stop_data': None
            })

    ai_analysis = None
    if request.GET.get('analyze') == 'true' and items:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        model_names = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
        model_name_to_use = 'gemini-pro'
        for m in model_names:
            try:
                client.models.generate_content(
                    model=m,
                    contents='ping'
                )
                model_name_to_use = m
                break
            except Exception:
                continue

        port_data = []
        for it in items:
            port_data.append(f"{it['obj'].symbol}: {it['obj'].quantity} units @ {it['obj'].entry_price} (Current: {it['current_price']}, P/L: {it['gain_loss_pct']:.2f}%, RSI: {it['rsi']})")
        port_str = "\n".join(port_data)
        
        # --- PyPortfolioOpt Integration ---
        # Get historical data for all symbols to calculate correlation & efficient frontier
        symbols = [it['obj'].symbol for it in items if it['obj'].quantity > 0]
        ppo_advice = ""
        if len(symbols) > 1:
            try:
                import pandas as pd
                from pypfopt import expected_returns, risk_models
                from pypfopt.efficient_frontier import EfficientFrontier

                # Fetch 1 yr of closing prices for correlation
                data = yf.download(symbols, period="1y")
                
                if isinstance(data.columns, pd.MultiIndex):
                    data = data['Close']
                elif 'Close' in data:
                    data = data[['Close']]
                else:
                    data = pd.DataFrame() # Fallback

                # Deal with missing values
                data = data.dropna(how="all")
                data = data.ffill().bfill()
                
                # Make sure data is not flat (in case of single symbol fallback bug, though handled by len(symbols) > 1)
                if data.empty or len(data.columns) < 2:
                    raise ValueError("Not enough overlapping price data to calculate correlation.")

                mu = expected_returns.mean_historical_return(data)
                S = risk_models.sample_cov(data)
                
                ef = EfficientFrontier(mu, S)
                
                # Optimise for maximal Sharpe ratio
                try:
                    raw_weights = ef.max_sharpe()
                except Exception as ef_e:
                    # Fallback to equal weighting if max_sharpe fails (e.g. non-convex/all negative returns)
                    raw_weights = {sym: 1.0/len(symbols) for sym in symbols}
                    
                cleaned_weights = ef.clean_weights()
                
                # Compare current weights to optimal weights
                portfolio_total = sum(it['market_value'] for it in items)
                current_weights = {it['obj'].symbol: (it['market_value'] / portfolio_total if portfolio_total > 0 else 0) for it in items}
                
                ppo_advice += "\n[PyPortfolioOpt Portfolio Optimization (Max Sharpe)]\n"
                for sym in symbols:
                    c_weight = current_weights.get(sym, 0) * 100
                    o_weight = cleaned_weights.get(sym, 0) * 100
                    action = "Hold"
                    if o_weight > c_weight + 5: action = "Buy/Increase Weight"
                    elif o_weight < c_weight - 5: action = "Sell/Reduce Weight"
                    ppo_advice += f"- {sym}: Current Weight = {c_weight:.1f}%, Optimal Weight = {o_weight:.1f}% -> Model says: {action}\n"
                
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
            
            # Strip any residual markdown blocks if AI disobeys
            if ai_analysis.startswith("```markdown"):
                ai_analysis = ai_analysis[len("```markdown"):].strip()
            if ai_analysis.endswith("```"):
                ai_analysis = ai_analysis[:-3].strip()
        except Exception as e:
            ai_analysis = f"ไม่สามารถวิเคราะห์พอร์ตได้ในขณะนี้: {str(e)}"

    context = {
        'items': items,
        'total_market_value': total_market_value,
        'total_gain_loss': total_gain_loss,
        'categories': AssetCategory.choices,
        'title': 'My Portfolio',
        'ai_analysis': ai_analysis
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
    import random
    from datetime import date

    # Pool of 100 high-quality Thai stocks (SET100 focus)
    full_pool = [
        'ADVANC.BK', 'AOT.BK', 'AWC.BK', 'BBL.BK', 'BDMS.BK', 'BEM.BK', 'BGRIM.BK', 'BH.BK', 'BJC.BK', 'BLA.BK', 
        'BPP.BK', 'BTS.BK', 'CBG.BK', 'CENTEL.BK', 'CHG.BK', 'CK.BK', 'CKP.BK', 'COM7.BK', 'CPALL.BK', 'CPAXT.BK', 
        'CPF.BK', 'CPN.BK', 'CRC.BK', 'DELTA.BK', 'EA.BK', 'EGCO.BK', 'EPG.BK', 'ERW.BK', 'FORTH.BK', 'GLOBAL.BK', 
        'GPSC.BK', 'GULF.BK', 'HMPRO.BK', 'ICHI.BK', 'INTUCH.BK', 'IRPC.BK', 'ITC.BK', 'IVL.BK', 'JMART.BK', 'JMT.BK', 
        'KBANK.BK', 'KCE.BK', 'KEX.BK', 'KKP.BK', 'KTB.BK', 'KTC.BK', 'LH.BK', 'MBK.BK', 'MEGA.BK', 'MINT.BK', 
        'MTC.BK', 'NEX.BK', 'OR.BK', 'ORI.BK', 'OSP.BK', 'PLANB.BK', 'PRM.BK', 'PSL.BK', 'PTG.BK', 'PTT.BK', 
        'PTTEP.BK', 'PTTGC.BK', 'QH.BK', 'RATCH.BK', 'RCL.BK', 'ROJNA.BK', 'RS.BK', 'SABINA.BK', 'SAWAD.BK', 'SCB.BK', 
        'SCC.BK', 'SCGP.BK', 'SINGER.BK', 'SIRI.BK', 'SPALI.BK', 'SPRC.BK', 'STA.BK', 'STEC.BK', 'STGT.BK', 'SUPER.BK', 
        'TASCO.BK', 'TCAP.BK', 'THANI.BK', 'THCOM.BK', 'THG.BK', 'TISCO.BK', 'TKN.BK', 'TLI.BK', 'TOA.BK', 'TOP.BK', 
        'TPIPL.BK', 'TPIPP.BK', 'TQM.BK', 'TRUE.BK', 'TTA.BK', 'TTB.BK', 'TU.BK', 'VGI.BK', 'WHA.BK', 'WHAUP.BK'
    ]
    
    # Use current date as a seed so the selection changes daily
    # but remains stable within the same day for consistent analysis.
    today_str = date.today().strftime("%Y%m%d")
    random.seed(today_str)
    candidate_symbols = random.sample(full_pool, min(20, len(full_pool)))
    
    # Reset random seed so it doesn't affect other parts of the app
    random.seed()
    
    # We will pick a handful to show detailed metrics for the AI to pick from
    stock_previews = []
    
    # Selection logic: We'll fetch basic data for these and let AI decide the top 10
    # To keep it fast, we'll only fetch the most critical ones
    for sym in candidate_symbols[:30]:
        try:
            t = yf.Ticker(sym)
            inf = t.info
            
            de = 'N/A'
            try:
                bs = t.quarterly_balance_sheet if not t.quarterly_balance_sheet.empty else t.balance_sheet
                if not bs.empty:
                    col = bs.columns[0]
                    tot_liab = bs.loc['Total Liabilities Net Minority Interest', col] if 'Total Liabilities Net Minority Interest' in bs.index else bs.loc['Total Liabilities', col]
                    tot_eq = bs.loc['Stockholders Equity', col] if 'Stockholders Equity' in bs.index else bs.loc['Total Equity Gross Minority Interest', col]
                    de = tot_liab / tot_eq
            except Exception:
                pass
            
            if de == 'N/A':
                de = inf.get('debtToEquity', 'N/A')
                if isinstance(de, (int, float)): de = de / 100
            elif isinstance(de, (int, float)):
                de = round(de, 2)
            
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
                'de': de,
                'volume': vol,
                'avg_volume': avg_vol
            })
        except:
            continue

    # Generate the recommendation report using Gemini
    report_text = None
    if request.GET.get('analyze') == 'true' and stock_previews:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model_names = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
        model = None
        for m in model_names:
            try:
                temp_model = genai.GenerativeModel(m)
                temp_model.generate_content("ping")
                model = temp_model
                break
            except Exception:
                continue
        if not model:
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
        IMPORTANT RULES:
        1. DO NOT include any conversational preamble or outro (e.g. "Okay, here's a professional Thai stock...", "Explanation of Choices:"). 
        2. Output ONLY the raw markdown text.
        3. DO NOT wrap the output in ```markdown code blocks. Start immediately with the analysis headings.
        """
        
        try:
            response = model.generate_content(prompt)
            report_text = response.text
            
            # Strip any residual markdown blocks if AI disobeys
            if report_text.startswith("```markdown"):
                report_text = report_text[len("```markdown"):].strip()
            if report_text.endswith("```"):
                report_text = report_text[:-3].strip()
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
    analysis_text = None
    if request.GET.get('analyze') == 'true' and data:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        model_names = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
        model_name_to_use = 'gemini-pro'
        for m in model_names:
            try:
                client.models.generate_content(
                    model=m,
                    contents='ping'
                )
                model_name_to_use = m
                break
            except Exception:
                continue

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
        IMPORTANT RULES:
        1. DO NOT include any conversational preamble or outro (e.g. "Okay, here's an analysis...", "Explanation of Choices:"). 
        2. Output ONLY the raw markdown text.
        3. DO NOT wrap the output in ```markdown code blocks. Start immediately with the analysis headings.
        """
        
        try:
            response = client.models.generate_content(
                model=model_name_to_use,
                contents=prompt
            )
            analysis_text = response.text

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
        'charts_json': json.dumps(charts)
    }
    return render(request, 'stocks/macro.html', context)

@user_passes_test(admin_only)
def momentum_scanner(request):
    """
    Globally scans SET100 roughly matching Mark Minervini Trend Template.
    Requires significant processing time, might be better offloaded in prod,
    but done synchronously here for demonstration.
    """
    # SET100 + MAI 30 candidates
    scan_symbols = [
        # SET100 (Approximate current representation)
        "ADVANC", "AOT", "AWC", "BBL", "BDMS", "BEM", "BGRIM", "BH", "BJC", "BTS",
        "CBG", "CENTEL", "CHG", "CK", "CKP", "COM7", "CPALL", "CPF", "CPN", "CRC",
        "DELTA", "EA", "EGCO", "GLOBAL", "GPSC", "GULF", "HMPRO", "INTUCH", "IRPC", "IVL",
        "JMART", "JMT", "KBANK", "KCE", "KTB", "KTC", "LH", "MINT", "MTC", "OR",
        "OSP", "PTT", "PTTEP", "PTTGC", "RATCH", "SAWAD", "SCB", "SCC", "SCGP", "SPALI",
        "STA", "STARK", "STGT", "TCAP", "TISCO", "TOP", "TRUE", "TTB", "TU", "WHA",
        "AMATA", "BAM", "BANPU", "BAY", "BCH", "BLA", "BPP", "DOHOME", "FORTH", "GUNKUL",
        "ICHI", "KEX", "KKP", "MEGA", "ONEE", "PLANB", "PSL", "PTG", "QH", "RBF",
        "RS", "SABINA", "SINGER", "SIRI", "SPRC", "STEC", "SYNEX", "THANI", "TIDLOR", "TIPH",
        "TKN", "TLI", "TQM", "TSTH", "TTW", "VGI", "BCP", "NYT",

        # MAI (30 popular representation)
        "AU", "SPA", "DITTO", "BE8", "BBIK", "IIG", "SABUY", "SECURE", "JDF", "PROEN",
        "ZIGA", "XPG", "SMD", "TACC", "TMC", "TPCH", "TACC", "FPI", "FSMART", "NDR",
        "NETBAY", "BIZ", "BROOK", "COLOR", "CHO", "D", "KUN", "MVP", "SE", "UKEM"
    ]
    
    candidates = []
    
    # We only scan if requested to avoid huge load on every page visit
    if request.method == "POST" or request.GET.get('scan') == 'true':
        import pandas_ta as ta
        for symbol in scan_symbols:
            try:
                df = yf.download(f"{symbol}.BK", period="1y", interval="1d", progress=False)
                
                if df.empty:
                    continue
                    
                if isinstance(df.columns, pd.MultiIndex):
                    # Flatten the columns by dropping the ticker level
                    df.columns = df.columns.droplevel(1)
                
                df = df.dropna(subset=['Close', 'High'])
                if len(df) < 150:
                    continue
                    
                df['EMA50'] = ta.ema(df['Close'], length=50)
                df['EMA150'] = ta.ema(df['Close'], length=150)
                df['EMA200'] = ta.ema(df['Close'], length=200)
                df['RSI'] = ta.rsi(df['Close'], length=14)
                
                # ADX Calculation
                adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                if adx_df is not None:
                    df = pd.concat([df, adx_df], axis=1)
                
                # Money Flow Index (MFI)
                mfi = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                df['MFI'] = mfi
                
                # Relative Volume (RVOL) - Current Volume vs 20-day Average
                avg_vol_20 = df['Volume'].rolling(window=20).mean()
                df['RVOL'] = df['Volume'] / avg_vol_20
                
                # Extract last values
                last_row = df.iloc[-1]
                
                current_price = float(last_row['Close'].iloc[0]) if isinstance(df['Close'], pd.DataFrame) else float(last_row['Close'])
                year_high = float(df['High'].max().iloc[0]) if isinstance(df['High'], pd.DataFrame) else float(df['High'].max())
                
                ema50 = float(last_row['EMA50']) if pd.notna(last_row['EMA50']) else 0
                ema150 = float(last_row['EMA150']) if pd.notna(last_row['EMA150']) else 0
                ema200 = float(last_row['EMA200']) if pd.notna(last_row['EMA200']) else 0
                rsi = float(last_row['RSI']) if pd.notna(last_row['RSI']) else 0
                adx = float(last_row['ADX_14']) if 'ADX_14' in last_row and pd.notna(last_row['ADX_14']) else 0
                mfi_val = float(last_row['MFI']) if pd.notna(last_row['MFI']) else 0
                rvol = float(last_row['RVOL']) if pd.notna(last_row['RVOL']) else 1.0
                
                # --- INTEGRATED SCORING LOGIC (0-100) ---
                integrated_score = 0
                
                # 1. Trend Quality (30%) - EMA Alignment & Price above EMA200
                trend_points = 0
                if current_price > ema200: trend_points += 15
                if ema50 > ema150 > ema200: trend_points += 15
                integrated_score += trend_points
                
                # 2. Price Momentum (20%) - RSI 60-75 & distance from high
                mom_points = 0
                if 60 <= rsi <= 75: mom_points += 10
                gap_to_high = ((year_high - current_price) / current_price) * 100
                if gap_to_high <= 15: mom_points += 10
                integrated_score += mom_points
                
                # 3. Relative Volume (RVOL) (30%) - "Large Hands" Action
                # If RVOL > 1.5 (Volume is 150% of avg), high points
                if rvol >= 2.0: integrated_score += 30
                elif rvol >= 1.5: integrated_score += 20
                elif rvol >= 1.0: integrated_score += 10
                
                # 4. Money Flow Index (MFI) (20%) - Positive Net Flow
                # MFI > 50 means energy is positive
                if mfi_val >= 60: integrated_score += 20
                elif mfi_val >= 50: integrated_score += 10

                # Base filter (Trend Template)
                is_uptrend = (current_price > ema150) and (ema150 > ema200)
                near_high = (current_price >= year_high * 0.70) # Relaxed slightly for better list
                
                if is_uptrend and near_high:
                    # Fetching sector only for candidates
                    sector = "Unknown"
                    try:
                        ticker = yf.Ticker(f"{symbol}.BK")
                        sector = ticker.info.get('sector', 'Other')
                    except:
                        pass
                        
                    candidates.append({
                        'symbol': symbol,
                        'symbol_bk': f"{symbol}.BK",
                        'sector': sector,
                        'price': round(current_price, 2),
                        'rsi': round(rsi, 2),
                        'adx': round(adx, 2),
                        'mfi': round(mfi_val, 2),
                        'rvol': round(rvol, 2),
                        'technical_score': int(integrated_score),
                        'year_high': round(year_high, 2),
                        'upside_to_high': round(gap_to_high, 2)
                    })
            except Exception as e:
                print(f"Error scanning {symbol}: {e}")
                continue
                
        # Sort candidates by "technical score" descending (highest score first)
        candidates.sort(key=lambda x: x['technical_score'], reverse=True)
                
    ai_analysis = None
    if candidates and request.GET.get('analyze') == 'true':
        symbols_list = [c['symbol'] for c in candidates]
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            model_names = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
            model_name_to_use = 'gemini-pro'
            for m in model_names:
                try:
                    client.models.generate_content(model=m, contents='ping')
                    model_name_to_use = m
                    break
                except Exception:
                    continue

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
        'has_scanned': request.method == "POST" or request.GET.get('scan') == 'true'
    }
    return render(request, 'stocks/momentum.html', context)
