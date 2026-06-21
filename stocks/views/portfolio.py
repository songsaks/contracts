from .base import * 

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
    total_set_value = 0
    total_set_cost = 0
    total_set_pl = 0
    total_us_value = 0
    total_crypto_value = 0
    total_crypto_cost = 0
    total_crypto_pl = 0
    total_us_cost = 0
    total_us_pl = 0
    print(f"DEBUG: Portfolio Scan Started for {getattr(request.user, 'username', 'Anonymous')}")
    _portfolio_us_set = _build_us_symbol_set(request.user)

    for item in portfolio_items:
        try:
            symbol = item.symbol
            print(f"DEBUG: Processing {symbol}")

            # ====== ดึงข้อมูลราคาจาก yfinance ======
            # Determine correct symbol string for yfinance based on database market field
            fetch_symbol = symbol
            if item.market == MarketType.SET and not symbol.endswith('.BK'):
                fetch_symbol = f"{symbol}.BK"
            elif item.market == MarketType.CRYPTO and '-' not in symbol:
                fetch_symbol = f"{symbol}-USD"
            
            t = yf.Ticker(fetch_symbol)
            hist = t.history(period="1y")

            # Fallback if empty (for robustness with manually entered symbols)
            used_symbol = fetch_symbol
            if hist.empty and fetch_symbol == symbol:
                alt_sym = f"{symbol}.BK" if ".BK" not in symbol else symbol.replace(".BK", "")
                print(f"DEBUG: {symbol} empty, trying {alt_sym}")
                t = yf.Ticker(alt_sym)
                hist = t.history(period="1y")
                if not hist.empty:
                    used_symbol = alt_sym

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
            is_us = item.market == MarketType.US

            # ====== คำนวณ ATR Trailing Stop ======
            from stocks.utils import calculate_atr_trailing_stop
            atr_ts = calculate_atr_trailing_stop(
                df=hist if not hist.empty else None,
                entry_price=float(item.entry_price or 0),
                highest_price_db=float(item.highest_price or 0),
                multiplier=float(item.trail_multiplier or 2.5),
            ) if current_price > 0 else None

            print(f"DEBUG: {symbol} Price={current_price}, DB_High={item.highest_price}, ATR_High={atr_ts['highest'] if atr_ts else 'N/A'}")
            
            # อัปเดต highest_price และ ATR ใน DB ถ้าสูงขึ้น
            if atr_ts and current_price > 0:
                new_high = atr_ts['highest']
                update_fields = []
                if float(item.highest_price or 0) < new_high:
                    item.highest_price = new_high
                    update_fields.append('highest_price')
                if abs(float(item.atr or 0) - atr_ts['atr']) > 0.0001:
                    item.atr = atr_ts['atr']
                    update_fields.append('atr')
                if update_fields:
                    item.save(update_fields=update_fields)

            # ====== Strategy Management Logic ======
            is_turtle = item.strategy and ('turtle' in item.strategy.lower() or '🐢' in item.strategy)
            is_pms = item.strategy in ['Precision', 'Precision Momentum']
            is_dividend = item.strategy == 'Dividend'
            is_value = item.strategy == 'Value'
            
            if is_turtle and atr_ts and hist is not None and not hist.empty:
                is_s2 = 'S2' in item.strategy.upper() or '20' in item.strategy
                periods = 20 if is_s2 else 10
                nday_low = float(hist['Low'].iloc[:-1].tail(periods).min()) if len(hist) > periods else float(hist['Low'].min())
                initial_stop = float(item.entry_price or 0) - (2.0 * atr_ts['atr'])
                current_stop = max(initial_stop, nday_low) if float(item.entry_price or 0) > 0 else nday_low
                pyramid_price = float(item.entry_price or 0) + (atr_ts['atr'] * 0.5) if float(item.entry_price or 0) > 0 else 0
                
                dist_pct = ((current_price - current_stop) / current_price * 100) if current_price > 0 else 0
                
                status = 'RIDE TREND 🚀'
                color = 'success'
                if current_price <= current_stop:
                    status = 'EXIT HIT'
                    color = 'danger'
                elif dist_pct <= 3.0:
                    status = 'NEAR EXIT'
                    color = 'warning'
                    
                atr_ts.update({
                    'trailing_stop': current_stop,
                    'color': color,
                    'status': status,
                    'is_turtle': True,
                    'pyramid_price': pyramid_price,
                    'pyramid_status': 'PYRAMID NOW! 🚀' if current_price >= pyramid_price else 'WAITING ⏳'
                })
            elif is_pms and atr_ts:
                pms_stop = float(atr_ts['highest']) - (2.0 * float(item.atr or 0))
                atr_ts.update({
                    'trailing_stop': pms_stop,
                    'is_pms': True,
                    'status': 'MOMENTUM RIDE' if current_price > pms_stop else 'TREND BROKEN',
                    'color': 'danger' if current_price <= pms_stop else 'success'
                })
            elif is_dividend and atr_ts:
                # Dividend: Safety first, 15% Max drawdown from cost or custom multiplier
                multiplier = float(item.trail_multiplier or 2.5)
                div_stop = float(item.entry_price or 0) - (multiplier * float(item.atr or 0))
                atr_ts.update({
                    'trailing_stop': div_stop,
                    'is_dividend': True,
                    'status': 'YIELD HARVESTING 💸',
                    'color': 'success'
                })
            elif is_value and atr_ts:
                # Value: Deep value holding
                multiplier = float(item.trail_multiplier or 3.0)
                val_stop = float(atr_ts['highest']) - (multiplier * float(item.atr or 0))
                atr_ts.update({
                    'trailing_stop': val_stop,
                    'is_value': True,
                    'status': 'VALUE HOLDING 💎',
                    'color': 'success' if current_price > val_stop else 'danger'
                })

            # ====== Volatility Gauge Logic ======
            if atr_ts and current_price > 0:
                vol_pct = (atr_ts['atr'] / current_price) * 100
                if vol_pct < 2.0:
                    vol_label, vol_color = "Low (นิ่ง/พื้นฐาน)", "success"
                elif vol_pct < 4.0:
                    vol_label, vol_color = "Mid (ปกติ)", "warning"
                else:
                    vol_label, vol_color = "High (ซิ่ง/ผันผวน)", "danger"
                
                atr_ts.update({
                    'vol_pct': vol_pct,
                    'vol_label': vol_label,
                    'vol_color': vol_color,
                    'vol_bar_width': min(vol_pct * 10, 100)  # คูณ 10 เพื่อความสวยงามและคุมไม่ให้เกิน 100%
                })

            ts_data = atr_ts

            # ====== ดึง/คำนวณ Zone Data - ใช้ PrecisionScanCandidate (v2) เสมอ ======
            clean_symbol = item.symbol.split('.')[0].upper()
            from stocks.models import PrecisionScanCandidate
            from stocks.utils import analyze_momentum_technical_v2

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
                mom_data.supply_zone_start = pyramid_price if is_turtle else prec_data.supply_zone_start
                mom_data.stop_loss         = current_stop if is_turtle else prec_data.stop_loss
                mom_data.zone_proximity    = prec_data.zone_proximity
                mom_data.year_high         = prec_data.year_high
                mom_data.price_pattern     = prec_data.price_pattern
                mom_data.price_pattern_score = prec_data.price_pattern_score
                mom_data.rel_momentum_1m   = prec_data.rel_momentum_1m
                mom_data.rel_momentum_3m   = prec_data.rel_momentum_3m
                mom_data.macd_histogram    = prec_data.macd_histogram
                mom_data.macd_crossover    = prec_data.macd_crossover
                mom_data.bb_squeeze        = prec_data.bb_squeeze
                mom_data.ema20_aligned     = prec_data.ema20_aligned
                mom_data.rs_rating         = prec_data.rs_rating
                mom_data.ema20_rising      = prec_data.ema20_rising
                mom_data.hh_hl_structure   = prec_data.hh_hl_structure
                mom_data.cmf               = prec_data.cmf
                mom_data.is_52w_breakout   = prec_data.is_52w_breakout
                mom_data.stage2            = prec_data.stage2  # Weinstein Stage 2 flag
                mom_data.ehlers_supersmoother = prec_data.ehlers_supersmoother
                mom_data.ehlers_laguerre_rsi  = prec_data.ehlers_laguerre_rsi
                mom_data.ehlers_fisher        = prec_data.ehlers_fisher
                mom_data.ehlers_fisher_trigger= prec_data.ehlers_fisher_trigger
                mom_data.ehlers_itl_daily     = prec_data.ehlers_itl_daily
                mom_data.ehlers_itl_weekly    = prec_data.ehlers_itl_weekly
                mom_data.ehlers_itl_bullish   = prec_data.ehlers_itl_bullish
                mom_data.ehlers_pattern_data  = prec_data.ehlers_pattern_data
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
                        mom_data.supply_zone_start = pyramid_price if is_turtle else sd.get('target', 0)
                        mom_data.stop_loss = current_stop if is_turtle else sd.get('stop_loss', None)
                        mom_data.zone_proximity = 0 if current_price <= sd['start'] else ((float(current_price) - sd['start']) / sd['start']) * 100
                    else:
                        mom_data.risk_reward_ratio = 0
                        mom_data.demand_zone_start = 0
                        mom_data.stop_loss = None
                        mom_data.zone_proximity = 999
                    mom_data.ehlers_supersmoother = tech_analysis.get('ehlers_supersmoother')
                    mom_data.ehlers_laguerre_rsi  = tech_analysis.get('ehlers_laguerre_rsi')
                    mom_data.ehlers_fisher        = tech_analysis.get('ehlers_fisher')
                    mom_data.ehlers_fisher_trigger= tech_analysis.get('ehlers_fisher_trigger')
                    mom_data.ehlers_itl_daily     = tech_analysis.get('ehlers_itl_daily')
                    mom_data.ehlers_itl_weekly    = tech_analysis.get('ehlers_itl_weekly')
                    mom_data.ehlers_itl_bullish   = tech_analysis.get('ehlers_itl_bullish', False)
                    from stocks.utils import classify_ehlers_pattern
                    mom_data.ehlers_pattern_data  = classify_ehlers_pattern(
                        mom_data.ehlers_laguerre_rsi,
                        mom_data.ehlers_fisher,
                        mom_data.ehlers_fisher_trigger,
                        current_price,
                        mom_data.ehlers_supersmoother
                    )
                else:
                    mom_data.ehlers_pattern_data = None
                    mom_data.technical_score = 0
                    mom_data.rvol = 0
                    mom_data.risk_reward_ratio = 0
                    mom_data.demand_zone_start = 0
                    mom_data.stop_loss = None
                    mom_data.zone_proximity = 999
                    mom_data.ehlers_supersmoother = None
                    mom_data.ehlers_laguerre_rsi  = 0.5
                    mom_data.ehlers_fisher        = 0.0
                    mom_data.ehlers_fisher_trigger= 0.0
                    mom_data.ehlers_itl_daily     = 0.0
                    mom_data.ehlers_itl_weekly    = 0.0
                    mom_data.ehlers_itl_bullish   = False

            total_market_value += market_value
            total_gain_loss += gain_loss
            _market = item.market
            if _market == MarketType.US:
                total_us_value += market_value
                total_us_cost += cost_basis
                total_us_pl += gain_loss
            elif _market == MarketType.CRYPTO:
                total_crypto_value += market_value
                total_crypto_cost += cost_basis
                total_crypto_pl += gain_loss
            else:
                total_set_value += market_value
                total_set_cost += cost_basis
                total_set_pl += gain_loss

            signals = _compute_signals(
                mom_data, 
                current_price, 
                is_turtle=is_turtle, 
                turtle_stop=(current_stop if is_turtle else None)
            ) if mom_data else {
                'buy_score': 0, 'sell_score': 0, 'exit_signal': '',
                'reversal_score': 0, 'reversal_alert': '', 'reversal_color': 'success',
                'reversal_reasons': [], 'stage_label': '—', 'stage_color': 'secondary',
            }

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
                'buy_score':       signals['buy_score'],
                'sell_score':      signals['sell_score'],
                'exit_signal':     signals['exit_signal'],
                'reversal_score':  signals['reversal_score'],
                'reversal_alert':  signals['reversal_alert'],
                'reversal_color':  signals['reversal_color'],
                'reversal_reasons': signals['reversal_reasons'],
                'stage_label':     signals['stage_label'],
                'stage_color':     signals['stage_color'],
                'in_scan': prec_data is not None,
                'scan_score': prec_data.technical_score if prec_data else None,
                'is_us': is_us,
                'symbol_base': item.symbol.split('.')[0],
                'market': item.market,
            })
        except Exception as e:
            print(f"DEBUG: ERROR for {item.symbol}: {e}")
            traceback.print_exc()
            # ถ้า error ใส่ข้อมูลเปล่าเพื่อแสดง error state ใน template
            items.append({
                'obj': item, 'current_price': 0, 'day_change': 0, 'market_value': 0,
                'gain_loss': 0, 'gain_loss_pct': 0, 'rsi': None,
                'trailing_stop_data': None, 'mom_data': None,
                'is_us': item.market == MarketType.US,
                'symbol_base': item.symbol.split('.')[0],
                'market': item.market,
            })

    # ── Calculate Suggested Pyramid Units & Alerts for Turtle Strategy ──
    for it in items:
        ts = it.get('trailing_stop_data')
        if ts and ts.get('is_turtle'):
            m_type = it.get('market')
            market_total = 0
            if m_type == MarketType.SET: market_total = total_set_value
            elif m_type == MarketType.US: market_total = total_us_value
            elif m_type == MarketType.CRYPTO: market_total = total_crypto_value
            
            atr = ts.get('atr', 0)
            cur_p = it.get('current_price', 0)
            
            if atr > 0 and market_total > 0 and cur_p > 0:
                # Conservative Turtle Rule for Stocks: 0.5% Risk
                risk_pct = 0.005 
                unit_size = (risk_pct * float(market_total)) / float(atr)
                
                # Safety Cap: 1 Unit should not exceed 15% of the total market portfolio
                max_unit_value = float(market_total) * 0.15
                max_shares_by_cap = max_unit_value / float(cur_p)
                unit_size = min(unit_size, max_shares_by_cap)

                # Store Unit Size
                if m_type == MarketType.SET:
                    ts['pyramid_units'] = round(unit_size / 100) * 100
                else:
                    ts['pyramid_units'] = round(unit_size)
                    
                # --- Advanced Target Calculation ---
                qty = float(it['obj'].quantity)
                # Estimate how many units currently held
                num_units = max(1, round(qty / unit_size)) if unit_size > 0 else 1
                entry_p = float(it['obj'].entry_price or cur_p)
                
                # Next pyramid price = entry_price + (0.5 * ATR * num_units)
                p_price = entry_p + (atr * 0.5 * num_units)
                ts['pyramid_price'] = p_price
                
                p_dist = ((cur_p - p_price) / p_price * 100) if p_price > 0 else 0
                if cur_p >= p_price:
                    ts['pyramid_status'], ts['pyramid_color'] = 'PYRAMID NOW! 🚀', 'primary'
                elif p_dist >= -1.5: # Within 1.5% of target
                    ts['pyramid_status'], ts['pyramid_color'] = 'APPROACHING... ⏳', 'info'
                else:
                    ts['pyramid_status'], ts['pyramid_color'] = 'WAITING ⏱️', 'secondary'
            else:
                ts['pyramid_status'], ts['pyramid_color'] = 'WAITING ⏱️', 'secondary'

    # ── USD/THB rate for combined totals ──
    usd_thb = _get_usd_thb() if any(it.get('market') in (MarketType.US, MarketType.CRYPTO) for it in items) else 1.0

    # ── Sort items: SET → US → CRYPTO → OTHER; mark group headers ──
    _market_order = {MarketType.SET: 0, MarketType.US: 1, MarketType.CRYPTO: 2, MarketType.OTHER: 3}
    items.sort(key=lambda x: (_market_order.get(x.get('market', MarketType.SET), 99), x['obj'].symbol))
    _prev_market = None
    for _it in items:
        _it['show_group_header'] = (_it.get('market') != _prev_market)
        _prev_market = _it.get('market')

    # ====== AI Portfolio Analysis ด้วย Gemini + PyPortfolioOpt ======
    ai_analysis = None
    if request.GET.get('analyze') == 'true' and items:
        # เลือก Gemini model ที่ดีที่สุดที่ตอบสนองได้
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        model_name_to_use = 'gemini-2.5-flash'

        # สร้าง string สรุปพอร์ตสำหรับส่งให้ AI
        port_data = []
        for it in items:
            mom_info = ""
            if it.get('mom_data'):
                m = it['mom_data']
                rvol = m.rvol if hasattr(m, 'rvol') else 0
                rs = getattr(m, 'rs_rating', 0)
                adx = m.adx if hasattr(m, 'adx') else 0
                score = m.technical_score if hasattr(m, 'technical_score') else 0
                buy_sc = it.get('buy_score', 0)
                exit_sig = it.get('exit_signal', '')
                mom_info = f", Score(0-100): {score}, BUY Score: {buy_sc}, RS(0-99): {rs}, RVOL: {rvol:.1f}x, ADX: {adx:.1f}, Exit Signal: '{exit_sig}'"
            port_data.append(f"{it['obj'].symbol}: {it['obj'].quantity} units @ {it['obj'].entry_price} (Current: {it['current_price']}, P/L: {it['gain_loss_pct']:.2f}%, RSI: {it['rsi']}{mom_info})")
        port_str = "\n".join(port_data)

        # ====== PyPortfolioOpt - คำนวณ Efficient Frontier / Max Sharpe ======
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
        You are an expert Stock Portfolio Analyst specializing in "Precision Momentum Trading" (similar to Mark Minervini and CANSLIM).
        The user has the following assets in their portfolio (with Entry Price, Current Price, and Profit/Loss, along with Momentum metrics):
        {port_str}

        {ppo_advice}

        Please analyze this portfolio and provide:
        2. A brief analysis and clear recommendation for EACH individual asset (e.g., Hold, Buy More, Take Profit, Cut Loss).
           - CRITICAL RULE: In your analysis, you MUST heavily weigh the Momentum metrics (Score, BUY Score, RS, RVOL, ADX, and Exit Signal).
           - Do NOT immediately suggest cutting a loss JUST because P/L is slightly negative or RSI is > 70.
           - **Consider Entry Price:** If a stock's price is below its technical Stop Loss but still above the Entry Price (in profit), suggest "Locking Profit" (ล็อกกำไร) or "Trailing Exit" instead of a harsh "Cut Loss".
           - If a stock has High RS (e.g. > 75), strong RVOL (> 1.5x) or a high BUY Score/Score, it indicates it is a "Market Leader" and in a strong uptrend. In such cases, suggest "Holding" to ride the momentum as long as the Exit Signal is not triggered, even if P/L is temporarily negative.
           - Acknowledge the strength of the momentum. E.g., "แม้จะขาดทุน -2.35% แต่หุ้นมี RS แข็งแกร่งถึง 88 และ RVOL สูง บ่งบอกถึงแรงซื้อที่ยังมีอยู่ แนะนำให้ถือเพื่อรอจังหวะเด้งกลับ"
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

    # ── Performance Chart data (All time) ──
    all_sold_stocks = SoldStock.objects.filter(user=request.user).order_by('sold_at')
    chart_labels = []
    chart_data = []
    running_pl = 0
    for s in all_sold_stocks:
        val = float(s.profit_loss)
        if s.market in (MarketType.US, MarketType.CRYPTO):
            val *= usd_thb
        running_pl += val
        chart_labels.append(s.sold_at.strftime('%Y-%m-%d %H:%M'))
        chart_data.append(running_pl)

    # ── Available Months for Filter ──
    # สร้าง list ของเดือน/ปีที่มีรายการขายจริง เพื่อให้ User เลือก
    available_months = []
    seen_months = set()
    for s in all_sold_stocks[::-1]:
        m_key = s.sold_at.strftime('%Y-%m')
        if m_key not in seen_months:
            available_months.append({
                'key': m_key,
                'name': s.sold_at.strftime('%B %Y')
            })
            seen_months.add(m_key)

    # ── Filter Transactions ──
    from django.utils import timezone
    now = timezone.now()
    default_month = now.strftime('%Y-%m')
    
    # ถ้าเดือนปัจจุบันไม่มีรายการขาย ให้เลือกเดือนล่าสุดที่มีรายการเป็นค่าเริ่มต้น
    if not all_sold_stocks.filter(sold_at__year=now.year, sold_at__month=now.month).exists() and available_months:
        default_month = available_months[0]['key']

    selected_month = request.GET.get('month', default_month)
    
    # ถ้าระบุ 'all' จะแสดงทั้งหมดเหมือนเดิม
    if selected_month == 'all':
        sold_stocks = all_sold_stocks[::-1]
    else:
        try:
            yr, mn = map(int, selected_month.split('-'))
            sold_stocks = all_sold_stocks.filter(sold_at__year=yr, sold_at__month=mn).order_by('-sold_at')
        except:
            sold_stocks = all_sold_stocks[::-1]

    # ── Monthly Summary (Table on the right) ──
    from collections import defaultdict
    monthly_summary_dict = defaultdict(lambda: {'items': [], 'total_pl': 0})
    for s in all_sold_stocks:
        month_key = s.sold_at.strftime('%B %Y')
        month_id = s.sold_at.strftime('%Y-%m')
        monthly_summary_dict[month_key]['items'].append(s)
        monthly_summary_dict[month_key]['month_id'] = month_id
        val = float(s.profit_loss)
        if s.market in (MarketType.US, MarketType.CRYPTO):
            val *= usd_thb
        monthly_summary_dict[month_key]['total_pl'] += val
    
    monthly_summary = []
    for m_name in [m['name'] for m in available_months]:
        monthly_summary.append({
            'month_name': m_name,
            'month_id': monthly_summary_dict[m_name]['month_id'],
            'items': monthly_summary_dict[m_name]['items'],
            'total_pl': monthly_summary_dict[m_name]['total_pl']
        })
    
    # ── Portfolio Cash Summary ──
    from stocks.models import CashTransaction, PortfolioCash
    cash_thb_obj = PortfolioCash.objects.filter(user=request.user, currency='THB').first()
    cash_usd_obj = PortfolioCash.objects.filter(user=request.user, currency='USD').first()
    total_cash_thb = float(cash_thb_obj.balance) if cash_thb_obj else 0.0
    total_cash_usd = float(cash_usd_obj.balance) if cash_usd_obj else 0.0
    
    cash_transactions = CashTransaction.objects.filter(user=request.user).order_by('-created_at')[:500]
    
    # ── Portfolio Fund Summary ──
    from stocks.models import PortfolioFund
    funds = PortfolioFund.objects.filter(user=request.user)
    for f in funds:
        f.pl = float(f.market_value) - float(f.cost)
    total_fund_cost = sum(float(f.cost) for f in funds)
    total_fund_value = sum(float(f.market_value) for f in funds)
    total_fund_pl = total_fund_value - total_fund_cost

    context = {
        'items': items,
        'total_market_value': total_market_value,
        'total_gain_loss': total_gain_loss,
        'total_set_value': total_set_value,
        'total_set_cost': total_set_cost,
        'total_set_pl': total_set_pl,
        'total_us_value': total_us_value,
        'total_us_cost': total_us_cost,
        'total_us_pl': total_us_pl,
        'total_us_value_thb': round(total_us_value * usd_thb, 2),
        'total_us_cost_thb': round(total_us_cost * usd_thb, 2),
        'total_us_pl_thb': round(total_us_pl * usd_thb, 2),
        'total_crypto_value': total_crypto_value,
        'total_crypto_cost': total_crypto_cost,
        'total_crypto_pl': total_crypto_pl,
        'total_crypto_value_thb': round(total_crypto_value * usd_thb, 2),
        'total_crypto_cost_thb': round(total_crypto_cost * usd_thb, 2),
        'total_crypto_pl_thb': round(total_crypto_pl * usd_thb, 2),
        'has_set': any(it.get('market') == MarketType.SET for it in items),
        'has_us': any(it.get('market') == MarketType.US for it in items),
        'has_crypto': any(it.get('market') == MarketType.CRYPTO for it in items),
        'usd_thb': round(usd_thb, 2),
        'total_combined_value': total_set_value + (total_us_value + total_crypto_value + total_cash_usd) * usd_thb + total_cash_thb + total_fund_value,
        'total_combined_cost': total_set_cost + (total_us_cost + total_crypto_cost) * usd_thb + total_fund_cost,
        'total_combined_pl': total_set_pl + (total_us_pl + total_crypto_pl) * usd_thb + total_fund_pl,
        'total_fund_value': total_fund_value,
        'total_fund_cost': total_fund_cost,
        'total_fund_pl': total_fund_pl,
        'funds': funds,
        'total_cash_thb': total_cash_thb,
        'total_cash_usd': total_cash_usd,
        'total_cash_combined_thb': total_cash_thb + (total_cash_usd * usd_thb),
        'cash_transactions': cash_transactions,
        'categories': AssetCategory.choices,
        'market_types': MarketType.choices,
        'title': 'My Portfolio',
        'ai_analysis': ai_analysis,
        'sold_stocks': sold_stocks,
        'monthly_summary': monthly_summary,
        'available_months': available_months,
        'selected_month': selected_month,
        'chart_labels': json.dumps(chart_labels),
        'chart_data': json.dumps(chart_data),
    }
    return render(request, 'stocks/portfolio.html', context)

