from .base import * 

from .base import (
    _get_usd_thb, _compute_signals, _get_market_condition, _get_precision_scan_data,
    _US_SECTOR_MAP, _US_MOMENTUM_SYMBOLS, _build_us_symbol_set, _is_us_symbol,
    _seed_us_symbols, _seed_value_symbols, _score_value_candidate, _check_rate_limit
)

@login_required
def portfolio_exit_plan(request):
    """
    แสดงแผนออกจากหุ้นแต่ละตัวในพอร์ต พร้อม:
    - Progress bar: SL → Entry → Current → TP
    - Action recommendation ชัดเจน (ออกทันที / ทยอยขาย / เฝ้า / ถือต่อ)
    - สัญญาณออกที่ active อยู่
    - เรียงตาม SELL Score สูงสุดก่อน (urgent first)
    """
    portfolio_items = Portfolio.objects.filter(user=request.user)
    items = []

    for item in portfolio_items:
        try:
            symbol = item.symbol
            # Determine correct symbol string for yfinance based on database market field
            fetch_symbol = symbol
            if item.market == MarketType.SET and not symbol.endswith('.BK'):
                fetch_symbol = f"{symbol}.BK"
            elif item.market == MarketType.CRYPTO and '-' not in symbol:
                fetch_symbol = f"{symbol}-USD"
            
            t = yf.Ticker(fetch_symbol)
            hist = t.history(period="1y")

            # Fallback if empty (for robustness with manually entered symbols)
            if hist.empty and fetch_symbol == symbol:
                alt_sym = f"{symbol}.BK" if ".BK" not in symbol else symbol.replace(".BK", "")
                print(f"DEBUG: {symbol} empty, trying {alt_sym}")
                t = yf.Ticker(alt_sym)
                hist = t.history(period="1y")
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = [col[0] for col in hist.columns]
            hist = hist.loc[:, ~hist.columns.duplicated()]

            current_price = float(hist['Close'].iloc[-1]) if not hist.empty else 0
            day_change = 0
            if not hist.empty and len(hist) >= 2:
                prev = float(hist['Close'].iloc[-2])
                day_change = ((current_price - prev) / prev * 100) if prev else 0

            # ====== Turtle Exit Logic (S1: 10D Low, S2: 20D Low) ======
            turtle_s1_exit = 0
            turtle_s2_exit = 0
            s1_hit = s2_hit = False
            
            if not hist.empty:
                # Use daily Low for Turtle exits
                hist_lows = hist['Low']
                if len(hist_lows) >= 10:
                    turtle_s1_exit = float(hist_lows.tail(10).min())
                if len(hist_lows) >= 20:
                    turtle_s2_exit = float(hist_lows.tail(20).min())
                
                s1_hit = current_price <= turtle_s1_exit if turtle_s1_exit > 0 else False
                s2_hit = current_price <= turtle_s2_exit if turtle_s2_exit > 0 else False

            entry_price  = float(item.entry_price or 0)
            quantity     = float(item.quantity or 0)
            gain_loss_pct = ((current_price - entry_price) / entry_price * 100) if entry_price else 0

            # days held
            from datetime import date
            days_held = (date.today() - item.added_at.date()).days if item.added_at else 0

            # ดึง PrecisionScanCandidate
            clean_symbol = symbol.split('.')[0].upper()
            from stocks.models import PrecisionScanCandidate
            prec_data = (PrecisionScanCandidate.objects
                         .filter(user=request.user, symbol=clean_symbol)
                         .order_by('-scan_run').first())

            sl_price = tp_price = rsi_val = adx_val = None
            price_pattern = ''
            price_pattern_score = 0
            rel_1m = rel_3m = 0.0
            rvol_bullish = True
            rvol = 1.0
            supply_zone_start = year_high = 0
            cmf_val = None

            if prec_data:
                sl_price    = prec_data.stop_loss
                tp_price    = prec_data.supply_zone_start
                rsi_val     = prec_data.rsi
                adx_val     = prec_data.adx
                price_pattern       = prec_data.price_pattern
                price_pattern_score = prec_data.price_pattern_score
                rel_1m      = prec_data.rel_momentum_1m
                rel_3m      = prec_data.rel_momentum_3m
                rvol_bullish = prec_data.rvol_bullish
                rvol        = prec_data.rvol
                supply_zone_start = prec_data.supply_zone_start or 0
                year_high   = prec_data.year_high or 0
                cmf_val     = prec_data.cmf

            signals = _compute_signals(prec_data, current_price) if prec_data else {'buy_score': 0, 'sell_score': 0, 'exit_signal': ''}
            sell_score   = signals['sell_score']
            exit_signal  = signals['exit_signal']

            # Boost sell score if Turtle exits are hit
            if s1_hit: sell_score = max(sell_score, 75)
            if s2_hit: sell_score = max(sell_score, 90)
            
            if sell_score >= 70: exit_signal = 'STRONG EXIT'
            elif sell_score >= 50: exit_signal = 'EXIT'
            elif sell_score >= 30: exit_signal = 'WATCH'

            # ====== Progress Bar: SL → Entry → Current → TP ======
            progress_pct   = None
            current_pct    = None
            entry_pct      = None
            sl_hit         = False
            tp_hit         = False

            if sl_price and tp_price and tp_price > sl_price:
                total_range    = tp_price - sl_price
                sl_hit         = current_price <= sl_price
                tp_hit         = current_price >= tp_price
                current_pct    = min(100, max(0, (current_price - sl_price) / total_range * 100))
                entry_pct      = min(100, max(0, (entry_price - sl_price) / total_range * 100))

            # ====== Momentum Classification ======
            # หุ้นผู้นำ (Leader) = Momentum แข็งแกร่งกว่าตลาดมาก
            is_leader = (rel_3m and rel_3m > 10) or (rel_1m and rel_1m > 5) or (adx_val and adx_val > 30)
            # หุ้นล้าหลัง (Laggard) = Momentum อ่อนแอกว่าตลาด
            is_laggard = (rel_3m and rel_3m < -5) or (adx_val and adx_val < 18)

            # ====== Action Recommendation (Momentum-Aware) ======
            if exit_signal == 'STRONG EXIT':
                if is_leader:
                    action       = 'ทยอยขาย (Leader)'
                    action_style = 'warning'
                    action_detail = f"สัญญาณขายแรง แต่หุ้นยังเป็นผู้นำ (RS สูง) - ขาย 70% เก็บ 30% เผื่อเด้งแรง"
                else:
                    action       = 'ออกทันที'
                    action_style = 'danger'
                    action_detail = f"ขายทั้งหมด {quantity:.0f} หุ้น - สัญญาณเทคนิคขาลงชัดเจนและหุ้นเริ่มล้าหลัง"
            
            elif sl_hit:
                if entry_price > 0 and current_price < entry_price:
                    if is_leader:
                        action       = 'เฝ้าจุดเด้ง (Cut?)'
                        action_style = 'warning'
                        action_detail = "หลุด SL แต่เป็นหุ้นผู้นำ - รอดูการดึงกลับที่เส้นค่าเฉลี่ย ถ้าไม่เด้งต้องคัท"
                    else:
                        action       = 'ตัดขาดทุน (Cut Loss)'
                        action_style = 'danger'
                        action_detail = f"ราคาหลุด SL และหุ้นอ่อนแอกว่าตลาด - แนะนำขายทันทีเพื่อปกป้องเงินทุน"
                else:
                    action       = 'ล็อกกำไร (Trailing)'
                    action_style = 'warning'
                    action_detail = f"ราคาหลุดจุดเฝ้าระวัง (SL) - กำไรยังเหลือ {gain_loss_pct:.1f}% แนะนำขายล็อกกำไร"

            elif exit_signal == 'EXIT':
                if is_leader:
                    action       = 'ถือต่อ (Leader)'
                    action_style = 'success'
                    action_detail = "มีสัญญาณขายบ้าง แต่ momentum แข็งแกร่งมาก - ถือต่อเพื่อรันเทรน"
                else:
                    action       = 'ทยอยขาย 50%'
                    action_style = 'warning'
                    action_detail = f"หุ้นเริ่มหมดแรงและไม่ใช่ผู้นำ - ขายครึ่งหนึ่งเก็บกำไรไว้ก่อน"

            elif is_laggard and gain_loss_pct < 0:
                action       = 'พิจารณาเปลี่ยนตัว'
                action_style = 'warning-soft'
                action_detail = "หุ้นเคลื่อนไหวช้ากว่าตลาด (Laggard) - แนะนำพิจารณาเปลี่ยนไปถือหุ้นผู้นำตัวอื่น"

            elif tp_price and current_price >= tp_price * 0.95:
                action       = 'ใกล้ TP'
                action_style = 'info'
                action_detail = f"ราคาใกล้เป้าหมายแล้ว - เตรียมทยอยรับทรัพย์"

            else:
                action       = 'ถือต่อ'
                action_style = 'success'
                action_detail = "ยังไม่มีสัญญาณออก และโครงสร้างราคายังดี - ถือรันเทรนต่อไป"

            # ====== Active Exit Triggers ======
            triggers = []
            if sl_hit:
                triggers.append({'label': 'SL HIT - หลุด Stop Loss', 'level': 'danger'})
            if tp_hit:
                triggers.append({'label': f'TP Hit - ถึงเป้า ฿{tp_price:.2f}', 'level': 'danger'})
            if rsi_val and rsi_val > 78:
                triggers.append({'label': f'RSI {rsi_val:.0f} - overbought มาก', 'level': 'danger'})
            elif rsi_val and rsi_val > 72:
                triggers.append({'label': f'RSI {rsi_val:.0f} - เริ่ม overbought', 'level': 'warning'})
            if not rvol_bullish and rvol >= 1.5:
                triggers.append({'label': f'RVOL {rvol:.1f}x Bear - แรงขายเข้ามา', 'level': 'danger'})
            elif not rvol_bullish:
                triggers.append({'label': 'RVOL Bear - volume หันขาลง', 'level': 'warning'})
            if rel_1m < -5:
                triggers.append({'label': f'Rel Mom 1m {rel_1m:.1f}% - แพ้ SET มาก', 'level': 'warning'})
            elif rel_1m < 0:
                triggers.append({'label': f'Rel Mom 1m {rel_1m:.1f}% - เริ่มแพ้ SET', 'level': 'info'})
            if price_pattern_score < -5:
                triggers.append({'label': f'Pattern: {price_pattern} - สัญญาณขาย', 'level': 'danger'})
            elif price_pattern_score < 0:
                triggers.append({'label': f'Pattern: {price_pattern}', 'level': 'warning'})
            if adx_val and adx_val < 20:
                triggers.append({'label': f'ADX {adx_val:.0f} - เทรนด์อ่อนแรง', 'level': 'warning'})
            if cmf_val is not None:
                if cmf_val < -0.1:
                    triggers.append({'label': f'CMF {cmf_val:.2f} - Distribution ชัดเจน เงินไหลออก', 'level': 'danger'})
                elif cmf_val < -0.05:
                    triggers.append({'label': f'CMF {cmf_val:.2f} - เริ่มมีแรงขายสุทธิ', 'level': 'warning'})
            if not triggers and exit_signal == '':
                triggers.append({'label': 'ไม่มีสัญญาณออก - ถือต่อได้', 'level': 'success'})
            
            # Turtle-specific signals (always show if near or hit)
            if s1_hit:
                triggers.append({'label': f'TURTLE S1 EXIT - หลุด 10D Low ({turtle_s1_exit:.2f})', 'level': 'danger'})
            elif turtle_s1_exit > 0 and current_price <= turtle_s1_exit * 1.02:
                triggers.append({'label': f'TURTLE S1 NEAR - ใกล้ 10D Low ({turtle_s1_exit:.2f})', 'level': 'warning'})

            if s2_hit:
                triggers.append({'label': f'TURTLE S2 EXIT - หลุด 20D Low ({turtle_s2_exit:.2f})', 'level': 'danger'})
            elif turtle_s2_exit > 0 and current_price <= turtle_s2_exit * 1.02:
                triggers.append({'label': f'TURTLE S2 NEAR - ใกล้ 20D Low ({turtle_s2_exit:.2f})', 'level': 'warning'})

            items.append({
                'obj':          item,
                'current_price': current_price,
                'day_change':   day_change,
                'entry_price':  entry_price,
                'gain_loss_pct': gain_loss_pct,
                'quantity':     quantity,
                'days_held':    days_held,
                'sl_price':     sl_price,
                'tp_price':     tp_price,
                'turtle_s1':    turtle_s1_exit,
                'turtle_s2':    turtle_s2_exit,
                's1_hit':       s1_hit,
                's2_hit':       s2_hit,
                'rsi':          rsi_val,
                'adx':          adx_val,
                'price_pattern': price_pattern,
                'price_pattern_score': price_pattern_score,
                'rel_1m':       rel_1m,
                'rel_3m':       rel_3m,
                'rvol':         rvol,
                'rvol_bullish': rvol_bullish,
                'sell_score':   sell_score,
                'exit_signal':  exit_signal,
                'current_pct':  current_pct,
                'entry_pct':    entry_pct,
                'sl_hit':       sl_hit,
                'tp_hit':       tp_hit,
                'action':       action,
                'action_style': action_style,
                'action_detail': action_detail,
                'triggers':     triggers,
                'is_leader':    is_leader,
                'is_laggard':   is_laggard,
                'cmf':          cmf_val,
            })
        except Exception as e:
            print(f"[ExitPlan] Error {item.symbol}: {e}")
            continue

    # เรียงตาม SELL Score สูงสุดก่อน
    items.sort(key=lambda x: x['sell_score'], reverse=True)

    # ====== Portfolio Health Summary ======
    urgent_count   = sum(1 for i in items if i['exit_signal'] in ('STRONG EXIT',) or i['sl_hit'])
    warning_count  = sum(1 for i in items if i['exit_signal'] == 'EXIT')
    watch_count    = sum(1 for i in items if i['exit_signal'] == 'WATCH')
    healthy_count  = sum(1 for i in items if not i['exit_signal'] and not i['sl_hit'])
    total_count    = len(items)
    avg_sell_score = round(sum(i['sell_score'] for i in items) / total_count, 1) if total_count else 0

    # Market Condition
    market_condition = {'phase': 'UNKNOWN', 'label': 'ไม่มีข้อมูล', 'color': 'secondary', 'score': 0}
    try:
        from datetime import datetime as _mcdt
        from datetime import timedelta as _mctd

        import pytz as _mcpytz
        _mc_bkk   = _mcpytz.timezone('Asia/Bangkok')
        _mc_now   = _mcdt.now(_mc_bkk)
        _mc_end   = _mc_now.date().strftime('%Y-%m-%d')
        _mc_start = (_mc_now.date() - _mctd(days=430)).strftime('%Y-%m-%d')
        _mc_df = yf.download("^SET.BK", start=_mc_start, end=_mc_end, interval="1d", progress=False)
        if _mc_df is not None and not _mc_df.empty:
            if isinstance(_mc_df.columns, pd.MultiIndex):
                _mc_df.columns = _mc_df.columns.droplevel(1)
            market_condition = _get_market_condition(_mc_df)
    except Exception:
        pass

    return render(request, 'stocks/portfolio_exit_plan.html', {
        'items': items,
        'urgent_count':  urgent_count,
        'warning_count': warning_count,
        'watch_count':   watch_count,
        'healthy_count': healthy_count,
        'total_count':   total_count,
        'avg_sell_score': avg_sell_score,
        'market_condition': market_condition,
    })


