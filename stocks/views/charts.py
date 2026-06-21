from .base import * 

@login_required
def stock_chart(request, symbol):
    market = request.GET.get('market', 'SET')
    context = {
        'symbol': symbol.upper(),
        'market': market,
    }
    return render(request, 'stocks/stock_chart.html', context)

@login_required
def chart_ai_analyze_ajax(request, symbol):
    import json
    from django.http import JsonResponse
    from django.conf import settings
    from google import genai
    from django.views.decorators.csrf import csrf_exempt
    from django.utils import timezone
    from .models import AnalysisCache, PrecisionScanCandidate, USSepaCandidate

    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=400)

    try:
        data = json.loads(request.body)
        market = data.get('market', '')
        price = data.get('price', 'N/A')
        trend = data.get('trend', 'N/A')
        signals = data.get('signals', [])
        force_refresh = data.get('force_refresh', False)
        active_indicators_data = data.get('active_indicators_data', 'ไม่มีข้อมูล (ผู้ใช้ปิด Indicator ทั้งหมด)')
        
        # Check cache if not forcing refresh
        if not force_refresh:
            cache_entry = AnalysisCache.objects.filter(user=request.user, symbol=symbol).first()
            if cache_entry and cache_entry.last_updated.date() == timezone.now().date():
                return JsonResponse({'result': cache_entry.analysis_data, 'cached': True})

        signal_text = ", ".join([s.get('type', '') for s in signals]) if signals else "ไม่มีสัญญาณซื้อขายล่าสุด"

        # ====== Fetch SEPA Data ======
        sepa_info = ""
        try:
            if market == 'US':
                sepa_cand = USSepaCandidate.objects.filter(user=request.user, symbol=symbol).order_by('-scan_run').first()
            else:
                sepa_cand = PrecisionScanCandidate.objects.filter(user=request.user, symbol=symbol, market='SET').order_by('-scan_run').first()
                
            if sepa_cand:
                eps_g = getattr(sepa_cand, 'eps_growth', 0.0) or 0.0
                rev_g = getattr(sepa_cand, 'rev_growth', 0.0) or 0.0
                rs_rt = getattr(sepa_cand, 'rs_rating', 0) or 0
                vcp   = getattr(sepa_cand, 'vcp_setup', False)
                stg2  = getattr(sepa_cand, 'stage2', False)
                adx_v = getattr(sepa_cand, 'adx', 0) or 0
                dist  = getattr(sepa_cand, 'upside_to_high', 0.0) or 0.0

                # Calculate roughly SEPA Score as in minervini_sepa_scanner
                sc = 0
                if vcp:
                    sc += 30
                    sc += int(max(0, (10 - min(getattr(sepa_cand, 'vcp_tightness', 0) or 0, 10)) * 2))
                    sc += min(getattr(sepa_cand, 'vcp_contractions', 0) or 0, 5) * 3
                if getattr(sepa_cand, 'vcp_vdu', False) or getattr(sepa_cand, 'vdu_near_zone', False):
                    sc += 20
                if getattr(sepa_cand, 'pocket_pivot', False):
                    sc += 10
                sc += int(rs_rt * 0.7)
                if adx_v >= 25: sc += 10
                elif adx_v >= 15: sc += 5
                
                if vcp:
                    if dist <= 5: sc += 10
                    elif dist <= 10: sc += 5
                    elif dist > 15: sc -= 5
                        
                if eps_g >= 50: sc += 20
                elif eps_g >= 25: sc += 12
                elif eps_g >= 10: sc += 5
                
                if rev_g >= 50: sc += 10
                elif rev_g >= 25: sc += 6
                
                sepa_info = f"""
ข้อมูล SEPA Scanner (Minervini) ปัจจุบัน:
- Stage 2 Trend: {'Yes' if stg2 else 'No'}
- VCP Setup: {'Yes' if vcp else 'No'}
- RS Rating: {rs_rt}
- EPS Growth: {eps_g}% / Rev Growth: {rev_g}%
- SEPA Score: {sc}
"""
        except Exception as e:
            sepa_info = f"<!-- SEPA Fetch Error: {e} -->"

        # ====== Fetch Fundamental & Business Data ======
        fundamentals_info = ""
        volume_profile_info = ""
        price_pattern_info = ""
        try:
            import yfinance as yf
            import numpy as np
            yf_symbol = '^SET.BK' if symbol == 'SET' else (symbol + '.BK' if market == 'SET' else symbol)
            ticker = yf.Ticker(yf_symbol)
            info = ticker.info
            
            biz_summary = info.get('longBusinessSummary', 'ไม่มีข้อมูลคำอธิบายธุรกิจ')
            sector = info.get('sector', 'N/A')
            industry = info.get('industry', 'N/A')
            
            roe = info.get('returnOnEquity', None)
            roe_str = f"{roe * 100:.2f}%" if roe is not None else "N/A"
            
            roa = info.get('returnOnAssets', None)
            roa_str = f"{roa * 100:.2f}%" if roa is not None else "N/A"
            
            pe = info.get('trailingPE', 'N/A')
            pb = info.get('priceToBook', 'N/A')
            
            div_yield = info.get('dividendYield', None)
            div_str = "N/A"
            if div_yield is not None:
                try:
                    val = float(div_yield)
                    if val > 100.0:
                        val = val / 100.0
                    elif val < 1.0:
                        val = val * 100.0
                    div_str = f"{val:.2f}%"
                except Exception:
                    div_str = f"{div_yield}"
            
            rev_latest = "N/A"
            net_income_latest = "N/A"
            try:
                financials = ticker.financials
                if financials is not None and not financials.empty:
                    rev_row = [r for r in financials.index if 'Revenue' in r or 'Total Revenue' in r]
                    if rev_row:
                        val = financials.loc[rev_row[0]].iloc[0]
                        rev_latest = f"{val:,.2f}" if not isinstance(val, str) else val
                    
                    net_inc_row = [r for r in financials.index if 'Net Income' in r]
                    if net_inc_row:
                        val = financials.loc[net_inc_row[0]].iloc[0]
                        net_income_latest = f"{val:,.2f}" if not isinstance(val, str) else val
            except Exception:
                pass
                
            fundamentals_info = f"""
ข้อมูลปัจจัยพื้นฐาน (Fundamental Data) จาก yfinance:
- กลุ่มอุตสาหกรรม/หมวดธุรกิจ: {sector} / {industry}
- คำอธิบายธุรกิจหลัก: {biz_summary}
- ROE (Return on Equity): {roe_str}
- ROA (Return on Assets): {roa_str}
- P/E Ratio: {pe} | P/BV Ratio: {pb}
- อัตราปันผล (Dividend Yield): {div_str}
- ผลประกอบการล่าสุด: รายได้รวม ~ {rev_latest} | กำไรสุทธิ ~ {net_income_latest}
"""
            
            # --- Calculate Volume Profile & Price Patterns ---
            try:
                df = ticker.history(period="1y", interval="1d")
                if df is not None and not df.empty:
                    # Resolve MultiIndex if any
                    if isinstance(df.columns, np.ndarray) or isinstance(df.columns, list) or hasattr(df.columns, 'levels'):
                        if hasattr(df.columns, 'get_level_values'):
                            df.columns = df.columns.get_level_values(0)
                    df.columns = [str(c).capitalize() for c in df.columns]
                    df = df.dropna(subset=['Close', 'Volume'])
                    
                    if len(df) >= 30:
                        hist_len = min(len(df), 120)
                        sub_df = df.tail(hist_len)
                        closes = sub_df['Close'].values
                        volumes = sub_df['Volume'].values
                        
                        min_p = float(closes.min())
                        max_p = float(closes.max())
                        
                        # Calculate POC, VAH, VAL
                        bins = np.linspace(min_p, max_p, 11)
                        bin_vols = np.zeros(10)
                        for i in range(10):
                            mask = (closes >= bins[i]) & (closes < bins[i+1])
                            bin_vols[i] = volumes[mask].sum()
                        mask_max = (closes == max_p)
                        if mask_max.any() and len(bin_vols) > 0:
                            bin_vols[-1] += volumes[mask_max].sum()
                            
                        max_vol_idx = int(np.argmax(bin_vols))
                        poc_price = (bins[max_vol_idx] + bins[max_vol_idx+1]) / 2.0
                        
                        total_volume = bin_vols.sum()
                        target_va_vol = total_volume * 0.70
                        va_indices = {max_vol_idx}
                        current_va_vol = bin_vols[max_vol_idx]
                        
                        while current_va_vol < target_va_vol and len(va_indices) < 10:
                            next_left = min(va_indices) - 1
                            next_right = max(va_indices) + 1
                            left_vol = bin_vols[next_left] if next_left >= 0 else -1
                            right_vol = bin_vols[next_right] if next_right < 10 else -1
                            
                            if left_vol > right_vol:
                                va_indices.add(next_left)
                                current_va_vol += left_vol
                            elif right_vol >= 0:
                                va_indices.add(next_right)
                                current_va_vol += right_vol
                            else:
                                break
                                
                        vah_price = bins[max(va_indices) + 1]
                        val_price = bins[min(va_indices)]
                        
                        volume_profile_info = f"""
ข้อมูล Volume Profile (ย้อนหลัง {hist_len} วันทำการ):
- Point of Control (POC): {poc_price:.2f} (ระดับราคาที่มีปริมาณการซื้อขายหนาแน่นสะสมมากที่สุด)
- Value Area High (VAH): {vah_price:.2f}
- Value Area Low (VAL): {val_price:.2f}
"""

                        # Price Patterns
                        detected_patterns = []
                        
                        # 1. VCP Detection
                        if len(df) >= 60:
                            p3 = df['Close'].tail(20)
                            p2 = df['Close'].iloc[-40:-20]
                            p1 = df['Close'].iloc[-60:-40]
                            
                            rng3 = (p3.max() - p3.min()) / p3.mean()
                            rng2 = (p2.max() - p2.min()) / p2.mean()
                            rng1 = (p1.max() - p1.min()) / p1.mean()
                            
                            if rng1 > rng2 > rng3 and rng3 < 0.10:
                                detected_patterns.append("Volatility Contraction Pattern (VCP) - ตรวจพบรูปแบบการบีบอัดของความผันผวนของราคา (Contractions)")
                                
                        # 2. Double Bottom Detection
                        if len(df) >= 40:
                            mins = []
                            for idx in range(5, len(closes)-5):
                                if closes[idx] == min(closes[idx-5:idx+6]):
                                    mins.append((idx, closes[idx]))
                            
                            db_found = False
                            support_level = 0.0
                            for i in range(len(mins)):
                                for j in range(i+1, len(mins)):
                                    idx1, val1 = mins[i]
                                    idx2, val2 = mins[j]
                                    if abs(idx1 - idx2) >= 10 and abs(val1 - val2) / val1 <= 0.03:
                                        db_found = True
                                        support_level = (val1 + val2) / 2.0
                                        break
                                if db_found:
                                    break
                                    
                            if db_found:
                                detected_patterns.append(f"Double Bottom / Support Zone - ตรวจพบแนวรับสำคัญแบบคู่ฐาน (Double Bottom / Support Zone) แถวๆ ระดับราคา {support_level:.2f}")
                                
                        recent_max = float(df['High'].tail(20).max())
                        if float(closes[-1]) >= recent_max * 0.98:
                            detected_patterns.append("ราคาเคลื่อนไหวใกล้ระดับสูงสุดของรอบ 20 วัน (20-day High Breakout Setup)")
                        elif float(closes[-1]) <= float(df['Low'].tail(20).min()) * 1.02:
                            detected_patterns.append("ราคาลงมาเคลี่อนไหวใกล้ระดับต่ำสุดของรอบ 20 วัน (20-day Low Breakdown Risk)")

                        if not detected_patterns:
                            detected_patterns.append("ไม่พบรูปแบบราคา Pattern เด่นชัดในระยะสั้น (ราคากำลังสร้างฐานสะสมกำลัง)")
                            
                        price_pattern_info = "รูปแบบราคาที่ตรวจพบ (Price Pattern Detection):\n" + "\n".join([f"- {pat}" for pat in detected_patterns])
            except Exception as e_calc:
                volume_profile_info = f"<!-- Volume Profile Calc Error: {e_calc} -->"

        except Exception as e:
            fundamentals_info = f"<!-- Fundamentals Fetch Error: {e} -->"

        prompt = f"""
คุณคือ AI ผู้ช่วยนักวิเคราะห์หุ้นระดับสากลและผู้เชี่ยวชาญด้านกลยุทธ์การลงทุน (ทั้งด้าน Technical, Quantitative และ Fundamental)
โปรดทำการวิเคราะห์เชิงลึกเกี่ยวกับหุ้น {symbol} (ตลาด: {market}) โดยสรุปเป็นภาษาไทยให้สวยงาม กระชับ ครอบคลุมหัวข้อต่อไปนี้:

1. **แนะนำบริษัทและการวิเคราะห์เชิงธุรกิจ (Business Overview & Profile)**: อธิบายสั้นๆ ว่าบริษัททำอะไร วิเคราะห์ความแข็งแกร่งเชิงธุรกิจ ปัจจัยบวก/ลบ
2. **การวิเคราะห์ทางเทคนิค (Technical & Indicator Analysis)**: วิเคราะห์จากราคาล่าสุด ({price}), แนวโน้ม ({trend}), สัญญาณที่เกิดขึ้น ({signal_text}) และข้อมูล Indicator ที่เปิดอยู่ตอนนี้:
{active_indicators_data}

โปรดรวมข้อมูลเชิงลึกเหล่านี้ในการวิเคราะห์ทางเทคนิคด้วย:
{volume_profile_info}
{price_pattern_info}

3. **การวิเคราะห์ปัจจัยพื้นฐานและเศรษฐกิจ (Fundamental, Financial & Economic)**: วิเคราะห์รายได้ กำไร อัตราผลตอบแทนอย่าง ROE, ROI/ROA และความเสี่ยงหรือโอกาสจากสภาวะเศรษฐกิจในปัจจุบัน
4. **คำแนะนำเชิงกลยุทธ์ (Strategic Recommendations)**: สรุปคำแนะนำที่ชัดเจน (ซื้อเพิ่ม / ถือ / ขายตัดขาดทุน / รอจังหวะ) พร้อมอธิบายเหตุผลประกอบ

{sepa_info}
{fundamentals_info}

จัดรูปแบบผลลัพธ์ด้วย Markdown ที่อ่านง่าย สวยงาม น่าเชื่อถือ และจำกัดความยาวของเนื้อหาแต่ละส่วนให้สั้นกระชับเข้าใจง่าย
"""

        api_key = getattr(settings, "GEMINI_API_KEY", None)
        if not api_key:
            return JsonResponse({'error': 'No GEMINI_API_KEY configured'}, status=500)

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )

        analysis_result = response.text
        
        # Save to Cache
        cache_entry, created = AnalysisCache.objects.get_or_create(
            user=request.user,
            symbol=symbol,
            defaults={'analysis_data': analysis_result}
        )
        if not created:
            cache_entry.analysis_data = analysis_result
            cache_entry.save()

        return JsonResponse({'result': analysis_result, 'cached': False})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)