@login_required
def add_cash_transaction(request):
    """
    บันทึกรายการเงินเข้า/ออก และอัปเดตยอดคงเหลือใน PortfolioCash
    """
    if request.method == 'POST':
        from decimal import Decimal

        from stocks.models import CashTransaction, PortfolioCash
        
        amount = Decimal(request.POST.get('amount', '0'))
        currency = request.POST.get('currency', 'THB')
        tx_type = request.POST.get('transaction_type')
        is_absolute = request.POST.get('is_absolute') == 'true'
        note = request.POST.get('note', '')
        
        # ค้นหาหรือสร้าง Cash Object
        cash_obj, created = PortfolioCash.objects.get_or_create(user=request.user, currency=currency)
        
        if is_absolute:
            cash_obj.balance = amount
            cash_obj.save()
            messages.success(request, f"อัปเดตยอดคงเหลือ {currency} เรียบร้อยแล้ว")
        else:
            # แบบ Transaction เดิม (Deposit/Withdrawal)
            if tx_type in ['WITHDRAWAL', 'BUY', 'FEE']:
                if amount > 0: amount = -amount
            
            CashTransaction.objects.create(
                user=request.user,
                amount=amount,
                currency=currency,
                transaction_type=tx_type,
                note=note
            )
            cash_obj.balance = Decimal(str(cash_obj.balance)) + amount
            cash_obj.save()
            messages.success(request, f"บันทึกรายการ {tx_type} เรียบร้อยแล้ว")
        
        return redirect('stocks:portfolio_list')
    
    return redirect('stocks:portfolio_list')