# ====== Portfolio Exit Plan AI Analysis ======
@login_required
def portfolio_exit_plan_ai_analysis(request):
    """
    สร้าง AI Analysis สำหรับ Portfolio Exit Plan ผ่าน AJAX
    """
    portfolio_items = Portfolio.objects.filter(user=request.user)
    port_str = ""
    for item in portfolio_items:
        clean_symbol = item.symbol.split('.')[0].upper()
        from stocks.models import PrecisionScanCandidate
        prec_data = PrecisionScanCandidate.objects.filter(user=request.user, symbol=clean_symbol).order_by('-scan_run').first()
        port_str += f"- Symbol: {item.symbol}, Qty: {item.quantity}, Entry Price: {item.entry_price}, Strategy: {item.strategy or 'Precision/Breakout'}\n"
        if prec_data:
            port_str += f"  RSI: {prec_data.rsi}, ADX: {prec_data.adx}, RVOL: {prec_data.rvol}, Rel Mom 3m: {prec_data.rel_momentum_3m}, Stop Loss: {prec_data.stop_loss}, Take Profit (Resistance/High): {prec_data.supply_zone_start}\n"
    
    prompt = f"""
    You are an expert Stock Portfolio Analyst specializing in "Precision Momentum Trading", "Stage 2 Breakout Trading (Minervini/O'Neil style)", and advanced exit strategies.
    The user has the following assets in their portfolio (with Entry Price, Stop Loss, Take Profit target, and Momentum metrics):
    {port_str}

    CRITICAL RULES FOR RECOMMENDATIONS:
    1. **Do not recommend selling just because the price reaches the Take Profit target (which is typically the previous 52-week high or resistance zone)**. The user's primary objective is **Breakout Trading** (waiting for the price to break out to new highs and ride the trend).
    2. **Look at Momentum (ADX, CMF, Rel Mom, and EMA Alignment)**:
       - If a stock has a strong trend (ADX > 25, positive CMF, strong Rel Mom), recommend **HOLDing to wait for a Breakout** and using a **Trailing Stop** (e.g., 10-day Low or 2.5x ATR) to protect profits rather than selling immediately.
       - Tell them: "ถือลุ้นเบรกเอาต์ (Hold for Breakout) และใช้ Trailing Stop รันเทรนด์" instead of recommending "ขายทำกำไร (Take Profit)".
    3. **Only recommend Take Profit (ขายทำกำไร) if there is clear evidence of trend exhaustion**, such as:
       - RSI is extremely overbought (> 80-85) with bearish divergence.
       - CMF is negative (below -0.05 or -0.10) indicating heavy institutional distribution.
       - A clear bearish price pattern has occurred.
       - RVOL shows a massive blow-off top (extreme volume on a massive green/red day with price reversing).
    4. **Tailor recommendations based on the stock's Strategy**:
       - If the strategy is "VCP" or "Cup & Handle", emphasize waiting for the pivot breakout and using trailing stops.
       - If "Turtle S1/S2", emphasize exiting only when the 10-day or 20-day low is breached.

    Please provide a DEEP analysis of each asset's status and its current trend.
    Include actionable insights and strategic recommendations for EACH stock in Thai Language (Sarabun professional tone).

    Format your response beautifully in Markdown.
    IMPORTANT RULES:
    1. Output ONLY the raw markdown text. Do not wrap in ```markdown blocks.
    2. Analyze each stock one by one.
    3. Do NOT include conversational preamble.
    """
    
    try:
        model_name_to_use = "gemini-2.5-flash"
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=model_name_to_use,
            contents=prompt
        )
        ai_analysis = response.text
        if ai_analysis.startswith("```markdown"):
            ai_analysis = ai_analysis[len("```markdown"):].strip()
        if ai_analysis.endswith("```"):
            ai_analysis = ai_analysis[:-3].strip()
        return JsonResponse({'success': True, 'analysis': ai_analysis})
    except Exception as e:
        return JsonResponse({'success': False, 'error': f"AI Error: {str(e)}"})

# ====== Portfolio Management - เพิ่ม/ลบ รายการพอร์ต ======

@login_required
def morning_briefing(request):
    """
    รายงานสรุปประจำวัน - กดปุ่มเดียว AI รวมข้อมูลทั้งหมด:
    Portfolio + Momentum SET/US + Precision + SEPA + Cup&Handle + Macro
    แล้วสร้างแผนซื้อ/ขายและภาพรวมเศรษฐกิจ
    """
    from django.core.cache import cache as _cp
    from django.http import JsonResponse as _JR

    from stocks.models import (
        CupHandleCandidate as _CHC,
    )
    from stocks.models import (
        MomentumCandidate as _MC,
    )
    from stocks.models import (
        MorningBriefing as _MB,
    )
    from stocks.models import (
        Portfolio as _Port,
    )
    from stocks.models import (
        PrecisionScanCandidate as _PSC,
    )
    from stocks.models import (
        USSepaCandidate as _USC,
    )

    cache_key = f'morning_briefing_{request.user.id}'

    # ── AJAX poll ────────────────────────────────────────────────
    if request.GET.get('mb_status') == '1':
        return _JR(_cp.get(cache_key, {'state': 'idle'}))

    # ── POST: trigger generation ──────────────────────────────────
    if request.method == 'POST':
        existing = _cp.get(cache_key, {})
        if existing.get('state') == 'running':
            return redirect('stocks:morning_briefing')

        _cp.set(cache_key, {'state': 'running', 'phase': 'กำลังรวบรวมข้อมูล…'}, timeout=600)

        def _run(uid, ckey):
            import django; django.setup()
            import google.genai as _genai
            import yfinance as _yf
            from django.conf import settings as _s
            from django.contrib.auth import get_user_model
            from django.core.cache import cache as _c
            from django.utils import timezone as tz

            from stocks.models import (
                CupHandleCandidate,
                MomentumCandidate,
                Portfolio,
                PrecisionScanCandidate,
                USSepaCandidate,
            )
            from stocks.models import (
                MorningBriefing as MB,
            )

            User = get_user_model()
            user = User.objects.get(pk=uid)

            try:
                # ── 1. Portfolio ────────────────────────────────
                _c.set(ckey, {'state': 'running', 'phase': 'ดึงข้อมูล Portfolio…'}, timeout=600)
                portfolio = list(Portfolio.objects.filter(user=user))
                port_lines = []
                for p in portfolio:
                    try:
                        ticker_sym = p.symbol if not p.symbol.endswith('.BK') else p.symbol
                        hist = _yf.Ticker(ticker_sym).history(period='5d')
                        if hist.empty:
                            hist = _yf.Ticker(f'{p.symbol}.BK').history(period='5d')
                        if not hist.empty:
                            cur = float(hist['Close'].iloc[-1])
                            entry = float(p.entry_price)
                            pl_pct = (cur - entry) / entry * 100
                            port_lines.append(f"  - {p.symbol}: ราคาปัจจุบัน {cur:.2f} (ทุน {entry:.2f}, P/L {pl_pct:+.1f}%)")
                        else:
                            port_lines.append(f"  - {p.symbol}: ทุน {float(p.entry_price):.2f} (ไม่สามารถดึงราคาได้)")
                    except Exception:
                        port_lines.append(f"  - {p.symbol}: ทุน {float(p.entry_price):.2f}")

                # ── 2. Momentum SET ─────────────────────────────
                _c.set(ckey, {'state': 'running', 'phase': 'ดึงข้อมูล Momentum SET…'}, timeout=600)
                mom_set = list(MomentumCandidate.objects.filter(user=user, market='SET').order_by('-technical_score')[:10])
                mom_set_lines = [f"  - {c.symbol}: Score={c.technical_score} RSI={c.rsi:.0f} RS={c.rs_rating} Price={c.price:.2f}" for c in mom_set]

                # ── 3. Momentum US ──────────────────────────────
                _c.set(ckey, {'state': 'running', 'phase': 'ดึงข้อมูล Momentum US…'}, timeout=600)
                mom_us = list(MomentumCandidate.objects.filter(user=user, market='US').order_by('-technical_score')[:10])
                mom_us_lines = [f"  - {c.symbol}: Score={c.technical_score} RSI={c.rsi:.0f} RS={c.rs_rating} Price={c.price:.2f}" for c in mom_us]

                # ── 4. Precision SET (latest run) ───────────────
                _c.set(ckey, {'state': 'running', 'phase': 'ดึงข้อมูล Precision…'}, timeout=600)
                prec_run = PrecisionScanCandidate.objects.filter(user=user, market='SET').values_list('scan_run', flat=True).order_by('-scan_run').first()
                prec_set = []
                if prec_run:
                    prec_set = list(PrecisionScanCandidate.objects.filter(user=user, market='SET', scan_run=prec_run).order_by('-technical_score')[:8])
                prec_lines = [f"  - {c.symbol}: Score={c.technical_score} RS={c.rs_rating} Stage2={'✓' if c.stage2 else '✗'} RR={c.risk_reward_ratio:.1f} Prox={c.zone_proximity:.1f}% PP={'✓' if c.pocket_pivot else '✗'} CMF={f'{c.cmf:.2f}' if c.cmf is not None else 'N/A'} VCP={'✓' if c.vcp_setup else '✗'}({c.vcp_contractions}T, {c.vcp_tightness:.1f}%)" for c in prec_set]

                # ── 5. SEPA SET (from Precision) ────────────────
                sepa_set = [c for c in prec_set if c.stage2 and c.rs_rating >= 70]
                sepa_lines = [f"  - {c.symbol}: RS={c.rs_rating} VCP={'✓' if c.vcp_setup else '✗'}({c.vcp_contractions}T, {c.vcp_tightness:.1f}%) PP={'✓' if c.pocket_pivot else '✗'} CMF={f'{c.cmf:.2f}' if c.cmf is not None else 'N/A'} Score={c.technical_score}" for c in sepa_set]

                # ── 6. Cup & Handle ─────────────────────────────
                _c.set(ckey, {'state': 'running', 'phase': 'ดึงข้อมูล Cup & Handle…'}, timeout=600)
                cup_run = CupHandleCandidate.objects.filter(user=user).values_list('scan_run', flat=True).order_by('-scan_run').first()
                cup_list = []
                if cup_run:
                    cup_list = list(CupHandleCandidate.objects.filter(user=user, scan_run=cup_run).order_by('-rs_rating')[:8])
                cup_lines = [f"  - {c.symbol}: Price={c.price:.2f} Breakout={c.breakout_price:.2f} Target={c.target_price:.2f} RS={c.rs_rating}" for c in cup_list]

                # ── 7. US SEPA ──────────────────────────────────
                _c.set(ckey, {'state': 'running', 'phase': 'ดึงข้อมูล US SEPA…'}, timeout=600)
                us_sepa_run = USSepaCandidate.objects.filter(user=user).values_list('scan_run', flat=True).order_by('-scan_run').first()
                us_sepa_list = []
                if us_sepa_run:
                    us_sepa_list = list(USSepaCandidate.objects.filter(user=user, scan_run=us_sepa_run, stage2=True).order_by('-rs_rating')[:8])
                us_sepa_lines = [f"  - {c.symbol}: RS={c.rs_rating} VCP={'✓' if c.vcp_setup else '✗'}({c.vcp_contractions}T, {c.vcp_tightness:.1f}%) PP={'✓' if c.pocket_pivot else '✗'} Price={c.price:.2f}" for c in us_sepa_list]

                # ── 8. Macro data ───────────────────────────────
                _c.set(ckey, {'state': 'running', 'phase': 'ดึงข้อมูล Macro…'}, timeout=600)
                macro_symbols = {
                    'SET Index': '^SET.BK', 'S&P 500': '^GSPC', 'Nasdaq': '^IXIC',
                    'USD/THB': 'USDTHB=X', 'DXY': 'DX-Y.NYB', 'US 10Y Yield': '^TNX',
                    'Gold': 'GC=F', 'WTI Oil': 'CL=F', 'Bitcoin': 'BTC-USD',
                }
                macro_lines = []
                for name, sym in macro_symbols.items():
                    try:
                        h = _yf.Ticker(sym).history(period='5d')
                        if not h.empty and len(h) >= 2:
                            cur = float(h['Close'].iloc[-1])
                            prev = float(h['Close'].iloc[-2])
                            chg = (cur - prev) / prev * 100
                            macro_lines.append(f"  - {name}: {cur:.2f} ({chg:+.2f}%)")
                    except Exception:
                        pass

                # ── 9. Build prompt ─────────────────────────────
                _c.set(ckey, {'state': 'running', 'phase': 'AI กำลังวิเคราะห์และสร้างรายงาน…'}, timeout=600)

                _now = tz.now()
                _months_th = ['', 'มกราคม','กุมภาพันธ์','มีนาคม','เมษายน','พฤษภาคม','มิถุนายน',
                              'กรกฎาคม','สิงหาคม','กันยายน','ตุลาคม','พฤศจิกายน','ธันวาคม']
                today_str = f"{_now.day} {_months_th[_now.month]} {_now.year}"  # ปี ค.ศ. เสมอ

                prompt = f"""คุณคือ Senior Portfolio Manager และ Macro Strategist ระดับสถาบัน
วันที่: {today_str}

จงสร้าง **Morning Briefing Report** ภาษาไทยแบบครบถ้วน จากข้อมูลด้านล่าง:

---
## 📊 MACRO ECONOMY
{chr(10).join(macro_lines) if macro_lines else 'ไม่มีข้อมูล'}

## 💼 PORTFOLIO (หุ้นที่ถืออยู่)
{chr(10).join(port_lines) if port_lines else 'ไม่มีพอร์ต'}

## 🇹🇭 MOMENTUM SET (Top 10 by Score)
{chr(10).join(mom_set_lines) if mom_set_lines else 'ยังไม่ได้สแกน'}

## 🇺🇸 MOMENTUM US (Top 10 by Score)
{chr(10).join(mom_us_lines) if mom_us_lines else 'ยังไม่ได้สแกน'}

## 🎯 PRECISION SCAN - SET (Top 8)
{chr(10).join(prec_lines) if prec_lines else 'ยังไม่ได้สแกน'}

## 🦅 SEPA - SET Stage 2 + RS≥70
{chr(10).join(sepa_lines) if sepa_lines else 'ยังไม่ได้สแกน'}

## ☕ CUP & HANDLE - SET
{chr(10).join(cup_lines) if cup_lines else 'ยังไม่ได้สแกน'}

## 🦅 US SEPA - Stage 2 + VCP
{chr(10).join(us_sepa_lines) if us_sepa_lines else 'ยังไม่ได้สแกน'}

---
จงเขียนรายงานเป็นภาษาไทย **Markdown** โดยมีหัวข้อดังนี้:

## 1. 🌍 ภาพรวมเศรษฐกิจและตลาดโลกวันนี้
วิเคราะห์ Macro: Risk-on/Risk-off, Fund Flow, SET vs S&P500, ทิศทางดอกเบี้ย, Gold/BTC

## 2. 💼 สถานะพอร์ต - ควรทำอะไรวันนี้?
รายหุ้นใน Portfolio - แต่ละตัวควร: ✅ Hold | ➕ Add | ⚠️ Trail Stop | 🔴 ขาย
ระบุเหตุผลสั้น ๆ จาก P/L% และบรรยากาศตลาด

## 3. 🇹🇭 หุ้น SET น่าสนใจวันนี้
Top 3-5 จาก Momentum + Precision + SEPA + Cup&Handle รวมกัน
พร้อม Entry Zone, Stop Loss, Target และ Priority (🔥 สูง / ⚡ กลาง / 👀 เฝ้าดู)

## 3. 🇹🇭 หุ้น SET น่าสนใจวันนี้
Top 3-5 จาก Momentum + Precision + SEPA + Cup&Handle รวมกัน
วิเคราะห์เปรียบเทียบในแง่กลยุทธ์:
- **Pocket Pivot (PP)**: ดูว่าเป็นจุดซื้อซุ่มเงียบในฐานราคา (Volume ยืนยัน) หรือไม่
- **CMF (Chaikin Money Flow)**: ประเมินการสะสมหุ้นของสถาบัน/รายใหญ่ (>0.1 คือสะสม)
- **CAN SLIM / SEPA VCP**: ดูการบีบตัวของราคา (จำนวนครั้ง T และเปอร์เซ็นต์ความลึกที่แคบลง)
พร้อมระบุ Entry Zone, Stop Loss, Target และ Priority (🔥 สูง / ⚡ กลาง / 👀 เฝ้าดู)

## 4. 🇺🇸 หุ้น US น่าสนใจวันนี้
Top 3-5 จาก Momentum US + US SEPA
วิเคราะห์คุณลักษณะตามเกณฑ์ Minervini SEPA VCP และสัญญาณ Pocket Pivot (PP) รวมทั้งแนวโน้มสถาบันสะสมหุ้น
พร้อม Entry, Stop, Target และ Priority

## 5. ⚡ สรุปแผนปฏิบัติการวันนี้
ตารางสรุป: หุ้น | ตลาด | Action | ราคาเข้า | Stop | เหตุผล (ระบุว่าเด่นด้าน PP / CMF / VCP หรือไม่)
เรียงตาม Priority สูงสุดก่อน

## 6. ⚠️ ความเสี่ยงที่ต้องระวังวันนี้
Macro risks, Earnings, การเมือง หรือสัญญาณที่น่าเป็นห่วง
"""

                client = _genai.Client(api_key=_s.GEMINI_API_KEY)
                resp = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                )
                report_text = resp.text or '## ไม่สามารถสร้างรายงานได้'

                # ── 10. Save to DB ──────────────────────────────
                MB.objects.create(
                    user=user,
                    report_md=report_text,
                    portfolio_count=len(portfolio),
                    momentum_set_count=len(mom_set),
                    momentum_us_count=len(mom_us),
                    precision_count=len(prec_set),
                    sepa_count=len(sepa_set),
                    cup_handle_count=len(cup_list),
                )

                # Keep only 7 latest reports per user
                old_ids = list(MB.objects.filter(user=user).order_by('-created_at').values_list('id', flat=True)[7:])
                if old_ids:
                    MB.objects.filter(id__in=old_ids).delete()

                _c.set(ckey, {'state': 'done'}, timeout=300)

            except Exception as exc:
                import logging
                logging.getLogger('stocks').exception(f'[MorningBriefing] error: {exc}')
                from django.core.cache import cache as _c2
                _c2.set(ckey, {'state': 'done', 'error': str(exc)}, timeout=60)
                from django.core.cache import cache as _c2
                _c2.set(ckey, {'state': 'done', 'error': str(exc)}, timeout=60)

        import threading as _th
        _th.Thread(target=_run, args=(request.user.id, cache_key), daemon=True).start()
        return redirect('stocks:morning_briefing')

    # ── GET: display ─────────────────────────────────────────────
    import json as _json
    from stocks.models import MorningBriefing as _MB, PrecisionScanCandidate as _PSC, CupHandleCandidate as _CHC
    from django.utils import timezone as _tz
    from datetime import timedelta as _td


    status_data = _cp.get(cache_key, {})
    is_generating = (status_data.get('state') == 'running')
    error_msg = status_data.get('error')
    if error_msg:
        _cp.set(cache_key, {'state': 'done'}, timeout=5)
        
    briefings = list(_MB.objects.filter(user=request.user)[:7])

    # Check scanner freshness (threshold: 12 hours)
    latest_prec_run = _PSC.objects.filter(user=request.user, market='SET').values_list('scan_run', flat=True).order_by('-scan_run').first()
    latest_us_prec_run = _PSC.objects.filter(user=request.user, market='US').values_list('scan_run', flat=True).order_by('-scan_run').first()
    latest_cup_run = _CHC.objects.filter(user=request.user).values_list('scan_run', flat=True).order_by('-scan_run').first()

    now = _tz.now()
    threshold = now - _td(hours=12)

    prec_is_old = latest_prec_run is None or latest_prec_run < threshold
    us_prec_is_old = latest_us_prec_run is None or latest_us_prec_run < threshold
    cup_is_old = latest_cup_run is None or latest_cup_run < threshold
    any_scanner_old = prec_is_old or us_prec_is_old or cup_is_old

    # Pass markdown as safe JSON so template JS can render without escape issues
    briefings_md_json = _json.dumps([b.report_md for b in briefings])

    return render(request, 'stocks/morning_briefing.html', {
        'briefings':       briefings,
        'latest':          briefings[0] if briefings else None,
        'is_generating':   is_generating,
        'error_msg':       error_msg,
        'briefings_md_json': briefings_md_json,
        'latest_prec_run': latest_prec_run,
        'latest_us_prec_run': latest_us_prec_run,
        'latest_cup_run':  latest_cup_run,
        'prec_is_old':     prec_is_old,
        'us_prec_is_old':  us_prec_is_old,
        'cup_is_old':      cup_is_old,
        'any_scanner_old': any_scanner_old,
    })