@login_required
def stock_chart_data(request, symbol):
    import json as _json

    import numpy as _np
    import pandas as _pd
    import yfinance as _yf
    from django.http import JsonResponse as _JR

    symbol = symbol.upper()
    market = request.GET.get('market', 'SET')
    period = request.GET.get('period', '1y')
    interval = request.GET.get('interval', '')

    # Append .BK for SET stocks, mapping index SET to ^SET
    if market == 'SET':
        yf_symbol = '^SET.BK' if symbol == 'SET' else symbol + '.BK'
    else:
        yf_symbol = symbol

    # ── Intraday / Custom interval mapping ─────────────────────────
    if interval == '1wk':
        is_intraday = False
        download_interval = '1wk'
        download_period = '10y'
    elif interval == '1mo':
        is_intraday = False
        download_interval = '1mo'
        download_period = 'max'
    elif interval == '1d':
        is_intraday = False
        download_interval = '1d'
        download_period = '2y' if period in ('1y', '2y') else '1y'
    else:
        # Fallback to existing logic based on period
        INTRADAY_MAP = {'1d': '5m', '5d': '15m', '1mo_h': '1h'}
        intraday_interval = INTRADAY_MAP.get(period)
        is_intraday = intraday_interval is not None

        if is_intraday:
            download_period  = period if period != '1mo_h' else '1mo'
            download_interval = intraday_interval
        else:
            download_period  = '2y' if period in ('1y', '2y') else '1y'
            download_interval = '1d'

    def _safe_val(val, default=0.0):
        try:
            v = float(val)
            if _np.isnan(v) or _np.isinf(v):
                return default
            return v
        except:
            return default

    try:
        df = _yf.download(yf_symbol, period=download_period, interval=download_interval,
                          auto_adjust=True, progress=False, group_by='column')
        
        if df is None or df.empty:
            return _JR({'error': f'ไม่พบข้อมูลสำหรับ {yf_symbol} (yfinance returned empty)'}, status=404)

        # 1. จัดการ MultiIndex (yfinance 0.2.x คืน (Price,Ticker) หรือ (Ticker,Price))
        if isinstance(df.columns, _pd.MultiIndex):
            _pf = {'Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close'}
            if any(v in _pf for v in df.columns.get_level_values(0)):
                df.columns = df.columns.get_level_values(0)
            else:
                df.columns = df.columns.get_level_values(1)

        # 2. ปรับชื่อคอลัมน์ให้เป็นมาตรฐาน (Standardize Capitalization)
        df.columns = [str(c).capitalize() for c in df.columns]
        
        # คืนค่าคอลัมน์ที่จำเป็น (Handle Adj Close/Close redundancy)
        if 'Adj close' in df.columns:
            df.rename(columns={'Adj close': 'Close'}, inplace=True)
        elif 'Adj close' not in df.columns and 'Close' not in df.columns:
            # บางกรณี yfinance คืนค่า 'Regular market price' หรืออื่นๆ
            potential_close = [c for c in df.columns if 'close' in c.lower()]
            if potential_close:
                df.rename(columns={potential_close[0]: 'Close'}, inplace=True)

        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing = [c for c in required if c not in df.columns]
        if missing:
            return _JR({'error': f'ไม่สามารถดึงข้อมูลที่จำเป็นได้: {missing}'}, status=500)

        df = df[required].copy()
        
        # 3. จัดการข้อมูลว่างเฉพาะจุด (หลีกเลี่ยงการ dropna ล้างทั้งแถว)
        # เติมค่าว่างด้วยวิธี ffill สำหรับราคาส่วน volume เป็น 0
        df[['Open', 'High', 'Low', 'Close']] = df[['Open', 'High', 'Low', 'Close']].ffill()
        df['Volume'] = df['Volume'].fillna(0)
        
        df.index = _pd.to_datetime(df.index)
        df.sort_index(inplace=True)

        # Donchian Channel 20 & 55
        df['dc10_upper'] = df['High'].rolling(10).max()
        df['dc10_lower'] = df['Low'].rolling(10).min()
        df['dc20_upper'] = df['High'].rolling(20).max()
        df['dc20_lower'] = df['Low'].rolling(20).min()
        df['dc55_upper'] = df['High'].rolling(55).max()
        df['dc55_lower'] = df['Low'].rolling(55).min()

        # RSI 14
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, _np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))

        # Stochastic (14, 3, 3)
        low_min = df['Low'].rolling(window=14).min()
        high_max = df['High'].rolling(window=14).max()
        df['stoch_k_fast'] = 100 * (df['Close'] - low_min) / (high_max - low_min)
        df['stoch_k'] = df['stoch_k_fast'].rolling(window=3).mean()
        df['stoch_d'] = df['stoch_k'].rolling(window=3).mean()

        # --- Trend Following: EMA ---
        df['ema9']   = df['Close'].ewm(span=9, adjust=False).mean()
        df['ema20']  = df['Close'].ewm(span=20, adjust=False).mean()
        df['ema50']  = df['Close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['Close'].ewm(span=200, adjust=False).mean()

        # --- Momentum: MACD ---
        exp12 = df['Close'].ewm(span=12, adjust=False).mean()
        exp26 = df['Close'].ewm(span=26, adjust=False).mean()
        df['macd']    = exp12 - exp26
        df['macd_sig'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_sig']

        # --- Volatility: Bollinger Bands ---
        ma20 = df['Close'].rolling(window=20).mean()
        std20 = df['Close'].rolling(window=20).std()
        df['bb_upper'] = ma20 + (std20 * 2)
        df['bb_lower'] = ma20 - (std20 * 2)

        # --- Ehlers Instantaneous Trendline (ITL) ---
        from .utils import calculate_ehlers_itl as _calc_itl
        _itl_arr = _calc_itl(df['Close'].values, alpha=0.07)
        df['itl'] = _itl_arr

        # --- Tactical Analysis (N and Next Units) ---
        # Calculate ATR (Wilder's method)
        df['h_l'] = df['High'] - df['Low']
        df['h_pc'] = (df['High'] - df['Close'].shift(1)).abs()
        df['l_pc'] = (df['Low'] - df['Close'].shift(1)).abs()
        df['tr'] = df[['h_l', 'h_pc', 'l_pc']].max(axis=1)
        df['atr_20'] = df['tr'].ewm(alpha=1/20, adjust=False).mean() # N for 20 days
        
        last_row = df.iloc[-1]
        n_val = round(float(last_row['atr_20']), 4)
        curr_price = float(last_row['Close'])
        
        # 🚥 Strategic Signal Logic
        def get_signal(buy_cond, sell_cond):
            if buy_cond: return 'BUY'
            if sell_cond: return 'SELL'
            return 'WAIT'

        # Short: DC10 + RSI
        short_buy = curr_price >= float(last_row['dc10_upper']) and float(last_row['rsi']) > 50
        short_sell = curr_price <= float(last_row['dc10_lower'])
        
        # ⏱️ Breakout Age Analysis (User Suggestion)
        breakout_age = 0
        dist_from_breakout = 0
        if short_buy:
            # Find how many candles ago it first broke DC10 upper
            past_df = df.iloc[:-1].iloc[::-1] # All except last, reversed
            for i, (idx, row) in enumerate(past_df.iterrows()):
                if row['Close'] >= row['dc10_upper']:
                    breakout_age += 1
                else:
                    break
            dist_from_breakout = round(((curr_price - float(last_row['dc10_upper'])) / float(last_row['dc10_upper'])) * 100, 2)

        # Medium: DC20 + EMA200
        med_buy = curr_price >= float(last_row['dc20_upper']) and curr_price > float(last_row['ema200'])
        med_sell = curr_price <= float(last_row['dc10_lower'])

        # Long: DC55
        long_buy = curr_price >= float(last_row['dc55_upper'])
        long_sell = curr_price <= float(last_row['dc20_lower'])

        # Volume Confirmation — ใช้ 20 bars ล่าสุด, รองรับทั้ง daily และ intraday
        # Contract Roll จริง = หลาย bars ปริมาณต่ำมาก (< 50), ไม่ต่อเนื่อง
        # ข้อมูล intraday ปกติ = consistent แม้ค่าสัมบูรณ์จะ < 1000 contracts/bar
        try:
            _raw_cur    = last_row['Volume'] if 'Volume' in last_row.index else 0
            vol_current = float(_raw_cur) if _pd.notna(_raw_cur) and _raw_cur == _raw_cur else 0.0

            vol_hist    = df['Volume'].iloc[:-1]
            _tail20     = vol_hist.tail(20)
            vol_nonzero = _tail20.replace(0, _pd.NA).dropna()
            vol_avg_10  = float(vol_nonzero.median()) if len(vol_nonzero) >= 5 else 0.0

            # coverage = สัดส่วน bars ที่มี volume จริง (contract roll มี gap เยอะ)
            _coverage  = len(vol_nonzero) / max(1, len(_tail20))
            _vol_min20 = float(vol_nonzero.min()) if len(vol_nonzero) >= 5 else 0.0

            # reliable ถ้า:
            # A) daily scale: median >= 1000 (gold daily trades 100K+ contracts)
            # B) intraday scale: median >= 200 AND coverage >= 80% AND min >= 50
            _is_daily    = bool(vol_avg_10 >= 1_000)
            _is_intraday = bool(vol_avg_10 >= 200 and _coverage >= 0.80 and _vol_min20 >= 50)
            vol_reliable = _is_daily or _is_intraday
            vol_ratio    = round(vol_current / vol_avg_10, 2) if (vol_avg_10 > 0 and vol_reliable) else 0.0
        except Exception:
            vol_current, vol_avg_10, vol_ratio, vol_reliable = 0.0, 0.0, 0.0, False

        tactical = {
            'price': round(_safe_val(curr_price), 2),
            'n': _safe_val(n_val),
            'signals': {
                'short':  get_signal(short_buy,  short_sell),
                'medium': get_signal(med_buy,     med_sell),
                'long':   get_signal(long_buy,    long_sell),
                'short_vol_ok':  bool(short_buy  and vol_ratio >= 1.5),
                'medium_vol_ok': bool(med_buy    and vol_ratio >= 1.5),
                'long_vol_ok':   bool(long_buy   and vol_ratio >= 1.5),
            },
            'volume': {
                'current':   int(vol_current) if vol_current and vol_current == vol_current else 0,
                'avg_10':    int(vol_avg_10)  if vol_avg_10  and vol_avg_10  == vol_avg_10  else 0,
                'ratio':     vol_ratio,
                'reliable':  vol_reliable,
                'confirmed': bool(vol_reliable and vol_ratio >= 1.5),
                'weak':      bool(vol_reliable and 0.8 <= vol_ratio < 1.5),
                'low':       bool(not vol_reliable or vol_ratio < 0.8),
            },
            'breakout_age': breakout_age,
            'breakout_dist': _safe_val(dist_from_breakout),
            'short_term_high': round(_safe_val(last_row['dc10_upper']), 2),
            'high_20d': round(_safe_val(last_row['dc20_upper']), 2),
            'high_55d': round(_safe_val(last_row['dc55_upper']), 2),
            'rsi': round(_safe_val(last_row['rsi']), 2),
            'ema9': round(_safe_val(last_row['ema9']), 2),
            'ema200': round(_safe_val(last_row['ema200']), 2),
            # Added missing fields for Tactical Command Center
            'exit_10d_low': round(_safe_val(last_row['dc10_lower']), 2),
            'exit_20d_low': round(_safe_val(last_row['dc20_lower']), 2),
            'next_unit': round(_safe_val(curr_price + (0.5 * n_val)), 2),
            
            # --- Extreme Precision CFD Levels (Stabilized for 1:200 Leverage) ---
            'levels': {
                'sniper': {
                    'target': _safe_val(round(curr_price + (0.5 * n_val), 2)),
                    'stop': _safe_val(round(_safe_val(last_row['ema9']) - (0.5 * n_val), 2)),  # Anchored to EMA9
                    'label': 'SNIPER (0.5N SL)'
                },
                'scalper': {
                    'target': _safe_val(round(curr_price + (0.3 * n_val), 2)),
                    'stop': _safe_val(round(_safe_val(last_row['dc10_upper']) - (0.3 * n_val), 2)), # Anchored to DC10 High
                    'label': 'SCALPER (0.3N SL)'
                }
            }
        }

        # ====== Fetch or dynamically compute Institutional Accumulation Zones ======
        try:
            from .models import PrecisionScanCandidate
            prec_data = PrecisionScanCandidate.objects.filter(symbol=symbol, market=market).order_by('-scan_run').first()
            if prec_data:
                tactical['demand_zone_start'] = _safe_val(prec_data.demand_zone_start)
                tactical['demand_zone_end'] = _safe_val(prec_data.demand_zone_end)
                tactical['stop_loss'] = _safe_val(prec_data.stop_loss)
                tactical['supply_zone_start'] = _safe_val(prec_data.supply_zone_start)
                tactical['supply_zone_end'] = _safe_val(prec_data.supply_zone_end)
                tactical['cmf'] = _safe_val(prec_data.cmf)
                tactical['pocket_pivot'] = bool(prec_data.pocket_pivot)
                tactical['vdu_near_zone'] = bool(prec_data.vdu_near_zone)
            else:
                # Calculate dynamically from historical data if possible
                from .utils import find_supply_demand_zones_v2
                sd = find_supply_demand_zones_v2(df)
                if sd:
                    tactical['demand_zone_start'] = _safe_val(sd.get('start'))
                    tactical['demand_zone_end'] = _safe_val(sd.get('end'))
                    tactical['stop_loss'] = _safe_val(sd.get('stop_loss'))
                    tactical['supply_zone_start'] = _safe_val(sd.get('target'))
                    tactical['supply_zone_end'] = _safe_val(sd.get('target'))
                    # Calculate CMF 20d dynamically
                    try:
                        high_low = df['High'] - df['Low']
                        clv = ((df['Close'] - df['Low']) - (df['High'] - df['Close'])) / high_low.replace(0, _np.nan)
                        clv = clv.fillna(0)
                        clv_vol = clv * df['Volume']
                        cmf_series = clv_vol.rolling(20).sum() / df['Volume'].rolling(20).sum().replace(0, _np.nan)
                        tactical['cmf'] = _safe_val(cmf_series.iloc[-1]) if not cmf_series.empty else 0.0
                    except Exception:
                        tactical['cmf'] = 0.0
                    tactical['pocket_pivot'] = False
                    tactical['vdu_near_zone'] = False
                else:
                    tactical['demand_zone_start'] = 0.0
                    tactical['demand_zone_end'] = 0.0
                    tactical['stop_loss'] = 0.0
                    tactical['supply_zone_start'] = 0.0
                    tactical['supply_zone_end'] = 0.0
                    tactical['cmf'] = 0.0
                    tactical['pocket_pivot'] = False
                    tactical['vdu_near_zone'] = False
        except Exception as ex:
            print(f"Error fetching/calculating zones for {symbol}: {ex}")
            tactical['demand_zone_start'] = 0.0
            tactical['demand_zone_end'] = 0.0
            tactical['stop_loss'] = 0.0
            tactical['supply_zone_start'] = 0.0
            tactical['supply_zone_end'] = 0.0
            tactical['cmf'] = 0.0
            tactical['pocket_pivot'] = False
            tactical['vdu_near_zone'] = False

        # Calculate Major Fibonacci Extension targets projected from the 52-week High (Supply Target)
        sz_start = tactical.get('supply_zone_start', 0.0)
        dz_end = tactical.get('demand_zone_end', 0.0)
        dz_start = tactical.get('demand_zone_start', 0.0)
        
        # Determine breakout high and base low for projection
        # If we have a supply zone (52w high), use it as breakout high. Else use demand zone start.
        breakout_high = sz_start if sz_start > 0.0 else dz_start
        base_low = dz_end if dz_end > 0.0 else (dz_start * 0.95 if dz_start > 0.0 else 0.0)
        
        if breakout_high > 0.0 and base_low > 0.0:
            base_depth = breakout_high - base_low
            if base_depth > 0.0:
                tactical['fib_1618'] = _safe_val(round(breakout_high + (1.618 * base_depth), 2))
                tactical['fib_2618'] = _safe_val(round(breakout_high + (2.618 * base_depth), 2))
            else:
                tactical['fib_1618'] = 0.0
                tactical['fib_2618'] = 0.0

        # Check if the user holds this stock in their portfolio
        portfolio_entry = 0.0
        portfolio_qty = 0.0
        try:
            from .models import Portfolio
            p_item = Portfolio.objects.filter(user=request.user, symbol__icontains=symbol).first()
            if p_item:
                portfolio_entry = _safe_val(p_item.entry_price)
                portfolio_qty = _safe_val(p_item.quantity)
        except Exception as p_ex:
            print(f"Error querying portfolio for chart: {p_ex}")

        tactical['portfolio_entry_price'] = portfolio_entry
        tactical['portfolio_quantity'] = portfolio_qty

        # --- Enhanced Intermarket Analysis (DXY & MTF) ---
        if symbol == 'GC=F':
            try:
                # 1. DXY Data
                dxy_ticker = _yf.Ticker('DX-Y.NYB')
                dxy_hist = dxy_ticker.history(period='2d')
                dxy_price, dxy_change = 0, 0
                if not dxy_hist.empty:
                    dxy_price = float(dxy_hist['Close'].iloc[-1])
                    dxy_prev = float(dxy_hist['Close'].iloc[-2]) if len(dxy_hist) > 1 else dxy_price
                    dxy_change = ((dxy_price - dxy_prev) / dxy_prev * 100) if dxy_prev else 0
                    tactical['dxy'] = {'price': round(dxy_price, 2), 'change': round(dxy_change, 2)}
                
                # 2. Multi-Timeframe Analysis (M15, H1, H4)
                # Helper to check trend
                def _get_trend(sym, interval, period='5d'):
                    tmp = _yf.download(sym, period=period, interval=interval, progress=False)
                    if tmp.empty: return 'NEUTRAL'
                    if isinstance(tmp.columns, _pd.MultiIndex): tmp.columns = tmp.columns.get_level_values(0)
                    tmp.columns = [str(c).capitalize() for c in tmp.columns]
                    ma = tmp['Close'].ewm(span=20, adjust=False).mean().iloc[-1]
                    price = float(tmp['Close'].iloc[-1])
                    return 'BULLISH' if price > ma else 'BEARISH'

                tactical['mtf'] = {
                    'm15': _get_trend(yf_symbol, '15m', '2d'),
                    'h1':  _get_trend(yf_symbol, '1h', '5d'),
                    'h4':  _get_trend(yf_symbol, '4h', '1mo'),
                    'd1':  'BULLISH' if curr_price > float(last_row['ema200']) else 'BEARISH'
                }

                # 3. AI Sentiment Advice
                advice = "สถานะตลาดเป็นกลาง รอสัญญาณที่ชัดเจน"
                bull_count = list(tactical['mtf'].values()).count('BULLISH')
                if dxy_change < -0.1 and bull_count >= 3:
                    advice = "ขาขึ้นแข็งแกร่ง: ดอลลาร์อ่อนค่าและเทรนด์ทุก Timeframe สอดคล้องเป็นขาขึ้น มีโอกาสสูงในการเข้า BUY"
                elif dxy_change > 0.1 and bull_count <= 1:
                    advice = "ขาลงรุนแรง: ดอลลาร์กำลังแข็งค่าและเทรนด์ส่วนใหญ่เป็นขาลง ระวังการปรับตัวลงต่อ"
                elif bull_count >= 3:
                    advice = "โน้มเอียงขาขึ้น: โมเมนตัมเป็นบวก แต่ควรจับตาดูกำลังของดอลลาร์ประกอบ"
                elif bull_count <= 1:
                    advice = "โน้มเอียงขาลง: หลาย Timeframe แสดงสัญญาณอ่อนแรง ควรระมัดระวังการถือสถานะ Buy"
                else:
                    advice = "ช่วงสะสมตัว: ตลาดมีสัญญาณผสมผสาน แนะนำให้รอจนกว่าเทรนด์ในหลาย Timeframe จะเริ่มสอดคล้องกัน"
                
                tactical['sentiment_advice'] = advice

            except Exception as e:
                print(f"Error fetching enhanced gold data: {e}")

        # Turtle breakout signals (compare close vs previous day's channel)
        df['sys1_signal'] = df['Close'] >= df['dc20_upper'].shift(1)
        df['sys2_signal'] = df['Close'] >= df['dc55_upper'].shift(1)
        df['sys1_exit']   = df['Close'] <= df['dc10_lower'].shift(1)

        def datestr(dt):
            ts = _pd.Timestamp(dt)
            if is_intraday:
                # LightweightCharts requires Unix seconds for intraday
                return int(ts.timestamp())
            return ts.strftime('%Y-%m-%d')

        candles, vol, rsi_data = [], [], []
        dc20u, dc20l, dc55u, dc55l = [], [], [], []
        ema20, ema50, ema200 = [], [], []
        bbu, bbl = [], []
        macd, macd_sig, macd_hist = [], [], []
        stoch_k, stoch_d = [], []
        itl_data = []
        signals = []

        for dt, row in df.iterrows():
            t = datestr(dt)
            o = _safe_val(row['Open'])
            h = _safe_val(row['High'])
            l = _safe_val(row['Low'])
            c = _safe_val(row['Close'])
            candles.append({'time': t, 'open': round(o, 2), 'high': round(h, 2),
                            'low': round(l, 2), 'close': round(c, 2)})
            vol.append({'time': t, 'value': int(_safe_val(row['Volume'])),
                        'color': '#26a69a' if c >= o else '#ef5350'})

            if _pd.notna(row['dc20_upper']):
                dc20u.append({'time': t, 'value': round(float(row['dc20_upper']), 2)})
                dc20l.append({'time': t, 'value': round(float(row['dc20_lower']), 2)})
            if _pd.notna(row['dc55_upper']):
                dc55u.append({'time': t, 'value': round(float(row['dc55_upper']), 2)})
                dc55l.append({'time': t, 'value': round(float(row['dc55_lower']), 2)})
            
            if _pd.notna(row['rsi']):
                rsi_data.append({'time': t, 'value': round(float(row['rsi']), 2)})
            
            if _pd.notna(row['stoch_k']) and _pd.notna(row['stoch_d']):
                stoch_k.append({'time': t, 'value': round(float(row['stoch_k']), 2)})
                stoch_d.append({'time': t, 'value': round(float(row['stoch_d']), 2)})
            
            if _pd.notna(row['ema20']):
                ema20.append({'time': t, 'value': round(float(row['ema20']), 2)})
            if _pd.notna(row['ema50']):
                ema50.append({'time': t, 'value': round(float(row['ema50']), 2)})
            if _pd.notna(row['ema200']):
                ema200.append({'time': t, 'value': round(float(row['ema200']), 2)})
            
            if _pd.notna(row['bb_upper']):
                bbu.append({'time': t, 'value': round(float(row['bb_upper']), 2)})
                bbl.append({'time': t, 'value': round(float(row['bb_lower']), 2)})
            
            if _pd.notna(row['macd']):
                macd.append({'time': t, 'value': round(float(row['macd']), 2)})
                macd_sig.append({'time': t, 'value': round(float(row['macd_sig']), 2)})
                macd_hist.append({'time': t, 'value': round(float(row['macd_hist']), 2)})

            if _pd.notna(row['itl']):
                itl_data.append({'time': t, 'value': round(float(row['itl']), 2)})

            if row['sys1_signal']:
                signals.append({'time': t, 'type': 'sys1_buy', 'price': round(float(row['Close']), 2)})
            if row['sys2_signal']:
                signals.append({'time': t, 'type': 'sys2_buy', 'price': round(float(row['Close']), 2)})
            if row['sys1_exit']:
                signals.append({'time': t, 'type': 'sys1_exit', 'price': round(float(row['Close']), 2)})

        return JsonResponse({
            'symbol': symbol, 'market': market, 'tactical': tactical,
            'candles': candles, 'volume': vol, 'rsi': rsi_data,
            'dc20_upper': dc20u, 'dc20_lower': dc20l,
            'dc55_upper': dc55u, 'dc55_lower': dc55l,
            'ema20': ema20, 'ema50': ema50, 'ema200': ema200,
            'bb_upper': bbu, 'bb_lower': bbl,
            'macd': macd, 'macd_sig': macd_sig, 'macd_hist': macd_hist,
            'stoch_k': stoch_k, 'stoch_d': stoch_d,
            'itl': itl_data,
            'signals': signals,
            'is_intraday': is_intraday,
            'interval': download_interval,
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