@login_required
def update_portfolio_fund(request):
    """
    แก้ไขข้อมูลกองทุนรวมแบบบันทึกด้วยมือ (Enforce single record)
    """
    if request.method == 'POST':
        from decimal import Decimal

        from stocks.models import PortfolioFund
        
        name = request.POST.get('name', 'Total Mutual Funds')
        cost = Decimal(request.POST.get('cost', '0'))
        market_value = Decimal(request.POST.get('market_value', '0'))
        
        # ป้องกันกรณีมีข้อมูลเก่าหลายตัว (MultipleObjectsReturned fix)
        funds = PortfolioFund.objects.filter(user=request.user)
        if funds.exists():
            fund = funds.first()
            # ลบตัวอื่นๆ ทิ้งเพื่อให้เหลือตัวเดียวตามนโยบายใหม่
            funds.exclude(id=fund.id).delete()
        else:
            fund = PortfolioFund.objects.create(user=request.user, name=name, cost=0, market_value=0)
        
        fund.name = name
        fund.cost = cost
        fund.market_value = market_value
        fund.save()
        
        messages.success(request, f"อัปเดตยอดเงินลงทุนกองทุนเรียบร้อยแล้ว")
        return redirect('stocks:portfolio_list')
    
    return redirect('stocks:portfolio_list')
    
    return redirect('stocks:portfolio_list')