# ====== Macro Economy - ภาพรวมเศรษฐกิจมหภาคและสินค้าโภคภัณฑ์ ======

@login_required
def macro_economy(request):
    """
    ดึงข้อมูล SET Index, USD/THB, ทองคำ, น้ำมัน WTI/Brent
    แสดงกราฟย้อนหลัง 3 เดือน และวิเคราะห์ด้วย AI ตามคำขอ
    """
    # รายการข้อมูลมหภาคที่ต้องดึงพร้อม symbol Yahoo Finance
    macro_items = [
        {'id': 'set', 'name': 'SET Index (ดัชนีหุ้นไทย)', 'symbol': '^SET.BK', 'unit': 'Points', 'desc': 'ดัชนีตลาดหลักทรัพย์แห่งประเทศไทย บ่งบอกสภาวะตลาดโดยรวม'},
        {'id': 'spx', 'name': 'S&P 500 (ตลาดหุ้นสหรัฐฯ)', 'symbol': '^GSPC', 'unit': 'Points', 'desc': 'ดัชนีหุ้นใหญ่ 500 ตัวของสหรัฐฯ สะท้อนภาพรวมตลาดโลก'},
        {'id': 'usdthb', 'name': 'USD/THB (อัตราแลกเปลี่ยน)', 'symbol': 'USDTHB=X', 'unit': 'THB', 'desc': 'ค่าเงินบาทเทียบดอลลาร์สิงคโปร์/สหรัฐฯ'},
        {'id': 'dxy', 'name': 'Dollar Index (DXY)', 'symbol': 'DX-Y.NYB', 'unit': 'Points', 'desc': 'ดัชนีดอลลาร์สหรัฐ บ่งบอกถึงกระแสเงินทุน (Fund Flow)'},
        {'id': 'us10y', 'name': 'US 10Y Bond Yield', 'symbol': '^TNX', 'unit': '%', 'desc': 'อัตราดอกเบี้ยพันธบัตรฯ 10 ปี สหรัฐฯ'},
        {'id': 'gold', 'name': 'Gold (ทองคำโลก)', 'symbol': 'GC=F', 'unit': 'USD/oz', 'desc': 'สินทรัพย์ปลอดภัยและตัววัดเงินเฟ้อ'},
        {'id': 'btc', 'name': 'Bitcoin (BTC-USD)', 'symbol': 'BTC-USD', 'unit': 'USD', 'desc': 'สินทรัพย์ดิจิทัล (Crypto) สะท้อนความกล้าเสี่ยง (Risk-on) ของตลาด'},
        {'id': 'wti', 'name': 'WTI Crude Oil (น้ำมันดิบ)', 'symbol': 'CL=F', 'unit': 'USD/bbl', 'desc': 'ต้นทุนพลังงานและเศรษฐกิจโลก'}
    ]

    data = []
    charts = {}

    # วนดึงข้อมูลราคาปัจจุบันและ % เปลี่ยนแปลงของแต่ละตัวชี้วัด
    for item in macro_items:
        try:
            t = yf.Ticker(item['symbol'])
            hist = t.history(period='1y')
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

    # ====== AI Macro Analysis - วิเคราะห์ภาพรวมเศรษฐกิจด้วย Gemini ======
    _MACRO_CACHE_KEY = 'MACRO_ECONOMY_V2'
    analysis_text = None
    analysis_last_updated = None

    # Load cached analysis on every page visit
    _cached = AnalysisCache.objects.filter(user=request.user, symbol=_MACRO_CACHE_KEY).first()
    if _cached:
        analysis_text = _cached.analysis_data
        analysis_last_updated = _cached.last_updated

    if request.GET.get('analyze') == 'true' and data:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        model_name_to_use = 'gemini-2.5-flash'

        # ดึงผลสแกนล่าสุดมาประกอบการวิเคราะห์กลุ่มอุตสาหกรรมและกลยุทธ์หุ้นรายตัว
        from stocks.models import PrecisionScanCandidate
        
        # หุ้นเด่นไทยล่าสุด
        latest_set_run = PrecisionScanCandidate.objects.filter(user=request.user, market='SET').values_list('scan_run', flat=True).order_by('-scan_run').first()
        set_stocks = []
        if latest_set_run:
            set_stocks = list(PrecisionScanCandidate.objects.filter(user=request.user, market='SET', scan_run=latest_set_run).order_by('-technical_score')[:5])
        set_stocks_str = "\n".join([
            f"  - {c.symbol}: Score={c.technical_score}, RS={c.rs_rating}, CMF={f'{c.cmf:.2f}' if c.cmf is not None else 'N/A'}, PP={'Yes' if c.pocket_pivot else 'No'}, VCP={'Yes' if c.vcp_setup else 'No'} ({c.vcp_contractions}T, {c.vcp_tightness:.1f}%)"
            for c in set_stocks
        ]) if set_stocks else "ไม่มีข้อมูลสแกนล่าสุด"

        # หุ้นเด่นสหรัฐล่าสุด
        latest_us_run = PrecisionScanCandidate.objects.filter(user=request.user, market='US').values_list('scan_run', flat=True).order_by('-scan_run').first()
        us_stocks = []
        if latest_us_run:
            us_stocks = list(PrecisionScanCandidate.objects.filter(user=request.user, market='US', scan_run=latest_us_run).order_by('-technical_score')[:5])
        us_stocks_str = "\n".join([
            f"  - {c.symbol}: Score={c.technical_score}, RS={c.rs_rating}, CMF={f'{c.cmf:.2f}' if c.cmf is not None else 'N/A'}, PP={'Yes' if c.pocket_pivot else 'No'}, VCP={'Yes' if c.vcp_setup else 'No'} ({c.vcp_contractions}T, {c.vcp_tightness:.1f}%)"
            for c in us_stocks
        ]) if us_stocks else "ไม่มีข้อมูลสแกนล่าสุด"

        # สร้าง string สรุปข้อมูลมหภาคเพื่อส่งให้ AI
        data_str = "\n".join([f"{d['name']}: {d['price']:.2f} ({d['change']:+.2f}%) - {d['desc']}" for d in data])
        prompt = f"""
        คุณคือผู้เชี่ยวชาญด้านเศรษฐศาสตร์มหาภาค (Senior Economist) และนักกลยุทธ์การลงทุนระดับโลก (Global Investment Strategist) 
        จงวิเคราะห์ข้อมูลตลาดปัจจุบันและหุ้นเด่นที่มีการตั้งทรงทางเทคนิคตามกลยุทธ์ด้านล่างนี้ และสรุปภาพรวมเศรษฐกิจและการลงทุนให้มีความลุ่มลึกระดับสถาบัน:
        
        [Market Data Summary]:
        {data_str}

        [Top Scanned Stocks & Setup (ระบบ O'Neil / Minervini)]:
        **ตลาดหุ้นไทย (SET Top Picks):**
        {set_stocks_str}

        **ตลาดหุ้นสหรัฐฯ (US Top Picks):**
        {us_stocks_str}

        โปรดเขียนรายงาน "Global Investment Outlook & Asset Allocation" เป็นภาษาไทย โดยมีหัวข้อดังนี้:
        1. **Fund Flow & Risk Appetite**: วิเคราะห์ความสัมพันธ์ของ DXY, Bond Yield เเละ Bitcoin ตอนนี้ตลาดอยู่ในภาวะ Risk-on (กล้าเสี่ยง) หรือ Risk-off (กลัว) เงินกำลังไหลออกจากตลาดหุ้นไปสู่หลุมหลบภัย (Gold) หรือไหลเข้าสู่ระบบใหม่ (Crypto)?
        2. **US vs Thai Market Direction**: วิเคราะห์เปรียบเทียบตลาดหุ้นสหรัฐฯ (S&P 500) และไทย (SET) ทิศทางเป็นอย่างไร? มีปัจจัยอะไรที่สวนทางกันหรือไม่?
        3. **Asset Allocation (การจัดพอร์ตแนะนำ)**: แนะนำสัดส่วนการลงทุนที่เหมาะสมใน 'ตอนนี้' (เช่น หุ้นกี่ %, ทองคำกี่ %, คริปโตกี่ %, เงินสดกี่ %) โดยอ้างอิงจากความเสี่ยงเศรษฐกิจมหาภาค
        4. **Deep Dive: Gold & Crypto**: เจาะลึกทองคำและบิทคอยน์ในฐานะสินทรัพย์ทางเลือก (Alternative Assets) ในสภาวะปัจจุบันควรสะสม, ถือเฉยๆ หรือหาจังหวะขาย?
        5. **Sector Strategy & Stock Selection (US & Thai)**: เจาะกลุ่มอุตสาหกรรมโดดเด่น:
           - **US Sectors & Stock Picks**: แนะนำกลุ่มอุตสาหกรรมที่น่าสนใจ พร้อมชี้เป้าหุ้นสหรัฐฯ ที่โดดเด่นจากรายชื่อสแกนข้างต้น โดยวิเคราะห์ปัจจัยสนับสนุนและจุดเด่นด้านเทคนิค เช่น ความแข็งแกร่งของ **Pocket Pivot (PP)**, แรงส่งจากสถาบันการเงินที่ดูจาก **CMF** และลักษณะการบีบตัวของราคา **VCP**
           - **Thai Sectors & Stock Picks**: แนะนำกลุ่ม Winner ในไทย พร้อมเจาะจงวิเคราะห์หุ้นไทย 3-5 ตัวที่มีสัญญาณซื้อซุ่มเงียบ **Pocket Pivot (PP)**, การสะสมของสถาบันที่ยอดเยี่ยม (**CMF > 0.1**) หรือฟอร์มตัวในรูปแบบ **VCP (Volatility Contraction Pattern)** ที่พร้อมเบรคเอาท์
        6. **Strategic Summary (1-3 Months Outlook)**: สรุปกลยุทธ์สั้นๆ 1-3 เดือนข้างหน้าว่าควรโฟกัสที่จุดใดมากที่สุด

        ข้อกำหนดการตอบ:
        - ใช้โทนเสียงระดับมืออาชีพ น่าเชื่อถือ (Institutional Tone)
        - ใช้ Markdown จัดรูปแบบให้สวยงาม (ใช้ตารางเเนะนำ Asset Allocation จะดีมาก)
        - ห้ามมีคำเกริ่นนำหรือคำส่งท้าย
        - ส่งออกมาเป็น Raw Markdown เท่านั้น
        """

        try:
            response = client.models.generate_content(
                model=model_name_to_use,
                contents=prompt
            )
            analysis_text = response.text or ""

            # ลบ markdown block wrapper ถ้า AI ไม่ปฏิบัติตาม prompt
            # Strip any residual markdown blocks if AI disobeys
            if analysis_text.startswith("```markdown"):
                analysis_text = analysis_text[len("```markdown"):].strip()
            if analysis_text.endswith("```"):
                analysis_text = analysis_text[:-3].strip()
            if not analysis_text:
                analysis_text = "ไม่สามารถรับผลจาก AI ได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง"

            # Save to cache so user can read it on next visit
            obj, _ = AnalysisCache.objects.update_or_create(
                user=request.user,
                symbol=_MACRO_CACHE_KEY,
                defaults={'analysis_data': analysis_text}
            )
            analysis_last_updated = obj.last_updated

        except Exception as e:
            analysis_text = f"ไม่สามารถสร้างบทวิเคราะห์ได้ในขณะนี้: {str(e)}"

    context = {
        'title': 'Macro Economy & Commodities',
        'data': data,
        'analysis': analysis_text,
        'analysis_last_updated': analysis_last_updated,
        # ส่ง charts data เป็น JSON string สำหรับ JavaScript
        'charts_json': json.dumps(charts)
    }
    return render(request, 'stocks/macro.html', context)

# ====== Momentum Scanner - สแกนหาหุ้น SET100+MAI ตามเกณฑ์ Trend Template ======

@login_required
def precision_scan_ai_analysis(request):
    import json as _json_lib

    from django.http import JsonResponse
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        body = _json_lib.loads(request.body)
        scan_data = body.get("scan_data", {})
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return JsonResponse({"error": "ไม่พบ GEMINI_API_KEY"}, status=500)

    qualified = scan_data.get("qualified_stocks", [])
    top_buy = scan_data.get("top_buy_stocks", [])
    scan_date = scan_data.get("scan_date", "ไม่ระบุ")
    total_passed = scan_data.get("total_passed", 0)
    top_sectors = scan_data.get("top_sectors", [])

    def _fmt_stock(s):
        lines = [
            "  - {sym}: ราคา {price} | BUY {buy} | RS {rs}".format(
                sym=s.get("symbol", "?"), price=s.get("price", "-"),
                buy=s.get("buy_score", 0), rs=s.get("rs_rating", 0)),
            "    RSI {rsi} | ADX {adx} | RVOL {rvol}x {dir} | RR 1:{rr}".format(
                rsi=s.get("rsi", "-"), adx=s.get("adx", "-"), rvol=s.get("rvol", "-"),
                dir="Bull ▲" if s.get("rvol_bullish") else "Bear ▼",
                rr=s.get("risk_reward_ratio", "-")),
            "    Zone {z}% | {sec} | RelMom3m {rm}%".format(
                z=s.get("zone_proximity", "-"), sec=s.get("sector", "-"),
                rm=s.get("rel_momentum_3m", 0)),
            "    Signals: {m}{e}{h}{b}{a}".format(
                m="MACD✕ " if s.get("macd_crossover") else "",
                e="EMA↑ " if s.get("ema20_rising") else "",
                h="HH/HL " if s.get("hh_hl_structure") else "",
                b="BB Squeeze " if s.get("bb_squeeze") else "",
                a="EMA20 Aligned " if s.get("ema20_aligned") else ""),
        ]
        if s.get("top_reasons"):
            lines.append("    เหตุผล: {r}".format(r=", ".join(s["top_reasons"])))
        return "\n".join(lines)

    q_text = "\n".join([_fmt_stock(s) for s in qualified]) if qualified else "  (ไม่มีหุ้นผ่านเกณฑ์ครบ)"
    b_text = "\n".join([_fmt_stock(s) for s in top_buy]) if top_buy else "  (ไม่มีข้อมูล)"
    sec_text = ", ".join(["{n}({c})".format(n=s["name"], c=s["count"]) for s in top_sectors]) if top_sectors else "ไม่ระบุ"

    prompt = (
        "คุณคือผู้เชี่ยวชาญด้านหุ้น SET"
        " ที่ใช้ Precision Momentum (สไตล์ Mark Minervini + William O'Neil)\n"
        "เชี่ยวชาญ Stage Analysis, RS Rating, Supply/Demand Zone,"
        " RVOL Bull/Bear, MACD Crossover, EMA Alignment, Trend Following (HH/HL)\n\n"
        "ผล Precision Scan วันที่ {sd} (ผ่านเกณฑ์ {tp} ตัว)"
        " | Leading Sectors: {sec}\n\n"
        "=== หุ้นผ่านเกณฑ์ครบทุกข้อ (Fully Qualified) ===\n{q}\n\n"
        "=== Top หุ้นแนะนำซื้อ (BUY Score) ===\n{b}\n\n"
        "วิเคราะห์ในหัวข้อต่อไปนี้:\n\n"
        "## 1. ✨ ภาพรวมตลาดวันนี้\n"
        "- บรรยากาศตลาด (Bullish/Mixed/Bearish), Sector นำตลาด\n\n"
        "## 2. ✅ วิเคราะห์หุ้นผ่านเกณฑ์ครบทุกข้อ\n"
        "- วิเคราะห์หุ้นรายตัว: จุดเด่น, ความเสี่ยง, โอกาสวิ่ง, ลำดับน่าสนใจ\n\n"
        "## 3. 🏆 วิเคราะห์ Top BUY Score\n"
        "- หุ้นที่น่าสนใจที่สุด และเหตุผลประกอบ | ข้อควรระวัง\n\n"
        "## 4. ⚡ กลยุทธ์แนะนำ\n"
        "- ลำดับการเข้าซื้อ: ตัวไหนก่อน-หลัง หรือรอจังหวะ | Entry Zone ที่เหมาะสม\n\n"
        "## 5. ⚠ ข้อควรระวัง\n"
        "- RSI/RVOL/Zone ที่ต้องระวัง, วินัยในการทำ Stop Loss\n\n"
        "**หมายเหตุ:** เมื่อใช้ Emoji ในหัวข้อ ให้เว้นวรรค 1 ช่องหลัง Emoji เสมอ เพื่อการแสดงผลที่ถูกต้องใน PDF\n"
        "ตอบภาษาไทย กระชับ เป็นมืออาชีพ"
        " จัดรูปแบบ Markdown"
        " เน้น Actionable Insights"
    ).format(sd=scan_date, tp=total_passed, sec=sec_text, q=q_text, b=b_text)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        if not response.text:
            return JsonResponse({"error": "AI ไม่ตอบกลับ"}, status=500)
        return JsonResponse({"status": "success", "analysis": response.text})
    except Exception as e:
        err = str(e)
        if "API_KEY_INVALID" in err:
            return JsonResponse({"error": "GEMINI_API_KEY ไม่ถูกต้อง"}, status=500)
        return JsonResponse({"error": "Gemini error: {}".format(err)}, status=500)


# ====== tithe_report - รายงานทศางค์ 10% จากกำไรหุ้นรายเดือน ======

@login_required
def us_precision_scan_ai_analysis(request):
    import json as _json_lib

    from django.http import JsonResponse
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        body = _json_lib.loads(request.body)
        scan_data = body.get("scan_data", {})
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return JsonResponse({"error": "No GEMINI_API_KEY configured"}, status=500)

    qualified    = scan_data.get("qualified_stocks", [])
    top_buy      = scan_data.get("top_buy_stocks", [])
    scan_date    = scan_data.get("scan_date", "N/A")
    total_passed = scan_data.get("total_passed", 0)
    top_sectors  = scan_data.get("top_sectors", [])

    def _fmt_stock(s):
        lines = [
            "  - {sym}: Price ${price} | BUY {buy} | RS {rs}".format(
                sym=s.get("symbol", "?"), price=s.get("price", "-"),
                buy=s.get("buy_score", 0), rs=s.get("rs_rating", 0)),
            "    RSI {rsi} | ADX {adx} | RVOL {rvol}x {dir} | RR 1:{rr}".format(
                rsi=s.get("rsi", "-"), adx=s.get("adx", "-"), rvol=s.get("rvol", "-"),
                dir="Bull ▲" if s.get("rvol_bullish") else "Bear ▼",
                rr=s.get("risk_reward_ratio", "-")),
            "    Zone {z}% | {sec} | RelMom3m vs SPY {rm}%".format(
                z=s.get("zone_proximity", "-"), sec=s.get("sector", "-"),
                rm=s.get("rel_momentum_3m", 0)),
            "    Signals: {m}{e}{h}{b}{a}".format(
                m="MACD✕ " if s.get("macd_crossover") else "",
                e="EMA↑ " if s.get("ema20_rising") else "",
                h="HH/HL " if s.get("hh_hl_structure") else "",
                b="BB Squeeze " if s.get("bb_squeeze") else "",
                a="EMA20 Aligned " if s.get("ema20_aligned") else ""),
        ]
        if s.get("top_reasons"):
            lines.append("    Reasons: {r}".format(r=", ".join(s["top_reasons"])))
        return "\n".join(lines)

    q_text   = "\n".join([_fmt_stock(s) for s in qualified]) if qualified else "  (No fully qualified stocks)"
    b_text   = "\n".join([_fmt_stock(s) for s in top_buy]) if top_buy else "  (No data)"
    sec_text = ", ".join(["{n}({c})".format(n=s["name"], c=s["count"]) for s in top_sectors]) if top_sectors else "N/A"

    prompt = (
        "You are an expert US equity analyst specializing in Precision Momentum trading"
        " (Mark Minervini SEPA + William O'Neil CAN SLIM methodology).\n"
        "Expert in Stage Analysis, RS Rating, Supply/Demand Zone,"
        " RVOL Bull/Bear, MACD Crossover, EMA Alignment, Trend Following (HH/HL).\n\n"
        "US Precision Scan Date: {sd} | Stocks Passed Filter: {tp}"
        " | Leading Sectors: {sec}\n\n"
        "=== Fully Qualified Stocks (All Criteria Met) ===\n{q}\n\n"
        "=== Top BUY Score Stocks ===\n{b}\n\n"
        "Analyze the following:\n\n"
        "## 1. 📊 US Market Overview\n"
        "- Market sentiment (Bullish/Mixed/Bearish), Leading sectors, SPY context\n\n"
        "## 2. ✅ Fully Qualified Setups\n"
        "- Each stock: Key strengths, risks, upside potential, priority ranking\n\n"
        "## 3. 🏆 Top BUY Score Analysis\n"
        "- Most attractive setup and why | What to watch out for\n\n"
        "## 4. ⚡ Trading Strategy\n"
        "- Entry order: Which first, which to wait | Optimal entry zones\n\n"
        "## 5. ⚠ Risk Warnings\n"
        "- RSI/RVOL/Zone concerns | Stop Loss discipline | Macro risks\n\n"
        "Reply in English. Be concise and professional."
        " Format as Markdown. Focus on Actionable Insights."
    ).format(sd=scan_date, tp=total_passed, sec=sec_text, q=q_text, b=b_text)

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        if not response.text:
            return JsonResponse({"error": "AI did not respond"}, status=500)
        return JsonResponse({"status": "success", "analysis": response.text})
    except Exception as e:
        err = str(e)
        if "API_KEY_INVALID" in err:
            return JsonResponse({"error": "GEMINI_API_KEY is invalid"}, status=500)
        return JsonResponse({"error": "Gemini error: {}".format(err)}, status=500)




# ============================================================
# US VALUE SCANNER
# ============================================================

@login_required
def macro_playbook_view(request):
    """
    หน้าแสดงรายงาน Daily Mastermind Briefing (Playbook)
    โครงสร้างแบบ AJAX Loading เหมือนหน้า Crew Analysis อื่นๆ
    """
    from stocks.models import PrecisionScanCandidate as _PSC, CupHandleCandidate as _CHC
    from django.utils import timezone as _tz
    from datetime import timedelta as _td

    # Check scanner freshness (threshold: 12 hours)
    latest_prec_run = _PSC.objects.filter(user=request.user, market='SET').values_list('scan_run', flat=True).order_by('-scan_run').first()
    latest_us_prec_run = _PSC.objects.filter(user=request.user, market='US').values_list('scan_run', flat=True).order_by('-scan_run').first()
    latest_cup_run = _CHC.objects.filter(user=request.user).values_list('scan_run', flat=True).order_by('-scan_run').first()

    now = _tz.now()
    threshold = now - _td(hours=12)

    prec_is_old = latest_prec_run is None or latest_prec_run < threshold
    us_prec_is_old = latest_us_prec_run is None or latest_us_prec_run < threshold
    cup_is_old = latest_cup_run is None or latest_cup_run < threshold
    any_scanner_old = prec_is_old or us_prec_is_old or cup_is_old

    return render(request, 'stocks/macro_playbook.html', {
        'latest_prec_run': latest_prec_run,
        'latest_us_prec_run': latest_us_prec_run,
        'latest_cup_run':  latest_cup_run,
        'prec_is_old':     prec_is_old,
        'us_prec_is_old':  us_prec_is_old,
        'cup_is_old':      cup_is_old,
        'any_scanner_old': any_scanner_old,
    })