@login_required
def delete_portfolio_fund(request, fund_id):
    from stocks.models import PortfolioFund
    fund = PortfolioFund.objects.filter(id=fund_id, user=request.user).first()
    if fund:
        name = fund.name
        fund.delete()
        messages.success(request, f"ลบกองทุน {name} เรียบร้อยแล้ว")
    return redirect('stocks:portfolio_list')


# ====== Mean Reversion Scanner — helpers ======

@login_required
def add_to_portfolio(request):
    """
    รับ POST form เพิ่มหรืออัปเดต position ในพอร์ต
    รองรับทั้ง AJAX (JSON) และ form submit ปกติ
    """
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST':
        form = AddPortfolioForm(request.POST)
        if form.is_valid():
            symbol = form.cleaned_data['symbol']
            market = form.cleaned_data['market']

            if market == MarketType.SET and not symbol.endswith('.BK'):
                symbol = f"{symbol}.BK"

            Portfolio.objects.update_or_create(
                user=request.user,
                symbol=symbol,
                defaults={
                    'name': form.cleaned_data['name'],
                    'quantity': form.cleaned_data['quantity'],
                    'entry_price': form.cleaned_data['entry_price'],
                    'category': form.cleaned_data['category'],
                    'market': market,
                    'strategy': form.cleaned_data.get('strategy', ''),
                    'trail_multiplier': form.cleaned_data.get('trail_multiplier', 2.5),
                }
            )
            if is_ajax:
                return JsonResponse({'success': True, 'symbol': symbol})
            messages.success(request, f"บันทึก {symbol} เข้าพอร์ตเรียบร้อยแล้ว")
        else:
            # รวม errors ทุก field พร้อม label ที่อ่านเข้าใจง่าย
            field_labels = {
                'symbol': 'Symbol', 'quantity': 'จำนวน', 'entry_price': 'ราคาทุน',
                'market': 'ตลาด', 'category': 'Category', 'trail_multiplier': 'ATR Multiplier',
            }
            error_list = []
            for field, errs in form.errors.items():
                label = field_labels.get(field, field)
                for err in errs:
                    error_list.append(f"{label}: {err}")
            if is_ajax:
                return JsonResponse({'success': False, 'errors': error_list}, status=400)
            for msg in error_list:
                messages.error(request, msg)

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
        form = SellStockForm(request.POST)
        if form.is_valid():
            sell_quantity = form.cleaned_data['quantity']
            sell_price = form.cleaned_data['sell_price']

            if sell_quantity > portfolio_item.quantity:
                messages.error(request, f"จำนวนเกินที่ถือครองอยู่ (มีอยู่ {portfolio_item.quantity} หุ้น)")
                return redirect('stocks:portfolio_list')

            # คำนวณกำไร/ขาดทุน
            cost_of_sold_shares = sell_quantity * portfolio_item.entry_price
            sell_revenue = sell_quantity * sell_price
            profit_loss = sell_revenue - cost_of_sold_shares
            profit_loss_pct = (profit_loss / cost_of_sold_shares * 100) if cost_of_sold_shares > 0 else 0

            # ── Currency Conversion (Tithe calculation requirement) ──
            # ดึงอัตราแลกเปลี่ยน ณ เดี๋ยวนี้ (ตอนขาย)
            fx_rate = 1.0
            if portfolio_item.market == MarketType.US:
                fx_rate = _get_usd_thb()
            
            # บันทึกประวัติการขาย พร้อม market จาก Portfolio
            SoldStock.objects.create(
                user=request.user,
                symbol=portfolio_item.symbol,
                quantity=sell_quantity,
                buy_price=portfolio_item.entry_price,
                bought_at=portfolio_item.added_at,
                sell_price=sell_price,
                profit_loss=profit_loss,
                profit_loss_pct=profit_loss_pct,
                market=portfolio_item.market,
                settlement_rate=fx_rate,
                profit_loss_thb=float(profit_loss) * fx_rate,
                sell_revenue_thb=float(sell_revenue) * fx_rate,
            )

            # อัปเดตพอร์ต
            portfolio_item.quantity -= sell_quantity
            if portfolio_item.quantity <= 0:
                portfolio_item.delete()
                messages.success(request, f"ขาย {portfolio_item.symbol} เรียบร้อยแล้ว (ปิดสถานะ)")
            else:
                portfolio_item.save()
                messages.success(request, f"ขาย {portfolio_item.symbol} จำนวน {sell_quantity} หุ้น เรียบร้อยแล้ว")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{error}")

    return redirect('stocks:portfolio_list')