@login_required
def macro_playbook_run_ajax(request):
    """
    รัน CrewAI 5 Agents เบื้องหลังและเคลียร์ Cache เมื่อให้ผลลัพธ์
    พร้อมวิเคราะห์ Portfolio ปัจจุบันของผู้ใช้งาน
    """
    import threading as _th

    from django.core.cache import cache as _cp
    from django.http import JsonResponse as _JR

    from stocks.models import Portfolio
    
    user_id = request.user.id
    cache_key = f'macro_playbook_{user_id}'

    # Check status
    if request.GET.get('status_check') == '1':
        st = _cp.get(cache_key, {'state': 'idle'})
        return _JR(st)

    # Fetch user portfolio data before threading to avoid DB context issues in thread
    try:
        user_portfolio_list = list(Portfolio.objects.filter(user=request.user).values('symbol', 'quantity', 'entry_price', 'market'))
    except Exception:
        user_portfolio_list = []

    def _run_bg(portfolio_data):
        from stocks.crew_analysis import MacroPlaybookCrew
        try:
            _cp.set(cache_key, {'state': 'running', 'phase': 'Agents กำลังประชุมและดึงราคาตลาด...'}, timeout=600)
            crew = MacroPlaybookCrew(portfolio_data=portfolio_data)
            result = crew.run_analysis()
            _cp.set(cache_key, {'state': 'done', 'result': result}, timeout=600)
        except Exception as exc:
            _cp.set(cache_key, {'state': 'done', 'result': f'## Error\nเกิดข้อผิดพลาดในการรัน Agents: {exc}'}, timeout=600)

    # Start if idle
    current_state = _cp.get(cache_key, {}).get('state', 'idle')
    if current_state == 'idle' or request.GET.get('force') == '1':
        _cp.set(cache_key, {'state': 'running', 'phase': 'กำลังเรียกทีมผู้เชี่ยวชาญ...'}, timeout=600)
        _th.Thread(target=_run_bg, args=(user_portfolio_list,), daemon=True).start()
        
    return _JR({'status': 'started'})

# ======================================================================
# Turtle Trader Scanner (Mechanical Breakout System)
# ======================================================================

@login_required
def ai_manual_scanner(request):
    """
    Render the UI for the AI Manual Scanner.
    """
    from stocks.models import AIManualScanResult, ScanWatchlistItem, PrecisionScanCandidate
    from django.db.models import Count, Q, Max
    import json
    
    market = request.GET.get('market', 'SET')
    
    # Get the latest scan run timestamp
    latest_run = AIManualScanResult.objects.filter(user=request.user, market=market)\
        .order_by('-scan_run').values_list('scan_run', flat=True).first()
        
    if latest_run:
        results = AIManualScanResult.objects.filter(user=request.user, market=market, scan_run=latest_run)\
            .order_by('rank', 'grade', 'symbol')
    else:
        results = AIManualScanResult.objects.none()
        
    # Get watchlisted symbols
    watchlisted = ScanWatchlistItem.objects.filter(user=request.user).values_list('symbol', flat=True)
    watchlisted_symbols = set(watchlisted)
    
    # Get cached Quick AI results
    from stocks.models import AnalysisCache
    crewai_caches = AnalysisCache.objects.filter(user=request.user, symbol__startswith='crewai_')
    crewai_dict = {}
    for c in crewai_caches:
        sym = c.symbol.replace('crewai_', '')
        crewai_dict[sym] = c.analysis_data
    crewai_json = json.dumps(crewai_dict)
    
    # ------ Statistics & History Datasets ------
    # 1. Top Recommended Stocks (Top AI Picks)
    stats_qs = AIManualScanResult.objects.filter(user=request.user, market=market)\
        .values('symbol')\
        .annotate(
            total_scans=Count('id'),
            grade_a_count=Count('id', filter=Q(grade='A')),
            grade_b_count=Count('id', filter=Q(grade='B')),
            grade_c_count=Count('id', filter=Q(grade='C')),
            last_scanned=Max('scan_run')
        ).order_by('-total_scans', '-grade_a_count', 'symbol')
    stats_data = list(stats_qs)
    
    # 2. History of Scan Runs
    history_runs_qs = AIManualScanResult.objects.filter(user=request.user, market=market)\
        .values('scan_run')\
        .annotate(
            scan_date=Max('created_at'),
            stock_count=Count('id')
        ).order_by('-scan_run')
        
    history_runs = []
    for r in history_runs_qs:
        s_run = r['scan_run']
        s_date = r['scan_date']
        if s_run is None:
            s_run_str = "Legacy (No Run ID)"
            s_run_iso = "legacy"
        else:
            s_run_str = s_run.strftime('%Y-%m-%d %H:%M')
            s_run_iso = s_run.isoformat()
            
        history_runs.append({
            'scan_run_str': s_run_str,
            'scan_run_iso': s_run_iso,
            'scan_date': s_date,
            'stock_count': r['stock_count']
        })
    
    # ------ Fetch Specific Historical Run if requested ------
    history_selected_run = request.GET.get('history_run')
    history_results = None
    if history_selected_run:
        if history_selected_run == 'legacy':
            history_results = AIManualScanResult.objects.filter(user=request.user, market=market, scan_run__isnull=True)\
                .order_by('rank', 'grade', 'symbol')
        else:
            history_results = AIManualScanResult.objects.filter(user=request.user, market=market, scan_run=history_selected_run)\
                .order_by('rank', 'grade', 'symbol')

    # ------ Pre-fetch latest PrecisionScanCandidate details to attach as properties ------
    latest_prec_run = PrecisionScanCandidate.objects.filter(user=request.user, market=market)\
        .order_by('-scan_run').values_list('scan_run', flat=True).first()
    
    prec_map = {}
    if latest_prec_run:
        prec_qs = PrecisionScanCandidate.objects.filter(
            user=request.user,
            market=market,
            scan_run=latest_prec_run
        )
        for cand in prec_qs:
            prec_map[cand.symbol] = cand

    # Map precision candidates to latest results
    results_list = list(results)
    for r in results_list:
        cand = prec_map.get(r.symbol)
        if cand:
            r.is_short_term = cand.is_short_term
            r.is_medium_term = cand.is_medium_term
            r.is_long_term = cand.is_long_term
            r.is_canslim = cand.is_canslim
            r.rs_rating = cand.rs_rating
            r.rsi = cand.rsi
            r.technical_score = cand.technical_score
            r.eps_growth = cand.eps_growth
            r.rev_growth = cand.rev_growth
            r.cmf = cand.cmf
        else:
            r.is_short_term = False
            r.is_medium_term = False
            r.is_long_term = False
            r.is_canslim = False
            r.rs_rating = 0
            r.rsi = 50
            r.technical_score = 0
            r.eps_growth = 0
            r.rev_growth = 0
            r.cmf = 0.0

    # Also map to historical results if selected
    if history_results:
        history_results_list = list(history_results)
        for r in history_results_list:
            cand = prec_map.get(r.symbol)
            if cand:
                r.is_short_term = cand.is_short_term
                r.is_medium_term = cand.is_medium_term
                r.is_long_term = cand.is_long_term
                r.is_canslim = cand.is_canslim
                r.rs_rating = cand.rs_rating
                r.rsi = cand.rsi
                r.technical_score = cand.technical_score
                r.eps_growth = cand.eps_growth
                r.rev_growth = cand.rev_growth
                r.cmf = cand.cmf
            else:
                r.is_short_term = False
                r.is_medium_term = False
                r.is_long_term = False
                r.is_canslim = False
                r.rs_rating = 0
                r.rsi = 50
                r.technical_score = 0
                r.eps_growth = 0
                r.rev_growth = 0
                r.cmf = 0.0
        history_results = history_results_list
    else:
        history_results = []

    results = results_list
    
    return render(request, 'stocks/ai_manual_scanner.html', {
        'results': results,
        'current_market': market,
        'watchlisted_symbols': watchlisted_symbols,
        'crewai_json': crewai_json,
        'stats_data': stats_data,
        'history_runs': history_runs,
        'history_results': history_results,
        'history_selected_run': history_selected_run
    })

def _run_ai_manual_scan_bg(user_id, cache_key, market, scan_run_time):
    from django.core.cache import cache
    from django.contrib.auth import get_user_model
    from django.conf import settings
    import json
    from google import genai
    from stocks.models import PrecisionScanCandidate, AIManualScanResult

    try:
        # Step 1: Initialize status
        cache.set(cache_key, {'state': 'running', 'progress': 15, 'phase': 'ดึงข้อมูลจาก Precision Scanner...'}, timeout=600)
        
        User = get_user_model()
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            cache.set(cache_key, {'state': 'failed', 'message': 'ไม่พบบัญชีผู้ใช้งาน'}, timeout=300)
            return

        # Get latest scan run
        latest_run = PrecisionScanCandidate.objects.filter(
            user=user,
            market=market
        ).order_by('-scan_run').values_list('scan_run', flat=True).first()

        if not latest_run:
            cache.set(cache_key, {
                'state': 'failed', 
                'message': f'ไม่พบหุ้นที่ผ่านเกณฑ์เบื้องต้น (RS > 60, Stage 2) ในตลาด {market} กรุณารัน Precision Scan ก่อน'
            }, timeout=300)
            return

        # Fetch candidate stocks (top 15 — fewer tokens = faster AI response)
        candidates = PrecisionScanCandidate.objects.filter(
            user=user,
            market=market,
            scan_run=latest_run,
            rs_rating__gte=65,
            stage2=True
        ).order_by('-technical_score')[:15]

        if not candidates.exists():
            cache.set(cache_key, {
                'state': 'failed',
                'message': f'ไม่พบหุ้นที่มีค่า RS >= 60 และเป็น Stage 2 ในฐานข้อมูลตลาด {market} ล่าสุด'
            }, timeout=300)
            return

        # Step 2: Prepare data for AI
        cache.set(cache_key, {'state': 'running', 'progress': 30, 'phase': 'จัดเตรียมข้อมูลส่งให้ AI...'}, timeout=600)
        
        stocks_data = []
        for c in candidates:
            # dist_piv = % ห่างจากจุด Pivot (52W high / supply zone)
            # ยิ่งน้อยยิ่งดี: ≤5% = AT pivot, ≤10% = near, >20% = extended
            dist_piv = round(float(c.upside_to_high) if c.upside_to_high else 99.0, 1)
            stocks_data.append({
                's': c.symbol,
                'rs': round(float(c.rs_rating) if c.rs_rating else 0, 1),
                'rsi': round(float(c.rsi) if c.rsi else 50.0, 1),
                'dist_piv': dist_piv,   # % ห่างจุด pivot (ยิ่งน้อยยิ่งดี)
                'vcp': c.vcp_setup,
                'adx': round(float(c.adx) if c.adx else 0, 1),
                'sc': round(float(c.technical_score) if c.technical_score else 0, 1),
                'cmf': round(float(c.cmf) if c.cmf else 0.0, 2),
                'vsurge': round(float(c.volume_surge) if c.volume_surge else 0.0, 2),
                'pp': c.pocket_pivot,
                'vdu': c.vdu_near_zone,
                'eps': round(float(c.eps_growth) if c.eps_growth else 0.0, 1),
                'rev': round(float(c.rev_growth) if c.rev_growth else 0.0, 1),
                'is_short': c.is_short_term,
                'is_medium': c.is_medium_term,
                'is_long': c.is_long_term,
                'is_canslim': c.is_canslim
            })

        # Step 3: Call Gemini API
        cache.set(cache_key, {'state': 'running', 'progress': 50, 'phase': 'AI (Gemini) กำลังประเมินผล...'}, timeout=600)
        
        from google.genai import types
        import concurrent.futures

        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        prompt = f"""คุณคือ AI Analyst ผู้เชี่ยวชาญระบบ SEPA (Minervini), CAN SLIM และ Turtle Breakout
คัดเลือก 5-8 หุ้นที่ดีที่สุดจากตลาด {market} โดยประเมินการจัดสรรพอร์ตการลงทุน 3 ระยะ (สั้น SEPA, กลาง CAN SLIM, ยาว Turtle) ตามเกณฑ์ด้านล่าง แล้วตอบเป็น JSON

กรอบการวิเคราะห์เชิงกลยุทธ์ (Horizon Groups):
1. ระยะสั้น (SEPA / Momentum): เน้นหุ้นที่มี Pocket Pivot (pp=true), Volume Surge (vsurge > 1.5) หรือ Launcher score >= 70
2. ระยะกลาง (CAN SLIM / VCP / Cup & Handle): เน้นหุ้นที่มีพื้นฐานเติบโตโดดเด่น (eps >= 20% หรือ rev >= 20%), ระดับความแข็งแกร่งของราคา RS >= 80, หรือมีการฟอร์มตัวของราคาแบบ VCP (vcp=true)
3. ระยะยาว (Turtle / Stage 2 Trend): เน้นการรันเทรนด์บน Weinstein Stage 2 ขาขึ้นหลัก และสัญญาณแนวโน้มที่สอดคล้อง

เกณฑ์การคัดเลือกและวิเคราะห์:
- พิจารณาและจัดอันดับหุ้นที่ผ่านการบูรณาการทั้ง 3 กลยุทธ์ (โดยเฉพาะหุ้นที่สอดคล้องกันข้ามขอบเวลา เช่น มีคุณสมบัติทั้งระยะสั้นและระยะกลาง/ยาวร่วมกัน)
- dist_piv คือ %% ที่ราคาปัจจุบันห่างจาก Pivot/52W-high (ยิ่งน้อยยิ่งดี: <= 5%% = AT pivot, <= 15%% = buy zone)
- RS ยิ่งสูงยิ่งดี, RSI 50-70 กำลังวิ่ง (หลีกเลี่ยง RSI > 75)

ข้อมูลหุ้น (s=symbol, rs=RS, rsi, dist_piv=%%จากPivot, vcp, adx, sc=score, cmf, vsurge, pp, vdu, eps=EPSgrowth%%, rev=Revgrowth%%, is_short=ระยะสั้น, is_medium=ระยะกลาง, is_long=ระยะยาว, is_canslim=CANSLIM):
{json.dumps(stocks_data, separators=(',',':'))}

ตอบ JSON เท่านั้น ห้ามมีข้อความอื่น reasoning ภาษาไทย 3-4 ประโยค วิเคราะห์ทิศทางและจุดแข็งตามกลยุทธ์ SEPA, CAN SLIM และ/หรือ Turtle พร้อมระบุเกรด:
{{"status":"success","market":"{market}","selected_stocks":[{{"rank":1,"symbol":"X","grade":"A","reasoning":"ภาษาไทย 3-4 ประโยค วิเคราะห์เชิงกลยุทธ์ของตัวหุ้นให้สอดคล้องกับขอบเวลาและสัญญาณเทคนิคัล/พื้นฐาน"}}]}}"""

        def _call_gemini():
            return client.models.generate_content(
                model='gemini-2.5-flash-lite',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type='application/json',
                    temperature=0.0,
                    max_output_tokens=2500,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                )
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_call_gemini)
            try:
                response = future.result(timeout=25)   # hard 25s cap
            except concurrent.futures.TimeoutError:
                future.cancel()
                cache.set(cache_key, {
                    'state': 'failed',
                    'message': 'AI (Gemini) ไม่ตอบสนองใน 25 วินาที — กรุณาลองใหม่ หรือตรวจสอบ API quota'
                }, timeout=300)
                return
        
        result_json = json.loads(response.text)
        
        if result_json.get('status') == 'success':
            # Step 4: Save results — delete AFTER new ones are ready (safe swap)
            cache.set(cache_key, {'state': 'running', 'progress': 85, 'phase': 'บันทึกผลลัพธ์และสถิติ...'}, timeout=600)

            selected_list = result_json.get('selected_stocks', [])
            if selected_list:
                # Build new records first
                new_objs = [
                    AIManualScanResult(
                        user=user, market=market,
                        symbol=stock.get('symbol'),
                        grade=stock.get('grade', 'C'),
                        reasoning=stock.get('reasoning', ''),
                        rank=stock.get('rank', idx + 1),
                        scan_run=scan_run_time,
                    )
                    for idx, stock in enumerate(selected_list)
                ]
                # Atomic: delete old → insert new (no window with 0 records)
                from django.db import transaction
                with transaction.atomic():
                    AIManualScanResult.objects.filter(user=user, market=market).delete()
                    AIManualScanResult.objects.bulk_create(new_objs)
            
            cache.set(cache_key, {
                'state': 'done',
                'progress': 100,
                'phase': 'เสร็จสิ้น',
                'selected_stocks': selected_list,
                'market': market
            }, timeout=300)
        else:
            cache.set(cache_key, {
                'state': 'failed',
                'message': result_json.get('message', 'AI สแกนล้มเหลว')
            }, timeout=300)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        import logging
        logging.getLogger('stocks').error(f"AI Manual Scan BG Error: {e}\n{tb}")
        
        err_msg = str(e)
        if "timeout" in err_msg.lower() or "deadline" in err_msg.lower() or "timed out" in err_msg.lower():
            err_msg = "การเชื่อมต่อกับ AI (Gemini) หมดเวลา (Timeout) กรุณาลองใหม่อีกครั้ง"
            
        cache.set(cache_key, {
            'state': 'failed',
            'message': f"เกิดข้อผิดพลาดในการรันสแกน: {err_msg}"
        }, timeout=300)

@login_required
def api_ai_manual_scan(request):
    """
    AJAX endpoint to run the AI scan based on the manuals.
    """
    import json
    from django.core.cache import cache
    
    # Handle GET request for status check
    if request.method == 'GET' or request.GET.get('status') == '1':
        market = request.GET.get('market', 'SET')
        cache_key = f'ai_manual_scan_{request.user.id}_{market}'
        st = cache.get(cache_key, {'state': 'idle'})
        return JsonResponse(st)

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=400)

    try:
        data = json.loads(request.body)
        market = data.get('market', 'SET')
    except Exception:
        market = 'SET'

    cache_key = f'ai_manual_scan_{request.user.id}_{market}'
    
    # Check if already running
    current_status = cache.get(cache_key, {})
    if current_status.get('state') == 'running':
        return JsonResponse({'status': 'running', 'message': 'การสแกนกำลังทำงานอยู่เบื้องหลัง กรุณารอสักครู่...'})

    # Start Asynchronous Scan in a background thread
    from django.utils import timezone
    scan_run_time = timezone.now()
    
    import threading
    threading.Thread(
        target=_run_ai_manual_scan_bg,
        args=(request.user.id, cache_key, market, scan_run_time),
        daemon=True
    ).start()

    return JsonResponse({'status': 'started', 'message': 'ระบบเริ่มการสแกนเบื้องหลังแล้ว'})


@login_required
def investment_dashboard(request):
    """
    หน้า Dashboard หลักสำหรับนักลงทุน Premium
    แสดง Top 5 SET และ US พร้อมบทวิเคราะห์ AI แบบถาวร
    """
    insight_id = request.GET.get('id')
    insights = InvestmentDashboardInsight.objects.filter(user=request.user).order_by('-created_at')[:3]
    
    if insight_id:
        latest_insight = InvestmentDashboardInsight.objects.filter(user=request.user, id=insight_id).first()
    else:
        latest_insight = insights[0] if insights else None

    # Fetch user's watchlist for toggle state
    from stocks.models import ScanWatchlistItem, PrecisionScanCandidate as _PSC, CupHandleCandidate as _CHC, Portfolio, MarketType, AssetCategory
    from django.utils import timezone as _tz
    from datetime import timedelta as _td

    watchlist_set = set(ScanWatchlistItem.objects.filter(user=request.user).values_list('symbol', flat=True))

    # Fetch user's portfolio items as a dictionary for details and check membership
    portfolio_items = Portfolio.objects.filter(user=request.user)
    portfolio_map = {}
    for item in portfolio_items:
        clean_sym = item.symbol.split('.')[0].upper()
        original_sym = item.symbol.upper()
        item_data = {
            'id': item.id,
            'symbol': item.symbol,
            'name': item.name,
            'quantity': float(item.quantity),
            'entry_price': float(item.entry_price),
            'market': item.market,
            'category': item.category,
            'strategy': item.strategy or '',
            'trail_multiplier': item.trail_multiplier,
        }
        portfolio_map[clean_sym] = item_data
        portfolio_map[original_sym] = item_data

    market_types = MarketType.choices
    categories = AssetCategory.choices

    # Check scanner freshness (threshold: 12 hours)
    latest_prec_run = _PSC.objects.filter(user=request.user, market='SET').values_list('scan_run', flat=True).order_by('-scan_run').first()
    latest_us_prec_run = _PSC.objects.filter(user=request.user, market='US').values_list('scan_run', flat=True).order_by('-scan_run').first()
    latest_cup_run = _CHC.objects.filter(user=request.user).values_list('scan_run', flat=True).order_by('-scan_run').first()

    now = _tz.now()
    threshold = now - _td(hours=12)

    prec_is_old = latest_prec_run is None or latest_prec_run < threshold
    us_prec_is_old = latest_us_prec_run is None or latest_us_prec_run < threshold
    cup_is_old = latest_cup_run is None or latest_cup_run < threshold
    any_scanner_old = prec_is_old or us_prec_is_old or cup_is_old

    ai_strategy_html = ''
    if latest_insight and latest_insight.ai_strategy:
        try:
            from markdown_it import MarkdownIt as _MdIt
            _md = _MdIt().enable('table')
            ai_strategy_html = _md.render(latest_insight.ai_strategy)
        except ImportError:
            try:
                import markdown as _md2
                ai_strategy_html = _md2.markdown(
                    latest_insight.ai_strategy,
                    extensions=['tables', 'nl2br', 'sane_lists'],
                )
            except ImportError:
                ai_strategy_html = ''
        except Exception:
            ai_strategy_html = ''

    return render(request, 'stocks/investment_dashboard.html', {
        'insight': latest_insight,
        'insights_history': insights,
        'watchlist_set': watchlist_set,
        'portfolio_map': portfolio_map,
        'market_types': market_types,
        'categories': categories,
        'latest_prec_run': latest_prec_run,
        'latest_us_prec_run': latest_us_prec_run,
        'latest_cup_run':  latest_cup_run,
        'prec_is_old':     prec_is_old,
        'us_prec_is_old':  us_prec_is_old,
        'cup_is_old':      cup_is_old,
        'any_scanner_old': any_scanner_old,
        'ai_strategy_html': ai_strategy_html,
    })

@login_required
@require_POST
def investment_dashboard_refresh(request):
    """
    ระบบคัดกรองหุ้นแบบ Multi-Scanner Funnel:
    Cup & Handle (Setup) -> Precision Momentum (Power) -> Minervini SEPA (Quality) -> Turtle Breakout (Trigger)
    """
    import json

    import google.genai as genai
    from django.conf import settings
    from django.contrib import messages
    from django.db.models import Max
    from django.shortcuts import redirect

    from stocks.models import (
        CupHandleCandidate,
        InvestmentDashboardInsight,
        PrecisionScanCandidate,
        TurtleScanCandidate,
        USSepaCandidate,
    )
    
    def get_consensus_top_10(market):
        # 1. หา scan_run ล่าสุดของแต่ละระบบ
        latest_prec   = PrecisionScanCandidate.objects.filter(market=market).aggregate(Max('scan_run'))['scan_run__max']
        latest_ch     = CupHandleCandidate.objects.filter(market=market).aggregate(Max('scan_run'))['scan_run__max']
        latest_turtle = TurtleScanCandidate.objects.filter(market=market).aggregate(Max('scan_run'))['scan_run__max']
        latest_sepa   = USSepaCandidate.objects.aggregate(Max('scan_run'))['scan_run__max'] if market == 'US' else None

        if not latest_prec and not latest_ch: return []

        # 2. Batch-fetch ข้อมูลทุกระบบพร้อมกัน (4 queries เท่านั้น แทน N*4)
        prec_map   = {c.symbol: c for c in PrecisionScanCandidate.objects.filter(market=market, scan_run=latest_prec)} if latest_prec else {}
        ch_map     = {c.symbol: c for c in CupHandleCandidate.objects.filter(market=market, scan_run=latest_ch)} if latest_ch else {}
        turtle_map = {c.symbol: c for c in TurtleScanCandidate.objects.filter(market=market, scan_run=latest_turtle)} if latest_turtle else {}
        sepa_map   = {c.symbol: c for c in USSepaCandidate.objects.filter(scan_run=latest_sepa)} if latest_sepa else {}

        # 3. รวม universe แล้ว sort ตัวอักษร → iteration order คงที่ทุกครั้ง
        all_symbols = sorted(set(prec_map) | set(ch_map) | set(turtle_map) | set(sepa_map))

        ch_lane    = []
        other_lane = []

        for sym in all_symbols:
            prec   = prec_map.get(sym)
            ch     = ch_map.get(sym)
            turtle = turtle_map.get(sym)
            sepa   = sepa_map.get(sym)

            score  = 0
            badges = []

            # Step 1: The Radar (Cup & Handle) (+40)
            if ch:
                score += 40
                if ch.stage in ['ready', 'handle']: score += 10 # Bonus for late-stage setup
                badges.append('RADAR')

            # Step 2: The Power (Precision Momentum) (+30)
            if prec:
                score += 30
                if prec.rs_rating >= 80: score += 15 # The Power bonus (RS > 80)
                badges.append('POWER')

            # Step 3: The Quality (SEPA / Stage 2) (+20)
            is_quality = bool(sepa) if market == 'US' else bool(prec and prec.stage2)
            if is_quality:
                score += 20
                badges.append('QUALITY')

            # Step 4: The Trigger (Turtle Breakout) (+20)
            if turtle:
                if turtle.sys1_breakout or turtle.sys2_breakout:
                    score += 20
                    badges.append('TRIGGER')
                elif turtle.sys1_near or turtle.sys2_near:
                    score += 5
                    badges.append('NEAR')

            if score < 25: continue

            rs = prec.rs_rating if prec else (getattr(ch, 'rs_rating', 0) or 0)
            _stage2 = bool(prec and prec.stage2)
            _ema_aligned = bool(prec and prec.ema20_aligned)
            _is_canslim = bool(prec and prec.is_canslim)
            _vcp = bool((prec and prec.vcp_setup) or (ch and ch.handle_vol_dry))
            _52w = bool(prec and prec.is_52w_breakout)
            _sepa_pass = _stage2 and rs >= 70 and _ema_aligned
            _canslim_reasons = (prec.canslim_reasons or '') if prec else ''
            
            # Additional strategy fields
            _pocket_pivot = bool((prec and prec.pocket_pivot) or (sepa and sepa.pocket_pivot))
            _cmf = float(prec.cmf) if (prec and prec.cmf is not None) else None
            _vcp_c = int(prec.vcp_contractions) if prec else (int(sepa.vcp_contractions) if sepa else 0)
            _vcp_t = float(prec.vcp_tightness) if prec else (float(sepa.vcp_tightness) if sepa else 0.0)
            _vcp_vdu = bool(prec and prec.vcp_vdu)

            entry = {
                'symbol':         sym,
                'price':          float((prec or ch or turtle).price),
                'total_score':    score,
                'badges':         badges,
                'sector':         (prec.sector if prec else (ch.sector if ch else (getattr(turtle, 'sector', None) or 'Unknown'))),
                'technical_score': prec.technical_score if prec else (ch.confidence_score if ch else 0),
                'rs_rating':      rs,
                'cup_stage':      ch.stage if ch else "None",
                'turtle_breakout': "YES" if (turtle and (turtle.sys1_breakout or turtle.sys2_breakout)) else "No",
                'vdu':            bool(prec and prec.vdu_near_zone),
                'vcp':            _vcp,
                'is_explosive':   bool(prec and prec.is_explosive),
                'stage2':         _stage2,
                'ema_aligned':    _ema_aligned,
                'is_canslim':     _is_canslim,
                'is_52w_breakout': _52w,
                'sepa_pass':      _sepa_pass,
                'canslim_reasons': _canslim_reasons[:120] if _canslim_reasons else '',
                'pocket_pivot':   _pocket_pivot,
                'cmf':            _cmf,
                'vcp_contractions': _vcp_c,
                'vcp_tightness':  _vcp_t,
                'vcp_vdu':        _vcp_vdu,
            }

            if ch:
                ch_lane.append(entry)
            elif score >= 45:
                other_lane.append(entry)

        # 4. Sort deterministic: score ↓, technical_score ↓, rs_rating ↓, symbol ↑
        def sort_key(x):
            return (-x['total_score'], -x['technical_score'], -x['rs_rating'], x['symbol'])

        ch_lane.sort(key=sort_key)
        other_lane.sort(key=sort_key)

        return (ch_lane + other_lane)[:10]

    set_top = get_consensus_top_10('SET')
    us_top = get_consensus_top_10('US')
    
    if not set_top and not us_top:
        messages.warning(request, "ไม่พบข้อมูลสแกนที่สอดคล้องกับ Funnel ในขณะนี้ กรุณารัน Scanner ให้ครบถ้วน")
        return redirect('stocks:investment_dashboard')

    set_summary = json.dumps(set_top, indent=2)
    us_summary = json.dumps(us_top, indent=2)

    prompt = f"""
คุณคือ Senior Quantitative Strategist ที่เชี่ยวชาญระบบ Minervini SEPA, O'Neil CAN SLIM และ Turtle Trend-Following
วิเคราะห์หุ้นที่ผ่านระบบ Funnel หลายขั้นตอน: Cup & Handle (Radar) → Precision Momentum (Power) → SEPA Quality → Turtle Trigger

**กลยุทธ์สำคัญของระบบที่ต้องเน้นวิเคราะห์:**
1. **Pocket Pivot (PP)**: จุดซื้อซุ่มเงียบในฐานราคา (Volume สูงยืนยันการไหลเข้าของเงินทุน)
2. **CMF (Chaikin Money Flow)**: การสะสมหุ้นของสถาบัน/รายใหญ่ (ค่า > 0.1 แสดงถึงแรงสะสมที่แข็งแกร่ง)
3. **CAN SLIM / SEPA VCP (Volatility Contraction Pattern)**: การบีบตัวของราคาเพื่อกำจัดผู้เล่นระยะสั้น (จดจำจำนวนครั้งการบีบตัว T และเปอร์เซ็นต์ความลึกที่แคบลง)

**เกณฑ์ SEPA Trend Template (Minervini) ที่ต้องผ่าน:**
1. ราคา > EMA150 และ EMA200 (Price above key MAs)
2. EMA150 > EMA200 (MA alignment)
3. EMA200 กำลังขึ้น (Uptrending 200MA)
4. EMA50 > EMA150 และ EMA200
5. ราคา > EMA50
6. ราคาสูงกว่า 52W Low อย่างน้อย 30%
7. ราคาอยู่ในช่วง 25% จาก 52W High
8. RS Rating >= 70 (Relative Strength สูง)
→ `sepa_pass: true` = ผ่านเกณฑ์ SEPA แล้ว

**เกณฑ์ CAN SLIM (O'Neil) ที่ระบบตรวจสอบ:**
- **C**: Current Earnings growth (กำไรไตรมาสล่าสุด +25%+)
- **A**: Annual Earnings growth (กำไรต่อเนื่อง)
- **N**: New product/mgmt/breakout (Catalyst)
- **S**: Supply & Demand (Volume ยืนยัน Breakout)
- **L**: Leader (RS Rating >= 80, outperform ตลาด)
- **I**: Institutional support (Volume Surge / CMF สะสม)
- **M**: Market direction (ตลาดอยู่ใน Uptrend)
→ `is_canslim: true` = ผ่านเกณฑ์ CAN SLIM ของระบบ

ข้อมูลหุ้น TOP 10 ที่ผ่านการคัดกรอง Confluence สูงสุด:
[SET Thailand]: {set_summary}
[US Market]: {us_summary}

เขียนรายงานวิเคราะห์เป็น**ภาษาไทย** โดยใช้โครงสร้าง Markdown ต่อไปนี้อย่างครบถ้วน:

## 🔍 Funnel Consensus
สรุปภาพรวม: หุ้นส่วนใหญ่ติดในขั้นตอนไหน และ Confluence ของตลาด SET กับ US เป็นอย่างไร โดยเฉพาะเรื่องสัญญาณการสะสมของสถาบัน (CMF) และจุดซื้อซุ่มเงียบ (PP) ของภาพรวมตลาด (3-4 ประโยค)

---

## 📋 SEPA Trend Template & VCP Deep Dive
| หุ้น | ตลาด | Stage 2 | RS | ผ่าน SEPA | Pocket Pivot (PP) | VCP Contractions (T) | ความแน่น (Tightness) |
|------|------|---------|-----|-----------|------------------|----------------------|----------------------|

วิเคราะห์เฉพาะหุ้นที่ `sepa_pass: true` หรือ `stage2: true` — เจาะลึกสัญญาณ **VCP setup** (จำนวนครั้ง T และความแน่นของการบีบตัวล่าสุด) พร้อมระบุว่าเหมาะกับ **ระยะสั้น (Swing)** หรือ **ระยะกลาง (Position)**

---

## 📊 CAN SLIM & Smart Money Flow
| หุ้น | ตลาด | CAN SLIM | CMF (สถาบัน) | RS Rating | Volume | สรุปพฤติกรรมสถาบัน |
|------|------|---------|--------------|-----------|--------|--------------------|

วิเคราะห์เฉพาะหุ้นที่ `is_canslim: true` หรือหุ้นที่มี **CMF > 0.1** (สถาบันสะสมหุ้นเด่นชัด) — ระบุจุดแข็งของ Smart Money และสัญญาณของ Pocket Pivot (PP) ถ้ามี

---

## 💎 High Conviction Picks
| ตลาด | หุ้น | Funnel | SEPA | CAN SLIM | ปัจจัยหลักด้าน PP/CMF/VCP | Horizon |
|------|------|--------|------|---------|-------------------------|--------|
เลือกเฉพาะ **Top 5** ที่มี Confluence สูงสุดจากทั้งสองตลาดรวมกัน ระบุ Horizon: สั้น/กลาง/ยาว

---

## 🎯 Entry & Risk Management
### Minervini SEPA Style
- **Entry:** ซื้อที่ Pivot Breakout พร้อม Volume > 40% above average
- **Stop Loss:** ต่ำกว่า Pivot / Handle Low 7-8% (Hard Stop)
- **Position Size:** Risk ไม่เกิน 1-2% ของพอร์ตต่อ trade

### CAN SLIM Style
- **Entry:** Breakout จาก Proper Base (Cup, VCP, Flat Base)
- **ตัดขาดทุน:** ทันทีถ้าหลุด 7-8% จากราคาซื้อ
- **Pyramid:** เพิ่ม position เมื่อ +2.5% และ +5% จากจุดซื้อแรก

### Turtle Style
- **Trailing Stop:** 20-day Low (System 2) สำหรับระยะยาว
- **ออก:** ทันทีเมื่อราคาปิดต่ำกว่า 20-day low

---

## 💡 Strategist's View
มุมมองรวมของตลาดในสัปดาห์นี้: ควรรุก รับ หรือเลือกหุ้น? (2-3 ประโยค กระชับ ตัดสินใจได้ทันที)
"""
    
    ai_strategy = "ระบบ AI ไม่สามารถประมวลผลได้ในขณะนี้"
    market_outlook = "Neutral"
    try:
        api_key = getattr(settings, "GEMINI_API_KEY", None)
        if api_key:
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            ai_strategy = response.text or ai_strategy
            _txt = ai_strategy.lower()
            if any(w in _txt for w in ["bullish", "ขาขึ้น", "รุก", "ซื้อ"]): market_outlook = "Bullish"
            elif any(w in _txt for w in ["bearish", "ขาลง", "ระวัง", "ขาย"]): market_outlook = "Bearish"
            else: market_outlook = "Sideways/Neutral"
    except Exception as e:
        ai_strategy = f"เกิดข้อผิดพลาด: {str(e)}"
        
    # เก็บเฉพาะ 3 ครั้งล่าสุดเพื่อประหยัดพื้นที่
    InvestmentDashboardInsight.objects.create(
        user=request.user, set_top_stocks=set_top, us_top_stocks=us_top,
        ai_strategy=ai_strategy, market_outlook=market_outlook, is_active=True
    )
    
    # ลบตัวที่เก่ากว่า 3 อันดับแรก
    all_ids = list(InvestmentDashboardInsight.objects.filter(user=request.user).order_by('-created_at').values_list('id', flat=True))
    if len(all_ids) > 3:
        InvestmentDashboardInsight.objects.filter(id__in=all_ids[3:]).delete()

    messages.success(request, "วิเคราะห์ข้อมูลแบบ Multi-System Funnel เรียบร้อยแล้ว")
    return redirect('stocks:investment_dashboard')