# ====== Recommendations - คำแนะนำหุ้นรายวันจาก AI ======

@login_required
def portfolio_scan(request):
    """
    สแกน Momentum เฉพาะหุ้นที่อยู่ใน Portfolio ของผู้ใช้
    ใช้ Logic เดียวกันกับ momentum_scanner() แต่เปลี่ยน Input จาก SET100+MAI เป็นหุ้นใน Portfolio
    """
    from types import SimpleNamespace

    from stocks.utils import analyze_momentum_technical, find_supply_demand_zones

    portfolio_items = Portfolio.objects.filter(user=request.user, category='STOCK')

    candidates = []
    scanned_at = None

    if request.method == "POST" or request.GET.get('scan') == 'true':
        import datetime

        import pandas_ta as ta

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
                            eps_growth = float(info.get('earningsQuarterlyGrowth') or info.get('earningsGrowth') or 0) * 100
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


# ====== Entry Finder - กราฟ Sniper Entry พร้อม Supply & Demand Zone ======

@login_required
def realized_pl_report(request):
    """
    รายงานกำไรขาดทุนสะสมที่เกิดขึ้นจริง (Realized P/L)
    พร้อมตัวกรอง รายวัน รายเดือน รายปี และช่วงเวลา
    แปลงกำไรหุ้น US → เงินบาท สำหรับใช้คำนวณทศางค์
    """
    import json
    from collections import defaultdict

    usd_thb = _get_usd_thb()

    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    group_by = request.GET.get('group_by', 'month')

    sold_stocks = list(SoldStock.objects.filter(user=request.user).order_by('sold_at'))

    if start_date:
        from datetime import datetime as _dt
        sold_stocks = [s for s in sold_stocks if s.sold_at.date() >= _dt.strptime(start_date, '%Y-%m-%d').date()]
    if end_date:
        from datetime import datetime as _dt2
        sold_stocks = [s for s in sold_stocks if s.sold_at.date() <= _dt2.strptime(end_date, '%Y-%m-%d').date()]

    # Annotate each record with is_us + pl_thb
    # ใช้ s.market ก่อน (บันทึกตอนขาย) - ถ้าไม่มีหรือ default SET ให้ fallback _is_us_symbol
    us_set = _build_us_symbol_set(request.user)
    for s in sold_stocks:
        if s.market and s.market != MarketType.SET:
            s.is_us = s.market == MarketType.US
        else:
            s.is_us = _is_us_symbol(s.symbol, us_set)
        
        # ลอจิกใหม่: ถ้ามี profit_loss_thb (ที่บันทึกตอนขาย) ให้ใช้ค่านั้นเลย
        # ถ้าเป็น 0 หรือเป็นข้อมูลเก่า ให้คำนวณจาก usd_thb ปัจจุบัน (fallback)
        if hasattr(s, 'profit_loss_thb') and s.profit_loss_thb != 0:
            s.pl_thb = float(s.profit_loss_thb)
        else:
            s.pl_thb = float(s.profit_loss) * usd_thb if s.is_us else float(s.profit_loss)

    summary_dict = defaultdict(lambda: {'items': [], 'total_pl': 0, 'total_pl_thb': 0})
    chart_labels = []
    chart_data = []
    running_pl = 0

    for s in sold_stocks:
        if group_by == 'day':
            key = s.sold_at.strftime('%Y-%m-%d')
        elif group_by == 'year':
            key = s.sold_at.strftime('%Y')
        else:
            key = s.sold_at.strftime('%Y-%m')

        summary_dict[key]['items'].append(s)
        summary_dict[key]['total_pl'] += float(s.profit_loss)
        summary_dict[key]['total_pl_thb'] += s.pl_thb

        running_pl += s.pl_thb
        chart_labels.append(s.sold_at.strftime('%Y-%m-%d %H:%M'))
        chart_data.append(round(running_pl, 2))

    summary_list = []
    for k in sorted(summary_dict.keys(), reverse=True):
        summary_list.append({
            'period': k,
            'items': summary_dict[k]['items'],
            'total_pl': summary_dict[k]['total_pl'],
            'total_pl_thb': summary_dict[k]['total_pl_thb'],
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
        'usd_thb': round(usd_thb, 2),
        'total_pl_thb': sum(s.pl_thb for s in sold_stocks),
    }
    return render(request, 'stocks/realized_pl_report.html', context)


# ======================================================================
# PRECISION SCAN AI ANALYSIS
# ======================================================================


@login_required
def tithe_report(request):
    """
    แสดงกำไร/ขาดทุนรายเดือนจากการขายหุ้น
    คำนวณทศางค์ 10% จากเดือนที่มีกำไร พร้อม track การจ่าย
    แปลงกำไรหุ้น US → เงินบาท ด้วยอัตราแลกเปลี่ยนปัจจุบัน
    """
    import calendar
    from collections import defaultdict

    # ── Exchange rate ──
    usd_thb = _get_usd_thb()
    usd_thb_d = Decimal(str(round(usd_thb, 4)))

    # ── Aggregate per month with USD→THB conversion ──
    sold_stocks = SoldStock.objects.filter(user=request.user).order_by('sold_at')
    us_set = _build_us_symbol_set(request.user)
    monthly_raw = defaultdict(Decimal)
    for s in sold_stocks:
        if s.market and s.market != MarketType.SET:
            is_us = s.market == MarketType.US
        else:
            is_us = _is_us_symbol(s.symbol, us_set)
        
        # ลอจิกใหม่: ใช้ profit_loss_thb ที่บันทึกไว้ ณ วันที่ขาย (ถ้ามี)
        if hasattr(s, 'profit_loss_thb') and s.profit_loss_thb != 0:
            pl_thb = Decimal(str(s.profit_loss_thb))
        else:
            pl_raw = Decimal(str(s.profit_loss or 0))
            pl_thb = pl_raw * usd_thb_d if is_us else pl_raw
            
        key = (s.sold_at.year, s.sold_at.month)
        monthly_raw[key] += pl_thb

    tithe_map = {
        (t.year, t.month): t
        for t in TitheRecord.objects.filter(user=request.user)
    }

    months = []
    total_profit = Decimal('0')
    total_tithe_owed = Decimal('0')
    total_tithe_paid = Decimal('0')

    for (yr, mo) in sorted(monthly_raw.keys(), reverse=True):
        pl = monthly_raw[(yr, mo)].quantize(Decimal('0.01'))
        tithe = (pl * Decimal('0.10')).quantize(Decimal('0.01')) if pl > 0 else Decimal('0')

        rec = tithe_map.get((yr, mo))
        is_paid = rec.is_paid if rec else False
        paid_at = rec.paid_at if rec else None

        if pl > 0:
            total_profit += pl
            total_tithe_owed += tithe
            if is_paid:
                total_tithe_paid += tithe

        months.append({
            'year': yr,
            'month': mo,
            'month_name': calendar.month_abbr[mo],
            'pl': pl,
            'tithe': tithe,
            'is_paid': is_paid,
            'paid_at': paid_at,
        })

    # Build chart data (chronological order = reversed from newest-first list)
    chart_months = list(reversed(months))
    chart_data = json.dumps({
        'labels':  [f"{m['month_name']} {m['year']}" for m in chart_months],
        'profit':  [float(m['pl'])    for m in chart_months],
        'tithe':   [float(m['tithe']) for m in chart_months],
    }, ensure_ascii=False)

    context = {
        'months': months,
        'total_profit': total_profit,
        'total_tithe_owed': total_tithe_owed,
        'total_tithe_paid': total_tithe_paid,
        'total_tithe_remaining': total_tithe_owed - total_tithe_paid,
        'chart_json': chart_data,
        'usd_thb': round(usd_thb, 2),
    }
    return render(request, 'stocks/tithe_report.html', context)


@login_required
def tithe_mark_paid(request):
    """Toggle paid/unpaid status for a tithe month via AJAX POST."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    from django.utils import timezone

    try:
        yr = int(request.POST.get('year', 0))
        mo = int(request.POST.get('month', 0))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid year/month'}, status=400)

    rec, _ = TitheRecord.objects.get_or_create(
        user=request.user, year=yr, month=mo,
        defaults={'is_paid': False}
    )
    rec.is_paid = not rec.is_paid
    rec.paid_at = timezone.now() if rec.is_paid else None
    rec.save()

    return JsonResponse({
        'is_paid': rec.is_paid,
        'paid_at': rec.paid_at.strftime('%d %b %Y %H:%M') if rec.paid_at else None,
    })


# ======================================================================
# US MOMENTUM SCANNER (no-DB) - same logic as SET scanner, US stocks
# ======================================================================

@login_required
@require_POST
def portfolio_refresh_prices(request):
    """
    Lightweight price refresh — fetches current price via fast_info (parallel)
    and updates highest_price in Portfolio if price has risen.
    Returns JSON: { updated: [...], skipped: [...], errors: [...] }
    """
    import concurrent.futures

    from django.http import JsonResponse

    items = list(Portfolio.objects.filter(user=request.user, category='STOCK'))
    if not items:
        return JsonResponse({'updated': [], 'skipped': [], 'errors': []})

    def _fetch_price(item):
        symbol = item.symbol.upper()
        market = item.market  # 'SET', 'US', 'CRYPTO', 'OTHER'

        if market == 'SET':
            sym_yf = symbol if symbol.endswith('.BK') else f"{symbol}.BK"
        elif market == 'CRYPTO':
            # BTC → BTC-USD, BTC-USD → BTC-USD (ใช้ตามที่บันทึกไว้)
            sym_yf = symbol if '-' in symbol else f"{symbol}-USD"
        else:
            # US + OTHER: ใช้ symbol ตรงๆ (DELL, KEY, AAPL ฯลฯ)
            sym_yf = symbol.replace('.BK', '')

        try:
            fi = yf.Ticker(sym_yf).fast_info
            price = float(getattr(fi, 'last_price', None) or 0)
            return item, price
        except Exception:
            return item, 0.0

    updated, skipped, errors = [], [], []

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_price, item): item for item in items}
        for fut in concurrent.futures.as_completed(futures):
            orig_item = futures[fut]
            try:
                item, price = fut.result(timeout=15)
                if price <= 0:
                    errors.append(item.symbol)
                    continue
                old_high = float(item.highest_price or 0)
                if price > old_high:
                    item.highest_price = price
                    item.save(update_fields=['highest_price'])
                    updated.append({'symbol': item.symbol, 'price': price, 'prev_high': old_high})
                else:
                    skipped.append({'symbol': item.symbol, 'price': price, 'highest': old_high})
            except Exception:
                errors.append(orig_item.symbol)

    return JsonResponse({'updated': updated, 'skipped': skipped, 'errors': errors})

@csrf_exempt
@login_required
def manual_update_trade_exit(request):
    """อนุญาตให้ user กรอก exit price ด้วยตนเอง สำหรับ trade ที่ API ไม่ส่งข้อมูลกลับมา"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)
    import json
    from decimal import Decimal, InvalidOperation

    from stocks.models import TradeOrder

    try:
        data       = json.loads(request.body)
        order_id   = data.get('order_id')
        exit_price = data.get('exit_price')

        if not order_id or exit_price is None:
            return JsonResponse({'success': False, 'error': 'order_id and exit_price required'})

        order = TradeOrder.objects.get(id=order_id, user=request.user)
        ep    = Decimal(str(exit_price))
        order.exit_price = ep

        if order.entry_price:
            diff = float(ep) - float(order.entry_price)
            if order.order_type == 'SELL':
                diff = -diff
            order.pips = round(diff, 2)
            lot = float(order.volume) if order.volume else 0.01
            order.gross_pl    = round(diff * lot * 100, 2)
            order.profit_loss = Decimal(str(order.gross_pl))

        if not order.exit_reason:
            order.exit_reason = 'MANUAL'
        if not order.closed_at:
            from django.utils import timezone
            order.closed_at = timezone.now()

        order.save()
        return JsonResponse({'success': True, 'pl': float(order.profit_loss)})

    except TradeOrder.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Order not found'})
    except (InvalidOperation, ValueError) as e:
        return JsonResponse({'success': False, 'error': f'Invalid price: {e}'})


# ==============================================================================
# AI Daily Agent Reports (SEPA / CAN SLIM / Trend Following / Momentum + Portfolio comparison)
# ==============================================================================