# ====== API for External Integration (Hermes Bot) ======

def api_stock_analysis(request, symbol):
    """
    API Endpoint สำหรับให้ Hermes (Telegram Bot) เรียกใช้ข้อมูลการวิเคราะห์ล่าสุด
    URL: http://app.9com.cloud/stocks/api/analysis/<symbol>/?token=YOUR_TOKEN
    """
    from django.http import JsonResponse
    from django.utils.timezone import localtime

    from stocks.models import MomentumCandidate, PrecisionScanCandidate
    
    # 1. Security Check
    # แนะนำให้กำหนด API_TOKEN ใน settings.py หรือ .env
    valid_token = getattr(settings, "HERMES_API_TOKEN", "song_secret_hermes_2024")
    provided_token = request.GET.get('token')
    
    if provided_token != valid_token:
        return JsonResponse({"error": "Unauthorized. Invalid or missing token."}, status=401)
    
    symbol = symbol.upper().strip()
    
    # 2. Fetch Latest Data
    # ลำดับการหา: Precision Scan -> Momentum Scan
    stock = PrecisionScanCandidate.objects.filter(symbol=symbol).order_by('-scan_run').first()
    
    if not stock:
        # ลองหาใน MomentumCandidate (แบบเก่า)
        stock = MomentumCandidate.objects.filter(symbol=symbol).order_by('-scanned_at').first()
        is_precision = False
    else:
        is_precision = True
        
    if not stock:
        return JsonResponse({
            "symbol": symbol,
            "error": f"ไม่พบข้อมูลการสแกนล่าสุดของหุ้น {symbol} ในระบบ",
            "instruction": "กรุณารัน Scanner ในหน้าเว็บก่อนเพื่อให้มีข้อมูลใน Database"
        }, status=404)

    # 3. Prepare JSON Response (Verbose Flat Structure for maximum AI compatibility)
    response_data = {
        "status": "success",
        "symbol": stock.symbol,
        "price": stock.price,
        
        # RSI (ส่งทั้ง 2 แบบ)
        "rsi": round(stock.rsi, 2),
        "RSI": round(stock.rsi, 2),
        
        # Momentum / Score
        "momentum_score": stock.technical_score,
        "Momentum Score": stock.technical_score,
        "technical_score": stock.technical_score,
        
        # ADX
        "adx": round(stock.adx, 2),
        "ADX": round(stock.adx, 2),
        
        # RVOL (ดึงจาก rvol field)
        "rvol": round(stock.rvol, 2),
        "RVOL": round(stock.rvol, 2),
        "Relative Volume": round(stock.rvol, 2),
        
        # RS Rating
        "rs_rating": getattr(stock, 'rs_rating', 0),
        "RS Rating": getattr(stock, 'rs_rating', 0),
        
        # Fundamentals (ส่งเพิ่มเพื่อให้บอทวิเคราะห์ได้ลึกขึ้น)
        "EPS Growth": f"{stock.eps_growth}%",
        "Revenue Growth": f"{stock.rev_growth}%",
        "Sector": stock.sector,
        "Pattern": getattr(stock, 'price_pattern', 'N/A'),
        
        # Zone / Strategy (ส่งหลายแบบ)
        "zone": getattr(stock, 'entry_strategy', 'N/A'),
        "Zone": getattr(stock, 'entry_strategy', 'N/A'),
        "Buy Zone": f"{stock.demand_zone_end} - {stock.demand_zone_start}" if stock.demand_zone_start else "N/A",
        "Sell Zone": f"{stock.supply_zone_start}" if stock.supply_zone_start else "N/A",
        "Target Price": stock.supply_zone_start,
        "Demand Zone": f"{stock.demand_zone_start} - {stock.demand_zone_end}",
        
        # Zones & Risk (Flat)
        "demand_start": stock.demand_zone_start,
        "demand_end": stock.demand_zone_end,
        "stop_loss": stock.stop_loss,
        "target": stock.supply_zone_start,
        "is_explosive": getattr(stock, 'is_explosive', False),
        
        # สำหรับบอทที่ชอบอ่านแบบ Nested (ส่งเผื่อไว้)
        "zones": {
            "demand_start": stock.demand_zone_start,
            "demand_end": stock.demand_zone_end,
            "stop_loss": stock.stop_loss,
            "target": stock.supply_zone_start,
        },
        
        "last_scan": localtime(getattr(stock, 'scan_run', None) or getattr(stock, 'scanned_at', None)).strftime('%Y-%m-%d %H:%M:%S'),
    }
    
    # เพิ่มข้อความแนะนำเบื้องต้นให้ Bot
    if stock.technical_score >= 80:
        response_data["bot_hint"] = "หุ้นตัวนี้มีคะแนนเทคนิคสูงมาก มีความแข็งแกร่งเชิงโมเมนตัมสูง"
    elif stock.technical_score < 50:
        response_data["bot_hint"] = "หุ้นตัวนี้คะแนนเทคนิคต่ำกว่าเกณฑ์ ควรระมัดระวัง"
        
    return JsonResponse(response_data, safe=False, json_dumps_params={'ensure_ascii': False})

@login_required
def daily_agent_reports(request):
    """
    หน้าแสดงรายงาน AI Daily Scanner & Portfolio Analysis รายวัน
    """
    import pytz
    from datetime import datetime
    from django.utils import timezone as tz
    from stocks.models import DailyAgentReport

    # เช็คเวลาของไทย
    bkk_tz = pytz.timezone('Asia/Bangkok')
    now_bkk = datetime.now(bkk_tz)
    today_date = now_bkk.date()
    current_hour = now_bkk.hour
    is_weekday = now_bkk.weekday() < 5

    missing_slot = None
    if is_weekday:
        # เช็ครอบ 10:00 (ถ้าเลย 10 โมงเช้าแล้ว และยังไม่มีรายงานรอบ 10:00)
        if current_hour >= 10:
            if not DailyAgentReport.objects.filter(user=request.user, report_date=today_date, time_slot='10:00').exists():
                missing_slot = '10:00'
        
        # เช็ครอบ 13:00 (ถ้าเลย 13:00 แล้ว และรายงานรอบ 10:00 มีแล้ว แต่รอบ 13:00 ยังไม่มี)
        if current_hour >= 13 and not missing_slot:
            if not DailyAgentReport.objects.filter(user=request.user, report_date=today_date, time_slot='13:00').exists():
                missing_slot = '13:00'

    # รายงานทั้งหมดของผู้ใช้
    reports = list(DailyAgentReport.objects.filter(user=request.user).order_by('-report_date', '-time_slot'))

    # หากยังไม่มีรายงานเลยสักชิ้นเดียว ให้เปิดปุ่มสำหรับรันรายงานแรกได้ทันทีเสมอ แม้จะเป็นวันหยุด
    if not reports and not missing_slot:
        missing_slot = '10:00'

    # ตรวจสอบสถานะการสร้างเบื้องหลังผ่าน Cache
    from django.core.cache import cache as _cp
    cache_key = f'daily_agent_report_generating_{request.user.id}'
    status_data = _cp.get(cache_key, {'state': 'idle'})
    is_generating = (status_data.get('state') == 'running')
    
    # ดึงรายงานชิ้นล่าสุดเป็น Default
    selected_report = None
    report_id = request.GET.get('id')
    if report_id:
        try:
            selected_report = DailyAgentReport.objects.get(id=report_id, user=request.user)
        except DailyAgentReport.DoesNotExist:
            pass
    
    if not selected_report and reports:
        selected_report = reports[0]

    # ทำเครื่องหมายว่าอ่านแล้วสำหรับรายงานที่เลือกดูอยู่
    if selected_report and not selected_report.is_read:
        selected_report.is_read = True
        selected_report.save()

    return render(request, 'stocks/daily_agent_reports.html', {
        'reports': reports,
        'selected_report': selected_report,
        'missing_slot': missing_slot,
        'is_generating': is_generating,
        'status_data': status_data,
    })


@login_required
def trigger_daily_agent_report_ajax(request):
    """
    API สำหรับเริ่มรันการวิเคราะห์รายงานใน Thread เบื้องหลัง
    """
    from django.http import JsonResponse
    from django.core.cache import cache as _cp
    import pytz
    from datetime import datetime

    cache_key = f'daily_agent_report_generating_{request.user.id}'
    status = _cp.get(cache_key, {'state': 'idle'})

    # GET: สำหรับ Polling เช็คสถานะอย่างเดียว ไม่กระตุ้นการสร้างใหม่
    if request.method == 'GET':
        return JsonResponse({'success': True, 'state': status.get('state', 'idle'), 'phase': status.get('phase', '')})

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST or GET method required'})

    if status.get('state') == 'running':
        return JsonResponse({'success': True, 'state': 'running', 'phase': status.get('phase')})

    # ระบุ slot ที่ขาดไปจากที่ได้วิเคราะห์ไว้
    bkk_tz = pytz.timezone('Asia/Bangkok')
    now_bkk = datetime.now(bkk_tz)
    today_date = now_bkk.date()
    current_hour = now_bkk.hour

    time_slot = '10:00'
    if current_hour >= 13:
        # ถ้าไม่มี 10:00 ให้สร้าง 10:00 ก่อน แต่ถ้ามีแล้วค่อยสร้าง 13:00
        from stocks.models import DailyAgentReport
        if DailyAgentReport.objects.filter(user=request.user, report_date=today_date, time_slot='10:00').exists():
            time_slot = '13:00'

    # สั่งลุยรัน Thread
    import threading as _th
    
    def _run_bg(uid, slot, r_date, ckey):
        import django; django.setup()
        import google.genai as _genai
        import yfinance as _yf
        from django.conf import settings as _s
        from django.contrib.auth import get_user_model
        from django.core.cache import cache as _c
        from django.utils import timezone as tz
        from stocks.models import (
            Portfolio, MomentumCandidate, PrecisionScanCandidate, 
            CupHandleCandidate, USSepaCandidate, DailyAgentReport
        )

        User = get_user_model()
        user = User.objects.get(pk=uid)

        try:
            # 1. โหลดข้อมูลพอร์ต
            _c.set(ckey, {'state': 'running', 'phase': 'ดึงข้อมูล Portfolio...'}, timeout=600)
            portfolio = list(Portfolio.objects.filter(user=user))
            port_lines = []
            for p in portfolio:
                try:
                    ticker_sym = p.symbol if not p.symbol.endswith('.BK') else p.symbol
                    hist = _yf.Ticker(ticker_sym).history(period='5d')
                    if hist.empty:
                        hist = _yf.Ticker(f'{p.symbol}.BK').history(period='5d')
                    if not hist.empty:
                        cur = float(hist['Close'].iloc[-1])
                        entry = float(p.entry_price)
                        pl_pct = (cur - entry) / entry * 100
                        port_lines.append(f"  - {p.symbol}: ราคาปัจจุบัน {cur:.2f} (ทุน {entry:.2f}, P/L {pl_pct:+.1f}%)")
                    else:
                        port_lines.append(f"  - {p.symbol}: ทุน {float(p.entry_price):.2f} (ไม่พบราคาเรียลไทม์)")
                except Exception:
                    port_lines.append(f"  - {p.symbol}: ทุน {float(p.entry_price):.2f}")

            # 2. ดึงหุ้นเด่นล่าสุดจากสแกนเนอร์รอบล่าสุด
            _c.set(ckey, {'state': 'running', 'phase': 'ดึงข้อมูลสแกนเนอร์ล่าสุด (SEPA/Momentum/Trend)...'}, timeout=600)
            
            # Momentum SET
            mom_set = list(MomentumCandidate.objects.filter(user=user, market='SET').order_by('-technical_score')[:8])
            mom_set_lines = [f"  - {c.symbol}: Score={c.technical_score} RSI={c.rsi:.0f} RS={c.rs_rating} Price={c.price:.2f}" for c in mom_set]
            
            # Momentum US
            mom_us = list(MomentumCandidate.objects.filter(user=user, market='US').order_by('-technical_score')[:8])
            mom_us_lines = [f"  - {c.symbol}: Score={c.technical_score} RSI={c.rsi:.0f} RS={c.rs_rating} Price={c.price:.2f}" for c in mom_us]
            
            # Precision Scan (SET/US)
            prec_run_set = PrecisionScanCandidate.objects.filter(user=user, market='SET').values_list('scan_run', flat=True).order_by('-scan_run').first()
            prec_set = list(PrecisionScanCandidate.objects.filter(user=user, market='SET', scan_run=prec_run_set).order_by('-technical_score')[:8]) if prec_run_set else []
            prec_set_lines = [f"  - {c.symbol}: Score={c.technical_score} RS={c.rs_rating} Stage2={'✓' if c.stage2 else '✗'} RR={c.risk_reward_ratio:.1f} Prox={c.zone_proximity:.1f}% PP={'✓' if c.pocket_pivot else '✗'} CMF={f'{c.cmf:.2f}' if c.cmf is not None else 'N/A'} VCP={'✓' if c.vcp_setup else '✗'}({c.vcp_contractions}T, {c.vcp_tightness:.1f}%)" for c in prec_set]

            # SEPA SET (Stage 2 + RS >= 70)
            sepa_set = [c for c in prec_set if c.stage2 and c.rs_rating >= 70]
            sepa_lines = [f"  - {c.symbol}: RS={c.rs_rating} VCP={'✓' if c.vcp_setup else '✗'}({c.vcp_contractions}T, {c.vcp_tightness:.1f}%) PP={'✓' if c.pocket_pivot else '✗'} CMF={f'{c.cmf:.2f}' if c.cmf is not None else 'N/A'} Score={c.technical_score}" for c in sepa_set]

            # Cup & Handle (SET)
            cup_run = CupHandleCandidate.objects.filter(user=user).values_list('scan_run', flat=True).order_by('-scan_run').first()
            cup_list = list(CupHandleCandidate.objects.filter(user=user, scan_run=cup_run).order_by('-rs_rating')[:8]) if cup_run else []
            cup_lines = [f"  - {c.symbol}: Price={c.price:.2f} Breakout={c.breakout_price:.2f} RS={c.rs_rating}" for c in cup_list]

            # US SEPA
            us_sepa_run = USSepaCandidate.objects.filter(user=user).values_list('scan_run', flat=True).order_by('-scan_run').first()
            us_sepa_list = list(USSepaCandidate.objects.filter(user=user, scan_run=us_sepa_run, stage2=True).order_by('-rs_rating')[:8]) if us_sepa_run else []
            us_sepa_lines = [f"  - {c.symbol}: RS={c.rs_rating} VCP={'✓' if c.vcp_setup else '✗'}({c.vcp_contractions}T, {c.vcp_tightness:.1f}%) PP={'✓' if c.pocket_pivot else '✗'} Price={c.price:.2f}" for c in us_sepa_list]

            # 3. ข้อมูลสภาวะตลาด (Macro)
            _c.set(ckey, {'state': 'running', 'phase': 'ดึงดัชนีตลาดและข้อมูลสินค้าโภคภัณฑ์...'}, timeout=600)
            macro_symbols = {
                'SET Index': '^SET.BK', 'S&P 500': '^GSPC', 'Nasdaq': '^IXIC',
                'USD/THB': 'USDTHB=X', 'US 10Y Yield': '^TNX', 'Gold': 'GC=F'
            }
            macro_lines = []
            for name, sym in macro_symbols.items():
                try:
                    h = _yf.Ticker(sym).history(period='5d')
                    if not h.empty and len(h) >= 2:
                        cur = float(h['Close'].iloc[-1])
                        prev = float(h['Close'].iloc[-2])
                        chg = (cur - prev) / prev * 100
                        macro_lines.append(f"  - {name}: {cur:.2f} ({chg:+.2f}%)")
                except:
                    pass

            # 4. เรียกโมเดล Gemini วิเคราะห์เปรียบเทียบเชิงลึก
            _c.set(ckey, {'state': 'running', 'phase': 'AI กำลังประกอบข้อมูลและเขียนรายงานเปรียบเทียบพอร์ต...'}, timeout=600)
            
            slot_th = "เปิดตลาดเช้า" if slot == '10:00' else "พักตลาดบ่าย"
            today_str = r_date.strftime('%d/%m/%Y')
            
            prompt = f"""คุณคือ AI Quantitative Analyst และ Senior Portfolio Manager 
หน้าที่ของคุณคือวิเคราะห์รายงานสรุปหุ้นเด่นประจำวันเทียบกับพอร์ตโฟลิโอปัจจุบันของนักลงทุน

ข้อมูลรอบเวลา: {slot} น. ({slot_th})
วันที่: {today_str}

---
## 🌍 ดัชนีเศรษฐกิจและทิศทางตลาดล่าสุด
{chr(10).join(macro_lines) if macro_lines else 'ไม่มีข้อมูล'}

## 💼 พอร์ตโฟลิโอปัจจุบัน (PORTFOLIO)
{chr(10).join(port_lines) if port_lines else 'ไม่มีข้อมูลการถือครองหุ้นในพอร์ต'}

## 🇹🇭 สัญญาณสแกนหุ้นไทย (SET Scanner Results)
- **Momentum (Top 8):**
{chr(10).join(mom_set_lines) if mom_set_lines else 'ไม่มีข้อมูล'}
- **Precision Zone & Trend Template (Top 8):**
{chr(10).join(prec_set_lines) if prec_set_lines else 'ไม่มีข้อมูล'}
- **SEPA (Stage 2 + RS >= 70):**
{chr(10).join(sepa_lines) if sepa_lines else 'ไม่มีข้อมูล'}
- **Cup & Handle:**
{chr(10).join(cup_lines) if cup_lines else 'ไม่มีข้อมูล'}

## 🇺🇸 สัญญาณสแกนหุ้นสหรัฐ (US Scanner Results)
- **Momentum US (Top 8):**
{chr(10).join(mom_us_lines) if mom_us_lines else 'ไม่มีข้อมูล'}
- **US SEPA (Minervini Rules):**
{chr(10).join(us_sepa_lines) if us_sepa_lines else 'ไม่มีข้อมูล'}

---
จงสร้างรายงานวิเคราะห์ภาษาไทยด้วยรูปแบบ **Markdown** ระดับมืออาชีพ โดยเน้นการวิเคราะห์เชิงเปรียบเทียบตรงตามระบบ SEPA, CAN SLIM, Trend Following และ Momentum:

### 1. 🔍 บทสรุปภาวะตลาดและการสแกนรอบ {slot} น.
- สรุปสั้นๆ เกี่ยวกับบรรยากาศตลาด (SET / US) และปริมาณการเกิดสัญญาณซื้อ โดยเน้นวิเคราะห์การสะสมหุ้นของสถาบัน (CMF) และการปรากฏของ Pocket Pivot (PP) ในภาพรวม

### 2. 📊 เปรียบเทียบผลสแกนกับพอร์ตโฟลิโอปัจจุบัน (Portfolio Sync & Action Plan)
- จับคู่หุ้นในพอร์ตปัจจุบันเทียบกับสัญญาณสแกนล่าสุด:
  - หุ้นตัวใดในพอร์ตที่ยังมี Momentum แข็งแกร่ง (อยู่ในผลสแกน) แนะนำให้ **✅ Hold** หรือ **➕ Buy More** (ระบุพิกัดราคาที่ได้เปรียบ และสัญญาณสะสมหุ้น CMF / PP)
  - หุ้นตัวใดในพอร์ตที่หลุดจากสัญญาณสแกนเนอร์ทั้งหมด และมีแนวโน้มอ่อนแอ แนะนำให้ **⚠️ Stop Loss / Profit Take / Reduce Position**
  - วิเคราะห์เปรียบเทียบว่ามีกลุ่มอุตสาหกรรม (Sectors) ใดในผลสแกนที่แข็งแกร่งกว่าหุ้นในพอร์ต เพื่อแนะนำสับเปลี่ยนตัวเล่น (Switching) โดยใช้ VCP / CMF เป็นตัวชี้วัดความแข็งแกร่ง

### 3. 🎯 คัดเลือกหุ้นเด่น 3 ตัวแรก (Top Picks) ที่มีความเสี่ยงต่ำกำไรสูง (Low-Risk, High-Reward)
- คัดกรองหุ้นสแกนเนอร์ที่ฟอร์มตัวดีที่สุด (เช่น เข้าเกณฑ์ VCP บีบตัวแน่น, เพิ่งเกิดจุดซื้อซุ่มเงียบ PP หรือมีค่า CMF สะสมสูง)
- แสดงรายละเอียด: หุ้น | แนวคิด (SEPA/VCP/Cup) | แนวรับโซนซื้อ (PP) | จุดตัดขาดทุน (SL) | เป้าหมายกำไร (TP) | ข้อวิเคราะห์ PP/CMF/VCP

### 4. 📈 สรุปตาราง Action Plan ประจำรอบ {slot} น.
- ทำตารางคอลัมน์: หุ้น | ตลาด | คำแนะนำ (ซื้อเพิ่ม/ถือต่อ/ขายทำกำไร/ขายทิ้ง/เฝ้าดู) | แนวรับ | จุดคัท | เหตุผล (เช่น CMF แข็งแกร่ง, เกิด Pocket Pivot หรือ VCP 3T บีบตัวเสร็จสิ้น)

เขียนรายงานออกมาให้น่าอ่าน เข้าใจง่าย ใช้ภาษาไทยที่กระชับและเป็นทางการ
"""

            client = _genai.Client(api_key=_s.GEMINI_API_KEY)
            resp = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            report_text = resp.text or '## ไม่สามารถสร้างรายงานประจำรอบได้เนื่องจากข้อผิดพลาดของ AI'

            # บันทึกลงตาราง (และหลีกเลี่ยงการบันทึกซ้ำโดยใช้ get_or_create หรือ handle unique_together)
            DailyAgentReport.objects.update_or_create(
                user=user,
                report_date=r_date,
                time_slot=slot,
                defaults={'report_md': report_text, 'is_read': False}
            )

            _c.set(ckey, {'state': 'done'}, timeout=300)

        except Exception as e:
            import logging
            logging.getLogger('stocks').exception(f'[DailyAgentReport] error in thread: {e}')
            _c.set(ckey, {'state': 'done', 'error': str(e)}, timeout=60)

    _cp.set(cache_key, {'state': 'running', 'phase': 'เริ่มประมวลผลคำสั่งในเบื้องหลัง...'}, timeout=600)
    t = _th.Thread(target=_run_bg, args=(request.user.id, time_slot, today_date, cache_key), daemon=True)
    t.start()

    return JsonResponse({'success': True, 'state': 'running', 'phase': 'กำลังจัดเตรียมการดึงข้อมูล...'})


@login_required
def delete_daily_agent_report(request, pk):
    """
    ลบรายงานที่ระบุ
    """
    from django.shortcuts import get_object_or_400, redirect
    from stocks.models import DailyAgentReport
    
    report = get_object_or_400(DailyAgentReport, id=pk, user=request.user)
    report.delete()
    return redirect('stocks:daily_agent_reports')


@login_required
def mark_daily_agent_report_read(request, pk):
    """
    ทำเครื่องหมายว่าอ่านแล้วผ่าน AJAX
    """
    from django.shortcuts import get_object_or_400
    from django.http import JsonResponse
    from stocks.models import DailyAgentReport

    report = get_object_or_400(DailyAgentReport, id=pk, user=request.user)
    report.is_read = True
    report.save()
    return JsonResponse({'success': True})


