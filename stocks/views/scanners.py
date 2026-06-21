from .base import * 

def _mr_detect_pattern(df):
    """Detect bullish reversal patterns for MR Scanner."""
    if len(df) < 3:
        return ''
    try:
        o1, h1, l1, c1 = float(df['Open'].iloc[-2]), float(df['High'].iloc[-2]), float(df['Low'].iloc[-2]), float(df['Close'].iloc[-2])
        o0, h0, l0, c0 = float(df['Open'].iloc[-1]), float(df['High'].iloc[-1]), float(df['Low'].iloc[-1]), float(df['Close'].iloc[-1])
        body0   = abs(c0 - o0)
        range0  = h0 - l0
        if range0 == 0:
            return ''
        upper0 = h0 - max(c0, o0)
        lower0 = min(c0, o0) - l0
        # Hammer
        if lower0 >= 2 * max(body0, 0.0001) and lower0 >= 2 * max(upper0, 0.0001) and c0 >= l0 + range0 * 0.5:
            return 'Hammer'
        # Pin Bar
        if lower0 >= 2.5 * max(upper0, 0.0001) and body0 < range0 * 0.35:
            return 'Pin Bar'
        # Bullish Engulf
        body1 = abs(c1 - o1)
        if c1 < o1 and c0 > o0 and c0 > o1 and o0 <= c1 and body0 > body1 * 0.9:
            return 'Bullish Engulf'
        # Morning Star
        if len(df) >= 3:
            o2, c2 = float(df['Open'].iloc[-3]), float(df['Close'].iloc[-3])
            body2 = abs(c2 - o2)
            if c2 < o2 and body1 < max(body2, 0.0001) * 0.5 and c0 > o0 and c0 > (o2 + c2) / 2:
                return 'Morning Star'
    except Exception:
        pass
    return ''


def _mr_swing_support(df, lookback=60):
    """Nearest swing low below current price."""
    try:
        curr  = float(df['Close'].iloc[-1])
        lows  = df['Low'].tail(lookback).values
        swing = [lows[i] for i in range(2, len(lows) - 2) if lows[i] == min(lows[i-2:i+3])]
        below = [s for s in swing if s < curr]
        return max(below) if below else None
    except Exception:
        return None


def _mr_swing_resistance(df, lookback=60):
    """Nearest swing high above current price."""
    try:
        curr   = float(df['Close'].iloc[-1])
        highs  = df['High'].tail(lookback).values
        swing  = [highs[i] for i in range(2, len(highs) - 2) if highs[i] == max(highs[i-2:i+3])]
        above  = [s for s in swing if s > curr]
        return min(above) if above else None
    except Exception:
        return None


def _mr_r_score(rsi, adx, rvol, pattern, direction, dist_support_pct):
    score = 50
    if adx < 15:   score += 15
    elif adx < 20: score += 10
    elif adx < 25: score += 5
    if direction == 'oversold':
        if rsi < 25:   score += 20
        elif rsi < 30: score += 12
        elif rsi < 35: score += 6
    else:
        if rsi > 75:   score += 20
        elif rsi > 70: score += 12
        elif rsi > 65: score += 6
    if rvol > 1.5:   score += 15
    elif rvol > 1.2: score += 8
    elif rvol > 1.0: score += 3
    bonus = {'Bullish Engulf': 20, 'Morning Star': 18, 'Hammer': 15, 'Pin Bar': 12}
    score += bonus.get(pattern, 0)
    if dist_support_pct < 2.0:   score += 10
    elif dist_support_pct < 5.0: score += 5
    return min(100, score)


_mr_bg_cache = {}


@login_required
def mean_reversion_scanner(request):
    """
    Mean Reversion Scanner — หาหุ้น Oversold/Overbought ใน Range-Bound Market
    เกณฑ์: ADX < 25 (ไม่มี Trend) + RSI < 35 หรือ > 65
    เหมาะใช้เมื่อ Regime = CHOPPY / SIDEWAYS
    """
    import threading as _thr

    from django.core.cache import cache as _cp
    from django.http import JsonResponse as _JR

    market    = request.GET.get('market', 'SET')
    user_id   = request.user.id
    cache_key = f'mr_scan_{user_id}_{market}'

    # ── Refresh Only Current Candidates in Table (Lightweight Real-time Update) ──
    if request.GET.get('refresh_only') == 'true' or request.GET.get('refresh_only') == '1':
        from django.contrib import messages

        from .models import MeanReversionCandidate as _MRC
        all_runs = list(
            _MRC.objects.filter(user=request.user, market=market)
            .values_list('scan_run', flat=True).distinct().order_by('-scan_run')
        )
        if all_runs:
            latest_run = all_runs[0]
            candidates = list(_MRC.objects.filter(user=request.user, market=market, scan_run=latest_run))
            sym_list = [c.symbol for c in candidates]
            
            if sym_list:
                import concurrent.futures as cf
                from datetime import datetime as _dt
                from datetime import timedelta as _td

                import pandas as pd
                import pandas_ta as ta
                import pytz
                import yfinance as yf
                
                _tz = pytz.timezone('Asia/Bangkok') if market == 'SET' else pytz.utc
                now = _dt.now(_tz)
                end = (now.date() + _td(days=1)).strftime('%Y-%m-%d')
                start = (now.date() - _td(days=300)).strftime('%Y-%m-%d')
                
                def _refresh_one(c):
                    try:
                        sym = c.symbol
                        fetch = f'{sym}.BK' if market == 'SET' else sym
                        df = yf.Ticker(fetch).history(start=start, end=end, interval='1d')
                        if df is None or df.empty or len(df) < 60:
                            return None
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(1)
                        df = df.dropna(subset=['Close', 'High', 'Low', 'Open'])
                        
                        curr = float(df['Close'].iloc[-1])
                        avg_vol = float(df['Volume'].tail(20).mean())
                        if avg_vol == 0:
                            return None
                        
                        adx_v = 30.0
                        try:
                            adf = ta.adx(df['High'], df['Low'], df['Close'], 14)
                            ac = [col for col in adf.columns if col.startswith('ADX_')]
                            if ac:
                                adx_v = float(adf[ac[0]].iloc[-1])
                        except Exception:
                            pass
                            
                        rsi_v = 50.0
                        try:
                            rs = ta.rsi(df['Close'], 14)
                            if rs is not None and pd.notna(rs.iloc[-1]):
                                rsi_v = float(rs.iloc[-1])
                        except Exception:
                            pass
                        
                        direction = 'oversold' if rsi_v < 35 else 'overbought'
                        pattern = _mr_detect_pattern(df)
                        rvol = float(df['Volume'].iloc[-1]) / avg_vol if avg_vol > 0 else 1.0
                        support = _mr_swing_support(df)
                        resistance = _mr_swing_resistance(df)
                        dist_sup = ((curr - support) / support * 100) if support else 999.0
                        dist_res = ((resistance - curr) / curr * 100) if resistance else 999.0
                        
                        mean_tgt = None
                        try:
                            s20 = ta.sma(df['Close'], 20)
                            if s20 is not None and pd.notna(s20.iloc[-1]):
                                mean_tgt = float(s20.iloc[-1])
                        except Exception:
                            pass
                            
                        upside = ((mean_tgt - curr) / curr * 100) if mean_tgt and curr > 0 else 0.0
                        
                        rs_raw = 0.0
                        if len(df) >= 66:
                            c66 = float(df['Close'].iloc[-66])
                            if c66 > 0:
                                rs_raw = (curr - c66) / c66 * 100
                                
                        r_score = _mr_r_score(rsi_v, adx_v, rvol, pattern, direction, dist_sup)
                        
                        return {
                            'id': c.id,
                            'price': round(curr, 4),
                            'direction': direction,
                            'rsi': round(rsi_v, 1),
                            'adx': round(adx_v, 1),
                            'avg_vol': avg_vol,
                            'rvol': round(rvol, 2),
                            'pattern': pattern,
                            'support': support,
                            'resistance': resistance,
                            'dist_sup': round(dist_sup, 2),
                            'dist_res': round(dist_res, 2),
                            'mean_tgt': mean_tgt,
                            'upside': round(upside, 2),
                            'r_score': r_score,
                        }
                    except Exception:
                        return None
                
                with cf.ThreadPoolExecutor(max_workers=5) as ex:
                    futures = {ex.submit(_refresh_one, c): c for c in candidates}
                    for fut in cf.as_completed(futures):
                        res = fut.result()
                        if res:
                            _MRC.objects.filter(id=res['id']).update(
                                price=res['price'],
                                direction=res['direction'],
                                rsi=res['rsi'],
                                adx=res['adx'],
                                avg_vol_20d=res['avg_vol'],
                                rvol=res['rvol'],
                                pattern=res['pattern'],
                                support_level=res['support'],
                                resistance_level=res['resistance'],
                                dist_to_support_pct=res['dist_sup'],
                                dist_to_resistance_pct=res['dist_res'],
                                mean_target=res['mean_tgt'],
                                upside_pct=res['upside'],
                                r_score=res['r_score']
                            )
                messages.success(request, f"อัปเดตราคาล่าสุดเฉพาะหุ้น {len(sym_list)} ตัวในตารางเรียบร้อยแล้ว!")
        return redirect(f"{request.path}?market={market}&direction={request.GET.get('direction', 'all')}&min_score={request.GET.get('min_score', 60)}&run_idx={request.GET.get('run_idx', 0)}")

    if request.GET.get('scan_status') == '1':
        st = _cp.get(cache_key, {'state': 'idle'})
        if st.get('state') == 'done':
            _cp.delete(cache_key)
        return _JR(st)

    if request.GET.get('scan') == 'true' or request.method == 'POST':
        if _mr_bg_cache.get(cache_key, {}).get('state') == 'running':
            return redirect('stocks:mean_reversion_scanner')

        if market == 'SET':
            from .utils import get_top_ranked_symbols
            sym_list = get_top_ranked_symbols(market='SET', limit=300, auto_refresh=True)
        else:
            from .models import ScannableSymbol as _SS
            sym_list = list(_SS.objects.filter(is_active=True, market='US').values_list('symbol', flat=True))
            if len(sym_list) < 100:
                _seed_us_symbols()
                sym_list = list(_SS.objects.filter(is_active=True, market='US').values_list('symbol', flat=True))

        _cp.set(cache_key, {'state': 'running', 'progress': 0, 'total': len(sym_list), 'phase': 'เริ่มสแกน Mean Reversion…'}, timeout=900)

        def _run_mr(uid, ckey, syms, mkt):
            try:
                import django; django.setup()
                import concurrent.futures as cf
                import logging
                from datetime import datetime as _dt
                from datetime import timedelta as _td

                import pandas as pd
                import pandas_ta as ta
                import pytz
                import yfinance as yf
                from django.contrib.auth import get_user_model
                from django.core.cache import cache as _c
                from django.utils import timezone as tz
                _log = logging.getLogger('stocks.mean_reversion')

                User = get_user_model()
                user = User.objects.get(pk=uid)
                _tz  = pytz.timezone('Asia/Bangkok') if mkt == 'SET' else pytz.utc
                now  = _dt.now(_tz)
                end  = (now.date() + _td(days=1)).strftime('%Y-%m-%d')
                start= (now.date() - _td(days=300)).strftime('%Y-%m-%d')
                scan_run = tz.now()

                from .models import MeanReversionCandidate as _MRC
                old = list(_MRC.objects.filter(user=user, market=mkt)
                           .values_list('scan_run', flat=True).distinct().order_by('-scan_run')[2:])
                if old:
                    _MRC.objects.filter(user=user, market=mkt, scan_run__in=old).delete()

                results = []

                def _scan_one(sym):
                    try:
                        fetch = f'{sym}.BK' if mkt == 'SET' else sym
                        df = yf.Ticker(fetch).history(start=start, end=end, interval='1d')
                        if df is None or df.empty or len(df) < 60:
                            return None
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(1)
                        df = df.dropna(subset=['Close', 'High', 'Low', 'Open'])

                        curr    = float(df['Close'].iloc[-1])
                        avg_vol = float(df['Volume'].tail(20).mean())
                        if avg_vol == 0:
                            return None

                        # Liquidity filter
                        if mkt == 'SET' and avg_vol * curr < 500_000:
                            return None
                        if mkt == 'US' and avg_vol < 200_000:
                            return None

                        # ADX filter — must be range-bound
                        adx_v = 30.0
                        try:
                            adf = ta.adx(df['High'], df['Low'], df['Close'], 14)
                            ac  = [c for c in adf.columns if c.startswith('ADX_')]
                            if ac:
                                adx_v = float(adf[ac[0]].iloc[-1])
                        except Exception as e:
                            _log.debug(f'MR ADX {sym}: {e}')
                        if adx_v >= 25:
                            return None

                        # RSI filter
                        rsi_v = 50.0
                        try:
                            rs = ta.rsi(df['Close'], 14)
                            if rs is not None and pd.notna(rs.iloc[-1]):
                                rsi_v = float(rs.iloc[-1])
                        except Exception as e:
                            _log.debug(f'MR RSI {sym}: {e}')

                        if rsi_v >= 35 and rsi_v <= 65:
                            return None   # neutral zone — skip

                        direction = 'oversold' if rsi_v < 35 else 'overbought'

                        # Pattern detection
                        pattern = _mr_detect_pattern(df)

                        # Volume confirmation: rvol
                        rvol = float(df['Volume'].iloc[-1]) / avg_vol if avg_vol > 0 else 1.0

                        # Support / Resistance
                        support    = _mr_swing_support(df)
                        resistance = _mr_swing_resistance(df)
                        dist_sup   = ((curr - support) / support * 100) if support else 999.0
                        dist_res   = ((resistance - curr) / curr * 100) if resistance else 999.0

                        # Mean target: SMA20
                        mean_tgt = None
                        try:
                            s20 = ta.sma(df['Close'], 20)
                            if s20 is not None and pd.notna(s20.iloc[-1]):
                                mean_tgt = float(s20.iloc[-1])
                        except Exception:
                            pass

                        upside = ((mean_tgt - curr) / curr * 100) if mean_tgt and curr > 0 else 0.0

                        # 3-month RS raw
                        rs_raw = 0.0
                        if len(df) >= 66:
                            c66 = float(df['Close'].iloc[-66])
                            if c66 > 0:
                                rs_raw = (curr - c66) / c66 * 100

                        r_score = _mr_r_score(rsi_v, adx_v, rvol, pattern, direction, dist_sup)

                        return {
                            'symbol': sym, 'price': round(curr, 4),
                            'direction': direction, 'rsi': round(rsi_v, 1),
                            'adx': round(adx_v, 1), 'avg_vol': avg_vol,
                            'rvol': round(rvol, 2), 'pattern': pattern,
                            'support': support, 'resistance': resistance,
                            'dist_sup': round(dist_sup, 2), 'dist_res': round(dist_res, 2),
                            'mean_tgt': mean_tgt, 'upside': round(upside, 2),
                            'rs_raw': rs_raw, 'r_score': r_score,
                        }
                    except Exception as e:
                        _log.debug(f'MR scan {sym}: {e}')
                        return None

                done = 0
                total = len(syms)
                with cf.ThreadPoolExecutor(max_workers=5) as ex:
                    futs = {ex.submit(_scan_one, s): s for s in syms}
                    for fut in cf.as_completed(futs):
                        done += 1
                        if done % 20 == 0:
                            _c.set(ckey, {'state': 'running', 'progress': done, 'total': total,
                                          'phase': f'สแกน {done}/{total}…'}, timeout=900)
                        try:
                            r = fut.result()
                            if r:
                                results.append(r)
                        except Exception as e:
                            _log.debug(f'MR future {futs[fut]}: {e}')

                # RS percentile ranking
                import pandas as _pd
                rs_map = {}
                rs_vals = {r['symbol']: r['rs_raw'] for r in results}
                if rs_vals:
                    ser = _pd.Series(rs_vals)
                    rs_map = (ser.rank(pct=True) * 99).clip(0, 99).astype(int).to_dict()

                bulk = [_MRC(
                    user=user, scan_run=scan_run, symbol=r['symbol'],
                    market=mkt, price=r['price'], direction=r['direction'],
                    rsi=r['rsi'], adx=r['adx'],
                    avg_vol_20d=r['avg_vol'], rvol=r['rvol'],
                    pattern=r['pattern'],
                    support_level=r['support'], resistance_level=r['resistance'],
                    dist_to_support_pct=r['dist_sup'],
                    dist_to_resistance_pct=r['dist_res'],
                    mean_target=r['mean_tgt'], upside_pct=r['upside'],
                    r_score=r['r_score'], rs_rating=rs_map.get(r['symbol'], 0),
                ) for r in results]
                _MRC.objects.bulk_create(bulk)
                _c.set(ckey, {'state': 'done'}, timeout=300)

            except Exception as exc:
                import logging as _l
                _l.getLogger('stocks').exception(f'[MR Scanner] bg error: {exc}')
                from django.core.cache import cache as _c2
                _c2.set(ckey, {'state': 'done'}, timeout=300)

        _thr.Thread(target=_run_mr, args=(user_id, cache_key, sym_list, market), daemon=True).start()
        return redirect(f'{request.path}?market={market}')

    # ── Display ───────────────────────────────────────────────────────
    from .models import MeanReversionCandidate as _MRC

    all_runs = list(
        _MRC.objects.filter(user=request.user, market=market)
        .values_list('scan_run', flat=True).distinct().order_by('-scan_run')
    )
    try:
        run_idx = max(0, min(int(request.GET.get('run_idx', 0)), len(all_runs) - 1)) if all_runs else 0
    except (ValueError, TypeError):
        run_idx = 0

    candidates  = []
    last_updated = None
    if all_runs:
        run_time    = all_runs[run_idx]
        candidates  = list(_MRC.objects.filter(user=request.user, market=market, scan_run=run_time))
        last_updated = run_time

    direction_filter = request.GET.get('direction', 'all')
    if direction_filter == 'oversold':
        candidates = [c for c in candidates if c.direction == 'oversold']
    elif direction_filter == 'overbought':
        candidates = [c for c in candidates if c.direction == 'overbought']

    min_score = int(request.GET.get('min_score', 60))
    candidates = [c for c in candidates if c.r_score >= min_score]

    oversold_count   = sum(1 for c in candidates if c.direction == 'oversold')
    overbought_count = sum(1 for c in candidates if c.direction == 'overbought')
    pattern_count    = sum(1 for c in candidates if c.pattern)
    top_score        = max((c.r_score for c in candidates), default=0)

    # Regime for recommendation banner
    from .utils import calculate_markov_regime
    _regime_key = f'markov_regime_global_{market}'
    regime = _cp.get(_regime_key)
    if not regime:
        regime = calculate_markov_regime('^SET.BK' if market == 'SET' else '^GSPC')
        _cp.set(_regime_key, regime, 1800)

    return render(request, 'stocks/mean_reversion_scanner.html', {
        'candidates':       candidates,
        'last_updated':     last_updated,
        'all_runs':         all_runs,
        'run_idx':          run_idx,
        'market':           market,
        'direction_filter': direction_filter,
        'min_score':        min_score,
        'oversold_count':   oversold_count,
        'overbought_count': overbought_count,
        'pattern_count':    pattern_count,
        'top_score':        top_score,
        'market_regime':    regime,
    })


# ====== Portfolio Exit Plan - แผนออกหุ้นแต่ละตัว เรียงตามความเร่งด่วน ======

@login_required
def recommendations(request):
    """
    Thai Stock Recommendations with Legendary 5-Pillar Scoring.
    Implements Manual Scan and Persistence (AnalysisCache).
    """
    import json
    import random
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime

    import pandas as pd
    import pandas_ta as ta
    import yfinance as yf

    def process_single_stock(sym):
        try:
            t = yf.Ticker(sym)
            try:
                inf = t.info
                if not isinstance(inf, dict): inf = {}
            except:
                inf = {}
            
            hist_short = t.history(period="1y")
            
            # If sym without .BK fails, try with .BK
            if (not inf or hist_short.empty) and ".BK" not in sym:
                try:
                    alt_t = yf.Ticker(f"{sym}.BK")
                    alt_inf = alt_t.info
                    alt_hist = alt_t.history(period="1y")
                    if isinstance(alt_inf, dict) and alt_inf:
                        t = alt_t
                        inf = alt_inf
                        hist_short = alt_hist
                except: pass

            rsi_val = 'N/A'
            rvol = 1.0
            if not hist_short.empty:
                rsi_series = ta.rsi(hist_short['Close'], length=14)
                if rsi_series is not None and not rsi_series.empty:
                    rsi_val = float(rsi_series.iloc[-1])
                current_vol = float(hist_short['Volume'].iloc[-1])
                avg_vol_20 = float(hist_short['Volume'].tail(20).mean())
                rvol = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

            de = 'N/A'
            try:
                bs = t.quarterly_balance_sheet if not t.quarterly_balance_sheet.empty else t.balance_sheet
                if not bs.empty:
                    col = bs.columns[0]
                    tot_liab = bs.loc['Total Liabilities Net Minority Interest', col] if 'Total Liabilities Net Minority Interest' in bs.index else bs.loc['Total Liabilities', col]
                    tot_eq = bs.loc['Stockholders Equity', col] if 'Stockholders Equity' in bs.index else bs.loc['Total Equity Gross Minority Interest', col]
                    de = tot_liab / tot_eq
            except: pass

            if de == 'N/A' or pd.isna(de):
                de = inf.get('debtToEquity', 'N/A')
                if isinstance(de, (int, float)): de = de / 100

            def scale_to_percent(val):
                if not isinstance(val, (int, float)): return val
                if abs(val) < 1.0: return val * 100
                return val

            pe = inf.get('trailingPE')
            pb = inf.get('priceToBook')
            peg = inf.get('pegRatio')
            roe = scale_to_percent(inf.get('returnOnEquity'))
            dy = scale_to_percent(inf.get('dividendYield'))
            npm = scale_to_percent(inf.get('profitMargins'))
            bv = inf.get('bookValue')
            price = inf.get('currentPrice') or inf.get('regularMarketPrice')

            p_graham = 0; p_buffett = 0; p_lynch = 0; p_greenblatt = 0; p_templeton = 0
            if isinstance(pe, (int, float)) and pe < 15: p_graham += 7
            if isinstance(pb, (int, float)) and pb < 1.2: p_graham += 7
            if isinstance(de, (int, float)) and de < 1.0: p_graham += 6
            fcf = inf.get('freeCashflow')
            if isinstance(roe, (int, float)) and roe > 18: p_buffett += 8
            if isinstance(fcf, (int, float)) and fcf > 0: p_buffett += 7
            if isinstance(npm, (int, float)) and npm > 10: p_buffett += 5
            eg = inf.get('earningsGrowth')
            if isinstance(peg, (int, float)) and 0 < peg < 1.0: p_lynch += 12
            elif isinstance(peg, (int, float)) and 0 < peg < 1.5: p_lynch += 8
            if isinstance(eg, (int, float)) and eg > 0.20: p_lynch += 8
            ev = inf.get('enterpriseValue'); ebitda = inf.get('ebitda')
            if ev and ebitda:
                ey = ebitda / ev
                if ey > 0.12: p_greenblatt += 10
            if isinstance(roe, (int, float)) and roe > 15: p_greenblatt += 10
            if isinstance(pe, (int, float)) and pe < 10: p_templeton += 10

            final_score = (p_graham * 0.75) + (p_buffett * 0.75) + (p_lynch * 2.0) + (p_greenblatt * 1.0) + (p_templeton * 0.5)
            momentum_bonus = 0
            if isinstance(rsi_val, (int, float)) and 30 <= rsi_val <= 50: momentum_bonus += 5
            if rvol > 1.2: momentum_bonus += 5
            final_score = min(100, final_score + momentum_bonus)

            ev_spread = (roe - 10.0) if isinstance(roe, (int, float)) else None
            
            # ====== ENHANCED VALUATION FRAMEWORK (Thai Market) ======
            # วิธีที่ใช้: 3 วิธีผสมกันแบบ Weighted Average
            #   1. Graham Number       - พื้นฐานราคาตามทรัพย์สิน
            #   2. Graham Revised      - คำนึงถึง Growth + Bond Yield (สูตรทองของ Graham)
            #   3. DCF (FCF-based)     - มูลค่าจากกระแสเงินสดอิสระ (multiplier ปรับตาม Growth)
            v_graham = None; v_graham_rev = None; v_dcf = None
            fair_value = None; upside = None; mos_price = None

            # ใช้ Forward EPS ก่อน (มองไปข้างหน้า) ถ้าไม่มีให้ใช้ Trailing EPS
            eps = inf.get('forwardEps') or inf.get('trailingEps') or (price / pe if pe and pe > 0 and price else 0)
            bv = inf.get('bookValue') or 0
            # เฉลี่ย Earnings Growth + Revenue Growth เพื่อลด noise
            eg = inf.get('earningsGrowth') or 0
            rg = inf.get('revenueGrowth') or 0
            raw_growth = ((eg + rg) / 2) if eg and rg else (eg or rg or 0.10)
            fcf = inf.get('freeCashflow')
            shares = inf.get('sharesOutstanding')

            # Bond Yield ของไทย (ใช้ค่าประมาณ Thai 10-yr Govt Bond)
            THAI_BOND_YIELD = 3.0

            import math
            try:
                # 1. Graham Number: √(22.5 × EPS × Book Value)
                #    เหมาะกับหุ้นที่มีทรัพย์สินมาก (Banks, Property, Industrial)
                if isinstance(eps, (int, float)) and eps > 0 and isinstance(bv, (int, float)) and bv > 0:
                    v_graham = math.sqrt(22.5 * eps * bv)

                # 2. Graham Revised: EPS × (8.5 + 2g) × (4.4 / bond_yield)
                #    สูตรดั้งเดิมของ Graham ที่ปรับด้วย Bond Yield เพื่อสะท้อนสภาพดอกเบี้ย
                g_rate = min(25, max(3, raw_growth * 100 if raw_growth < 1 else raw_growth))
                bond_adj = 4.4 / THAI_BOND_YIELD  # ปรับตามดอกเบี้ย (สูงกว่า 1.0 เมื่อ yield ต่ำ)
                if isinstance(eps, (int, float)) and eps > 0:
                    v_graham_rev = eps * (8.5 + 2 * g_rate) * bond_adj

                # 3. FCF-based DCF: (FCF/Share) × Multiplier
                #    Multiplier ปรับตาม Growth Rate (growth สูง = มูลค่าในอนาคตสูงกว่า)
                if fcf and shares and shares > 0:
                    fcf_per_share = fcf / shares
                    if fcf_per_share > 0:
                        fcf_multiple = 20 if g_rate > 15 else (15 if g_rate >= 7 else 12)
                        v_dcf = fcf_per_share * fcf_multiple

                # รวม 3 วิธีด้วย Weighted Average (Graham Rev มีน้ำหนักมากสุด)
                weighted_sum = 0.0; total_weight = 0.0
                if v_graham and v_graham > 0:
                    weighted_sum += v_graham * 1.0; total_weight += 1.0
                if v_graham_rev and v_graham_rev > 0:
                    weighted_sum += v_graham_rev * 2.0; total_weight += 2.0
                if v_dcf and v_dcf > 0:
                    weighted_sum += v_dcf * 1.5; total_weight += 1.5

                if total_weight > 0:
                    fair_value = weighted_sum / total_weight
                elif bv > 0:
                    fair_value = bv * 0.9  # Fallback: 90% ของ Book Value

                if fair_value and price and price > 0:
                    fair_value = min(fair_value, price * 3.0)  # Cap ที่ 200% upside
                    upside = ((fair_value / price) - 1) * 100
                    mos_price = fair_value * 0.75  # ราคาที่ควรซื้อ = Fair Value - 25% Margin of Safety
            except: pass

            return {
                'symbol': sym, 'name': inf.get('longName', sym),
                'pe': pe, 'pb': pb, 'roe': roe, 'dy': dy, 'npm': npm, 'de': de,
                'rsi': rsi_val, 'peg': peg, 'price': price, 'rvol': round(rvol, 2),
                'ev_spread': ev_spread,
                'fair_value': round(fair_value, 2) if fair_value else None,
                'mos_price': round(mos_price, 2) if mos_price else None,
                'upside': round(upside, 1) if upside else None,
                'value_score': round(final_score, 1),
                'legendary': {'graham': p_graham, 'buffett': p_buffett, 'lynch': p_lynch, 'greenblatt': p_greenblatt, 'templeton': p_templeton}
            }
        except: return None

    cache_symbol = 'THAI_REC_ALL'
    cached_data = AnalysisCache.objects.filter(user=request.user, symbol=cache_symbol).first()
    
    stock_previews = []
    last_scanned = None
    if cached_data:
        try:
            stock_previews = json.loads(cached_data.analysis_data)
            last_scanned = cached_data.last_updated
        except: pass

    # If manual scan is requested
    if request.GET.get('scan') == 'true':
        set100_pool = [
            'ADVANC.BK', 'AOT.BK', 'AWC.BK', 'BANPU.BK', 'BBL.BK', 'BDMS.BK', 'BEM.BK', 'BGRIM.BK', 'BH.BK', 'BJC.BK',
            'BTS.BK', 'CBG.BK', 'CENTEL.BK', 'COM7.BK', 'CPALL.BK', 'CPAXT.BK', 'CPF.BK', 'CPN.BK', 'CRC.BK', 'DELTA.BK',
            'EA.BK', 'EGCO.BK', 'GLOBAL.BK', 'GPSC.BK', 'GULF.BK', 'HMPRO.BK', 'INTUCH.BK', 'IRPC.BK', 'IVL.BK', 'JMART.BK',
            'JMT.BK', 'KBANK.BK', 'KCE.BK', 'KKP.BK', 'KTB.BK', 'KTC.BK', 'LH.BK', 'MINT.BK', 'MTC.BK', 'OR.BK',
            'OSP.BK', 'PTT.BK', 'PTTEP.BK', 'PTTGC.BK', 'RATCH.BK', 'SCB.BK', 'SCC.BK', 'SCGP.BK', 'TISCO.BK', 'TOP.BK',
            'TRUE.BK', 'TTB.BK', 'TU.BK', 'WHA.BK', 'AMATA.BK', 'AP.BK', 'BAM.BK', 'BCH.BK', 'BCP.BK', 'BCPG.BK',
            'BLA.BK', 'BPP.BK', 'CHG.BK', 'CK.BK', 'CKP.BK', 'DOHOME.BK', 'ERW.BK', 'FORTH.BK', 'GUNKUL.BK', 'HANA.BK',
            'ICHI.BK', 'ITC.BK', 'M.BK', 'MBK.BK', 'MEGA.BK', 'ORI.BK', 'PLANB.BK', 'PRM.BK', 'PSL.BK', 'PTG.BK',
            'QH.BK', 'RCL.BK', 'ROJNA.BK', 'RS.BK', 'SABINA.BK', 'SAWAD.BK', 'SINGER.BK', 'SIRI.BK', 'SPALI.BK', 'SPRC.BK',
            'STA.BK', 'STEC.BK', 'STGT.BK', 'SUPER.BK', 'TASCO.BK', 'TCAP.BK', 'THANI.BK', 'THCOM.BK', 'THG.BK', 'TIDLOR.BK',
            'TKN.BK', 'TLI.BK', 'TOA.BK', 'TPIPL.BK', 'TPIPP.BK', 'TQM.BK', 'TTA.BK', 'VGI.BK', 'WHAUP.BK'
        ]
        mai_pool = [
            'SPA.BK', 'AU.BK', 'D.BK', 'CHAYO.BK', 'YGG.BK', 'BE8.BK', 'BBIK.BK', 'SNNP.BK', 'TNP.BK', 'TACC.BK',
            'SICT.BK', 'ADD.BK', 'ABM.BK', 'CHO.BK', 'PSTC.BK', 'TVDH.BK', 'NDR.BK', 'BOL.BK', 'IP.BK', 'PLANET.BK'
        ]
        full_pool = set100_pool + mai_pool
        candidate_symbols = random.sample(full_pool, min(100, len(full_pool))) # Limit to 100 for speed
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            scanned_list = list(filter(None, executor.map(process_single_stock, candidate_symbols)))
        
        # Save to Cache
        scanned_list = sorted(scanned_list, key=lambda x: x['value_score'], reverse=True)
        AnalysisCache.objects.update_or_create(
            user=request.user, symbol=cache_symbol,
            defaults={'analysis_data': json.dumps(scanned_list)}
        )
        stock_previews = scanned_list
        last_scanned = datetime.now()


    # Generate Report
    report_text = None
    if request.GET.get('analyze') == 'true' and stock_previews:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        data_str = "\n".join([f"{s['symbol']} Price:{s['price']} Score:{s['value_score']} PEG:{s['peg']}" for s in stock_previews[:30]])
        prompt = f"""คุณคือนักวิเคราะห์หุ้นที่เน้น Maximum Returns ในปี 2026 โดยใช้สไตล์ Peter Lynch (GARP) และ Greenblatt (Magic Formula) เป็นหลัก
        นี่คือข้อมูลหุ้น 30 อันดับแรก:
        {data_str}
        โปรดวิเคราะห์หุ้นที่น่าเข้าซื้อที่สุดสำหรับปี 2026 ภายใต้ธีม AI และ พลังงานสะอาด เขียนรายงานภาษาไทยแบบมืออาชีพ เจาะลึกรายตัวท็อป 10"""
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            report_text = response.text
            if report_text.startswith("```markdown"): report_text = report_text[11:].strip()
            if report_text.endswith("```"): report_text = report_text[:-3].strip()
        except Exception as e: report_text = f"Error: {e}"

    context = {
        'title': 'AI Thai Stock Recommendations',
        'report': report_text,
        'stocks': stock_previews,
        'market': 'thai',
        'last_scanned': last_scanned
    }
    return render(request, 'stocks/recommendations.html', context)


@login_required
def us_recommendations(request):
    """
    US Stock Recommendations with Manual Scan and Persistence.
    """
    import json
    import random
    from datetime import datetime

    import pandas as pd
    import pandas_ta as ta

    cache_symbol = 'US_REC_ALL'
    cached_data = AnalysisCache.objects.filter(user=request.user, symbol=cache_symbol).first()
    
    stock_previews = []
    last_scanned = None
    if cached_data:
        try:
            stock_previews = json.loads(cached_data.analysis_data)
            last_scanned = cached_data.last_updated
        except: pass

    if request.GET.get('scan') == 'true':
        full_pool = [
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B', 'UNH', 'JNJ',
            'XOM', 'JPM', 'V', 'PG', 'MA', 'CVX', 'HD', 'PFE', 'ABBV', 'KO',
            'PEP', 'COST', 'MCD', 'WMT', 'DIS', 'ADBE', 'CRM', 'NFLX', 'AMD', 'INTC',
            'QCOM', 'TXN', 'AMAT', 'MU', 'LRCX', 'AVGO', 'NKE', 'TMUS', 'SBUX', 'LOW',
            'UPS', 'CAT', 'GE', 'HON', 'DE', 'MMM', 'LMT', 'BA', 'RTX', 'T'
        ]
        candidate_symbols = random.sample(full_pool, min(50, len(full_pool)))
        
        scanned_list = []
        for sym in candidate_symbols:
            try:
                t = yf.Ticker(sym)
                inf = t.info
                hist = t.history(period="1y")
                if hist.empty: continue
                
                rsi_series = ta.rsi(hist['Close'], length=14)
                rsi_val = float(rsi_series.iloc[-1]) if rsi_series is not None and not rsi_series.empty else None
                current_vol = float(hist['Volume'].iloc[-1])
                avg_vol_20 = float(hist['Volume'].tail(20).mean())
                rvol = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

                def scale_to_percent(val):
                    if not isinstance(val, (int, float)): return val
                    if abs(val) < 1.0: return val * 100
                    return val

                pe = inf.get('trailingPE')
                pb = inf.get('priceToBook')
                peg = inf.get('pegRatio')
                roe = scale_to_percent(inf.get('returnOnEquity'))
                dy = scale_to_percent(inf.get('dividendYield'))
                npm = scale_to_percent(inf.get('profitMargins'))
                price = inf.get('currentPrice') or inf.get('regularMarketPrice')
                de = inf.get('debtToEquity')
                if isinstance(de, (int, float)) and de > 5: de = de / 100

                # 5 PILLARS v2 (US Focus)
                p_graham = 0; p_buffett = 0; p_lynch = 0; p_greenblatt = 0; p_templeton = 0
                
                if isinstance(pe, (int, float)) and pe < 18: p_graham += 7
                if isinstance(de, (int, float)) and de < 1.0: p_graham += 6
                
                fcf = inf.get('freeCashflow')
                if isinstance(roe, (int, float)) and roe > 20: p_buffett += 8
                if isinstance(fcf, (int, float)) and fcf > 0: p_buffett += 7
                
                eg = inf.get('earningsGrowth')
                if isinstance(peg, (int, float)) and 0 < peg < 1.0: p_lynch += 12
                if isinstance(eg, (int, float)) and eg > 0.15: p_lynch += 8
                
                ev = inf.get('enterpriseValue'); ebitda = inf.get('ebitda')
                if ev and ebitda:
                    ey = ebitda / ev
                    if ey > 0.10: p_greenblatt += 10
                if isinstance(roe, (int, float)) and roe > 15: p_greenblatt += 10
                
                if isinstance(pe, (int, float)) and pe < 12: p_templeton += 10
                if isinstance(pb, (int, float)) and pb < 1.2: p_templeton += 10

                final_score = (p_graham * 0.75) + (p_buffett * 0.75) + (p_lynch * 2.0) + (p_greenblatt * 1.0) + (p_templeton * 0.5)
                final_score = min(100, final_score + 5 if rvol > 1.2 else final_score)

                # Economic Profit (ROE - CoE 10%)
                ev_spread = None
                if isinstance(roe, (int, float)):
                    ev_spread = roe - 10.0

                # ====== ENHANCED VALUATION FRAMEWORK (US Market) ======
                # ใช้ 3 วิธีเหมือน Thai Framework แต่ Bond Yield อิง US 10-yr Treasury
                fair_value = None; upside = None; mos_price = None
                v_graham = None; v_graham_rev = None; v_dcf = None

                eps = inf.get('forwardEps') or inf.get('trailingEps') or (price / pe if pe and pe > 0 and price else 0)
                bv = inf.get('bookValue') or 0
                eg = inf.get('earningsGrowth') or 0
                rg = inf.get('revenueGrowth') or 0
                raw_growth = ((eg + rg) / 2) if eg and rg else (eg or rg or 0.10)
                fcf_us = inf.get('freeCashflow')
                shares_us = inf.get('sharesOutstanding')

                # Bond Yield ของสหรัฐฯ (US 10-yr Treasury - ประมาณ 4.4%)
                US_BOND_YIELD = 4.4

                if isinstance(eps, (int, float)):
                    import math
                    try:
                        g_rate = min(25, max(3, raw_growth * 100 if raw_growth < 1 else raw_growth))
                        bond_adj = 4.4 / US_BOND_YIELD  # ≈ 1.0 เมื่อ yield ปกติ

                        # 1. Graham Number
                        if eps > 0 and isinstance(bv, (int, float)) and bv > 0:
                            v_graham = math.sqrt(22.5 * eps * bv)

                        # 2. Graham Revised + Bond Yield adjustment
                        if eps > 0:
                            v_graham_rev = eps * (8.5 + 2 * g_rate) * bond_adj

                        # 3. DCF (FCF-based, dynamic multiplier)
                        if fcf_us and shares_us and shares_us > 0:
                            fcf_ps = fcf_us / shares_us
                            if fcf_ps > 0:
                                fcf_multiple = 20 if g_rate > 15 else (15 if g_rate >= 7 else 12)
                                v_dcf = fcf_ps * fcf_multiple

                        # Weighted Average (Graham Rev: น้ำหนัก 2, DCF: 1.5, Graham No.: 1)
                        ws = 0.0; tw = 0.0
                        if v_graham and v_graham > 0: ws += v_graham * 1.0; tw += 1.0
                        if v_graham_rev and v_graham_rev > 0: ws += v_graham_rev * 2.0; tw += 2.0
                        if v_dcf and v_dcf > 0: ws += v_dcf * 1.5; tw += 1.5

                        if tw > 0:
                            fair_value = ws / tw
                        elif bv > 0:
                            fair_value = bv * 0.7  # Fallback: 70% ของ Book Value

                        if fair_value and price and price > 0:
                            fair_value = min(fair_value, price * 3.0)  # Cap ที่ 200% upside
                            upside = ((fair_value / price) - 1) * 100
                            mos_price = fair_value * 0.75  # ราคาที่ควรซื้อ (25% Margin of Safety)
                    except: pass

                scanned_list.append({
                    'symbol': sym, 'name': inf.get('shortName', sym),
                    'pe': pe, 'pb': pb, 'roe': roe, 'dy': dy, 'npm': npm, 'de': de,
                    'rsi': rsi_val, 'peg': peg, 'price': price, 'rvol': round(rvol, 2),
                    'ev_spread': ev_spread,
                    'fair_value': round(fair_value, 2) if fair_value else None,
                    'mos_price': round(mos_price, 2) if mos_price else None,
                    'upside': round(upside, 1) if upside else None,
                    'value_score': round(final_score, 1),
                    'legendary': {'graham': p_graham, 'buffett': p_buffett, 'lynch': p_lynch, 'greenblatt': p_greenblatt, 'templeton': p_templeton}
                })
            except: continue
            
        scanned_list = sorted(scanned_list, key=lambda x: x['value_score'], reverse=True)
        AnalysisCache.objects.update_or_create(
            user=request.user, symbol=cache_symbol,
            defaults={'analysis_data': json.dumps(scanned_list)}
        )
        stock_previews = scanned_list
        last_scanned = datetime.now()

    report_text = None
    if request.GET.get('analyze') == 'true' and stock_previews:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        data_str = "\n".join([f"{s['symbol']} Price:{s['price']} Score:{s['value_score']} PEG:{s['peg']}" for s in stock_previews[:20]])
        prompt = f"คุณคือนักวิเคราะห์หุ้นอเมริกัน เน้น Maximum Returns ปี 2026 โดยใช้ Lynch และ Greenblatt สแกนหุ้น {data_str} โปรดสรุปตัวท็อปในธีม AI/Semiconductor/Energy ภาษาไทย"
        try:
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            report_text = response.text
        except: report_text = "Analysis service unavailable."

    context = {
        'title': 'AI US Stock Recommendations',
        'report': report_text,
        'stocks': stock_previews,
        'market': 'us',
        'last_scanned': last_scanned
    }
    return render(request, 'stocks/recommendations.html', context)



# ====== Morning Briefing - รายงานสรุปประจำวัน ======

@login_required
def momentum_scanner(request):
    """
    Globally scans SET100 roughly matching Mark Minervini Trend Template.
    Runs in a background thread to avoid 504 timeout.
    """
    import threading as _th

    from django.core.cache import cache as _cp
    from django.http import JsonResponse as _JR

    user_id   = request.user.id
    cache_key = f'momentum_scan_{user_id}'

    # --- Markov Market Regime Pulse ---
    from django.core.cache import cache

    from .utils import calculate_markov_regime
    regime_cache_key = 'markov_regime_SET' # Momentum mainly for SET
    regime = cache.get(regime_cache_key)
    if not regime:
        regime = calculate_markov_regime('^SET.BK')
        cache.set(regime_cache_key, regime, timeout=1800)

    # ── AJAX status poll ──────────────────────────────────────────────
    if request.GET.get('scan_status') == '1':
        st = _cp.get(cache_key, {'state': 'idle'})
        if st.get('state') == 'done':
            _cp.delete(cache_key)
        return _JR(st)

    # ── Trigger background scan ───────────────────────────────────────
    if request.GET.get('scan') == 'true' or request.method == 'POST':
        from .utils import get_top_ranked_symbols, refresh_all_thai_symbols
        # ใช้ Top 300 หุ้นใหญ่เท่านั้นเพื่อความเร็วและคุณภาพ
        scan_symbols = get_top_ranked_symbols(market='SET', limit=300, auto_refresh=True)
        
        if not scan_symbols:
            refresh_all_thai_symbols()
            scan_symbols = get_top_ranked_symbols(market='SET', limit=300, auto_refresh=True)

        already = _cp.get(cache_key, {})
        if already.get('state') != 'running':
            total_syms = len(scan_symbols)
            _cp.set(cache_key, {'state': 'running', 'progress': 0, 'total': total_syms, 'phase': 'เริ่มสแกน…'}, timeout=900)

            def _run_momentum_bg(uid, ckey, sym_list):
                try:
                    import numpy as _np
                    import pandas as _pd
                    import pandas_ta as _ta
                    import yfinance as _yf
                    from django.contrib.auth import get_user_model
                    from django.core.cache import cache as _c

                    from .models import MomentumCandidate as _MC
                    from .utils import (
                        analyze_momentum_technical,
                        find_supply_demand_zones,
                    )
                    from .utils import get_top_ranked_symbols as _GTRS
                    User = get_user_model()
                    user = User.objects.get(pk=uid)
                    
                    sym_list = _GTRS(market='SET', limit=300, auto_refresh=True)
                    _MC.objects.filter(user=user, market='SET').delete()
                    
                    # --- STAGE 1: Fast Screening (The Radar) ---
                    # Scan all 800+ symbols for basic liquidity and trend
                    total_syms = len(sym_list)
                    _c.set(ckey, {'state': 'running', 'progress': 5, 'total': total_syms, 'phase': f'Stage 1: สแกนด่วน {total_syms} ตัว...'}, timeout=900)
                    
                    # Align dates with Precision scanner for better data consistency
                    from datetime import datetime as _dt
                    from datetime import timedelta as _td

                    import pytz as _pytz
                    _bkk_tz = _pytz.timezone('Asia/Bangkok')
                    _now_bkk = _dt.now(_bkk_tz)
                    scan_end_date  = _now_bkk.date() + _td(days=1)
                    scan_end_str   = scan_end_date.strftime('%Y-%m-%d')
                    scan_start_str = (_now_bkk.date() - _td(days=600)).strftime('%Y-%m-%d')
                    
                    # --- STAGE 1: Fast Screening (Turbo Chunks) ---
                    from yahooquery import Ticker as _TQ
                    _c.set(ckey, {'state': 'running', 'progress': 5, 'total': total_syms, 'phase': 'Stage 1: 🔎 Fast Screening...'}, timeout=900)
                    
                    candidates = []
                    chunk_size = 100
                    for i in range(0, total_syms, chunk_size):
                        chunk = sym_list[i : i + chunk_size]
                        chunk_bk = [f"{s}.BK" for s in chunk]
                        _c.set(ckey, {'state': 'running', 'progress': 5 + int((i/total_syms)*15), 'total': total_syms, 'phase': f'Phase 1: กรองราคาด่วน {i}/{total_syms}...'}, timeout=600)
                        try:
                            tq = _TQ(chunk_bk, timeout=60)
                            prices = tq.price
                            for symbol in chunk:
                                try:
                                    s_bk = f"{symbol}.BK"
                                    if not isinstance(prices, dict) or s_bk not in prices:
                                        candidates.append({'symbol': symbol}); continue
                                    
                                    p_data = prices.get(s_bk)
                                    if not isinstance(p_data, dict) or 'regularMarketPrice' not in p_data:
                                        candidates.append({'symbol': symbol}); continue
                                    
                                    curr_p = p_data.get('regularMarketPrice')
                                    avg_vol = p_data.get('averageDailyVolume3Month', 0)
                                    # Very loose liquidity filter to ensure we get results
                                    if (curr_p * avg_vol) < 150000: continue
                                    candidates.append({'symbol': symbol})
                                except Exception: candidates.append({'symbol': symbol})
                        except Exception:
                            for sym in chunk: candidates.append({'symbol': sym})

                    if len(candidates) < 20: # Emergency fallback
                        candidates = [{'symbol': s} for s in sym_list[:150]]
                        
                    # --- STAGE 2: Deep Technical Analysis (Multi-threaded Turbo) ---
                    total_cand = len(candidates)
                    pre_results = []
                    _c.set(ckey, {'state': 'running', 'progress': 20, 'total': total_cand, 'phase': f'Stage 2: Technical Scan ({total_cand})...'}, timeout=900)
                    
                    import concurrent.futures as _cf
                    def _analyze_one(symbol):
                        try:
                            s_bk = f"{symbol}.BK"
                            df = _yf.download(s_bk, period="1y", interval="1d", progress=False, timeout=20)
                            if df is None or df.empty or len(df) < 55: return None
                            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
                            
                            df['EMA50'] = _ta.ema(df['Close'], length=50)
                            df['EMA200'] = _ta.ema(df['Close'], length=200)
                            df['RSI'] = _ta.rsi(df['Close'], length=14)
                            adx = _ta.adx(df['High'], df['Low'], df['Close'], length=14)
                            if adx is not None: df = pd.concat([df, adx], axis=1)
                            df['MFI'] = _ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                            
                            tech = analyze_momentum_technical_v2(df)
                            if tech.get('rsi', 0) < 35: return None 
                            
                            return {
                                'symbol': symbol, 'df': df, 'tech': tech,
                                'price': float(df['Close'].iloc[-1]),
                                'year_high': float(df['High'].tail(252).max()),
                                'sd_zone': find_supply_demand_zones(df)
                            }
                        except Exception: return None

                    # Run Stage 2 in parallel for speed
                    with _cf.ThreadPoolExecutor(max_workers=15) as executor:
                        futs = {executor.submit(_analyze_one, c['symbol']): c['symbol'] for c in candidates[:150]}
                        done = 0
                        for fut in _cf.as_completed(futs):
                            done += 1
                            if done % 10 == 0:
                                _c.set(ckey, {'state': 'running', 'progress': 20 + int((done/150)*65), 'phase': f'Analyzing {done}/150...'}, timeout=600)
                            
                            res = None
                            try:
                                res = fut.result(timeout=25)
                            except Exception: pass
                            
                            # FALLBACK: If Threaded yfinance fails, try ONE last Sync check with YahooQuery for this symbol
                            if not res:
                                symbol = futs[fut]
                                try:
                                    s_bk = f"{symbol}.BK"
                                    tq_single = _TQ(s_bk)
                                    h = tq_single.history(period='1y', interval='1d')
                                    if h is not None and not h.empty:
                                        if isinstance(h.index, pd.MultiIndex): h = h.xs(s_bk, level=0)
                                        # Minimal data requirement reduced to 40
                                        if len(h) >= 40:
                                            h.rename(columns={'adjclose': 'Close', 'high': 'High', 'low': 'Low', 'open': 'Open', 'volume': 'Volume'}, inplace=True)
                                            h['EMA50'] = _ta.ema(h['Close'], length=50)
                                            h['EMA200'] = _ta.ema(h['Close'], length=min(200, len(h)-1))
                                            h['RSI'] = _ta.rsi(h['Close'], length=14)
                                            tech = analyze_momentum_technical_v2(h)
                                            if tech.get('rsi', 0) > 30: 
                                                 res = {
                                                    'symbol': symbol, 'df': h, 'tech': tech,
                                                    'price': float(h['Close'].iloc[-1]),
                                                    'year_high': float(h['High'].tail(252).max()),
                                                    'sd_zone': find_supply_demand_zones(h)
                                                }
                                except Exception: pass
                                
                            if res: pre_results.append(res)

                    # --- STAGE 3: Bulk Fundamental ---
                    fund_data = {}
                    if pre_results:
                        _c.set(ckey, {'state': 'running', 'progress': 85, 'phase': 'Stage 3: Fundamental...'}, timeout=900)
                        from .utils import YQTicker
                        match_bk = [f"{r['symbol']}.BK" for r in pre_results]
                        try:
                            yq_all = YQTicker(match_bk)
                            modules = yq_all.get_modules('financialData summaryProfile defaultKeyStatistics')
                            for s_bk, val in modules.items():
                                if not isinstance(val, dict): continue
                                sym_clean = s_bk.replace('.BK','')
                                prof = val.get('summaryProfile', {})
                                fin  = val.get('financialData', {})
                                keystat = val.get('defaultKeyStatistics', {})
                                eps_g = keystat.get('earningsQuarterlyGrowth') or fin.get('earningsGrowth') or 0.0
                                fund_data[sym_clean] = {
                                    'sector': prof.get('sector', 'Other'),
                                    'eps_growth': float(eps_g) * 100,
                                    'rev_growth': float(fin.get('revenueGrowth', 0) or 0) * 100
                                }
                        except Exception: pass

                    # FINAL: Save to DB
                    _c.set(ckey, {'state': 'running', 'progress': 95, 'phase': 'Saving results...'}, timeout=600)
                    bulk_objs = []
                    for r in pre_results:
                        sym = r['symbol']
                        sd  = r['sd_zone']
                        tech = r['tech']
                        df = r['df']
                        f   = fund_data.get(sym, {'sector': 'N/A', 'eps_growth': 0.0, 'rev_growth': 0.0})
                        
                        dz_start = dz_end = sz_start = sz_end = sl_price = rr_val = None
                        entry_strat = ''
                        if sd:
                            entry_strat = sd['type']; dz_start = sd['start']; dz_end = sd['end']
                            sz_start = sd['target']; sz_end = sd['target'] * 1.02
                            sl_price = sd['stop_loss']; rr_val = sd['rr_ratio']

                        bulk_objs.append(_MC(
                            user=user, symbol=sym, symbol_bk=f"{sym}.BK", market='SET', price=r['price'],
                            rsi=tech.get('rsi', 0), 
                            adx=float(df['ADX_14'].iloc[-1]) if 'ADX_14' in df.columns else 0,
                            mfi=float(df['MFI'].iloc[-1]) if 'MFI' in df.columns else 0,
                            rvol=tech.get('rvol', 0), 
                            rvol_bullish=tech.get('rvol_bullish', False),
                            technical_score=tech.get('score', 0), 
                            rs_rating=0,
                            entry_strategy=entry_strat, 
                            demand_zone_start=dz_start, 
                            demand_zone_end=dz_end,
                            supply_zone_start=sz_start, 
                            supply_zone_end=sz_end, 
                            stop_loss=sl_price, 
                            risk_reward_ratio=rr_val,
                            year_high=r['year_high'], 
                            upside_to_high=((r['year_high'] - r['price'])/r['price'])*100 if r['price'] > 0 else 0,
                            sector=f['sector'], 
                            eps_growth=f['eps_growth'], 
                            rev_growth=f['rev_growth'],
                            stage2=r['price'] > float(df['EMA200'].iloc[-1]) if 'EMA200' in df.columns else False
                        ))
                    if bulk_objs:
                        _MC.objects.bulk_create(bulk_objs)
                except Exception as e:
                    import logging; logging.getLogger('stocks').error(f"Momentum Scan Error: {e}")
                finally:
                    _c.set(ckey, {'state': 'done', 'progress': 100, 'total': total_syms, 'phase': 'เสร็จสิ้น'}, timeout=120)

            # Start Worker
            _th.Thread(target=_run_momentum_bg, args=(user_id, cache_key, scan_symbols), daemon=True).start()

    # ====== Handle AI Summary Analysis (Optional) ======
    ai_analysis = ""
    if request.GET.get('analyze') == 'true':
        try:
            data_to_analyze = []
            top_best = MomentumCandidate.objects.filter(user=request.user, market='SET').order_by('-technical_score')[:15]
            for t in top_best:
                data_to_analyze.append({
                    'symbol': t.symbol, 'score': t.technical_score, 'rvol': t.rvol, 'rsi': t.rsi,
                    'eps_growth': t.eps_growth, 'rev_growth': t.rev_growth, 'upside': t.upside_to_high
                })
            
            if data_to_analyze:
                prompt = f"หุ้นไทย Momentum แรงที่สุด 15 ตัวจากระบบสแกน: {json.dumps(data_to_analyze)}\nช่วยวิเคราะห์และคัดเลือก 3-5 ตัวที่น่าสนใจที่สุด พร้อมเหตุผลเชิงกลยุทธ์ตามสไตล์ Mark Minervini และบอกจุดระวัง"
                ai_analysis = analyze_with_ai(prompt)
        except Exception as e:
            ai_analysis = f"AI Analysis Error: {str(e)}"

    # ป้องกัน FieldError จาก ?sort= ค่าที่ไม่มีในฐานข้อมูล
    _MOMENTUM_SORT_MAP = {
        'score':          '-technical_score',
        'technical_score':'-technical_score',
        'price':          '-price',
        'rsi':            '-rsi',
        'rvol':           '-rvol',
        'rs':             '-rs_rating',
        'rs_rating':      '-rs_rating',
        'symbol':         'symbol',
        'adx':            '-adx',
        'upside':         '-upside_to_high',
    }
    raw_sort   = request.GET.get('sort', '-technical_score')
    sort_by    = _MOMENTUM_SORT_MAP.get(raw_sort, raw_sort if raw_sort.lstrip('-') in {
        'technical_score','price','rsi','rvol','rs_rating','symbol','adx','upside_to_high','mfi'
    } else '-technical_score')
    candidates = MomentumCandidate.objects.filter(user=request.user, market='SET').order_by(sort_by)
    scanned_at = candidates.first().scanned_at if candidates.exists() else None

    # ตรวจว่ากำลังสแกนอยู่ - ถ้าใช่ ซ่อน results เพื่อไม่ให้กระพริบ
    _scan_state = _cp.get(cache_key, {})
    is_scanning = _scan_state.get('state') == 'running'

    candidate_list = list(candidates) if not is_scanning else []

    # ====== Live Price + Fresh Zone - recompute zone จาก historical data ใหม่ทุกครั้ง ======
    if candidate_list:
        try:
            import concurrent.futures as _mcf
            from datetime import datetime as _mdt
            from datetime import time as _mtime
            from datetime import timedelta as _mtd

            # คำนวณ end date เหมือน entry_finder - ห้ามรวม today's incomplete bar ตอนตลาดเปิด
            import pytz as _mpytz
            _mnow   = _mdt.now(_mpytz.timezone('Asia/Bangkok'))
            _mt     = _mnow.time()
            _market_open_now = (
                _mnow.weekday() < 5 and
                (
                    _mt < _mtime(10, 0) or
                    (_mtime(10, 0) <= _mt <= _mtime(12, 30)) or
                    (_mtime(12, 30) < _mt < _mtime(14, 30)) or
                    (_mtime(14, 30) <= _mt <= _mtime(16, 30))
                )
            )
            _mend_date  = (_mnow.date() - _mtd(days=1)) if _market_open_now else _mnow.date()
            _mend_str   = _mend_date.strftime('%Y-%m-%d')
            _mstart_str = (_mend_date - _mtd(days=600)).strftime('%Y-%m-%d')

            def _mom_live(arg):
                sym, mkt = arg
                try:
                    full_sym = f"{sym}.BK" if mkt == 'SET' else sym
                    fi = yf.Ticker(full_sym).fast_info
                    p = getattr(fi, 'last_price', None)
                    pc = getattr(fi, 'regular_market_previous_close', getattr(fi, 'previous_close', None))
                    live_price = float(p) if p else None
                    prev_close = float(pc) if pc else None

                    # Recompute zone - ใช้ Ticker().history() (thread-safe), end date เหมือน entry_finder
                    _t = yf.Ticker(full_sym)
                    df = _t.history(start=_mstart_str, end=_mend_str, interval='1d')
                    fresh_zone = None
                    if df is not None and len(df) >= 50:
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.get_level_values(0)
                        fresh_zone = find_supply_demand_zones_v2(df)
                    return sym, live_price, fresh_zone, prev_close
                except Exception:
                    return sym, None, None, None

            live_map = {}
            zone_map = {}   # fresh zones - keyed by symbol
            prev_close_map = {}
            with _mcf.ThreadPoolExecutor(max_workers=6) as _mex:
                for _s, _p, _z, _pc in _mex.map(_mom_live, [(c.symbol, c.market) for c in candidate_list]):
                    if _p: live_map[_s] = _p
                    if _z: zone_map[_s] = _z
                    if _pc: prev_close_map[_s] = _pc
        except Exception:
            live_map = {}
            zone_map = {}
            prev_close_map = {}

        for c in candidate_list:
            lp  = live_map.get(c.symbol)
            pc  = prev_close_map.get(c.symbol) or float(c.price or 0)
            c.live_price = lp
            ref = lp if lp else float(c.price or 0)

            # ใช้ fresh zone ถ้ามี มิฉะนั้น fallback ไป DB zone
            fz = zone_map.get(c.symbol)
            if fz:
                dz_s = float(fz.get('start') or 0)
                dz_e = float(fz.get('end')   or 0)
                sz_s = float(fz.get('target') or 0)
                # อัปเดต zone ใน candidate object ด้วย เพื่อให้ template แสดงถูก
                c.demand_zone_start = dz_s or c.demand_zone_start
                c.demand_zone_end   = dz_e or c.demand_zone_end
                c.supply_zone_start = sz_s or c.supply_zone_start
            else:
                dz_s = float(c.demand_zone_start or 0)
                dz_e = float(c.demand_zone_end   or 0)
                sz_s = float(c.supply_zone_start or 0)

            # zone status ตาม live price + fresh zone
            c.live_in_zone    = dz_s > 0 and dz_e > 0 and dz_e <= ref <= dz_s
            c.live_broke_zone = dz_e > 0 and ref < dz_e
            c.live_above_tp   = sz_s > 0 and ref >= sz_s
            c.live_near_tp    = (not c.live_above_tp) and sz_s > 0 and dz_s > 0 and (sz_s - ref) / (sz_s - dz_s) * 100 <= 15 if (sz_s - dz_s) > 0 else False
            c.live_zone_prox  = 0.0 if ref <= dz_s else round((ref - dz_s) / dz_s * 100, 1) if dz_s > 0 else 999
            if lp and pc > 0:
                c.live_change_pct = round((lp - pc) / pc * 100, 2)
            else:
                c.live_change_pct = None

    context = {
        'title': 'Global Momentum Scanner (CAN SLIM)',
        'candidates': candidate_list,
        'ai_analysis': ai_analysis,
        'scanned_at': scanned_at,
        'current_sort': sort_by,
        'is_scanning': is_scanning,
        'has_scanned': bool(candidate_list) or (candidates.exists() and not is_scanning),
        'market_regime': regime,
    }
    return render(request, 'stocks/momentum.html', context)


# ====== Market Condition Analyzer - วิเคราะห์สภาวะตลาด SET Index ======

# ====== Precision Momentum Scanner - เวอร์ชันกรองคุณภาพสูง ======
@login_required
def indicator_manual(request):
    """Complete guide for all indicators used in the system."""
    return render(request, 'stocks/indicator_manual.html')

@login_required
def vcp_manual(request):
    return render(request, 'stocks/vcp_manual.html')

@login_required
def sepa_manual(request):
    """SEPA Complete Manual — Minervini Superperformance System guide"""
    return render(request, 'stocks/sepa_manual.html')

@login_required
def ehlers_manual(request):
    return render(request, 'stocks/ehlers_manual.html')

@login_required
def mm_manual(request):
    """Trading with Market Makers (MM) Manual"""
    return render(request, 'stocks/mm_manual.html')


@login_required
def minervini_sepa_scanner(request):
    """
    Minervini SEPA Scanner - ระบบสแกนเจาะจงเฉพาะตามตำรา Mark Minervini
    กรองเฉพาะหุ้นที่อยู่ใน Stage 2 และมีฟอร์ม VCP/VDU
    """
    # ดึงรายชื่อรอบการสแกน (ใช้จาก PrecisionScanCandidate)
    all_runs = list(
        PrecisionScanCandidate.objects
        .filter(user=request.user, market='SET')
        .values_list('scan_run', flat=True)
        .order_by('-scan_run')
        .distinct()
    )
    
    candidates = []
    last_updated = None
    selected_run_idx = int(request.GET.get('run_idx', 0))

    if all_runs:
        if selected_run_idx < len(all_runs):
            run_time = all_runs[selected_run_idx]
            # กรองเฉพาะ Stage 2 + RS Rating >= 70 (ตาม SEPA criteria)
            candidates = list(PrecisionScanCandidate.objects.filter(
                user=request.user,
                scan_run=run_time,
                stage2=True,
                rs_rating__gte=70,
            ).order_by('-vcp_setup', '-rs_rating'))
            last_updated = run_time

    # เพิ่มเติม: กรองเฉพาะตัวที่มีสัญญาณ VCP เพื่อความ Clean
    vcp_only = request.GET.get('vcp_only') == '1'
    if vcp_only:
        candidates = [c for c in candidates if c.vcp_setup]

    # hide_at_tp: ซ่อนหุ้นที่ราคาอยู่ใกล้/ถึง Target (upside_to_high < 10%)
    hide_at_tp = request.GET.get('hide_at_tp', '1') == '1'
    if hide_at_tp:
        candidates = [c for c in candidates if c.upside_to_high >= 10.0]

    # earnings_filter: กรองเฉพาะหุ้นที่ผ่านเกณฑ์ Minervini Earnings (EPS ≥ 25% หรือ Rev ≥ 25%)
    earnings_filter = request.GET.get('earnings_filter') == '1'
    if earnings_filter:
        candidates = [c for c in candidates if (getattr(c, 'eps_growth', 0) or 0) >= 25 or (getattr(c, 'rev_growth', 0) or 0) >= 25]

    # คำนวณ field เพิ่มเติมสำหรับแสดงผล + SEPA Score
    for c in candidates:
        # % ห่างจาก Pivot (52w High)
        c.dist_from_pivot = round(c.upside_to_high, 1)
        # สถานะ TP
        if c.upside_to_high < 5:
            c.tp_status = 'at_tp'
        elif c.upside_to_high < 10:
            c.tp_status = 'near_tp'
        else:
            c.tp_status = None

        # Earnings badge helper attrs
        eps_g = getattr(c, 'eps_growth', 0.0) or 0.0
        rev_g = getattr(c, 'rev_growth', 0.0) or 0.0
        c.eps_badge = 'strong' if eps_g >= 50 else ('pass' if eps_g >= 25 else ('warn' if eps_g >= 0 else 'fail'))
        c.rev_badge = 'strong' if rev_g >= 50 else ('pass' if rev_g >= 25 else ('warn' if rev_g >= 0 else 'fail'))

        # SEPA Score (รวม Earnings bonus)
        sc = 0
        if c.vcp_setup:
            sc += 30
            sc += int(max(0, (10 - min(c.vcp_tightness, 10)) * 2))
            sc += min(c.vcp_contractions, 5) * 3
        if c.vcp_vdu or c.vdu_near_zone:
            sc += 20
        if c.pocket_pivot:
            sc += 10
        sc += int(c.rs_rating * 0.7)
        if c.adx >= 25:
            sc += 10
        elif c.adx >= 15:
            sc += 5
        if c.vcp_setup:
            if c.dist_from_pivot <= 5:
                sc += 10
            elif c.dist_from_pivot <= 10:
                sc += 5
            elif c.dist_from_pivot > 15:
                sc -= 5
        # ── Earnings bonus (Minervini) ──────────────────────────
        if eps_g >= 50:  sc += 20
        elif eps_g >= 25: sc += 12
        elif eps_g >= 10: sc += 5
        if rev_g >= 50:  sc += 10
        elif rev_g >= 25: sc += 6
        c.sepa_score = sc

    # Sort by SEPA Score descending
    candidates.sort(key=lambda c: c.sepa_score, reverse=True)

    # Assign rank
    for i, c in enumerate(candidates, 1):
        c.sepa_rank = i

    context = {
        'candidates': candidates,
        'last_updated': last_updated,
        'all_runs': all_runs,
        'selected_run_idx': selected_run_idx,
        'vcp_only': vcp_only,
        'hide_at_tp': hide_at_tp,
        'earnings_filter': earnings_filter,
    }
    return render(request, 'stocks/sepa_scanner.html', context)

@login_required
def precision_momentum_scanner(request):
    """
    Precision Momentum Scanner - กรองคุณภาพสูงกว่า momentum_scanner
    ปรับปรุงจาก momentum_scanner:
    1. ERC ต้องมี Body + Volume > 1.5x avg (ทั้งสองเงื่อนไข)
    2. ADX >= 20 (กรองเทรนด์แข็งแกร่งเท่านั้น)
    3. Liquidity filter: avg 20d volume >= 500,000 หุ้น
    4. Supply target = 52-week high เสมอ
    5. ATR-based stop loss
    6. Direction-aware RVOL scoring
    7. เก็บประวัติ scan 3 รอบล่าสุด
    8. is_new_entry flag (หุ้นใหม่ vs ยังอยู่จากรอบก่อน)
    """
    # ====== AJAX Status Poll ======
    if request.GET.get('scan_status') == '1':
        from django.core.cache import cache as _cp
        from django.http import JsonResponse as _JR
        _key = f'precision_scan_{request.user.id}'
        _st = _cp.get(_key, {'state': 'idle'})
        if _st.get('state') == 'done':
            _cp.delete(_key)
        return _JR(_st)
    from django.utils import timezone as tz
    from yahooquery import Ticker as YQTicker
    from .utils import analyze_momentum_technical_v2, get_top_ranked_symbols

    # โหลด symbols เบื้องต้นแบบรวดเร็ว (ดึงจาก Cache/DB เดิม) สำหรับใช้ใน context ของ GET request
    scan_symbols = get_top_ranked_symbols(market='SET', limit=400, auto_refresh=False)

    if request.method == "POST" and request.POST.get('action') == 'scan':
        import threading

        from django.core.cache import cache as _cache_bg

        user_id   = request.user.id
        cache_key = f'precision_scan_{user_id}'
        
        # เก็บหน้าที่ต้องกลับไปหลังสแกนเสร็จ
        raw_next = request.POST.get('next_url')
        next_url = 'stocks:minervini_sepa_scanner' if raw_next == 'sepa' else 'stocks:precision_momentum_scanner'

        # cache.add() เป็น atomic lock - กัน double-submit เปิด background thread ซ้อนกัน
        _init_status = {'state': 'running', 'progress': 0, 'total': 0, 'phase': 'เตรียมข้อมูล…'}
        if not _cache_bg.add(cache_key, _init_status, timeout=900):
            _cur = _cache_bg.get(cache_key) or {}
            if _cur.get('state') == 'running':
                return redirect(next_url)
            # key ค้างจากรอบก่อน (done/idle) - เขียนทับแล้วสแกนต่อ
            _cache_bg.set(cache_key, _init_status, timeout=900)

        def _run_precision_bg(uid, ckey):
            try:
                import django
                django.setup()
                import concurrent.futures
                from datetime import datetime as _dt
                from datetime import time as _dtime
                from datetime import timedelta as _td

                import pandas_ta as ta
                import pytz as _pytz
                from django.contrib.auth import get_user_model
                from django.core.cache import cache as _cache
                from django.utils import timezone as tz
                from yahooquery import Ticker as YQTicker

                from .models import PrecisionScanCandidate

                from .utils import analyze_momentum_technical_v2, get_top_ranked_symbols as _GTRS, refresh_all_thai_symbols as _RATS
                sym_list = _GTRS(market='SET', limit=400, auto_refresh=True)
                if not sym_list:
                    try:
                        _RATS()
                    except Exception:
                        pass
                    sym_list = _GTRS(market='SET', limit=400, auto_refresh=True)


                User = get_user_model()
                user = User.objects.get(pk=uid)
                scan_run_time = tz.now()

                # ====== Pin Scan Date ======
                _bkk_tz = _pytz.timezone('Asia/Bangkok')
                _now_bkk = _dt.now(_bkk_tz)
                # yfinance download end= is exclusive. To include today's data, use tomorrow.
                scan_end_date  = _now_bkk.date() + _td(days=1)
                scan_end_str   = scan_end_date.strftime('%Y-%m-%d')
                scan_start_str = (_now_bkk.date() - _td(days=600)).strftime('%Y-%m-%d')  # 600 วัน → ~430 trading days, EMA200 warm-up มีพอ
                set_start_str  = (_now_bkk.date() - _td(days=600)).strftime('%Y-%m-%d')  # ใช้เท่ากับ stock เพื่อ RS เทียบกันถูกต้อง

                prev_run = (
                    PrecisionScanCandidate.objects
                    .filter(user=user, market='SET')
                    .values_list('scan_run', flat=True)
                    .order_by('-scan_run')
                    .distinct()
                    .first()
                )
                prev_symbols = set()
                if prev_run:
                    prev_symbols = set(
                        PrecisionScanCandidate.objects
                        .filter(user=user, scan_run=prev_run)
                        .values_list('symbol', flat=True)
                    )

                # ====== SET Index ======
                set_1m_return = 0.0
                set_3m_return = 0.0
                try:
                    set_df = yf.download("^SET.BK", start=set_start_str, end=scan_end_str, interval="1d", progress=False)
                    if set_df is not None and not set_df.empty:
                        if isinstance(set_df.columns, pd.MultiIndex):
                            set_df.columns = set_df.columns.droplevel(1)
                        set_close = set_df['Close'].dropna()
                        if len(set_close) >= 66:
                            set_1m_return = float((set_close.iloc[-1] - set_close.iloc[-22]) / set_close.iloc[-22] * 100)
                            set_3m_return = float((set_close.iloc[-1] - set_close.iloc[-66]) / set_close.iloc[-66] * 100)
                    import logging; logging.getLogger('stocks').info(f"[Precision] SET Index: 1m={set_1m_return:.2f}% 3m={set_3m_return:.2f}%")
                except Exception as e:
                    import logging; logging.getLogger('stocks').warning(f"[Precision] SET Index fetch failed: {e}")


                # ====== Phase 1: Fast Screening with YahooQuery (Institutional Speed) ======
                total_syms = len(sym_list)
                _cache.set(ckey, {'state': 'running', 'progress': 5, 'total': total_syms, 'phase': 'ดึงข้อมูล RS Rating...'}, timeout=900)
                
                from yahooquery import Ticker as _TQ
                rs_returns_all = {}
                
                # Fetch history in chunks of 80 to prevent hangs
                import logging; logger = logging.getLogger('stocks')
                chunk_size = 80
                for i in range(0, len(sym_list), chunk_size):
                    chunk = sym_list[i : i + chunk_size]
                    chunk_bk = [f"{s}.BK" for s in chunk]
                    _cache.set(ckey, {'state': 'running', 'progress': 5 + int((i/total_syms)*15), 'total': total_syms, 'phase': f'Phase 1: โหลดข้อมูลกลุ่ม {i//chunk_size + 1}...'}, timeout=900)
                    try:
                        tq = _TQ(chunk_bk)
                        tq_hist = tq.history(start=scan_start_str, end=scan_end_str, interval="1d")
                        if tq_hist is not None and not tq_hist.empty:
                            if isinstance(tq_hist.index, pd.MultiIndex):
                                for symbol in chunk:
                                    try:
                                        s_bk = f"{symbol}.BK"
                                        if s_bk in tq_hist.index.get_level_values(0):
                                            _close = tq_hist.loc[s_bk]['adjclose'].dropna()
                                            if len(_close) >= 66:
                                                ret = float((_close.iloc[-1] - _close.iloc[-66]) / abs(_close.iloc[-66]) * 100)
                                                rs_returns_all[symbol] = ret
                                    except Exception: continue
                    except Exception as e:
                        logger.error(f"RS Chunk Error at {i}: {e}")

                # FAILSAFE: If results are empty or too small, force evaluation of a subset
                if len(rs_returns_all) < 10:
                    import logging; logging.getLogger('stocks').warning(f"[Precision] Data recovery mode: Only {len(rs_returns_all)} found. Force fallback.")
                    # Use at least top 50 symbols to ensure some results
                    for s in sym_list[:100]:
                        if s not in rs_returns_all: rs_returns_all[s] = 0.0 # Dummy score to pass filter

                rs_ratings_map = {}
                if rs_returns_all:
                    _rs_ser = pd.Series(rs_returns_all)
                    rs_ratings_map = (_rs_ser.rank(pct=True) * 99).clip(0, 99).astype(int).to_dict()

                # Phase 2: เจาะลึกหุ้นที่เข้ารอบ (ผ่อนปรนให้หุ้นที่มี RS >= 45 หลุดเข้าประเมินเชิงลึก เพื่อความยืดหยุ่นของ Early Accumulation)
                results_to_process = [s for s in sym_list if rs_ratings_map.get(s, 0) >= 45]
                if not results_to_process:
                    # Fallback: ถ้าไม่มีข้อมูล RS เพียงพอ ให้ใช้ทุกหุ้นที่อยู่ใน rs_ratings_map หรือ top 50
                    results_to_process = [s for s in sym_list if s in rs_ratings_map] or sym_list[:50]
                    import logging; logging.getLogger('stocks').warning(f"[Precision] RS filter returned 0 — fallback to {len(results_to_process)} symbols")

                def _process_precision_scan(symbol):
                    try:
                        # ใช้ yf.Ticker().history() แทน yf.download() เพราะ yf.download() 
                        # มีบั๊ก Thread-safety กรองข้อมูลข้าม Symbol กันเมื่อรันใน ThreadPool 
                        ticker_obj = yf.Ticker(f"{symbol}.BK")
                        df = ticker_obj.history(start=scan_start_str, end=scan_end_str, interval="1d")

                        if df is None or df.empty:
                            try:
                                yq = YQTicker(f"{symbol}.BK")
                                df = yq.history(start=scan_start_str, end=scan_end_str, interval="1d")
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
                            return None

                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(1)

                        df = df.dropna(subset=['Close', 'High'])
                        if len(df) < 200:
                            return None

                        # ====== Liquidity & Quality Filters (Institutional Grade) ======
                        avg_vol_20 = float(df['Volume'].tail(20).mean())
                        avg_close_20 = float(df['Close'].tail(20).mean())
                        avg_turnover_20 = avg_vol_20 * avg_close_20
                
                        import logging as _lg; _scan_log = _lg.getLogger('stocks.scan')
                        current_price = float(df['Close'].iloc[-1])

                        # 1. Turnover >= 10M THB
                        if avg_turnover_20 < 10_000_000:
                            _scan_log.info(f"[SCAN SKIP] {symbol}: Turnover ฿{avg_turnover_20/1e6:.1f}M < 10M")
                            return None

                        # 2. Minimum Price >= 1.00
                        if current_price < 1.00:
                            _scan_log.info(f"[SCAN SKIP] {symbol}: Price ฿{current_price} < 1.00")
                            return None

                        # ====== Early Accumulation (Pre-Breakout Volume Surge & Tightness) ======
                        # เช็คว่ามี Volume พุ่งสูง หรือ ราคากำลังบีบตัว (VCP) หรือ ปริมาณการซื้อขายแห้ง (VDU)
                        early_accumulation = False
                        try:
                            if len(df) >= 20:
                                # 1. Check Volume Surge (2.5x)
                                for i in range(-5, 0):
                                    vol_i = float(df['Volume'].iloc[i])
                                    close_i = float(df['Close'].iloc[i])
                                    open_i = float(df['Open'].iloc[i])
                                    if close_i > open_i and vol_i >= (avg_vol_20 * 2.5):
                                        early_accumulation = True
                                        break
                                
                                # 2. Check Price Tightness (SD < 2.5%) -> VCP / Coiling
                                if not early_accumulation:
                                    std_5 = float(df['Close'].tail(5).std())
                                    tightness = (std_5 / current_price * 100) if current_price > 0 else 99
                                    if tightness <= 2.5:
                                        early_accumulation = True
                                        
                                # 3. Check Volume Dry Up (VDU) -> แรงขายหมด
                                if not early_accumulation:
                                    vol_3d_avg = float(df['Volume'].tail(3).mean())
                                    if vol_3d_avg < avg_vol_20 * 0.5:
                                        early_accumulation = True
                        except Exception:
                            pass

                        # 3. RS Rating >= 60 (อนุโลมถ้ามี Early Accumulation)
                        rs_val = rs_ratings_map.get(symbol, None)
                        if rs_val is not None and rs_val < 60 and not early_accumulation:
                            _scan_log.info(f"[SCAN SKIP] {symbol}: RS {rs_val} < 60")
                            return None

                        # ====== คำนวณ Indicators ======
                        df['EMA200'] = ta.ema(df['Close'], length=200)
                        df['EMA50'] = ta.ema(df['Close'], length=50)
                        df['RSI'] = ta.rsi(df['Close'], length=14)
                        adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                        if adx_df is not None and not adx_df.empty:
                            df = pd.concat([df, adx_df], axis=1)
                        mfi_series = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                        df['MFI'] = mfi_series

                        last_row = df.iloc[-1]
                        current_price = float(last_row['Close'])
                        ema200 = float(df['EMA200'].iloc[-1]) if pd.notna(df['EMA200'].iloc[-1]) else current_price
                        year_high = float(df['High'].tail(252).max())

                        # ====== ADX Filter ======
                        adx_val = float(df['ADX_14'].iloc[-1]) if 'ADX_14' in df.columns and pd.notna(df['ADX_14'].iloc[-1]) else 0
                        if adx_val < 15 and not early_accumulation:
                            _scan_log.info(f"[SCAN SKIP] {symbol}: ADX {adx_val:.1f} < 15")
                            return None

                        # ====== Trend Template Filter ======
                        near_high  = current_price >= year_high * 0.65
                        if not near_high and not early_accumulation:
                            _scan_log.info(f"[SCAN SKIP] {symbol}: Price ฿{current_price} < 65% of 52wH ฿{year_high} ({current_price/year_high*100:.0f}%)")
                            return None

                        import logging; logger = logging.getLogger('stocks')
                        logger.debug(f"[Precision] MATCH: {symbol} (ADX:{adx_val:.1f})")

                        # ====== Precision Technical Analysis (v3) ======
                        tech = analyze_momentum_technical_v2(df)
                        integrated_score = tech['score']
                        rvol         = tech['rvol']
                        rsi          = tech['rsi']
                        rvol_bullish = tech['rvol_bullish']
                        sd_zone      = tech['sd_zone']
                        ema20_aligned_flag = tech.get('ema20_aligned', False)
                        ema20_slope_val    = tech.get('ema20_slope', 0.0)
                        ema20_rising_flag  = tech.get('ema20_rising', False)
                        hh_hl_flag         = tech.get('hh_hl_structure', False)

                        mfi_val = float(df['MFI'].iloc[-1]) if 'MFI' in df.columns and pd.notna(df['MFI'].iloc[-1]) else 0

                        # ====== MACD (12,26,9) - histogram + bullish crossover detection ======
                        macd_hist_val  = None
                        macd_cross_val = False
                        try:
                            macd_df = ta.macd(df['Close'], fast=12, slow=26, signal=9)
                            if macd_df is not None and not macd_df.empty:
                                hist_col = [c for c in macd_df.columns if 'h' in c.lower() or 'hist' in c.lower()]
                                macd_col = [c for c in macd_df.columns if c.lower().startswith('macd_')]
                                sig_col  = [c for c in macd_df.columns if 'macds' in c.lower() or 'signal' in c.lower()]
                                if hist_col:
                                    macd_hist_val = float(macd_df[hist_col[0]].iloc[-1]) if pd.notna(macd_df[hist_col[0]].iloc[-1]) else None
                                # Bullish crossover = MACD line crosses above signal line in last 3 bars
                                if macd_col and sig_col:
                                    m_ser = macd_df[macd_col[0]].dropna()
                                    s_ser = macd_df[sig_col[0]].dropna()
                                    if len(m_ser) >= 4 and len(s_ser) >= 4:
                                        # Check if MACD crossed above signal in last 3 candles
                                        for i in range(-3, 0):
                                            if m_ser.iloc[i-1] <= s_ser.iloc[i-1] and m_ser.iloc[i] > s_ser.iloc[i]:
                                                macd_cross_val = True
                                                break
                        except Exception:
                            pass

                        # ====== Bollinger Bands Squeeze - bandwidth in bottom 20th pct (pending breakout) ======
                        bb_squeeze_flag = False
                        try:
                            bb_df = ta.bbands(df['Close'], length=20, std=2)
                            if bb_df is not None and not bb_df.empty:
                                upper_col = [c for c in bb_df.columns if 'BBU' in c or 'upper' in c.lower()]
                                lower_col = [c for c in bb_df.columns if 'BBL' in c or 'lower' in c.lower()]
                                mid_col   = [c for c in bb_df.columns if 'BBM' in c or 'mid' in c.lower()]
                                if upper_col and lower_col and mid_col:
                                    bbu = bb_df[upper_col[0]].dropna()
                                    bbl = bb_df[lower_col[0]].dropna()
                                    bbm = bb_df[mid_col[0]].dropna()
                                    if len(bbu) >= 20:
                                        bw = (bbu - bbl) / bbm  # bandwidth ratio
                                        pct20 = bw.quantile(0.20)
                                        if float(bw.iloc[-1]) <= float(pct20):
                                            bb_squeeze_flag = True
                        except Exception:
                            pass

                        # ====== Stage 2 (Weinstein): price > SMA150 AND SMA150 rising ======
                        # Stage 2 = markup phase - หุ้นที่ผ่าน filter นี้อยู่ในช่วงที่ดีที่สุดสำหรับการซื้อ
                        stage2_flag = False
                        try:
                            sma150 = ta.sma(df['Close'], length=150)
                            if sma150 is not None:
                                sma150_clean = sma150.dropna()
                                if len(sma150_clean) >= 20:
                                    sma150_cur = float(sma150_clean.iloc[-1])
                                    sma150_4w  = float(sma150_clean.iloc[-20])  # ~4 สัปดาห์ก่อน
                                    stage2_flag = (current_price > sma150_cur) and (sma150_cur > sma150_4w)
                        except Exception:
                            pass

                        # ====== Fundamental Data (bulk-fetched after all threads complete) ======
                        # ตัวแปรเหล่านี้ไม่ถูกใช้ใน thread - bulk enrichment เป็นตัวทำใน step 2

                        # ====== Supply & Demand Zone ======
                        entry_strat = ""
                        dz_start = None
                        dz_end = None
                        sz_start = None
                        sz_end = None
                        sl_price = None
                        rr_val = None
                        erc_vol_confirmed = False
                        zone_target_src = '52w'

                        if sd_zone:
                            entry_strat = sd_zone['type']
                            dz_start = sd_zone['start']
                            dz_end = sd_zone['end']
                            sz_start = sd_zone['target']
                            sz_end = sd_zone['target'] * 1.02
                            sl_price = sd_zone['stop_loss']
                            rr_val = sd_zone['rr_ratio']
                            erc_vol_confirmed = sd_zone.get('erc_volume_confirmed', False)
                            zone_target_src = sd_zone.get('zone_target_source', '52w')

                        prox_val = 999.0
                        if dz_start:
                            if current_price <= dz_start:
                                prox_val = 0.0
                            else:
                                prox_val = ((current_price - dz_start) / dz_start) * 100

                        gap_to_high = ((year_high - current_price) / current_price) * 100

                        # ====== Pocket Pivot (Morales & Kacher) ======
                        # Up-day volume > highest down-day volume in prior 10 sessions
                        pocket_pivot_flag = False
                        try:
                            if len(df) >= 14:
                                closes = df['Close'].values
                                volumes = df['Volume'].values
                                for _i in [-1, -2]:
                                    if float(closes[_i]) <= float(closes[_i - 1]):
                                        continue  # not an up day
                                    _start = len(volumes) + _i - 10
                                    _end   = len(volumes) + _i
                                    if _start < 1:
                                        continue
                                    _prior_c = closes[_start:_end]
                                    _prior_v = volumes[_start:_end]
                                    _prior_prev_c = closes[_start - 1:_end - 1]
                                    _down_mask = _prior_c < _prior_prev_c
                                    if not _down_mask.any():
                                        continue
                                    _max_down_vol = float(_prior_v[_down_mask].max())
                                    if float(volumes[_i]) > _max_down_vol and _max_down_vol > 0:
                                        pocket_pivot_flag = True
                                        break
                        except Exception:
                            pass

                        # ====== Volume Dry-Up (VDU): เงียบสะสม - volume ลด 3 วันติด + ต่ำกว่า median 70% (ป้องกัน volume spike) ======
                        vdu_flag = False
                        try:
                            if len(df) >= 4:
                                _vols = df['Volume'].tail(4).values.astype(float)
                                _median20 = float(df['Volume'].tail(20).median())
                                _declining = (_vols[-1] < _vols[-2]) and (_vols[-2] < _vols[-3])
                                _quiet     = _vols[-1] < _median20 * 0.7
                                vdu_flag   = _declining and _quiet
                        except Exception:
                            pass

                        # ====== Ichimoku Cloud ======
                        ichimoku_above_kumo = False
                        ichimoku_tk_cross   = False
                        ichimoku_kumo_green = False
                        ichimoku_chikou_ok  = False
                        ichimoku_score_val  = 0
                        try:
                            if len(df) >= 52:
                                _h9  = df['High'].rolling(9).max()
                                _l9  = df['Low'].rolling(9).min()
                                _h26 = df['High'].rolling(26).max()
                                _l26 = df['Low'].rolling(26).min()
                                _h52 = df['High'].rolling(52).max()
                                _l52 = df['Low'].rolling(52).min()
                                _tenkan = (_h9  + _l9)  / 2
                                _kijun  = (_h26 + _l26) / 2
                                _span_a = ((_tenkan + _kijun) / 2).shift(26)
                                _span_b = ((_h52   + _l52)  / 2).shift(26)
                                _sa_cur = float(_span_a.iloc[-1]) if pd.notna(_span_a.iloc[-1]) else 0
                                _sb_cur = float(_span_b.iloc[-1]) if pd.notna(_span_b.iloc[-1]) else 0
                                # 1) Price above Kumo
                                ichimoku_above_kumo = current_price > max(_sa_cur, _sb_cur) > 0
                                # 2) TK Cross bullish in last 5 bars
                                for _i in range(-5, 0):
                                    if (_tenkan.iloc[_i-1] <= _kijun.iloc[_i-1]
                                            and _tenkan.iloc[_i] > _kijun.iloc[_i]):
                                        ichimoku_tk_cross = True
                                        break
                                # 3) Future Kumo green (SpanA > SpanB at current shifted position)
                                ichimoku_kumo_green = _sa_cur > _sb_cur and _sa_cur > 0
                                # 4) Chikou Span clear (current close > close 26 bars ago)
                                if len(df) >= 27:
                                    ichimoku_chikou_ok = float(df['Close'].iloc[-1]) > float(df['Close'].iloc[-27])
                                ichimoku_score_val = sum([ichimoku_above_kumo, ichimoku_tk_cross,
                                                         ichimoku_kumo_green, ichimoku_chikou_ok])
                        except Exception:
                            pass

                        # Price Pattern detection (ใช้ df ที่มีอยู่แล้ว)
                        pattern_result = detect_price_pattern(df)
                        pattern_name  = pattern_result['name']
                        pattern_score = pattern_result['score']

                        close_series = df['Close'].dropna()
                        rel_1m = rel_3m = 0.0
                        stock_3m_ret = 0.0
                        if len(close_series) >= 66:
                            stock_1m = float((close_series.iloc[-1] - close_series.iloc[-22]) / close_series.iloc[-22] * 100)
                            stock_3m = float((close_series.iloc[-1] - close_series.iloc[-66]) / close_series.iloc[-66] * 100)
                            stock_3m_ret = stock_3m
                            rel_1m = round(stock_1m - set_1m_return, 2)
                            rel_3m = round(stock_3m - set_3m_return, 2)
                        elif len(close_series) >= 22:
                            stock_1m = float((close_series.iloc[-1] - close_series.iloc[-22]) / close_series.iloc[-22] * 100)
                            rel_1m = round(stock_1m - set_1m_return, 2)

                        # Return dict instead of model to allow bulk fundamental enrichment and RS Ranking
                        return {
                            'symbol': symbol,
                            'price': round(current_price, 2),
                            'rsi': round(rsi, 2),
                            'adx': round(adx_val, 2),
                            'mfi': round(mfi_val, 2),
                            'rvol': round(rvol, 2),
                            'technical_score': int(integrated_score),
                            'avg_volume_20d': round(avg_vol_20, 0),
                            'rvol_bullish': rvol_bullish,
                            'erc_volume_confirmed': erc_vol_confirmed,
                            'zone_target_src': zone_target_src,
                            'entry_strat': entry_strat,
                            'dz_start': dz_start,
                            'dz_end': dz_end,
                            'sz_start': sz_start,
                            'sz_end': sz_end,
                            'sl_price': sl_price,
                            'rr_val': rr_val,
                            'year_high': round(year_high, 2),
                            'upside_to_high': round(gap_to_high, 2),
                            'prox_val': round(prox_val, 2),
                            'pattern_name': pattern_name,
                            'pattern_score': pattern_score,
                            'rel_1m': rel_1m,
                            'rel_3m': rel_3m,
                            'macd_histogram': round(macd_hist_val, 4) if macd_hist_val is not None else None,
                            'macd_crossover': macd_cross_val,
                            'bb_squeeze': bb_squeeze_flag,
                            'ema20_aligned': ema20_aligned_flag,
                            'ema20_slope': round(ema20_slope_val, 3),
                            'ema20_rising': ema20_rising_flag,
                            'hh_hl_structure': hh_hl_flag,
                            'stock_3m_ret': stock_3m_ret,
                            'rs_rating': rs_ratings_map.get(symbol, 0),
                            'stage2': stage2_flag,
                            'pocket_pivot': pocket_pivot_flag,
                            'vdu_near_zone': vdu_flag,
                            'cmf': tech.get('cmf', 0.0),
                            'is_52w_breakout': tech.get('is_52w_breakout', False),
                            'volume_surge': tech.get('volume_surge', 1.0),
                            'is_volume_surge': tech.get('is_volume_surge', False),
                            'ichimoku_above_kumo': ichimoku_above_kumo,
                            'ichimoku_tk_cross': ichimoku_tk_cross,
                            'ichimoku_kumo_green': ichimoku_kumo_green,
                            'ichimoku_chikou_ok': ichimoku_chikou_ok,
                            'ichimoku_score': ichimoku_score_val,
                            # ====== VCP Detection ======
                            'vcp': detect_vcp_pattern(df),
                            # ====== Launcher Data (v10) ======
                            'launcher_score': tech.get('launcher_score', 0),
                            'turtle_dist_pct': tech.get('turtle_dist_pct', 99.0),
                            'is_explosive': tech.get('is_explosive', False),
                            'tightness_idx': tech.get('tightness_idx', 99.0),
                            # ====== John Ehlers Indicators (v12) ======
                            'ehlers_supersmoother': tech.get('ehlers_supersmoother', current_price),
                            'ehlers_laguerre_rsi': tech.get('ehlers_laguerre_rsi', 0.5),
                            'ehlers_fisher': tech.get('ehlers_fisher', 0.0),
                            'ehlers_fisher_trigger': tech.get('ehlers_fisher_trigger', 0.0),
                            'ehlers_itl_daily': tech.get('ehlers_itl_daily', current_price),
                            'ehlers_itl_weekly': tech.get('ehlers_itl_weekly', current_price),
                            'ehlers_itl_bullish': tech.get('ehlers_itl_bullish', False),
                        }

                    except Exception as e:
                        import logging
                        logging.getLogger('stocks').exception(f"[Precision] Error scanning {symbol}: {e}")
                        return None


                # ====== Phase 2: Deep Scan (only for candidates) ======
                _cache.set(ckey, {'state': 'running', 'progress': 25, 'total': 100, 'phase': f'สแกนละเอียด (จำนวน {len(results_to_process)} ตัว)...'}, timeout=900)
                
                results = []
                done_count = 0
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    futures = [executor.submit(_process_precision_scan, sym) for sym in results_to_process]
                    for future in concurrent.futures.as_completed(futures):
                        res = future.result()
                        if res:
                            results.append(res)
                        done_count += 1
                        _cache.set(ckey, {'state': 'running', 'progress': 25 + int((done_count/len(results_to_process))*70), 
                                          'total': 100, 'phase': f'สแกนละเอียด {done_count}/{len(results_to_process)}...'}, timeout=900)

                if results:
                    scan_df = pd.DataFrame(results)
                    if 'rs_rating' not in scan_df.columns:
                        scan_df['rs_rating'] = 0

                    _cache.set(ckey, {'state': 'running', 'progress': 95, 'total': 100, 'phase': 'ดึงข้อมูล Fundamental…'}, timeout=900)

                    # ====== Bulk Fundamental Enrichment ======
                    matched_symbols = [r['symbol'] for r in results]
                    symbols_bk = [f"{s}.BK" for s in matched_symbols]
                    fund_data = {}
                    try:
                        yq_all = YQTicker(symbols_bk)
                        modules = yq_all.get_modules('financialData summaryProfile defaultKeyStatistics')
                        for sym_bk, data in modules.items():
                            if not isinstance(data, dict):
                                continue
                            clean_sym = sym_bk.replace('.BK', '')
                            profile  = data.get('summaryProfile', {})
                            fin_data = data.get('financialData', {})
                            keystat  = data.get('defaultKeyStatistics', {})
                            sector   = (
                                profile.get('sector')
                                or data.get('assetProfile', {}).get('sector')
                                or 'Unknown'
                            )
                            eps_g = keystat.get('earningsQuarterlyGrowth') or fin_data.get('earningsGrowth') or 0.0
                            eps_growth = float(eps_g) * 100
                            rev_growth = float(fin_data.get('revenueGrowth', 0) or 0) * 100
                            fund_data[clean_sym] = {'sector': sector, 'eps_growth': eps_growth, 'rev_growth': rev_growth}
                    except Exception as e:
                        print(f"[Precision] Bulk Fundamental fetch failed: {e}")

                    # ====== Bulk Create ======
                    bulk_candidates = []
                    for r in scan_df.to_dict('records'):
                        sym = r['symbol']
                        f = fund_data.get(sym, {'sector': 'N/A', 'eps_growth': 0.0, 'rev_growth': 0.0})
                        bulk_candidates.append(PrecisionScanCandidate(
                            user=user,
                            market='SET',
                            scan_run=scan_run_time,
                            symbol=sym,
                            symbol_bk=f"{sym}.BK",
                            sector=f.get('sector') or 'Unknown',
                            price=r['price'],
                            rsi=r['rsi'],
                            adx=r['adx'],
                            mfi=r['mfi'],
                            rvol=r['rvol'],
                            eps_growth=round(f.get('eps_growth', 0), 2),
                            rev_growth=round(f.get('rev_growth', 0), 2),
                            technical_score=r['technical_score'],
                            rs_rating=r['rs_rating'],
                            avg_volume_20d=r['avg_volume_20d'],
                            rvol_bullish=r['rvol_bullish'],
                            erc_volume_confirmed=r['erc_volume_confirmed'],
                            zone_target_source=r['zone_target_src'],
                            is_new_entry=(sym not in prev_symbols),
                            entry_strategy=r['entry_strat'],
                            demand_zone_start=r['dz_start'],
                            demand_zone_end=r['dz_end'],
                            supply_zone_start=r['sz_start'],
                            supply_zone_end=r['sz_end'],
                            stop_loss=r['sl_price'],
                            risk_reward_ratio=r['rr_val'],
                            year_high=r['year_high'],
                            upside_to_high=r['upside_to_high'],
                            zone_proximity=r['prox_val'],
                            price_pattern=r['pattern_name'],
                            price_pattern_score=r['pattern_score'],
                            rel_momentum_1m=r['rel_1m'],
                            rel_momentum_3m=r['rel_3m'],
                            macd_histogram=r['macd_histogram'],
                            macd_crossover=r['macd_crossover'],
                            bb_squeeze=r['bb_squeeze'],
                            ema20_aligned=r['ema20_aligned'],
                            ema20_slope=r.get('ema20_slope', 0.0),
                            ema20_rising=r.get('ema20_rising', False),
                            hh_hl_structure=r.get('hh_hl_structure', False),
                            stage2=r.get('stage2', False),
                            pocket_pivot=r.get('pocket_pivot', False),
                            vdu_near_zone=r.get('vdu_near_zone', False),
                            cmf=r.get('cmf', None),
                            is_52w_breakout=r.get('is_52w_breakout', False),
                            volume_surge=r.get('volume_surge', 1.0),
                            is_volume_surge=r.get('is_volume_surge', False),
                            ichimoku_above_kumo=r.get('ichimoku_above_kumo', False),
                            ichimoku_tk_cross=r.get('ichimoku_tk_cross', False),
                            ichimoku_kumo_green=r.get('ichimoku_kumo_green', False),
                            ichimoku_chikou_ok=r.get('ichimoku_chikou_ok', False),
                            ichimoku_score=r.get('ichimoku_score', 0),
                            # VCP v9
                            vcp_setup=r.get('vcp', {}).get('setup', False),
                            vcp_contractions=r.get('vcp', {}).get('contractions', 0),
                            vcp_tightness=r.get('vcp', {}).get('tightness', 0.0),
                            vcp_vdu=r.get('vcp', {}).get('vdu_confirmed', False),
                            # Launcher v10
                            launcher_score=r.get('launcher_score', 0),
                            turtle_dist_pct=r.get('turtle_dist_pct', 99.0),
                            is_explosive=r.get('is_explosive', False),
                            tightness_idx=r.get('tightness_idx', 99.0),
                            # Ehlers v12
                            ehlers_supersmoother=r.get('ehlers_supersmoother', None),
                            ehlers_laguerre_rsi=r.get('ehlers_laguerre_rsi', None),
                            ehlers_fisher=r.get('ehlers_fisher', None),
                            ehlers_fisher_trigger=r.get('ehlers_fisher_trigger', None),
                            ehlers_itl_daily=r.get('ehlers_itl_daily', None),
                            ehlers_itl_weekly=r.get('ehlers_itl_weekly', None),
                            ehlers_itl_bullish=r.get('ehlers_itl_bullish', False),
                        ))

                    if bulk_candidates:
                        PrecisionScanCandidate.objects.bulk_create(bulk_candidates)

                # เก็บ 3 รอบล่าสุด
                distinct_runs = (
                    PrecisionScanCandidate.objects
                    .filter(user=user, market='SET')
                    .values_list('scan_run', flat=True)
                    .order_by('-scan_run')
                    .distinct()
                )
                runs_list = list(distinct_runs)
                if len(runs_list) > 3:
                    old_runs = runs_list[3:]
                    PrecisionScanCandidate.objects.filter(user=user, market='SET', scan_run__in=old_runs).delete()

                _cache.set(ckey, {'state': 'done', 'count': len(results)}, timeout=300)

            except Exception as _bg_err:
                import logging
                logging.getLogger('stocks').exception(f"[PrecisionBG] Error: {_bg_err}")
                from django.core.cache import cache as _ec
                _ec.set(ckey, {'state': 'idle'}, timeout=60)

        # เปิด background thread แล้ว return ทันที
        _t = threading.Thread(
            target=_run_precision_bg,
            args=(user_id, cache_key),
            daemon=True
        )
        _t.start()

        # Redirect กลับหน้าที่ส่งมา (เช่น SEPA) - next_url resolve ไว้แล้วด้านบน
        return redirect(next_url)

    # ====== จัดเรียงผลลัพธ์ ======
    sort_by = request.GET.get('sort', 'score')
    valid_db_sorts = {
        'symbol': 'symbol',
        'score': '-technical_score',
        'price': '-price',
        'rsi': '-rsi',
        'rvol': '-rvol',
        'adx': '-adx',
        'prox': 'zone_proximity',
        'round_rr': '-risk_reward_ratio',
        'rs': '-rs_rating',          # RS Rating (Minervini Relative Strength)
        'launcher': '-launcher_score', # Explosive Launcher Score
        'cmf': '-cmf',                # Chaikin Money Flow (Institutional Accumulation)
    }
    use_db_sort = sort_by in valid_db_sorts
    order_field = valid_db_sorts.get(sort_by, '-technical_score')

    # รายชื่อ scan runs ทั้งหมด (index 0 = ล่าสุด)
    all_runs = list(
        PrecisionScanCandidate.objects
        .filter(user=request.user, market='SET')
        .values_list('scan_run', flat=True)
        .order_by('-scan_run')
        .distinct()
    )

    # เลือกรอบสแกนตาม ?run_idx= (0 = ล่าสุด, 1 = ก่อนหน้า, ...)
    try:
        run_idx = int(request.GET.get('run_idx', 0))
    except (ValueError, TypeError):
        run_idx = 0
    run_idx = max(0, min(run_idx, len(all_runs) - 1)) if all_runs else 0

    candidates = []
    scanned_at = None
    if all_runs:
        selected_run = all_runs[run_idx]
        qs = PrecisionScanCandidate.objects.filter(user=request.user, scan_run=selected_run, market='SET')
        if use_db_sort:
            qs = qs.order_by(order_field)
        candidates = list(qs)
        scanned_at = selected_run

        # ====== Live Price Fetch (ถ้าตลาดเปิด) - แสดงราคาปัจจุบันคู่กับราคา close เมื่อวาน ======
        # Indicator ยังคำนวณจาก settled close (คงที่), live price ใช้แสดงเท่านั้น
        from datetime import datetime as _ldt
        from datetime import time as _ldtime

        import pytz as _lpytz
        _lbkk = _lpytz.timezone('Asia/Bangkok')
        _lnow = _ldt.now(_lbkk)
        _lt = _lnow.time()
        # Live price: เฉพาะช่วงที่ตลาด SET ซื้อขายจริง (ไม่รวม midday break 12:30-14:30)
        _lmarket_open = (
            _lnow.weekday() < 5 and
            (_ldtime(10, 0) <= _lt <= _ldtime(12, 30) or
             _ldtime(14, 30) <= _lt <= _ldtime(16, 30))
        )
        live_prices = {}
        live_mcaps  = {}
        live_prev_closes = {}
        if candidates:
            try:
                # แคชผล fetch ไว้ - กันยิง yfinance เท่าจำนวนหุ้นทุกครั้งที่ refresh หน้า
                # ตลาดเปิด: 60s (ราคาขยับ), ตลาดปิด: 10 นาที (ราคา close ไม่เปลี่ยน)
                from django.core.cache import cache as _lp_cache
                _lp_key = f'precision_live_set_{request.user.id}_{run_idx}'
                _lp_cached = _lp_cache.get(_lp_key)
                if _lp_cached:
                    if isinstance(_lp_cached, tuple) and len(_lp_cached) == 3:
                        live_prices, live_mcaps, live_prev_closes = _lp_cached
                    elif isinstance(_lp_cached, tuple) and len(_lp_cached) == 2:
                        live_prices, live_mcaps = _lp_cached
                        live_prev_closes = {}
                    else:
                        live_prices, live_mcaps, live_prev_closes = {}, {}, {}
                else:
                    import concurrent.futures as _lcf
                    def _get_live(sym):
                        try:
                            full_sym = f"{sym}.BK"
                            # Use fast_info for quick price/mcap without downloading full history
                            fi = yf.Ticker(full_sym).fast_info
                            p  = getattr(fi, 'last_price', None)
                            mc = getattr(fi, 'market_cap', None)
                            pc = getattr(fi, 'regular_market_previous_close', getattr(fi, 'previous_close', None))
                            return (
                                sym,
                                (float(p) if p else None),
                                (round(float(mc)/1e9, 2) if mc else None),
                                (float(pc) if pc else None)
                            )
                        except Exception:
                            return sym, None, None, None
                    with _lcf.ThreadPoolExecutor(max_workers=6) as _lex:
                        for _sym, _p, _mc, _pc in _lex.map(_get_live, [c.symbol for c in candidates]):
                            if _p:  live_prices[_sym] = _p
                            if _mc: live_mcaps[_sym]  = _mc
                            if _pc: live_prev_closes[_sym] = _pc
                    if live_prices:
                        _lp_cache.set(_lp_key, (live_prices, live_mcaps, live_prev_closes), 60 if _lmarket_open else 600)
            except Exception:
                pass

        for c in candidates:
            lp = live_prices.get(c.symbol)
            pc = live_prev_closes.get(c.symbol) or c.price
            c.live_price      = lp
            c.live_market_cap = live_mcaps.get(c.symbol)
            c.is_live         = _lmarket_open and lp is not None

            ref_price = lp if lp else float(c.price or 0)
            dz_top = float(c.demand_zone_start or 0)
            dz_bot = float(c.demand_zone_end   or 0)
            tp     = float(c.supply_zone_start or 0)

            if lp and dz_top > 0:
                c.live_zone_prox = 0.0 if lp <= dz_top else round(((lp - dz_top) / dz_top) * 100, 1)
            else:
                c.live_zone_prox = None
            if lp and pc and float(pc) > 0:
                c.live_change_pct = round(((lp - float(pc)) / float(pc)) * 100, 2)
            else:
                c.live_change_pct = None

            # precompute zone status flags - ใช้ใน template แทนการคำนวณใน {% if %}
            c.live_at_tp      = tp > 0 and ref_price >= tp
            c.live_broke_zone = dz_bot > 0 and ref_price < dz_bot
            c.live_in_zone    = dz_top > 0 and dz_bot > 0 and dz_bot <= ref_price <= dz_top

            # upside_to_tp: % ของ range Entry→TP ที่ยังเหลืออยู่
            entry = dz_top
            total_range = tp - entry
            if tp > 0 and entry > 0 and total_range > 0 and ref_price > 0:
                remaining = tp - ref_price
                c.upside_to_tp = round((remaining / total_range) * 100, 1)
            else:
                c.upside_to_tp = 999

        # ====== คำนวณ BUY/SELL Score ด้วย _compute_signals() เดียวกับ Dashboard/Watchlist ======
        for c in candidates:
            sigs = _compute_signals(c)
            c.buy_score  = sigs['buy_score']
            c.sell_score = sigs['sell_score']
            c.exit_signal = sigs['exit_signal']
            c.reversal_score = sigs['reversal_score']
            c.reversal_alert = sigs['reversal_alert']
            c.reversal_color = sigs['reversal_color']

        # ====== BUY Score Delta เทียบกับรอบก่อนหน้า ======
        prev_buy_scores = {}
        if len(all_runs) > run_idx + 1:
            for _p in PrecisionScanCandidate.objects.filter(
                    user=request.user, scan_run=all_runs[run_idx + 1]):
                _ps = _compute_signals(_p)
                prev_buy_scores[_p.symbol] = _ps['buy_score']
        for c in candidates:
            _prev = prev_buy_scores.get(c.symbol)
            c.buy_score_delta = (c.buy_score - _prev) if _prev is not None else None

    # ====== Markov Market Regime (v11) ======
    from django.core.cache import cache as _regime_cache

    from .utils import calculate_markov_regime
    
    _regime_key = 'markov_regime_set'
    markov_regime = _regime_cache.get(_regime_key)
    
    if not markov_regime:
        markov_regime = calculate_markov_regime("^SET.BK", window=60)
        _regime_cache.set(_regime_key, markov_regime, 1800) # 30 min cache

    # ====== Win Probability Calculation (v11.1) ======
    if candidates:
        m_state = markov_regime.get('state', 'UNKNOWN')
        m_prob = markov_regime.get('prob', 0) / 100.0
        for c in candidates:
            score = 35.0
            rs_val = getattr(c, 'rs_rating', 0) or 0
            score += (rs_val / 99.0) * 25.0
            tech_val = getattr(c, 'technical_score', 0) or 0
            score += (min(tech_val, 100) / 100.0) * 15.0
            adx_val = getattr(c, 'adx', 0) or 0
            score += (min(adx_val, 50) / 50.0) * 10.0
            cmf_val = getattr(c, 'cmf', 0) or 0
            vol_surge = getattr(c, 'volume_surge', 1.0) or 1.0
            if cmf_val > 0.15: score += 10.0
            elif cmf_val > 0: score += 5.0
            if vol_surge >= 1.5: score += 5.0
            elif vol_surge >= 1.2: score += 2.0
            if m_state == 'TRENDING': score += 10.0 * (0.5 + 0.5 * m_prob)
            elif m_state == 'CHOPPY': score += 4.0
            elif m_state == 'UNKNOWN' and m_prob == 0: score += 5.0
            prox = getattr(c, 'live_zone_prox', None)
            if prox is None:
                prox = getattr(c, 'zone_proximity', 99.0)
            if prox is None:
                prox = 99.0
            if prox > 15 and prox < 100: score -= 10.0
            elif prox > 10 and prox < 100: score -= 5.0
            c.win_probability = round(max(min(score, 98.2), 30.0), 1)

        # เรียงตาม BUY/SELL/RS score ด้วย Python (fallback ถ้าไม่ใช่ DB sort)
        if sort_by == 'buy':
            candidates.sort(key=lambda x: x.buy_score, reverse=True)
        elif sort_by == 'sell':
            candidates.sort(key=lambda x: x.sell_score, reverse=True)
        elif sort_by == 'rs':
            candidates.sort(key=lambda x: getattr(x, 'rs_rating', 0), reverse=True)
        elif sort_by == 'win':
            candidates.sort(key=lambda x: getattr(x, 'win_probability', 0), reverse=True)

        # ====== Top 5 หุ้นแนะนำซื้อ (BUY score สูง) ======
        # เงื่อนไข: RVOL Bull ≥ 1.0x (มีแรงซื้อจริง) + RSI ไม่ overbought
        def _top5_filter(min_rvol, max_rsi=85):
            # max_rsi=85 สอดคล้องกับ _compute_signals ที่ยังให้ +2 กับ RSI 80-85
            return sorted(
                [c for c in candidates
                 if c.buy_score >= 50
                 and c.rvol_bullish
                 and c.rvol >= min_rvol
                 and c.rsi <= max_rsi
                 and not (c.demand_zone_end and float(getattr(c, 'live_price', None) or c.price or 0) < float(c.demand_zone_end))],
                key=lambda x: x.buy_score, reverse=True
            )[:5]

        top5_buy = _top5_filter(1.0)
        if len(top5_buy) < 5:
            top5_buy = _top5_filter(0.7)
        if len(top5_buy) < 3:
            top5_buy = _top5_filter(0.0)

        # ====== Top 5 หุ้นที่ "ผ่านเกณฑ์ครบทุกข้อ" ======
        # ผ่อนปรนเกณฑ์ ADX 20 (เดิม 25) และ RSI ขยายเพื่อให้มีตัวเลือกมากขึ้น 
        def _is_fully_qualified(c):
            rr = c.risk_reward_ratio or 0
            dz_start = float(c.demand_zone_start or 0)
            dz_end   = float(c.demand_zone_end   or 0)
            # ใช้ live price ถ้ามี เพราะ zone_proximity ใน DB เป็นค่า ณ เวลาสแกน
            price    = float(getattr(c, 'live_price', None) or c.price or 0)
            live_prox = getattr(c, 'live_zone_prox', None)
            effective_prox = live_prox if live_prox is not None else c.zone_proximity
            in_zone  = dz_start > 0 and dz_end > 0 and dz_end <= price <= dz_start
            above_zone = price > dz_start and effective_prox <= 30
            near_zone  = in_zone or above_zone
            # ตัดหุ้นที่ราคาหลุดต่ำกว่า demand zone (ทะลุ SL) - ไม่ใช่จุดซื้อแล้ว
            broke_zone = dz_end > 0 and price < dz_end
            # ตัดหุ้นที่ราคาวิ่งขึ้นเกือบถึง/เกิน target แล้ว
            target = c.supply_zone_start or 0
            upside_pct = ((target - price) / price * 100) if (target > 0 and price > 0) else 999
            price_near_target = target > 0 and upside_pct < 8
            return (
                c.buy_score >= 65
                and rr >= 1.5
                and c.adx >= 20
                and 45 <= c.rsi <= 82
                and c.rvol_bullish
                and c.rvol >= 0.8
                and near_zone
                and not broke_zone             # กรอง: ราคาหลุดต่ำกว่า zone (ทะลุ SL)
                and not price_near_target      # กรอง: ราคาใกล้ target แล้ว
                and (c.sell_score or 0) < 50
                and getattr(c, 'rs_rating', 0) >= 60
            )

        top5_qualified = sorted(
            [c for c in candidates if _is_fully_qualified(c)],
            key=lambda x: x.buy_score, reverse=True
        )

        for c in top5_buy:
            reasons = []
            in_zone = (c.demand_zone_start and c.demand_zone_end and
                       c.price <= c.demand_zone_start and c.price >= c.demand_zone_end)
            if in_zone:
                reasons.append("อยู่ใน Entry Zone แล้ว")
            elif c.zone_proximity <= 10:
                reasons.append(f"เหนือโซน {c.zone_proximity:.0f}% (รอย่อ)")
            elif c.zone_proximity <= 30:
                reasons.append(f"เหนือโซน {c.zone_proximity:.0f}%")

            if c.rvol_bullish and c.rvol >= 1.5:
                reasons.append(f"RVOL {c.rvol:.1f}x Bull แรง")
            elif c.rvol_bullish and c.rvol >= 1.0:
                reasons.append(f"RVOL {c.rvol:.1f}x Bull ยืนยัน")

            rr = c.risk_reward_ratio or 0
            if rr >= 3:
                reasons.append(f"RR 1:{rr:.1f} ดีเยี่ยม")
            elif rr >= 2:
                reasons.append(f"RR 1:{rr:.1f} ดี")

            if c.adx >= 30:
                reasons.append(f"ADX {c.adx:.0f} เทรนด์แข็ง")
            elif c.adx >= 25:
                reasons.append(f"ADX {c.adx:.0f} มีเทรนด์")

            if c.technical_score >= 85:
                reasons.append(f"Precision {c.technical_score} สูงมาก")
            elif c.technical_score >= 75:
                reasons.append(f"Precision {c.technical_score} ดี")

            if c.erc_volume_confirmed:
                reasons.append("ERC ยืนยันแล้ว")

            if 55 <= c.rsi <= 70:
                reasons.append(f"RSI {c.rsi:.0f} จุดหวาน")

            if c.price_pattern and c.price_pattern_score > 0:
                reasons.append(f"Pattern: {c.price_pattern}")

            rel = c.rel_momentum_3m if c.rel_momentum_3m != 0.0 else c.rel_momentum_1m
            if rel >= 8:
                reasons.append(f"ชนะ SET +{rel:.1f}% (3m)")
            elif rel >= 3:
                reasons.append(f"ชนะ SET +{rel:.1f}%")

            rs = getattr(c, 'rs_rating', 0)
            if rs >= 85:
                reasons.insert(1, f"RS {rs} - ผู้นำตลาด")   # สอดในตำแหน่ง 2 เสมอ
            elif rs >= 70:
                reasons.insert(1, f"RS {rs} - แข็งแกร่ง")

            c.top_reasons = reasons[:4]

        # เพิ่ม reasons ให้ top5_qualified ด้วย (บางตัวอาจซ้ำกับ top5_buy)
        for c in top5_qualified:
            if not hasattr(c, 'top_reasons'):
                reasons = []
                in_zone = (c.demand_zone_start and c.demand_zone_end and
                           c.price <= c.demand_zone_start and c.price >= c.demand_zone_end)
                if in_zone:
                    reasons.append("อยู่ใน Entry Zone แล้ว")
                elif c.zone_proximity <= 10:
                    reasons.append(f"เหนือโซน {c.zone_proximity:.0f}% (รอย่อ)")
                else:
                    reasons.append(f"เหนือโซน {c.zone_proximity:.0f}%")
                rr = c.risk_reward_ratio or 0
                reasons.append(f"RR 1:{rr:.1f} ✓")
                reasons.append(f"ADX {c.adx:.0f} ✓")
                rs = getattr(c, 'rs_rating', 0)
                if rs >= 85:
                    reasons.insert(1, f"RS {rs} - ผู้นำตลาด")
                elif rs >= 70:
                    reasons.insert(1, f"RS {rs} - แข็งแกร่ง")
                if c.rvol >= 1.5:
                    reasons.append(f"RVOL {c.rvol:.1f}x Bull ✓")
                c.top_reasons = reasons[:4]

        # ====== Leading Sectors Analysis (v3) ======
        # นับจำนวนหุ้นที่ 'แข็งแกร่ง' (buy_score >= 65) ในแต่ละ sector เพื่อหาผู้นำกลุ่ม
        sector_counts = {}
        for c in candidates:
            if c.buy_score >= 65:
                sec = c.sector or 'Unknown'
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
        
        # เรียงลำดับกลุ่มที่แข็งแกร่งที่สุด 5 อันดับแรก
        top_sectors = sorted(
            [{'name': k, 'count': v} for k, v in sector_counts.items()],
            key=lambda x: x['count'], reverse=True
        )[:5]

        # ====== Automated AI Insights (คำอธิบายวิเคราะห์ผลสแกน) ======
        scan_insights = []
        if top5_qualified:
            best_setup = top5_qualified[0]
            rr_val = best_setup.risk_reward_ratio or 0
            rs_val = getattr(best_setup, "rs_rating", 0)
            target_val = best_setup.supply_zone_start or 0
            upside_left = ((target_val - best_setup.price) / best_setup.price * 100) if (target_val > 0 and best_setup.price > 0) else 0
            scan_insights.append({
                'icon': '🏆',
                'title': f'โฟกัสหลัก: {best_setup.symbol} (หน้าเทรดคุ้มค่า ปลอดภัยสูง)',
                'desc': f'ถือเป็นหน้าเทรด Swing Trade ที่สมบูรณ์แบบที่สุดในรอบนี้ เพราะมีความแข็งแกร่ง (RS {rs_val}) เทรนด์ทำมุมสวยงาม แต่ราคาปัจจุบันกลับอยู่ใกล้จุดเข้าซื้อ ทำให้มีความคุ้มค่ากับความเสี่ยงสูง (RR 1:{rr_val:.1f}) Upside เหลืออีก {upside_left:.1f}% ถึง Target ซื้อแล้วมีโอกาสชนะสูง'
            })
        
        # หาหุ้นซิ่งที่สุดแต่เสี่ยงสูง (RS > 90 แต่ RR < 1.0)
        high_risk_momentum = [c for c in top5_buy if getattr(c, 'rs_rating', 0) >= 90 and (c.risk_reward_ratio or 0) < 1.5]
        if high_risk_momentum:
            hm = high_risk_momentum[0]
            if not top5_qualified or hm.symbol != top5_qualified[0].symbol:
                scan_insights.append({
                    'icon': '🚀',
                    'title': f'สายซิ่ง (เสี่ยงสูง): {hm.symbol} (แรงทะลุกราฟ)',
                    'desc': f'นี่คือ "หุ้นโคตรโมเมนตัม" วิ่งแรงชนะตลาดถึง {getattr(hm, "rs_rating", 0)}% วอลุ่มเข้าหนัก แต่อัตราคุ้มทุน (RR) ณ ราคานี้ได้เพียง 1:{hm.risk_reward_ratio or 0:.1f} แปลว่าราคาลอยขึ้นมาพอสมควรแล้ว "อย่าเพิ่งไล่ราคา (Market Buy) แนะนำให้เอาเข้า Watchlist แล้วรอซื้อตอนย่อตัวพักฐาน"'
                })

        # หาหุ้นเพิ่งเริ่มกลับตัว (MACD crossover)
        reversal_stocks = [c for c in top5_buy if getattr(c, 'macd_crossover', False)]
        if reversal_stocks and len(scan_insights) < 3:
            rev = reversal_stocks[0]
            skip = False
            if top5_qualified and rev.symbol == top5_qualified[0].symbol: skip = True
            if high_risk_momentum and rev.symbol == high_risk_momentum[0].symbol: skip = True
            if not skip:
                scan_insights.append({
                    'icon': '🥈',
                    'title': f'สัญญาณกลับตัว: {rev.symbol} (ต้นเทรนด์)',
                    'desc': f'หุ้นตัวนี้มีสัญญาณเชิงบวกคือเกิด MACD Crossover (ตัดเส้น Signal ขึ้นมา) มักใช้ระบุจุดเริ่มต้นของรอบขาขึ้นชุดใหม่ น่าเก็บสะสมที่บริเวณแนวรับปัจจุบัน'
                })
        
        # ถ้าระบบยังไม่มีคำแนะนำเลย
        if not scan_insights and top5_buy:
            top = top5_buy[0]
            scan_insights.append({
                'icon': '💡',
                'title': f'น่าปั้นเทรนด์: {top.symbol}',
                'desc': f'ได้คะแนนเข้าซื้อสูงสุดในรอบนี้ มีโครงสร้างทางเทคนิคโดยรวมเฉลี่ยดีที่สุด เหมาะเป็นหุ้นน่าจับตามอง'
            })

    else:
        top5_buy = []
        top5_qualified = []
        top_sectors = []
        scan_insights = []

    # ====== Market Condition - ดึงข้อมูล SET Index สำหรับแสดงผล (GET + POST) ======
    from django.core.cache import cache as _mcache
    market_condition_key = 'market_condition_set'
    market_condition = _mcache.get(market_condition_key)
    if not market_condition:
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
                _mcache.set(market_condition_key, market_condition, 1800) # 30 min cache
        except Exception:
            pass
        if market_condition.get('phase') == 'UNKNOWN':
            # ดึงไม่สำเร็จ - cache ค่า default สั้นๆ กัน yf.download 430 วันซ้ำทุก request
            _mcache.set(market_condition_key, market_condition, 300)

    context = {
        'title': 'Precision Momentum Scanner - กรองคุณภาพ',
        'candidates': candidates,
        'scanned_at': scanned_at,
        'current_sort': sort_by,
        'all_runs': all_runs,
        'selected_run_idx': run_idx,
        'has_scanned': request.method == "POST" or request.GET.get('scan') == 'true' or bool(all_runs),
        'top5_buy': top5_buy,
        'top5_qualified': top5_qualified,
        'scan_total': len(scan_symbols),
        'scan_passed': len(candidates),
        'top_sectors': top_sectors,
        'scan_insights': scan_insights,
        'scan_data_date': None,  # คำนวณด้านล่าง
        'market_condition': market_condition,
        'markov_regime': markov_regime,
    }
    # คำนวณ scan_data_date จาก scanned_at - ถ้า scan ทำหลัง 16:30 BKK ข้อมูลคือวันเดียวกัน
    # ถ้า scan ทำระหว่าง 10:00-16:30 (ตลาดเปิด) ข้อมูลจะเป็นวันก่อนหน้า
    if scanned_at:
        import pytz as _sddtz
        _bkk = _sddtz.timezone('Asia/Bangkok')
        _st = scanned_at.astimezone(_bkk) if hasattr(scanned_at, 'astimezone') else scanned_at
        from datetime import time as _t
        from datetime import timedelta as _tdd
        # scan_data_date: midday break ยังถือว่า candle ของวันนั้นยังไม่ settle
        _in_mkt = (
            _st.weekday() < 5 and (
                _t(10, 0) <= _st.time() <= _t(12, 30) or
                _t(12, 30) < _st.time() < _t(14, 30) or
                _t(14, 30) <= _st.time() <= _t(16, 30)
            )
        )
        context['scan_data_date'] = (_st.date() - _tdd(days=1)) if _in_mkt else _st.date()

    # Build AI scan JSON for Gemini analysis button
    import json as _scan_json
    def _ser_c(c):
        return {
            "symbol": c.symbol,
            "price": c.price,
            "buy_score": getattr(c, 'buy_score', 0),
            "rs_rating": getattr(c, 'rs_rating', 0),
            "rsi": round(c.rsi, 1),
            "adx": round(c.adx, 1),
            "rvol": round(c.rvol, 2),
            "rvol_bullish": c.rvol_bullish,
            "risk_reward_ratio": c.risk_reward_ratio,
            "zone_proximity": round(c.zone_proximity, 1) if c.zone_proximity else None,
            "macd_crossover": getattr(c, 'macd_crossover', False),
            "ema20_aligned": getattr(c, 'ema20_aligned', False),
            "ema20_rising": getattr(c, 'ema20_rising', False),
            "hh_hl_structure": getattr(c, 'hh_hl_structure', False),
            "bb_squeeze": getattr(c, 'bb_squeeze', False),
            "rel_momentum_3m": getattr(c, 'rel_momentum_3m', 0),
            "sector": c.sector,
            "exit_signal": getattr(c, 'exit_signal', ''),
            "top_reasons": getattr(c, 'top_reasons', []),
        }
    _ai_data = {
        "scan_date": str(context.get('scan_data_date', '')),
        "qualified_stocks": [_ser_c(c) for c in top5_qualified],
        "top_buy_stocks": [_ser_c(c) for c in top5_buy],
        "total_passed": len(candidates),
        "top_sectors": [{"name": s["name"], "count": s["count"]} for s in top_sectors],
    }
    context['ai_scan_json'] = _scan_json.dumps(_ai_data, ensure_ascii=False, default=str).replace('</script>', '<\\/script>')

    # Fetch latest Cup & Handle and Turtle breakout symbols for horizon classification
    from .models import CupHandleCandidate, TurtleScanCandidate, Portfolio as _PortfolioSET

    # Latest Cup & Handle
    latest_ch_run = CupHandleCandidate.objects.filter(user=request.user, market='SET').values_list('scan_run', flat=True).order_by('-scan_run').first()
    ch_symbols = set(CupHandleCandidate.objects.filter(user=request.user, market='SET', scan_run=latest_ch_run).values_list('symbol', flat=True)) if latest_ch_run else set()
    context['cup_handle_symbols'] = ch_symbols

    # Latest Turtle Breakout
    latest_turtle_run = TurtleScanCandidate.objects.filter(user=request.user, market='SET').values_list('scan_run', flat=True).order_by('-scan_run').first()
    turtle_symbols = set(TurtleScanCandidate.objects.filter(user=request.user, market='SET', scan_run=latest_turtle_run).values_list('symbol', flat=True)) if latest_turtle_run else set()
    context['turtle_symbols'] = turtle_symbols

    # ── Pyramid Alert ──────────────────────────────────────────────────
    # แสดง badge เมื่อหุ้นในพอร์ตขึ้น >=3%, Volume >=1.5x, ยังเหลือ upside >=5%, ไม่มี exit signal
    _port_entry = {}
    for p in _PortfolioSET.objects.filter(user=request.user, market='SET'):
        ep = float(p.entry_price or 0)
        if ep > 0:
            _port_entry[p.symbol.split('.')[0].upper()] = ep

    pyramid_ready = set()
    for _c in candidates:
        _entry = _port_entry.get(_c.symbol.split('.')[0].upper(), 0)
        if _entry <= 0:
            continue
        _curr = float(getattr(_c, 'live_price', None) or _c.price or 0)
        if _curr <= 0:
            continue
        _gain = (_curr - _entry) / _entry * 100
        if (
            _gain >= 3.0 and
            getattr(_c, 'exit_signal', '') not in ('EXIT', 'STRONG EXIT') and
            float(getattr(_c, 'volume_surge', 0) or 0) >= 1.5 and
            float(getattr(_c, 'upside_to_tp', 0) or 0) >= 5
        ):
            pyramid_ready.add(_c.symbol)
    context['pyramid_ready'] = pyramid_ready

    return render(request, 'stocks/precision_scan.html', context)


# ====== Portfolio Momentum Scan - สแกนเฉพาะหุ้นใน Portfolio ======

@login_required
def entry_finder(request, symbol):
    """
    Detailed view for Supply & Demand / Sniper Entry zone for a specific symbol.
    แสดงกราฟ 120 วันพร้อม:
    - Demand Zone (โซนเข้าซื้อ)
    - Supply Zone / Target (โซนขาย)
    - Stop Loss Line
    - EMA50 และ EMA200
    """
    # ถ้า market=US ไม่ต้องเติม .BK (US stocks ใช้ ticker เดิม)
    market = request.GET.get('market')
    
    # หากไม่ได้ระบุ market มาใน URL ให้ลองตรวจสอบจากฐานข้อมูลก่อน
    if not market:
        from .models import MomentumCandidate, PrecisionScanCandidate
        # ลองหาจากรอบสแกนล่าสุด
        cand = PrecisionScanCandidate.objects.filter(symbol=symbol).order_by('-scan_run').first()
        if cand:
            market = cand.market
        else:
            # ลองหาจาก momentum
            mom = MomentumCandidate.objects.filter(symbol=symbol).first()
            if mom:
                market = mom.market
            else:
                market = 'SET' # Default
    
    if market == 'US':
        full_symbol = symbol
    else:
        full_symbol = f"{symbol}.BK" if not symbol.endswith(".BK") else symbol

    try:
        # ใช้ scan_end_date เดียวกับ Precision Scanner เพื่อให้ Zone ตรงกัน
        from datetime import datetime as _efdt
        from datetime import time as _efdtime
        from datetime import timedelta as _eftd

        import pytz as _efpytz
        _ef_bkk = _efpytz.timezone('Asia/Bangkok')
        _ef_now = _efdt.now(_ef_bkk)
        _ef_t   = _ef_now.time()
        _ef_market_day = (
            _ef_now.weekday() < 5 and
            (
                _ef_t < _efdtime(10, 0) or                                      # ก่อนเปิด
                (_efdtime(10, 0) <= _ef_t <= _efdtime(12, 30)) or               # เช้า
                (_efdtime(12, 30) < _ef_t < _efdtime(14, 30)) or               # พัก
                (_efdtime(14, 30) <= _ef_t <= _efdtime(16, 30))                 # บ่าย
            )
        )
        _ef_end_date  = (_ef_now.date() - _eftd(days=1)) if _ef_market_day else _ef_now.date()
        _ef_end_str   = _ef_end_date.strftime('%Y-%m-%d')
        _ef_start_str = (_ef_end_date - _eftd(days=600)).strftime('%Y-%m-%d')

        # Retry up to 4 times with exponential backoff (handles yfinance rate limits)
        import random as _efrnd
        import time as _eftime
        df = None
        for _ef_attempt in range(4):
            try:
                _ef_ticker = yf.Ticker(full_symbol)
                df = _ef_ticker.history(start=_ef_start_str, end=_ef_end_str, interval='1d')
                if df is not None and not df.empty:
                    break
            except Exception as _ef_exc:
                _ef_msg = str(_ef_exc).lower()
                if 'rate' in _ef_msg or 'too many' in _ef_msg or '429' in _ef_msg:
                    _wait = 2 ** _ef_attempt + _efrnd.uniform(0, 1)
                    _eftime.sleep(_wait)
                    continue
                raise
            if _ef_attempt < 3:
                _eftime.sleep(1.5 * (_ef_attempt + 1))

        if df is None or df.empty:
            messages.error(request, f"ไม่พบข้อมูลสำหรับ {symbol}")
            if market == 'US':
                return redirect('stocks:us_precision_scanner')
            return redirect('stocks:momentum_scanner')

        # แก้ไข MultiIndex columns (ถ้ามี)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        # คำนวณ Supply & Demand Zone ด้วย v2 (ใช้ข้อมูลชุดเดียวกับ Precision Scanner)
        sd_zone = find_supply_demand_zones_v2(df)

        # คำนวณ EMA บน df เต็ม (600 วัน) ก่อน เพื่อให้ EMA200 warm-up ครบ
        # ถ้าคำนวณบน subset 120 วัน → EMA200 จะเป็น NaN ทั้งหมด
        import pandas_ta as ta
        df['EMA50']  = ta.ema(df['Close'], length=50)
        df['EMA200'] = ta.ema(df['Close'], length=200)

        # เตรียมข้อมูลกราฟ 120 วันล่าสุด (slice หลังจากคำนวณ EMA แล้ว)
        history_subset = df.tail(120).copy()
        chart_labels = [d.strftime('%Y-%m-%d') for d in history_subset.index]
        chart_values = [round(float(v), 2) for v in history_subset['Close'].values]

        ema50_vals  = [round(float(v), 2) if pd.notna(v) else None for v in history_subset['EMA50'].values]
        ema200_vals = [round(float(v), 2) if pd.notna(v) else None for v in history_subset['EMA200'].values]

        # OHLCV สำหรับ candlestick chart
        ohlcv_data = [
            {
                'x': chart_labels[i],
                'o': round(float(history_subset['Open'].values[i]), 2),
                'h': round(float(history_subset['High'].values[i]), 2),
                'l': round(float(history_subset['Low'].values[i]), 2),
                'c': round(float(history_subset['Close'].values[i]), 2),
            }
            for i in range(len(chart_labels))
        ]

        # ====== RS Line (Relative Strength vs SET) ======
        rs_line_vals = []
        try:
            set_df = yf.download("^SET.BK", start=_ef_start_str, end=_ef_end_str, interval='1d', progress=False)
            if set_df is not None and not set_df.empty:
                if isinstance(set_df.columns, pd.MultiIndex):
                    set_df.columns = set_df.columns.droplevel(1)
                
                # รวมข้อมูลเพื่อเฉลี่ย ratio (RS Line = Stock / Index)
                combined = pd.concat([df['Close'], set_df['Close']], axis=1, keys=['stock', 'set']).dropna()
                combined['rs'] = combined['stock'] / combined['set']
                
                rs_subset = combined['rs'].tail(len(history_subset))
                rs_line_vals = [float(v) for v in rs_subset.values]
        except Exception as e:
            import logging; logging.getLogger('stocks').error(f"RS Line Error: {e}")

        # แปลงข้อมูล chart เป็น JSON สำหรับ JavaScript
        chart_labels_json = json.dumps(chart_labels)
        chart_values_json = json.dumps(chart_values)
        ema50_vals_json = json.dumps(ema50_vals)
        ema200_vals_json = json.dumps(ema200_vals)
        rs_line_json = json.dumps(rs_line_vals)
        ohlcv_json = json.dumps(ohlcv_data)
        sd_zone_json = json.dumps(sd_zone)

        # ราคาปิดวันสุดท้ายของ historical data (ใช้คำนวณ zone เท่านั้น)
        hist_close = float(df['Close'].iloc[-1])

        # Live price จาก fast_info (ตรงกับ momentum card)
        try:
            _live_fi = yf.Ticker(full_symbol).fast_info
            _live_p  = getattr(_live_fi, 'last_price', None)
            curr_price = float(_live_p) if _live_p else hist_close
        except Exception:
            curr_price = hist_close

        # ถ้า live price ต่างจาก hist_close → เพิ่มเป็น data point สุดท้ายในกราฟ
        if abs(curr_price - hist_close) > 0.001:
            _today_str = _ef_now.strftime('%Y-%m-%d')
            chart_labels.append(_today_str)
            chart_values.append(round(curr_price, 2))
            ema50_vals.append(None)
            ema200_vals.append(None)
            ohlcv_data.append({
                'x': _today_str,
                'o': round(curr_price, 2),
                'h': round(curr_price, 2),
                'l': round(curr_price, 2),
                'c': round(curr_price, 2),
            })
            chart_labels_json = json.dumps(chart_labels)
            chart_values_json = json.dumps(chart_values)
            ema50_vals_json   = json.dumps(ema50_vals)
            ema200_vals_json  = json.dumps(ema200_vals)
            ohlcv_json        = json.dumps(ohlcv_data)

        def _set_tick(price):
            """คืน tick size ของหุ้น SET ตามช่วงราคา"""
            p = float(price or 0)
            if p < 2:    return 0.01
            if p < 5:    return 0.02
            if p < 10:   return 0.05
            if p < 25:   return 0.10
            if p < 100:  return 0.25
            if p < 200:  return 0.50
            return 1.00

        # คำนวณ zone_proximity และ zone_status
        ef_zone_prox   = None
        ef_zone_ticks  = None   # จำนวน ticks ที่ห่างจาก zone
        ef_zone_baht   = None   # ระยะห่างในหน่วยบาท
        ef_zone_status = 'above'   # 'at_tp' | 'in_zone' | 'broke' | 'above'
        if sd_zone and sd_zone.get('start'):
            dz_top  = float(sd_zone['start'])
            dz_bot  = float(sd_zone.get('end') or 0)
            target  = float(sd_zone.get('target') or 0)
            tick    = _set_tick(curr_price)
            if target > 0 and curr_price >= target:
                # ราคาถึงหรือเกิน target แล้ว - Take Profit zone
                gap = round(curr_price - target, 4)
                ef_zone_prox  = round((gap / target) * 100, 1)
                ef_zone_ticks = round(gap / tick)
                ef_zone_baht  = round(gap, 2)
                ef_zone_status = 'at_tp'
            elif dz_bot > 0 and curr_price < dz_bot:
                # ราคาหลุดต่ำกว่า zone (ทะลุ SL)
                gap = round(dz_bot - curr_price, 4)
                ef_zone_prox  = round((gap / dz_bot) * 100, 1)
                ef_zone_ticks = round(gap / tick)
                ef_zone_baht  = round(gap, 2)
                ef_zone_status = 'broke'
            elif curr_price <= dz_top:
                # ราคาอยู่ใน demand zone
                ef_zone_prox  = 0.0
                ef_zone_ticks = 0
                ef_zone_baht  = 0.0
                ef_zone_status = 'in_zone'
            else:
                # ราคาอยู่เหนือ zone
                gap = round(curr_price - dz_top, 4)
                ef_zone_prox  = round((gap / dz_top) * 100, 1)
                ef_zone_ticks = round(gap / tick)
                ef_zone_baht  = round(gap, 2)
                ef_zone_status = 'above'

        currency = '$' if market == 'US' else '฿'
        context = {
            'symbol': symbol,
            'full_symbol': full_symbol,
            'market': market,
            'currency': currency,
            'sd_zone': sd_zone,
            'sd_zone_json': sd_zone_json,
            'curr_price': round(curr_price, 2),
            'zone_proximity': ef_zone_prox,
            'zone_ticks': ef_zone_ticks,
            'zone_baht': ef_zone_baht,
            'zone_status': ef_zone_status,
            'scan_end_date': _ef_end_str,
            'chart_labels': chart_labels_json,
            'chart_values': chart_values_json,
            'ema50_vals': ema50_vals_json,
            'ema200_vals': ema200_vals_json,
            'rs_line_vals': rs_line_json,
            'ohlcv_data': ohlcv_json,
            'title': f"Sniper Entry: {symbol}"
        }
        return render(request, 'stocks/entry_finder.html', context)
    except Exception as e:
        messages.error(request, f"Error finding zones for {symbol}: {str(e)}")
        # Redirect back to the referring page, fallback to US or SET scanner by symbol suffix
        referer = request.META.get('HTTP_REFERER', '')
        if 'momentum/us' in referer:
            return redirect('stocks:us_momentum_scanner')
        if 'us-precision' in referer or 'us-sepa' in referer:
            return redirect('stocks:us_precision_scanner')
        if referer:
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(referer)
        # Fallback: US scanner if symbol has no .BK suffix, else SET
        if symbol.endswith('.BK') or '.' not in symbol and len(symbol) <= 5:
            return redirect('stocks:momentum_scanner')
        return redirect('stocks:us_momentum_scanner')

# ====== Signup - สมัครสมาชิกใหม่ ======

@login_required
@require_POST
def clear_scan_data(request):
    """
    ลบผลสแกนของ user ออกจาก database
    POST parameter: scanner = momentum_set | momentum_us | precision_set | precision_us |
                               multifactor | cup_handle | us_sepa | us_value
    """
    from django.contrib import messages as _msg

    from .models import (
        CupHandleCandidate,
        MomentumCandidate,
        MultiFactorCandidate,
        PrecisionScanCandidate,
        USSepaCandidate,
        ValueScanCandidate,
    )

    scanner = request.POST.get('scanner', '')
    next_url = request.POST.get('next', '/')

    _map = {
        'momentum_set':  (MomentumCandidate,       {'user': request.user, 'market': 'SET'}),
        'momentum_us':   (MomentumCandidate,        {'user': request.user, 'market': 'US'}),
        'precision_set': (PrecisionScanCandidate,   {'user': request.user, 'market': 'SET'}),
        'precision_us':  (PrecisionScanCandidate,   {'user': request.user, 'market': 'US'}),
        'multifactor':   (MultiFactorCandidate,     {'user': request.user, 'market': 'SET'}),
        'us_multifactor':(MultiFactorCandidate,     {'user': request.user, 'market': 'US'}),
        'cup_handle':    (CupHandleCandidate,        {'user': request.user, 'market': 'SET'}),
        'us_cup_handle': (CupHandleCandidate,        {'user': request.user, 'market': 'US'}),
        'us_sepa':       (USSepaCandidate,           {'user': request.user}),
        'us_value':      (ValueScanCandidate,        {'user': request.user}),
    }

    if scanner in _map:
        model_cls, filters = _map[scanner]
        deleted_count, _ = model_cls.objects.filter(**filters).delete()
        _msg.success(request, f'ลบข้อมูลสแกน {deleted_count} รายการเรียบร้อยแล้ว')
    else:
        _msg.error(request, 'ไม่พบประเภท scanner ที่ระบุ')

    return redirect(next_url)


@login_required
def multi_factor_scanner(request):
    """
    สแกนหุ้นด้วยระบบ Multi-Factor Super Score
    รวม 4 ปัจจัย: Momentum(40) + Volume/Flow(30) + Sentiment AI(20) + Fundamental(10)
    """
    # ====== SCAN STATUS POLL (AJAX) ======
    if request.GET.get('scan_status') == '1':
        from django.core.cache import cache
        from django.http import JsonResponse as _JsonResponse
        key = f'multifactor_scan_{request.user.id}'
        status = cache.get(key, {'state': 'idle'})
        # เมื่อ done ถูก poll แล้ว ให้ reset เป็น idle ทันที ป้องกัน reload loop
        if status.get('state') == 'done':
            cache.delete(key)
        return _JsonResponse(status)

    # ====== SCAN (POST - ทำ background เพื่อไม่ให้ nginx timeout) ======
    if request.method == "POST" and request.POST.get('action') == 'scan':
        import threading

        from django.core.cache import cache

        user_id  = request.user.id
        cache_key = f'multifactor_scan_{user_id}'

        # ป้องกันการสแกนซ้ำถ้ายังรันอยู่
        current = cache.get(cache_key, {})
        if current.get('state') == 'running':
            return redirect('stocks:multi_factor_scanner')

        cache.set(cache_key, {'state': 'running', 'progress': 0, 'total': 0}, timeout=600)

        def _run_scan(user_id, cache_key):
            import django
            django.setup()
            from concurrent.futures import ThreadPoolExecutor, as_completed

            import pandas_ta as ta
            from django.contrib.auth import get_user_model
            from django.core.cache import cache as _cache

            User = get_user_model()
            user = User.objects.get(pk=user_id)

            try:
                scan_symbols = ScannableSymbol.objects.filter(
                    is_active=True, market='SET'
                ).values_list('symbol', flat=True).distinct()
                if not scan_symbols:
                    refresh_all_thai_symbols()
                    scan_symbols = ScannableSymbol.objects.filter(
                        is_active=True, market='SET'
                    ).values_list('symbol', flat=True).distinct()

                # deduplicate while preserving order
                seen = set()
                sym_list = [s for s in scan_symbols if not (s in seen or seen.add(s))]

                # Delete any existing SET records for these symbols
                MultiFactorCandidate.objects.filter(user=user, symbol__in=sym_list).delete()

                _cache.set(cache_key, {'state': 'running', 'progress': 0, 'total': len(sym_list)}, timeout=600)

                # โหลด sector cache จาก DB ครั้งเดียว
                sector_cache = {
                    s.symbol: s.sector
                    for s in ScannableSymbol.objects.filter(
                        is_active=True, market='SET'
                    ).only('symbol', 'sector')
                }

                # Phase 1: Batch download
                tickers_str = " ".join(f"{s}.BK" for s in sym_list)
                try:
                    batch_df = yf.download(
                        tickers_str, period="1y", interval="1d",
                        group_by='ticker', progress=False, threads=True,
                    )
                except Exception as e:
                    print(f"[MultiFactorScan] Batch download failed: {e}")
                    batch_df = None

                def _get_df(symbol):
                    sym_bk = f"{symbol}.BK"
                    df = None
                    if batch_df is not None and not batch_df.empty:
                        try:
                            df = batch_df[sym_bk].copy() if len(sym_list) > 1 else batch_df.copy()
                        except Exception:
                            df = None
                    if df is None or (hasattr(df, 'empty') and df.empty):
                        try:
                            df = yf.download(sym_bk, period="1y", interval="1d", progress=False)
                        except Exception:
                            return None
                    return df

                def process_one(symbol):
                    try:
                        df = _get_df(symbol)
                        if df is None or df.empty:
                            return None
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(1)
                        df = df.dropna(subset=['Close', 'High'])
                        if len(df) < 60:
                            return None
                        df = df.copy()
                        df['EMA50']  = ta.ema(df['Close'], length=50)
                        df['EMA200'] = ta.ema(df['Close'], length=200)
                        df['RSI']    = ta.rsi(df['Close'], length=14)
                        adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                        if adx_df is not None and not adx_df.empty:
                            df = pd.concat([df, adx_df], axis=1)
                        df['MFI']  = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                        df['RVOL'] = df['Volume'] / df['Volume'].rolling(20).mean()
                        last    = df.iloc[-1]
                        price   = float(df['Close'].iloc[-1])
                        rsi     = float(last.get('RSI')    or 0) if pd.notna(last.get('RSI'))    else 0
                        adx_val = float(last.get('ADX_14') or 0) if 'ADX_14' in df.columns and pd.notna(last.get('ADX_14')) else 0
                        mfi_val = float(last.get('MFI')    or 0) if pd.notna(last.get('MFI'))    else 0
                        rvol    = float(last.get('RVOL')   or 1) if pd.notna(last.get('RVOL'))   else 1.0
                        ema50   = float(last.get('EMA50')  or 0) if pd.notna(last.get('EMA50'))  else 0
                        ema200  = float(last.get('EMA200') or 0) if pd.notna(last.get('EMA200')) else 0
                        above_ema200 = bool(price > ema200) if ema200 else False
                        above_ema50  = bool(price > ema50)  if ema50  else False
                        mom = 0
                        if above_ema200:                        mom += 15
                        if above_ema50:                         mom += 5
                        if 55 <= rsi <= 72:                     mom += 15
                        elif 45 <= rsi < 55 or 72 < rsi <= 80: mom += 7
                        if adx_val >= 30:                       mom += 5
                        vol = 0
                        if rvol >= 3.0:     vol += 15
                        elif rvol >= 2.0:   vol += 12
                        elif rvol >= 1.5:   vol += 8
                        elif rvol >= 1.0:   vol += 4
                        if mfi_val >= 70:   vol += 15
                        elif mfi_val >= 60: vol += 10
                        elif mfi_val >= 50: vol += 5
                        sector = sector_cache.get(symbol, 'Unknown')
                        vol_score = min(vol, 30)
                        return dict(
                            symbol=symbol, sector=sector, price=round(price, 2),
                            market='SET',
                            momentum_score=mom, volume_score=vol_score,
                            sentiment_score=0, fundamental_score=0,
                            super_score=mom + vol_score,
                            rsi=round(rsi, 2), adx=round(adx_val, 2),
                            mfi=round(mfi_val, 2), rvol=round(rvol, 2),
                            eps_growth=0.0, rev_growth=0.0,
                            above_ema200=above_ema200, above_ema50=above_ema50,
                        )
                    except Exception as e:
                        print(f"[MultiFactorScan] {symbol}: {e}")
                        return None

                # Phase 2: รันขนาน + update progress
                raw_results = []
                seen_symbols = set()
                done = 0
                with ThreadPoolExecutor(max_workers=12) as executor:
                    futures = {executor.submit(process_one, s): s for s in sym_list}
                    for future in as_completed(futures):
                        r = future.result()
                        if r and r['symbol'] not in seen_symbols:
                            raw_results.append(r)
                            seen_symbols.add(r['symbol'])
                        done += 1
                        _cache.set(cache_key, {'state': 'running', 'progress': done, 'total': len(sym_list)}, timeout=600)

                # Phase 3: Atomic delete+create to guarantee no duplicates
                from django.db import transaction
                with transaction.atomic():
                    MultiFactorCandidate.objects.filter(
                        user=user, symbol__in=[r['symbol'] for r in raw_results]
                    ).delete()
                    MultiFactorCandidate.objects.bulk_create([
                        MultiFactorCandidate(user=user, **r) for r in raw_results
                    ])
                _cache.set(cache_key, {'state': 'done', 'count': len(raw_results)}, timeout=300)
            except Exception as e:
                import traceback
                print(f"[MultiFactorScan] CRITICAL ERROR: {e}\n{traceback.format_exc()}")
                _cache.set(cache_key, {'state': 'done', 'error': str(e)}, timeout=300)

        # เปิด background thread แล้ว return ทันที - ไม่ block nginx
        t = threading.Thread(target=_run_scan, args=(user_id, cache_key), daemon=True)
        t.start()
        return redirect('stocks:multi_factor_scanner')

    # ====== AI SENTIMENT (batch) ======
    if request.GET.get('sentiment') == 'true':
        candidates_qs = MultiFactorCandidate.objects.filter(user=request.user, market='SET').order_by('-super_score')[:30]
        symbols_list  = [c.symbol for c in candidates_qs]
        if symbols_list:
            try:
                client     = genai.Client(api_key=settings.GEMINI_API_KEY)
                prompt = f"""วิเคราะห์ข่าวและ Sentiment ล่าสุดสำหรับหุ้นไทยเหล่านี้ในตลาด SET:
{', '.join(symbols_list)}

ตอบเป็น JSON array เท่านั้น ไม่มีข้อความอื่นนอก array:
[{{"symbol":"PTT","score":15,"label":"บวก","reason":"สรุปเหตุผล 1 ประโยค"}}]

score: 0-20 (20=บวกมาก, 10=กลาง, 0=ลบมาก)
label: "บวก" หรือ "กลาง" หรือ "ลบ"
reason: ภาษาไทย ไม่เกิน 60 ตัวอักษร"""
                resp = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                import json
                import re
                raw = resp.text.strip()
                raw = re.sub(r'^```(?:json)?\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw)
                data = json.loads(raw)
                for item in data:
                    sym   = item.get('symbol','').upper()
                    score = int(item.get('score', 0))
                    label = item.get('label', '')
                    reason= item.get('reason', '')
                    MultiFactorCandidate.objects.filter(
                        user=request.user, symbol=sym, market='SET'
                    ).update(
                        sentiment_score=score,
                        sentiment_label=label,
                        sentiment_reason=reason,
                    )
                # recalculate super_score for updated records
                for c in MultiFactorCandidate.objects.filter(user=request.user, market='SET'):
                    c.super_score = c.momentum_score + c.volume_score + c.sentiment_score + c.fundamental_score
                    c.save(update_fields=['super_score'])
            except Exception as e:
                messages.warning(request, f"AI Sentiment Error: {e}")
        return redirect('stocks:multi_factor_scanner')

    # ====== Sort & Render ======
    sort_by = request.GET.get('sort', 'super')
    valid_sorts = {
        'super': '-super_score',
        'momentum': '-momentum_score',
        'volume': '-volume_score',
        'sentiment': '-sentiment_score',
        'fundamental': '-fundamental_score',
        'rsi': '-rsi',
        'rvol': '-rvol',
        'symbol': 'symbol',
    }
    order_field = valid_sorts.get(sort_by, '-super_score')
    candidates  = MultiFactorCandidate.objects.filter(user=request.user, market='SET').order_by(order_field)
    last_scan   = candidates.first()

    context = {
        'candidates':    candidates,
        'current_sort':  sort_by,
        'has_scanned':   candidates.exists(),
        'scanned_at':    last_scan.scanned_at if last_scan else None,
        'has_sentiment': candidates.filter(sentiment_score__gt=0).exists(),
    }
    return render(request, 'stocks/multi_factor.html', context)


@login_required
def us_multi_factor_scanner(request):
    """
    US Multi-Factor Super Score Scanner
    Same 4-factor logic as SET scanner but for US stocks (Nasdaq/S&P 500 universe)
    """
    # ====== SCAN STATUS POLL (AJAX) ======
    if request.GET.get('scan_status') == '1':
        from django.core.cache import cache
        from django.http import JsonResponse as _JsonResponse
        key = f'us_multifactor_scan_{request.user.id}'
        status = cache.get(key, {'state': 'idle'})
        if status.get('state') == 'done':
            cache.delete(key)
        return _JsonResponse(status)

    # ====== SCAN (POST) ======
    if request.method == "POST" and request.POST.get('action') == 'scan':
        import threading

        from django.core.cache import cache

        user_id   = request.user.id
        cache_key = f'us_multifactor_scan_{user_id}'

        current = cache.get(cache_key, {})
        if current.get('state') == 'running':
            return redirect('stocks:us_multi_factor_scanner')

        cache.set(cache_key, {'state': 'running', 'progress': 0, 'total': 0}, timeout=600)

        def _run_scan(user_id, cache_key):
            import django
            django.setup()
            from concurrent.futures import ThreadPoolExecutor, as_completed

            import pandas_ta as ta
            from django.contrib.auth import get_user_model
            from django.core.cache import cache as _cache

            User = get_user_model()
            user = User.objects.get(pk=user_id)

            try:
                # deduplicate while preserving order
                _excl = {'SPY', 'QQQ', 'IWM'}
                _seen = set()
                sym_list = [s for s in _US_MOMENTUM_SYMBOLS
                            if s not in _excl and not (s in _seen or _seen.add(s))]
                # Delete any existing US records (market='US') AND any stale records
                # with wrong market value (e.g. market='SET' from before migration)
                MultiFactorCandidate.objects.filter(user=user, symbol__in=sym_list).delete()

                _cache.set(cache_key, {'state': 'running', 'progress': 0, 'total': len(sym_list)}, timeout=600)

                # Phase 1: Batch download
                tickers_str = " ".join(sym_list)
                try:
                    batch_df = yf.download(
                        tickers_str, period="1y", interval="1d",
                        group_by='ticker', progress=False, threads=True,
                    )
                except Exception as e:
                    print(f"[USMultiFactorScan] Batch download failed: {e}")
                    batch_df = None

                def _get_df(symbol):
                    df = None
                    if batch_df is not None and not batch_df.empty:
                        try:
                            df = batch_df[symbol].copy() if len(sym_list) > 1 else batch_df.copy()
                        except Exception:
                            df = None
                    if df is None or (hasattr(df, 'empty') and df.empty):
                        try:
                            df = yf.download(symbol, period="1y", interval="1d", progress=False)
                        except Exception:
                            return None
                    return df

                def process_one(symbol):
                    try:
                        df = _get_df(symbol)
                        if df is None or df.empty:
                            return None
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(1)
                        df = df.dropna(subset=['Close', 'High'])
                        if len(df) < 60:
                            return None
                        df = df.copy()
                        df['EMA50']  = ta.ema(df['Close'], length=50)
                        df['EMA200'] = ta.ema(df['Close'], length=200)
                        df['RSI']    = ta.rsi(df['Close'], length=14)
                        adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                        if adx_df is not None and not adx_df.empty:
                            df = pd.concat([df, adx_df], axis=1)
                        df['MFI']  = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                        df['RVOL'] = df['Volume'] / df['Volume'].rolling(20).mean()
                        last    = df.iloc[-1]
                        price   = float(df['Close'].iloc[-1])
                        rsi     = float(last.get('RSI')    or 0) if pd.notna(last.get('RSI'))    else 0
                        adx_val = float(last.get('ADX_14') or 0) if 'ADX_14' in df.columns and pd.notna(last.get('ADX_14')) else 0
                        mfi_val = float(last.get('MFI')    or 0) if pd.notna(last.get('MFI'))    else 0
                        rvol    = float(last.get('RVOL')   or 1) if pd.notna(last.get('RVOL'))   else 1.0
                        ema50   = float(last.get('EMA50')  or 0) if pd.notna(last.get('EMA50'))  else 0
                        ema200  = float(last.get('EMA200') or 0) if pd.notna(last.get('EMA200')) else 0
                        above_ema200 = bool(price > ema200) if ema200 else False
                        above_ema50  = bool(price > ema50)  if ema50  else False
                        # Use static sector map - avoid per-symbol API call (193 calls = very slow)
                        sector = _US_SECTOR_MAP.get(symbol, 'Unknown')
                        mom = 0
                        if above_ema200:                        mom += 15
                        if above_ema50:                         mom += 5
                        if 55 <= rsi <= 72:                     mom += 15
                        elif 45 <= rsi < 55 or 72 < rsi <= 80: mom += 7
                        if adx_val >= 30:                       mom += 5
                        vol = 0
                        if rvol >= 3.0:     vol += 15
                        elif rvol >= 2.0:   vol += 12
                        elif rvol >= 1.5:   vol += 8
                        elif rvol >= 1.0:   vol += 4
                        if mfi_val >= 70:   vol += 15
                        elif mfi_val >= 60: vol += 10
                        elif mfi_val >= 50: vol += 5
                        vol_score = min(vol, 30)
                        return dict(
                            symbol=symbol, sector=sector, price=round(price, 2),
                            market='US',
                            momentum_score=mom, volume_score=vol_score,
                            sentiment_score=0, fundamental_score=0,
                            super_score=mom + vol_score,
                            rsi=round(rsi, 2), adx=round(adx_val, 2),
                            mfi=round(mfi_val, 2), rvol=round(rvol, 2),
                            eps_growth=0.0, rev_growth=0.0,
                            above_ema200=above_ema200, above_ema50=above_ema50,
                        )
                    except Exception as e:
                        print(f"[USMultiFactorScan] {symbol}: {e}")
                        return None

                raw_results = []
                seen_symbols = set()
                done = 0
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {executor.submit(process_one, s): s for s in sym_list}
                    for future in as_completed(futures):
                        r = future.result()
                        if r and r['symbol'] not in seen_symbols:
                            raw_results.append(r)
                            seen_symbols.add(r['symbol'])
                        done += 1
                        _cache.set(cache_key, {'state': 'running', 'progress': done, 'total': len(sym_list)}, timeout=600)

                # Final atomic delete+create to guarantee no duplicates
                from django.db import transaction
                with transaction.atomic():
                    MultiFactorCandidate.objects.filter(
                        user=user, symbol__in=[r['symbol'] for r in raw_results]
                    ).delete()
                    MultiFactorCandidate.objects.bulk_create([
                        MultiFactorCandidate(user=user, **r) for r in raw_results
                    ])
                _cache.set(cache_key, {'state': 'done', 'count': len(raw_results)}, timeout=300)
            except Exception as e:
                import traceback
                print(f"[USMultiFactorScan] CRITICAL ERROR: {e}\n{traceback.format_exc()}")
                _cache.set(cache_key, {'state': 'done', 'error': str(e)}, timeout=300)

        t = threading.Thread(target=_run_scan, args=(user_id, cache_key), daemon=True)
        t.start()
        return redirect('stocks:us_multi_factor_scanner')

    # ====== AI SENTIMENT (batch) ======
    if request.GET.get('sentiment') == 'true':
        candidates_qs = MultiFactorCandidate.objects.filter(user=request.user, market='US').order_by('-super_score')[:30]
        symbols_list  = [c.symbol for c in candidates_qs]
        if symbols_list:
            try:
                client = genai.Client(api_key=settings.GEMINI_API_KEY)
                prompt = f"""Analyze the latest news sentiment for these US stocks:
{', '.join(symbols_list)}

Reply with a JSON array only, no other text:
[{{"symbol":"AAPL","score":15,"label":"Positive","reason":"One-sentence summary"}}]

score: 0-20 (20=very positive, 10=neutral, 0=very negative)
label: "Positive" or "Neutral" or "Negative"
reason: English, max 80 characters"""
                resp = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                import json
                import re
                raw = resp.text.strip()
                raw = re.sub(r'^```(?:json)?\s*', '', raw)
                raw = re.sub(r'\s*```$', '', raw)
                data = json.loads(raw)
                for item in data:
                    sym   = item.get('symbol','').upper()
                    score = int(item.get('score', 0))
                    label = item.get('label', '')
                    reason= item.get('reason', '')
                    MultiFactorCandidate.objects.filter(
                        user=request.user, symbol=sym, market='US'
                    ).update(
                        sentiment_score=score,
                        sentiment_label=label,
                        sentiment_reason=reason,
                    )
                for c in MultiFactorCandidate.objects.filter(user=request.user, market='US'):
                    c.super_score = c.momentum_score + c.volume_score + c.sentiment_score + c.fundamental_score
                    c.save(update_fields=['super_score'])
            except Exception as e:
                messages.warning(request, f"AI Sentiment Error: {e}")
        return redirect('stocks:us_multi_factor_scanner')

    # ====== Sort & Render ======
    sort_by = request.GET.get('sort', 'super')
    valid_sorts = {
        'super': '-super_score',
        'momentum': '-momentum_score',
        'volume': '-volume_score',
        'sentiment': '-sentiment_score',
        'fundamental': '-fundamental_score',
        'rsi': '-rsi',
        'rvol': '-rvol',
        'symbol': 'symbol',
    }
    order_field = valid_sorts.get(sort_by, '-super_score')
    candidates  = MultiFactorCandidate.objects.filter(user=request.user, market='US').order_by(order_field)
    last_scan   = candidates.first()

    context = {
        'candidates':    candidates,
        'current_sort':  sort_by,
        'has_scanned':   candidates.exists(),
        'scanned_at':    last_scan.scanned_at if last_scan else None,
        'has_sentiment': candidates.filter(sentiment_score__gt=0).exists(),
        'total_symbols': len([s for s in _US_MOMENTUM_SYMBOLS if s not in ('SPY', 'QQQ', 'IWM')]),
    }
    return render(request, 'stocks/us_multi_factor.html', context)

@login_required
def precision_scan_report(request):
    """View to display the standalone Precision Scan AI Report for SET."""
    scan_data = _get_precision_scan_data(request.user, market='SET')
    if not scan_data:
        return redirect('stocks:precision_momentum_scanner')
    
    return render(request, 'stocks/precision_scan_report.html', {
        'market': 'SET',
        'symbol': 'SET Index',
        'scan_data_json': json.dumps(scan_data),
        'title': 'Precision Scan AI Report (TH)'
    })

@login_required
def us_precision_scan_report(request):
    """View to display the standalone Precision Scan AI Report for US."""
    scan_data = _get_precision_scan_data(request.user, market='US')
    if not scan_data:
        return redirect('stocks:us_precision_scanner')
    
    return render(request, 'stocks/precision_scan_report.html', {
        'market': 'US',
        'symbol': 'US Market',
        'scan_data_json': json.dumps(scan_data),
        'title': 'Precision Scan AI Report (US)'
    })

@login_required
def us_momentum_scanner(request):
    """
    US Momentum Scanner - scans ~200 Nasdaq/S&P 500 stocks using Minervini Trend Template.
    Results saved to MomentumCandidate (market='US') - same as SET scanner.
    """
    import threading as _th

    from django.core.cache import cache as _cp
    from django.http import JsonResponse as _JR

    user_id   = request.user.id
    cache_key = f'us_momentum_scan_{user_id}'

    # ── AJAX scan progress poll ───────────────────────────────────────
    if request.GET.get('scan_status') == '1':
        st = _cp.get(cache_key, {'state': 'idle'})
        if st.get('state') == 'done':
            _cp.delete(cache_key)
        return _JR(st)

    # ── Trigger background scan ───────────────────────────────────────
    if request.GET.get('scan') == 'true' or request.method == 'POST':
        cur = _cp.get(cache_key, {})
        if cur.get('state') != 'running':
            scan_syms = [s for s in _US_MOMENTUM_SYMBOLS if s not in ('SPY', 'QQQ', 'IWM')]
            _cp.set(cache_key, {
                'state': 'running', 'progress': 0,
                'total': len(scan_syms), 'phase': 'เตรียมข้อมูล…'
            }, timeout=900)

            def _run_us_bg(uid, ckey, sym_list):
                try:
                    import concurrent.futures as _cf
                    from datetime import timedelta as _td

                    import pandas as _pd
                    import pandas_ta as _ta
                    from django.contrib.auth import get_user_model
                    from django.core.cache import cache as _c
                    from django.utils import timezone as _tz

                    from .models import MomentumCandidate as _MCM
                    from .utils import find_supply_demand_zones_v2
                    _User = get_user_model()
                    _user = _User.objects.get(pk=uid)

                    from datetime import datetime as _dt

                    import pytz as _pytz
                    _ny_tz      = _pytz.timezone('America/New_York')
                    _now_ny     = _dt.now(_ny_tz)
                    _end_date   = _now_ny.date()
                    _end_str    = (_end_date + _td(days=1)).strftime('%Y-%m-%d')
                    _start_str  = (_end_date - _td(days=600)).strftime('%Y-%m-%d')
                    _spy_start  = (_end_date - _td(days=400)).strftime('%Y-%m-%d')

                    total = len(sym_list)

                    # ── Step 1: SPY benchmark returns ─────────────────
                    _c.set(ckey, {'state': 'running', 'progress': 0, 'total': total, 'phase': 'โหลด SPY Benchmark…'}, timeout=900)
                    spy_1m = spy_3m = 0.0
                    try:
                        spy_df = yf.download("SPY", start=_spy_start, end=_end_str, interval="1d", progress=False)
                        if spy_df is not None and not spy_df.empty:
                            if isinstance(spy_df.columns, _pd.MultiIndex):
                                spy_df.columns = spy_df.columns.droplevel(1)
                            sc = spy_df['Close'].dropna()
                            if len(sc) >= 66:
                                spy_1m = float((sc.iloc[-1] - sc.iloc[-22]) / sc.iloc[-22] * 100)
                                spy_3m = float((sc.iloc[-1] - sc.iloc[-66]) / sc.iloc[-66] * 100)
                    except Exception:
                        pass

                    # ── Step 2: RS Rating (4-quarter weighted) ────────
                    _c.set(ckey, {'state': 'running', 'progress': 0, 'total': total, 'phase': 'คำนวณ RS Rating…'}, timeout=900)

                    def _fetch_rs(sym):
                        import random as _rnd
                        import time as _t
                        _t.sleep(_rnd.uniform(0.05, 0.3))
                        for _att in range(3):
                            try:
                                d = yf.Ticker(sym).history(start=_start_str, end=_end_str, interval="1d")
                                if d is None or d.empty:
                                    return sym, None
                                if isinstance(d.columns, _pd.MultiIndex):
                                    d.columns = d.columns.droplevel(1)
                                cl = d['Close'].dropna()
                                if len(cl) >= 252:
                                    r = float(
                                        (cl.iloc[-1] - cl.iloc[-64]) / abs(cl.iloc[-64]) * 0.4 +
                                        (cl.iloc[-64] - cl.iloc[-127]) / abs(cl.iloc[-127]) * 0.2 +
                                        (cl.iloc[-127] - cl.iloc[-190]) / abs(cl.iloc[-190]) * 0.2 +
                                        (cl.iloc[-190] - cl.iloc[-253]) / abs(cl.iloc[-253]) * 0.2
                                    ) * 100
                                    return sym, r
                                return sym, None
                            except Exception as _e:
                                _emsg = str(_e).lower()
                                if 'rate' in _emsg or 'too many' in _emsg or '429' in _emsg:
                                    _t.sleep(2 ** _att + _rnd.uniform(0, 1))
                                    continue
                                return sym, None
                        return sym, None

                    rs_raw = {}
                    _rs_done = 0
                    with _cf.ThreadPoolExecutor(max_workers=6) as ex:
                        futs = {ex.submit(_fetch_rs, s): s for s in sym_list}
                        for f in _cf.as_completed(futs, timeout=180):
                            try:
                                s, r = f.result()
                                if r is not None:
                                    rs_raw[s] = r
                            except Exception:
                                pass
                            _rs_done += 1
                            if _rs_done % 5 == 0 or _rs_done == total:
                                _c.set(ckey, {
                                    'state': 'running',
                                    'progress': _rs_done,
                                    'total': total,
                                    'phase': f'RS Ratings ({_rs_done}/{total})…',
                                }, timeout=900)

                    rs_map = {}
                    if rs_raw:
                        ser = _pd.Series(rs_raw)
                        rs_map = (ser.rank(pct=True) * 99).clip(0, 99).astype(int).to_dict()

                    # ── Step 3: Technical scan ─────────────────────────
                    _c.set(ckey, {'state': 'running', 'progress': 0, 'total': total, 'phase': 'Technical Scan…'}, timeout=900)

                    results    = []
                    lock       = _th.Lock()
                    done_count = [0]

                    def _scan_one(symbol):
                        import random as _random
                        import time as _time
                        # Small random jitter to spread requests
                        _time.sleep(_random.uniform(0.1, 0.6))
                        try:
                            # Retry up to 3 times with exponential backoff on rate-limit
                            df = _pd.DataFrame()
                            for _attempt in range(3):
                                try:
                                    ticker = yf.Ticker(symbol)
                                    df = ticker.history(start=_start_str, end=_end_str, interval="1d")
                                    if df is not None and not df.empty:
                                        break
                                except Exception as _e:
                                    _emsg = str(_e).lower()
                                    if 'rate' in _emsg or 'too many' in _emsg or '429' in _emsg:
                                        _time.sleep(2 ** _attempt + _random.uniform(0, 1))
                                        continue
                                    break
                            if df is None or df.empty:
                                return None
                            if isinstance(df.columns, _pd.MultiIndex):
                                df.columns = df.columns.droplevel(1)
                            df = df.dropna(subset=['Close', 'High'])
                            if len(df) < 150:
                                return None

                            # Liquidity filter - ≥500K avg daily volume
                            av20 = float(df['Volume'].tail(20).mean())
                            if av20 < 500_000:
                                return None

                            # Indicators
                            df['EMA50']  = _ta.ema(df['Close'], length=50)
                            df['EMA150'] = _ta.ema(df['Close'], length=150)
                            df['EMA200'] = _ta.ema(df['Close'], length=200)
                            df['RSI']    = _ta.rsi(df['Close'], length=14)
                            adx_df = _ta.adx(df['High'], df['Low'], df['Close'], length=14)
                            if adx_df is not None and not adx_df.empty:
                                df = _pd.concat([df, adx_df], axis=1)
                            mfi_s = _ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                            if mfi_s is not None:
                                df['MFI'] = mfi_s
                            vol_avg = df['Volume'].rolling(20).mean()
                            df['RVOL'] = df['Volume'] / vol_avg

                            last         = df.iloc[-1]
                            current_p    = float(last['Close'])
                            year_high    = float(df['High'].tail(252).max())
                            ema200       = float(last.get('EMA200', 0) or 0)
                            ema50        = float(last.get('EMA50', 0) or 0)
                            rsi_val      = float(last.get('RSI', 50) or 50)
                            adx_val      = float(last['ADX_14']) if 'ADX_14' in df.columns and _pd.notna(last.get('ADX_14')) else 0
                            mfi_val      = float(last['MFI']) if 'MFI' in df.columns and _pd.notna(last.get('MFI')) else 0
                            rvol_val     = float(last['RVOL']) if _pd.notna(last.get('RVOL')) else 1.0

                            # ── Minervini Trend Template filters ──────
                            if not (current_p > ema200 and current_p >= year_high * 0.65):
                                return None
                            if adx_val < 15:
                                return None

                            rs_v = rs_map.get(symbol, 0)

                            # ── Score (0–100) ─────────────────────────
                            score = 0
                            # Trend alignment (max 35)
                            if current_p > ema200:               score += 15
                            if current_p > ema50:                score += 10
                            if ema50 > ema200:                   score += 10
                            # Momentum (max 20)
                            if 55 < rsi_val < 80:                score += 15
                            elif 45 < rsi_val <= 55:             score += 5
                            # Volume/RVOL (max 20)
                            last_close  = float(df['Close'].iloc[-1])
                            prev_close  = float(df['Close'].iloc[-2]) if len(df) > 1 else last_close
                            is_bullish  = last_close >= prev_close
                            if is_bullish and rvol_val >= 1.5:   score += 20
                            elif is_bullish and rvol_val >= 1.0: score += 12
                            elif rvol_val >= 1.0:                score += 5
                            # Price strength (max 10)
                            if current_p >= year_high * 0.90:    score += 10
                            elif current_p >= year_high * 0.80:  score += 5
                            # RS Rating bonus (max 15)
                            if rs_v >= 85:                       score += 15
                            elif rs_v >= 70:                     score += 8
                            elif rs_v >= 60:                     score += 3
                            score = min(score, 100)

                            # ── MACD crossover ────────────────────────
                            m_cross = False
                            try:
                                md = _ta.macd(df['Close'])
                                if md is not None and not md.empty:
                                    mc = md.columns[0]
                                    ms = next((c for c in md.columns if 'MACDs' in c), None)
                                    if mc and ms:
                                        for i in range(-3, 0):
                                            if md[mc].iloc[i-1] <= md[ms].iloc[i-1] and md[mc].iloc[i] > md[ms].iloc[i]:
                                                m_cross = True
                                                break
                            except Exception:
                                pass

                            # ── BB Squeeze ────────────────────────────
                            bb_sqz = False
                            try:
                                bb = _ta.bbands(df['Close'])
                                if bb is not None and not bb.empty:
                                    bu = next((c for c in bb.columns if 'BBU' in c), None)
                                    bl = next((c for c in bb.columns if 'BBL' in c), None)
                                    bm = next((c for c in bb.columns if 'BBM' in c), None)
                                    if bu and bl and bm:
                                        bw = (bb[bu] - bb[bl]) / bb[bm]
                                        if float(bw.iloc[-1]) <= float(bw.quantile(0.2)):
                                            bb_sqz = True
                            except Exception:
                                pass

                            # ── Stage 2 ───────────────────────────────
                            stage2 = False
                            try:
                                s150 = _ta.sma(df['Close'], length=150)
                                if s150 is not None and not s150.empty:
                                    stage2 = (current_p > float(s150.iloc[-1])) and (float(s150.iloc[-1]) > float(s150.iloc[-20]))
                            except Exception:
                                pass

                            # ── Supply / Demand Zone ──────────────────
                            sd_zone = find_supply_demand_zones_v2(df)
                            dz_s = dz_e = sz_s = rr_v = None
                            prox = 999.0
                            if sd_zone:
                                dz_s = sd_zone.get('start')
                                dz_e = sd_zone.get('end')
                                sz_s = sd_zone.get('target')
                                rr_v = sd_zone.get('rr_ratio')
                                if dz_s:
                                    prox = 0.0 if current_p <= dz_s else round((current_p - dz_s) / dz_s * 100, 2)

                            # ── Relative returns ──────────────────────
                            rel_1m = rel_3m = 0.0
                            cl = df['Close'].dropna()
                            if len(cl) >= 22:
                                rel_1m = round(float((cl.iloc[-1] - cl.iloc[-22]) / cl.iloc[-22] * 100) - spy_1m, 2)
                            if len(cl) >= 66:
                                rel_3m = round(float((cl.iloc[-1] - cl.iloc[-66]) / cl.iloc[-66] * 100) - spy_3m, 2)

                            # ── Sector ────────────────────────────────
                            sector = 'Unknown'
                            try:
                                info = ticker.info or {}
                                sector = info.get('sector', 'Unknown') or 'Unknown'
                            except Exception:
                                pass

                            return {
                                'symbol':            symbol,
                                'price':             round(current_p, 2),
                                'technical_score':   score,
                                'rs_rating':         rs_v,
                                'rsi':               round(rsi_val, 2),
                                'adx':               round(adx_val, 2),
                                'mfi':               round(mfi_val, 2),
                                'rvol':              round(rvol_val, 2),
                                'rvol_bullish':      is_bullish and rvol_val >= 1.0,
                                'demand_zone_start': round(dz_s, 2) if dz_s else None,
                                'demand_zone_end':   round(dz_e, 2) if dz_e else None,
                                'supply_zone_start': round(sz_s, 2) if sz_s else None,
                                'risk_reward_ratio': round(rr_v, 2) if rr_v else None,
                                'zone_proximity':    round(prox, 2),
                                'year_high':         round(year_high, 2),
                                'upside_to_high':    round((year_high - current_p) / current_p * 100, 2),
                                'sector':            sector,
                                'stage2':            stage2,
                                'macd_crossover':    m_cross,
                                'bb_squeeze':        bb_sqz,
                                'rel_1m':            rel_1m,
                                'rel_3m':            rel_3m,
                                # live fields (filled on display)
                                'live_price':       None,
                                'live_change_pct':  None,
                                'live_in_zone':     False,
                                'live_broke_zone':  False,
                                'live_above_tp':    False,
                                'live_near_tp':     False,
                                'live_zone_prox':   999,
                            }
                        except Exception:
                            return None

                    with _cf.ThreadPoolExecutor(max_workers=4) as ex:
                        futs = {ex.submit(_scan_one, s): s for s in sym_list}
                        for idx, f in enumerate(_cf.as_completed(futs, timeout=900)):
                            try:
                                r = f.result()
                                if r:
                                    with lock:
                                        results.append(r)
                            except Exception:
                                pass
                            done_count[0] += 1
                            if done_count[0] % 5 == 0:
                                _c.set(ckey, {
                                    'state': 'running',
                                    'progress': done_count[0],
                                    'total': total,
                                    'phase': f'Scanning… ({done_count[0]}/{total})',
                                }, timeout=900)

                    # ── Save to DB (delete old, bulk create new) ──────
                    _MCM.objects.filter(user=_user, market='US').delete()
                    _bulk = []
                    for r in results:
                        _bulk.append(_MCM(
                            user=_user,
                            market='US',
                            symbol=r['symbol'],
                            symbol_bk=r['symbol'],   # US has no .BK suffix
                            sector=r.get('sector', 'Unknown'),
                            price=r['price'],
                            rsi=r['rsi'],
                            adx=r['adx'],
                            mfi=r['mfi'],
                            rvol=r['rvol'],
                            rvol_bullish=r.get('rvol_bullish', False),
                            eps_growth=0.0,
                            rev_growth=0.0,
                            technical_score=r['technical_score'],
                            rs_rating=r.get('rs_rating', 0),
                            stage2=r.get('stage2', False),
                            macd_crossover=r.get('macd_crossover', False),
                            bb_squeeze=r.get('bb_squeeze', False),
                            rel_1m=r.get('rel_1m', 0.0),
                            rel_3m=r.get('rel_3m', 0.0),
                            demand_zone_start=r.get('demand_zone_start'),
                            demand_zone_end=r.get('demand_zone_end'),
                            supply_zone_start=r.get('supply_zone_start'),
                            supply_zone_end=None,
                            stop_loss=None,
                            risk_reward_ratio=r.get('risk_reward_ratio'),
                            year_high=r.get('year_high', 0.0),
                            upside_to_high=r.get('upside_to_high', 0.0),
                            zone_proximity=r.get('zone_proximity', 999.0),
                        ))
                    if _bulk:
                        _MCM.objects.bulk_create(_bulk, ignore_conflicts=True)

                    _c.set(ckey, {'state': 'done'}, timeout=300)

                except Exception as exc:
                    from django.core.cache import cache as _c2
                    _c2.set(ckey, {'state': 'done'}, timeout=300)

            _th.Thread(
                target=_run_us_bg,
                args=(user_id, cache_key, scan_syms),
                daemon=True,
            ).start()

        from django.shortcuts import redirect as _redir
        return _redir('stocks:us_momentum_scanner')

    # ── Display results from DB ───────────────────────────────────────
    sort_by = request.GET.get('sort', 'score')
    valid_sorts = {
        'symbol':    'symbol',
        'score':     '-technical_score',
        'rs':        '-rs_rating',
        'rsi':       '-rsi',
        'rvol':      '-rvol',
        'adx':       '-adx',
        'mfi':       '-mfi',
        'price':     '-price',
        'gap':       'upside_to_high',
        'prox':      'zone_proximity',
        'round_rr':  '-risk_reward_ratio',
        'rel1m':     '-rel_1m',
    }
    order_field = valid_sorts.get(sort_by, '-technical_score')

    _scan_state = _cp.get(cache_key, {})
    is_scanning = _scan_state.get('state') == 'running'

    db_candidates = (
        MomentumCandidate.objects.filter(user=request.user, market='US')
        .order_by(order_field)
        if not is_scanning else MomentumCandidate.objects.none()
    )

    # Attach live price + zone status (same pattern as SET scanner)
    candidate_list = list(db_candidates)
    if candidate_list:
        try:
            import concurrent.futures as _mcf

            def _live_us(sym):
                try:
                    fi = yf.Ticker(sym).fast_info
                    p  = getattr(fi, 'last_price', None)
                    pc = getattr(fi, 'regular_market_previous_close', getattr(fi, 'previous_close', None))
                    return sym, (float(p) if p else None), (float(pc) if pc else None)
                except Exception:
                    return sym, None, None

            live_map = {}
            prev_close_map = {}
            with _mcf.ThreadPoolExecutor(max_workers=6) as ex:
                for sym, lp, lpc in ex.map(_live_us, [c.symbol for c in candidate_list]):
                    if lp:
                        live_map[sym] = lp
                    if lpc:
                        prev_close_map[sym] = lpc
        except Exception:
            live_map = {}
            prev_close_map = {}

        for c in candidate_list:
            lp  = live_map.get(c.symbol)
            pc  = prev_close_map.get(c.symbol) or float(c.price or 0)
            c.live_price = lp
            ref  = lp if lp else float(c.price or 0)
            dz_s = float(c.demand_zone_start or 0)
            dz_e = float(c.demand_zone_end   or 0)
            sz_s = float(c.supply_zone_start or 0)
            c.live_in_zone    = dz_s > 0 and dz_e > 0 and dz_e <= ref <= dz_s
            c.live_broke_zone = dz_e > 0 and ref < dz_e
            c.live_above_tp   = sz_s > 0 and ref >= sz_s
            c.live_near_tp    = (
                not c.live_above_tp and sz_s > 0 and dz_s > 0 and
                (sz_s - dz_s) > 0 and (sz_s - ref) / (sz_s - dz_s) * 100 <= 15
            )
            c.live_zone_prox  = (
                0.0 if ref <= dz_s else
                round((ref - dz_s) / dz_s * 100, 1) if dz_s > 0 else 999
            )
            c.live_change_pct = (
                round((lp - pc) / pc * 100, 2)
                if lp and pc > 0 else None
            )

    # ── AI Superperformance filter ────────────────────────────────────
    ai_analysis = None
    if candidate_list and request.GET.get('analyze') == 'true':
        syms = [c.symbol for c in candidate_list[:30]]
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            prompt = f"""You are a top US momentum stock analyst using Minervini/O'Neil methodology.

From this list of US stocks that passed the Trend Template filter:
{', '.join(syms)}

Analyze current news, earnings momentum, sector rotation, and market sentiment to identify
the top 5-7 "Superperformance" candidates most likely to make significant moves in the next 2-6 weeks.

Write in Thai language, markdown format:
- For each pick: symbol, why it's the leader (RS Rating, Stage 2, Catalyst), key risk
- Focus on Relative Strength leaders and stocks near breakout pivots
- Note any Earnings dates or Fed events to watch
- No intro, no outro"""
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            ai_analysis = response.text
            if ai_analysis and ai_analysis.startswith("```"):
                ai_analysis = ai_analysis.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
        except Exception as e:
            ai_analysis = f"AI Error: {str(e)}"

    last_scan = MomentumCandidate.objects.filter(user=request.user, market='US').order_by('-scanned_at').first()
    scanned_at = last_scan.scanned_at if last_scan else None

    return render(request, 'stocks/us_momentum.html', {
        'title':        'US Momentum Scanner',
        'candidates':   candidate_list,
        'ai_analysis':  ai_analysis,
        'scanned_at':   scanned_at,
        'current_sort': sort_by,
        'is_scanning':  is_scanning,
        'has_scanned':  db_candidates.exists() if not is_scanning else True,
    })


@login_required
def us_momentum_quick_analysis(request, symbol):
    """
    Quick CrewAI multi-agent analysis for a US momentum stock.
    AJAX endpoint - returns JSON, displayed in a modal.
    """
    import threading as _th

    from django.core.cache import cache as _cp
    from django.http import JsonResponse as _JR

    user_id   = request.user.id
    cache_key = f'us_mq_analysis_{user_id}_{symbol}'

    # Poll
    if request.GET.get('mq_status') == '1':
        return _JR(_cp.get(cache_key, {'state': 'idle'}))

    cached = _cp.get(cache_key)
    if cached:
        if cached.get('state') == 'running':
            return _JR({'state': 'running'})
        if cached.get('state') == 'done':
            _cp.delete(cache_key)
            return _JR({'state': 'done', 'result': cached.get('result', '')})

    # Get scan data from cache results
    scan_data = {}
    # Load scan data from DB (market='US')
    try:
        cand = MomentumCandidate.objects.filter(user=request.user, symbol=symbol, market='US').first()
        if cand:
            scan_data = {
                'symbol':            cand.symbol,
                'price':             float(cand.price),
                'technical_score':   cand.technical_score,
                'rs_rating':         cand.rs_rating,
                'rsi':               float(cand.rsi),
                'adx':               float(cand.adx),
                'mfi':               float(cand.mfi),
                'rvol':              float(cand.rvol),
                'rvol_bullish':      cand.rvol_bullish,
                'demand_zone_start': float(cand.demand_zone_start) if cand.demand_zone_start else None,
                'demand_zone_end':   float(cand.demand_zone_end) if cand.demand_zone_end else None,
                'supply_zone_start': float(cand.supply_zone_start) if cand.supply_zone_start else None,
                'risk_reward_ratio': float(cand.risk_reward_ratio) if cand.risk_reward_ratio else None,
                'zone_proximity':    float(cand.zone_proximity),
                'sector':            cand.sector or 'Unknown',
                'year_high':         float(cand.year_high),
                'upside_to_high':    float(cand.upside_to_high),
                'stage2':            cand.stage2,
                'macd_crossover':    cand.macd_crossover,
                'bb_squeeze':        cand.bb_squeeze,
                'rel_1m':            float(cand.rel_1m),
                'rel_3m':            float(cand.rel_3m),
            }
    except Exception:
        pass

    # Background analysis
    _cp.set(cache_key, {'state': 'running'}, timeout=600)

    def _run_us_crew(ckey, sym, sd):
        from django.core.cache import cache as _c
        try:
            _c.set(ckey, {'state': 'running', 'phase': 'กำลังวิเคราะห์ด้วย 3 US Expert Agents…'}, timeout=600)
            import concurrent.futures as _cf

            from .crew_analysis import USMomentumShortTermCrew as _USC
            crew = _USC(sym, scan_data=sd)
            with _cf.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(crew.run_analysis)
                try:
                    result = fut.result(timeout=180)
                except _cf.TimeoutError:
                    result = '## Timeout\n\nกรุณาลองใหม่อีกครั้ง'
            _c.set(ckey, {'state': 'done', 'result': result}, timeout=900)
        except Exception as exc:
            from django.core.cache import cache as _c2
            _c2.set(ckey, {'state': 'done', 'result': f'## Error\n\n{exc}'}, timeout=60)

    _th.Thread(target=_run_us_crew, args=(cache_key, symbol, scan_data), daemon=True).start()
    return _JR({'state': 'running'})


@login_required
def us_momentum_crew_page(request, symbol):
    """
    Standalone full-page CrewAI analysis for a US momentum stock.
    Opens in a new tab - does not block the scanner page.
    GET  → render the page (triggers analysis in background)
    GET ?mq_status=1 → AJAX poll (same logic as us_momentum_quick_analysis)
    """
    import threading as _th

    from django.core.cache import cache as _cp
    from django.http import JsonResponse as _JR

    user_id   = request.user.id
    # share the same cache key so existing in-progress analysis is reused
    cache_key = f'us_mq_analysis_{user_id}_{symbol}'

    # AJAX poll
    if request.GET.get('mq_status') == '1':
        return _JR(_cp.get(cache_key, {'state': 'idle'}))

    # Load scan data from DB
    scan_data = {}
    try:
        cand = MomentumCandidate.objects.filter(user=request.user, symbol=symbol, market='US').first()
        if cand:
            scan_data = {
                'symbol':            cand.symbol,
                'price':             float(cand.price),
                'technical_score':   cand.technical_score,
                'rs_rating':         cand.rs_rating,
                'rsi':               float(cand.rsi),
                'adx':               float(cand.adx),
                'mfi':               float(cand.mfi),
                'rvol':              float(cand.rvol),
                'rvol_bullish':      cand.rvol_bullish,
                'demand_zone_start': float(cand.demand_zone_start) if cand.demand_zone_start else None,
                'demand_zone_end':   float(cand.demand_zone_end) if cand.demand_zone_end else None,
                'supply_zone_start': float(cand.supply_zone_start) if cand.supply_zone_start else None,
                'risk_reward_ratio': float(cand.risk_reward_ratio) if cand.risk_reward_ratio else None,
                'zone_proximity':    float(cand.zone_proximity),
                'sector':            cand.sector or 'Unknown',
                'year_high':         float(cand.year_high),
                'upside_to_high':    float(cand.upside_to_high),
                'stage2':            cand.stage2,
                'macd_crossover':    cand.macd_crossover,
                'bb_squeeze':        cand.bb_squeeze,
                'rel_1m':            float(cand.rel_1m),
                'rel_3m':            float(cand.rel_3m),
            }
    except Exception:
        pass

    # Trigger background analysis (skip if already running/done)
    existing = _cp.get(cache_key)
    if not existing or existing.get('state') not in ('running', 'done'):
        _cp.set(cache_key, {'state': 'running'}, timeout=600)

        def _run(ckey, sym, sd):
            from django.core.cache import cache as _c
            try:
                _c.set(ckey, {'state': 'running', 'phase': 'กำลังวิเคราะห์ด้วย 3 US Expert Agents…'}, timeout=600)
                import concurrent.futures as _cf

                from .crew_analysis import USMomentumShortTermCrew as _USC
                crew = _USC(sym, scan_data=sd)
                with _cf.ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(crew.run_analysis)
                    try:
                        result = fut.result(timeout=180)
                    except _cf.TimeoutError:
                        result = '## Timeout\n\nกรุณาลองใหม่อีกครั้ง'
                _c.set(ckey, {'state': 'done', 'result': result}, timeout=900)
            except Exception as exc:
                from django.core.cache import cache as _c2
                _c2.set(ckey, {'state': 'done', 'result': f'## Error\n\n{exc}'}, timeout=60)

        _th.Thread(target=_run, args=(cache_key, symbol, scan_data), daemon=True).start()

    return render(request, 'stocks/us_momentum_crew_page.html', {
        'symbol':    symbol,
        'scan_data': scan_data,
    })


# ======================================================================
# US PRECISION MOMENTUM SCANNER - Nasdaq & S&P 500
# ======================================================================

@login_required
def us_precision_scanner(request):
    """
    US Precision Momentum Scanner - Nasdaq & S&P 500
    - market='US' filter on all DB queries
    - Background scanning to prevent timeouts
    """
    from django.utils import timezone as tz
    from yahooquery import Ticker as YQTicker

    from .models import PrecisionScanCandidate
    from .utils import analyze_momentum_technical_v2

    # AJAX status polling
    if request.GET.get('scan_status') == '1':
        from django.core.cache import cache as _cp
        from django.http import JsonResponse as _JR
        _key = f'us_precision_scan_{request.user.id}'
        _st = _cp.get(_key, {'state': 'idle'})
        if _st.get('state') == 'done':
            _cp.delete(_key)
        return _JR(_st)

    scan_symbols = list(
        ScannableSymbol.objects.filter(is_active=True, market='US').values_list('symbol', flat=True)
    )
    # If symbols are missing or deactivated (e.g. by Thai refresh bug), re-seed them
    if len(scan_symbols) < 100:
        _seed_us_symbols()
        scan_symbols = list(
            ScannableSymbol.objects.filter(is_active=True, market='US').values_list('symbol', flat=True)
        )

    if request.method == "POST" or request.GET.get('scan') == 'true':
        import threading

        from django.core.cache import cache as _cache_bg
        user_id = request.user.id
        cache_key = f'us_precision_scan_{user_id}'

        # cache.add() เป็น atomic lock - กัน double-submit เปิด background thread ซ้อนกัน
        _init_status = {'state': 'running', 'progress': 0, 'total': 0, 'phase': 'เตรียมข้อมูล…'}
        if not _cache_bg.add(cache_key, _init_status, timeout=1200):
            _cur = _cache_bg.get(cache_key) or {}
            if _cur.get('state') == 'running':
                return redirect('stocks:us_precision_scanner')
            # key ค้างจากรอบก่อน (done/idle) - เขียนทับแล้วสแกนต่อ
            _cache_bg.set(cache_key, _init_status, timeout=1200)

        def _run_us_scan_bg(uid, ckey, sym_list):
            try:
                import django
                django.setup()
                import concurrent.futures
                from datetime import datetime as _dt
                from datetime import time as _dtime
                from datetime import timedelta as _td

                import pandas as pd
                import pandas_ta as ta
                import pytz as _pytz
                import requests
                import yfinance as yf
                from django.contrib.auth import get_user_model
                from django.core.cache import cache as _cache_inner

                # Create a session with timeout to prevent hanging
                _session = requests.Session()
                _session.mount("https://", requests.adapters.HTTPAdapter(max_retries=2))
                _session.mount("http://", requests.adapters.HTTPAdapter(max_retries=2))
                # Patch yfinance to use this session with a timeout if needed, 
                # but usually passing session to Ticker is enough.
                
                User = get_user_model()
                user = User.objects.get(pk=uid)
                scan_run_time = tz.now()

                _ny_tz = _pytz.timezone('America/New_York')
                _now_ny = _dt.now(_ny_tz)
                
                # yfinance end date is exclusive. To include today's data, we must set end to tomorrow.
                scan_end_date  = _now_ny.date()
                scan_end_str   = (scan_end_date + _td(days=1)).strftime('%Y-%m-%d')
                scan_start_str = (scan_end_date - _td(days=600)).strftime('%Y-%m-%d')
                spy_start_str  = (scan_end_date - _td(days=600)).strftime('%Y-%m-%d')  # ใช้เท่ากับ stock เพื่อ RS เทียบกันถูกต้อง

                _cache_inner.set(ckey, {'state': 'running', 'progress': 0, 'total': len(sym_list), 'phase': 'Benchmarks…'}, timeout=1200)

                # Previous symbols
                prev_run = PrecisionScanCandidate.objects.filter(user=user, market='US').order_by('-scan_run').values_list('scan_run', flat=True).distinct().first()
                prev_symbols = set(PrecisionScanCandidate.objects.filter(user=user, market='US', scan_run=prev_run).values_list('symbol', flat=True)) if prev_run else set()

                # SPY
                import logging as _lg; _us_log = _lg.getLogger('stocks.us_scan')
                spy_1m = spy_3m = 0.0
                try:
                    spy_df = yf.download("SPY", start=spy_start_str, end=scan_end_str, interval="1d", progress=False)
                    if spy_df is not None and not spy_df.empty:
                        if isinstance(spy_df.columns, pd.MultiIndex): spy_df.columns = spy_df.columns.droplevel(1)
                        c = spy_df['Close'].dropna()
                        if len(c) >= 66:
                            spy_1m = float((c.iloc[-1] - c.iloc[-22])/c.iloc[-22]*100)
                            spy_3m = float((c.iloc[-1] - c.iloc[-66])/c.iloc[-66]*100)
                except Exception as e:
                    _us_log.warning(f"[US Scan] SPY fetch failed: {e}")

                # RS Rating (Bulk Fetch for speed)
                total_syms = len(sym_list)
                _cache_inner.set(ckey, {'state': 'running', 'progress': 0, 'total': total_syms, 'phase': 'Fetching RS Data (Bulk)…'}, timeout=1200)
                rs_returns_all = {}
                try:
                    from yahooquery import Ticker as _TQ
                    chunk_size = 80
                    for i in range(0, len(sym_list), chunk_size):
                        chunk = sym_list[i : i + chunk_size]
                        _cache_inner.set(ckey, {'state': 'running', 'progress': 5 + int((i/total_syms)*15), 'total': total_syms, 'phase': f'Fetching RS Data ({i//chunk_size + 1})…'}, timeout=900)
                        try:
                            tq = _TQ(chunk)
                            tq_hist = tq.history(start=scan_start_str, end=scan_end_str, interval="1d")
                            if tq_hist is not None and not tq_hist.empty:
                                if isinstance(tq_hist.index, pd.MultiIndex):
                                    for symbol in chunk:
                                        try:
                                            if symbol in tq_hist.index.get_level_values(0):
                                                _close = tq_hist.loc[symbol]['adjclose'].dropna()
                                                if len(_close) >= 66:
                                                    ret = float((_close.iloc[-1] - _close.iloc[-66]) / abs(_close.iloc[-66]) * 100)
                                                    rs_returns_all[symbol] = ret
                                        except Exception: continue
                        except Exception as e:
                            _us_log.warning(f"[US Scan] RS chunk error: {e}")
                except Exception as e:
                    _us_log.error(f"[US Scan] Bulk RS fetch failed: {e}")

                # FAILSAFE: If results are empty or too small, force evaluation of a subset
                if len(rs_returns_all) < 10:
                    for s in sym_list[:100]:
                        if s not in rs_returns_all: rs_returns_all[s] = 0.0

                rs_map = {}
                if rs_returns_all:
                    ser = pd.Series(rs_returns_all)
                    rs_map = (ser.rank(pct=True)*99).clip(0,99).astype(int).to_dict()

                # Main Scan
                results_to_process = [s for s in sym_list if rs_map.get(s, 0) >= 60]
                _cache_inner.set(ckey, {'state': 'running', 'progress': 0, 'total': len(results_to_process), 'phase': 'Technical Scan…'}, timeout=1200)
                
                results = []
                def _scan_one(symbol):
                    try:
                        rs_v = rs_map.get(symbol, 0)
                        if rs_v < 60: return None

                        try:
                            ticker_obj = yf.Ticker(symbol)
                            df = ticker_obj.history(start=scan_start_str, end=scan_end_str, interval="1d")

                            if df is None or df.empty:
                                try:
                                    yq = YQTicker(symbol)
                                    df = yq.history(start=scan_start_str, end=scan_end_str, interval="1d")
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
                        except Exception:
                            df = None

                        if df is None or df.empty: return None
                        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
                        df = df.dropna(subset=['Close','High'])
                        if len(df) < 200: return None
                        
                        av20 = float(df['Volume'].tail(20).mean())
                        if av20 < 500_000: return None  # ลด threshold จาก 1M → 500K รับ mid-cap growth
                        
                        current_p = float(df['Close'].iloc[-1])

                        # ====== Early Accumulation (Pre-Breakout Volume Surge & Tightness) ======
                        early_accumulation = False
                        try:
                            if len(df) >= 20:
                                # 1. Check Volume Surge (2.5x)
                                for i in range(-5, 0):
                                    vol_i = float(df['Volume'].iloc[i])
                                    close_i = float(df['Close'].iloc[i])
                                    open_i = float(df['Open'].iloc[i])
                                    if close_i > open_i and vol_i >= (av20 * 2.5):
                                        early_accumulation = True
                                        break
                                
                                # 2. Check Price Tightness (SD < 2.5%) -> VCP / Coiling
                                if not early_accumulation:
                                    std_5 = float(df['Close'].tail(5).std())
                                    tightness = (std_5 / current_p * 100) if current_p > 0 else 99
                                    if tightness <= 2.5:
                                        early_accumulation = True
                                        
                                # 3. Check Volume Dry Up (VDU)
                                if not early_accumulation:
                                    vol_3d_avg = float(df['Volume'].tail(3).mean())
                                    if vol_3d_avg < av20 * 0.5:
                                        early_accumulation = True
                        except Exception:
                            pass

                        rs_v = rs_map.get(symbol, 0)
                        if rs_v < 60 and not early_accumulation: return None
                        
                        # Indicators
                        df['EMA200'] = ta.ema(df['Close'], length=200)
                        df['EMA50']  = ta.ema(df['Close'], length=50)
                        df['RSI']    = ta.rsi(df['Close'], length=14)
                        adx_d = ta.adx(df['High'], df['Low'], df['Close'], length=14)
                        if adx_d is not None and not adx_d.empty: df = pd.concat([df, adx_d], axis=1)
                        df['MFI'] = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
                        
                        year_h = float(df['High'].tail(252).max())
                        
                        if current_p < year_h * 0.65 and not early_accumulation: return None
                        adx_v = float(df['ADX_14'].iloc[-1]) if 'ADX_14' in df.columns and pd.notna(df['ADX_14'].iloc[-1]) else 0
                        if adx_v < 15 and not early_accumulation: return None

                        tech = analyze_momentum_technical_v2(df)

                        mfi_val = float(df['MFI'].iloc[-1]) if 'MFI' in df.columns and pd.notna(df['MFI'].iloc[-1]) else 0

                        # MACD (12,26,9)
                        macd_hist_val = None
                        macd_cross_val = False
                        try:
                            macd_df = ta.macd(df['Close'], fast=12, slow=26, signal=9)
                            if macd_df is not None and not macd_df.empty:
                                hist_col = [c for c in macd_df.columns if 'h' in c.lower() or 'hist' in c.lower()]
                                macd_col = [c for c in macd_df.columns if c.lower().startswith('macd_')]
                                sig_col  = [c for c in macd_df.columns if 'macds' in c.lower() or 'signal' in c.lower()]
                                if hist_col: macd_hist_val = float(macd_df[hist_col[0]].iloc[-1]) if pd.notna(macd_df[hist_col[0]].iloc[-1]) else None
                                if macd_col and sig_col:
                                    m_ser = macd_df[macd_col[0]].dropna()
                                    s_ser = macd_df[sig_col[0]].dropna()
                                    if len(m_ser) >= 4 and len(s_ser) >= 4:
                                        for i in range(-3, 0):
                                            if m_ser.iloc[i-1] <= s_ser.iloc[i-1] and m_ser.iloc[i] > s_ser.iloc[i]:
                                                macd_cross_val = True; break
                        except: pass

                        # Bollinger Bands Squeeze
                        bb_squeeze_flag = False
                        try:
                            bb_df = ta.bbands(df['Close'], length=20, std=2)
                            if bb_df is not None and not bb_df.empty:
                                upper_col = [c for c in bb_df.columns if 'BBU' in c or 'upper' in c.lower()]
                                lower_col = [c for c in bb_df.columns if 'BBL' in c or 'lower' in c.lower()]
                                mid_col   = [c for c in bb_df.columns if 'BBM' in c or 'mid' in c.lower()]
                                if upper_col and lower_col and mid_col:
                                    bbu = bb_df[upper_col[0]].dropna()
                                    bbl = bb_df[lower_col[0]].dropna()
                                    bbm = bb_df[mid_col[0]].dropna()
                                    if len(bbu) >= 20:
                                        bw = (bbu - bbl) / bbm
                                        pct20 = bw.quantile(0.20)
                                        if float(bw.iloc[-1]) <= float(pct20): bb_squeeze_flag = True
                        except: pass

                        # Stage 2 (Weinstein)
                        stage2_flag = False
                        try:
                            sma150 = ta.sma(df['Close'], length=150)
                            if sma150 is not None:
                                sma150_clean = sma150.dropna()
                                if len(sma150_clean) >= 20:
                                    sma150_cur = float(sma150_clean.iloc[-1])
                                    sma150_4w  = float(sma150_clean.iloc[-20])
                                    stage2_flag = (current_p > sma150_cur) and (sma150_cur > sma150_4w)
                        except: pass

                        # Pocket Pivot
                        pocket_pivot_flag = False
                        try:
                            if len(df) >= 14:
                                closes = df['Close'].values
                                volumes = df['Volume'].values
                                for _i in [-1, -2]:
                                    if float(closes[_i]) <= float(closes[_i - 1]): continue
                                    _start = len(volumes) + _i - 10
                                    _end   = len(volumes) + _i
                                    if _start < 1: continue
                                    _prior_c = closes[_start:_end]
                                    _prior_v = volumes[_start:_end]
                                    _prior_prev_c = closes[_start - 1:_end - 1]
                                    _down_mask = _prior_c < _prior_prev_c
                                    if not _down_mask.any(): continue
                                    _max_down_vol = float(_prior_v[_down_mask].max())
                                    if float(volumes[_i]) > _max_down_vol and _max_down_vol > 0:
                                        pocket_pivot_flag = True; break
                        except: pass

                        # Volume Dry-Up (VDU)
                        vdu_flag = False
                        try:
                            if len(df) >= 4:
                                _vols = df['Volume'].tail(4).values.astype(float)
                                _avg20 = float(df['Volume'].tail(20).mean())
                                _declining = (_vols[-1] < _vols[-2]) and (_vols[-2] < _vols[-3])
                                _quiet     = _vols[-1] < _avg20 * 0.7
                                vdu_flag   = _declining and _quiet
                        except: pass

                        # Ichimoku Score
                        ichimoku_score_val = 0
                        ichimoku_above_kumo = False
                        ichimoku_tk_cross = False
                        ichimoku_kumo_green = False
                        ichimoku_chikou_ok = False
                        try:
                            if len(df) >= 52:
                                _h9 = df['High'].rolling(9).max(); _l9 = df['Low'].rolling(9).min()
                                _h26 = df['High'].rolling(26).max(); _l26 = df['Low'].rolling(26).min()
                                _h52 = df['High'].rolling(52).max(); _l52 = df['Low'].rolling(52).min()
                                _tenkan = (_h9 + _l9) / 2; _kijun = (_h26 + _l26) / 2
                                _span_a = ((_tenkan + _kijun) / 2).shift(26); _span_b = ((_h52 + _l52) / 2).shift(26)
                                _sa_cur = float(_span_a.iloc[-1]); _sb_cur = float(_span_b.iloc[-1])
                                ichimoku_above_kumo = current_p > max(_sa_cur, _sb_cur) > 0
                                for _i in range(-5, 0):
                                    if _tenkan.iloc[_i-1] <= _kijun.iloc[_i-1] and _tenkan.iloc[_i] > _kijun.iloc[_i]:
                                        ichimoku_tk_cross = True; break
                                ichimoku_kumo_green = _sa_cur > _sb_cur > 0
                                ichimoku_chikou_ok = current_p > float(df['Close'].iloc[-27]) if len(df) >= 27 else False
                                ichimoku_score_val = sum([ichimoku_above_kumo, ichimoku_tk_cross, ichimoku_kumo_green, ichimoku_chikou_ok])
                        except: pass

                        # Price Pattern detection
                        try:
                            pattern_result = detect_price_pattern(df)
                            pattern_name = pattern_result['name']
                            pattern_score = pattern_result['score']
                        except:
                            pattern_name = "None"
                            pattern_score = 0

                        return {
                            'symbol': symbol, 'price': round(current_p, 2),
                            'rsi': round(tech['rsi'], 2), 'adx': round(adx_v, 2), 'mfi': round(mfi_val, 2),
                            'rvol': round(tech['rvol'], 2), 'technical_score': int(tech['score']),
                            'avg_volume_20d': round(av20, 0), 'rvol_bullish': tech['rvol_bullish'],
                            'erc_volume_confirmed': tech.get('erc_volume_confirmed', False),
                            'zone_target_src': tech.get('zone_target_source', '52w'),
                            'entry_strat': tech['sd_zone']['type'] if tech['sd_zone'] else '',
                            'dz_start': tech['sd_zone']['start'] if tech['sd_zone'] else None,
                            'dz_end': tech['sd_zone']['end'] if tech['sd_zone'] else None,
                            'sz_start': tech['sd_zone']['target'] if tech['sd_zone'] else None,
                            'sz_end': (tech['sd_zone']['target']*1.02) if tech['sd_zone'] else None,
                            'sl_price': tech['sd_zone']['stop_loss'] if tech['sd_zone'] else None,
                            'rr_val': tech['sd_zone']['rr_ratio'] if tech['sd_zone'] else None,
                            'year_high': round(year_h, 2), 'upside_to_high': round((year_h-current_p)/current_p*100, 2),
                            'prox_val': round(0.0 if current_p <= (tech['sd_zone']['start'] or 0) else ((current_p - tech['sd_zone']['start']) / tech['sd_zone']['start']) * 100, 2) if tech['sd_zone'] else 999,
                            'rel_1m': round(float((df['Close'].iloc[-1]-df['Close'].iloc[-22])/df['Close'].iloc[-22]*100) - spy_1m, 2) if len(df)>=22 else 0,
                            'rel_3m': round(float((df['Close'].iloc[-1]-df['Close'].iloc[-66])/df['Close'].iloc[-66]*100) - spy_3m, 2) if len(df)>=66 else 0,
                            'macd_histogram': round(macd_hist_val, 4) if macd_hist_val is not None else None,
                            'macd_crossover': macd_cross_val, 'bb_squeeze': bb_squeeze_flag, 'stage2': stage2_flag, 'rs_rating': rs_v,
                            'ema20_aligned': tech.get('ema20_aligned', False), 'ema20_rising': tech.get('ema20_rising', False),
                            'ema20_slope': tech.get('ema20_slope', 0.0),
                            'hh_hl_structure': tech.get('hh_hl_structure', False),
                            'pocket_pivot': pocket_pivot_flag,
                            'vdu_near_zone': vdu_flag,
                            'cmf': tech.get('cmf', 0.0),
                            'is_52w_breakout': tech.get('is_52w_breakout', False),
                            'volume_surge': tech.get('volume_surge', 1.0),
                            'is_volume_surge': tech.get('is_volume_surge', False),
                            'ichimoku_above_kumo': ichimoku_above_kumo, 'ichimoku_tk_cross': ichimoku_tk_cross,
                            'ichimoku_kumo_green': ichimoku_kumo_green, 'ichimoku_chikou_ok': ichimoku_chikou_ok,
                            'ichimoku_score': ichimoku_score_val,
                            'price_pattern': pattern_name, 'price_pattern_score': pattern_score,
                            'vcp': detect_vcp_pattern(df),
                            'launcher_score': tech.get('launcher_score', 0),
                            'turtle_dist_pct': tech.get('turtle_dist_pct', 99.0),
                            'is_explosive': tech.get('is_explosive', False),
                            'tightness_idx': tech.get('tightness_idx', 99.0),
                            # ====== John Ehlers Indicators (v12) ======
                            'ehlers_supersmoother': tech.get('ehlers_supersmoother', current_p),
                            'ehlers_laguerre_rsi': tech.get('ehlers_laguerre_rsi', 0.5),
                            'ehlers_fisher': tech.get('ehlers_fisher', 0.0),
                            'ehlers_fisher_trigger': tech.get('ehlers_fisher_trigger', 0.0),
                            'ehlers_itl_daily': tech.get('ehlers_itl_daily', current_p),
                            'ehlers_itl_weekly': tech.get('ehlers_itl_weekly', current_p),
                            'ehlers_itl_bullish': tech.get('ehlers_itl_bullish', False),
                        }
                    except Exception as e:
                        import logging
                        logging.getLogger('stocks').exception(f"[US Precision] Error scanning {symbol}: {e}")
                        return None

                count = 0
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:  # ลดจาก 10→5 ป้องกัน rate limit
                    futs = {ex.submit(_scan_one, s): s for s in results_to_process}
                    for f in concurrent.futures.as_completed(futs):
                        try:
                            r = f.result()
                            if r: results.append(r)
                        except: pass
                        count += 1
                        if count % 10 == 0 or count == len(results_to_process):
                            _cache_inner.set(ckey, {'state': 'running', 'progress': count, 'total': len(results_to_process), 'phase': f'Technical Scan ({count}/{len(results_to_process)})…'}, timeout=1200)

                if results:
                    _cache_inner.set(ckey, {'state': 'running', 'progress': count, 'total': len(results_to_process), 'phase': f'Enriching Fundamentals ({len(results)} matches)…'}, timeout=1200)
                    matched = [r['symbol'] for r in results]
                    fund = {}
                    try:
                        yqa = YQTicker(matched)
                        mods = yqa.get_modules('financialData summaryProfile')
                        for k, d in mods.items():
                            if isinstance(d, dict):
                                p = d.get('summaryProfile', {}); fd = d.get('financialData', {})
                                fund[k.upper()] = {
                                    'sector': p.get('sector') or 'Unknown',
                                    'eps': float(fd.get('earningsQuarterlyGrowth',0) or 0)*100,
                                    'rev': float(fd.get('revenueGrowth',0) or 0)*100
                                }
                    except: pass
                    
                    bulk = []
                    for r in results:
                        f = fund.get(r['symbol'].upper(), {'sector':'N/A','eps':0,'rev':0})
                        bulk.append(PrecisionScanCandidate(
                            user=user, market='US', scan_run=scan_run_time, symbol=r['symbol'], symbol_bk=r['symbol'],
                            sector=f['sector'], price=r['price'], rsi=r['rsi'], adx=r['adx'], mfi=r['mfi'], rvol=r['rvol'],
                            eps_growth=round(f['eps'], 2), rev_growth=round(f['rev'], 2),
                            technical_score=r['technical_score'], rs_rating=r['rs_rating'],
                            avg_volume_20d=r['avg_volume_20d'], rvol_bullish=r['rvol_bullish'],
                            erc_volume_confirmed=r['erc_volume_confirmed'], zone_target_source=r['zone_target_src'],
                            is_new_entry=(r['symbol'] not in prev_symbols), entry_strategy=r['entry_strat'],
                            demand_zone_start=r['dz_start'], demand_zone_end=r['dz_end'],
                            supply_zone_start=r['sz_start'], supply_zone_end=r['sz_end'],
                            stop_loss=r['sl_price'], risk_reward_ratio=r['rr_val'],
                            year_high=r['year_high'], upside_to_high=r['upside_to_high'],
                            zone_proximity=r['prox_val'], rel_momentum_1m=r['rel_1m'], rel_momentum_3m=r['rel_3m'],
                            price_pattern=r.get('price_pattern', 'None'),
                            price_pattern_score=r.get('price_pattern_score', 0),
                            macd_histogram=r.get('macd_histogram'),
                            macd_crossover=r['macd_crossover'], bb_squeeze=r['bb_squeeze'],
                            ema20_aligned=r['ema20_aligned'], ema20_slope=r.get('ema20_slope', 0.0), ema20_rising=r['ema20_rising'],
                            hh_hl_structure=r['hh_hl_structure'], stage2=r['stage2'],
                            pocket_pivot=r.get('pocket_pivot', False),
                            vdu_near_zone=r.get('vdu_near_zone', False),
                            cmf=r.get('cmf', None),
                            is_52w_breakout=r.get('is_52w_breakout', False),
                            volume_surge=r.get('volume_surge', 1.0),
                            is_volume_surge=r.get('is_volume_surge', False),
                            ichimoku_above_kumo=r.get('ichimoku_above_kumo', False),
                            ichimoku_tk_cross=r.get('ichimoku_tk_cross', False),
                            ichimoku_kumo_green=r.get('ichimoku_kumo_green', False),
                            ichimoku_chikou_ok=r.get('ichimoku_chikou_ok', False),
                            ichimoku_score=r.get('ichimoku_score', 0),
                            vcp_setup=r.get('vcp', {}).get('setup', False),
                            vcp_contractions=r.get('vcp', {}).get('contractions', 0),
                            vcp_tightness=r.get('vcp', {}).get('tightness', 0.0),
                            vcp_vdu=r.get('vcp', {}).get('vdu_confirmed', False),
                            launcher_score=r.get('launcher_score', 0),
                            turtle_dist_pct=r.get('turtle_dist_pct', 99.0),
                            is_explosive=r.get('is_explosive', False),
                            tightness_idx=r.get('tightness_idx', 99.0),
                            # Ehlers v12
                            ehlers_supersmoother=r.get('ehlers_supersmoother', None),
                            ehlers_laguerre_rsi=r.get('ehlers_laguerre_rsi', None),
                            ehlers_fisher=r.get('ehlers_fisher', None),
                            ehlers_fisher_trigger=r.get('ehlers_fisher_trigger', None),
                            ehlers_itl_daily=r.get('ehlers_itl_daily', None),
                            ehlers_itl_weekly=r.get('ehlers_itl_weekly', None),
                            ehlers_itl_bullish=r.get('ehlers_itl_bullish', False),
                        ))
                    PrecisionScanCandidate.objects.bulk_create(bulk)
                    
                    runs = list(PrecisionScanCandidate.objects.filter(user=user, market='US').values_list('scan_run', flat=True).order_by('-scan_run').distinct())
                    if len(runs) > 3: PrecisionScanCandidate.objects.filter(user=user, market='US', scan_run__in=runs[3:]).delete()

                _cache_inner.set(ckey, {'state': 'done'}, timeout=300)
            except Exception as e:
                import traceback
                with open('us_scan_error.txt', 'w') as err_file:
                    err_file.write(traceback.format_exc())
                _cache_inner.set(ckey, {'state': 'done', 'error': str(e)}, timeout=300)

        t = threading.Thread(target=_run_us_scan_bg, args=(user_id, cache_key, scan_symbols), daemon=True)
        t.start()
        return redirect('stocks:us_precision_scanner')

    # Selection & Rendering
    sort_by = request.GET.get('sort', 'score')
    valid_sorts = {
        'symbol':'symbol','score':'-technical_score','price':'-price',
        'rsi':'-rsi','rvol':'-rvol','adx':'-adx','prox':'zone_proximity','rs':'-rs_rating',
        'launcher': '-launcher_score',
        'cmf': '-cmf',
    }
    order = valid_sorts.get(sort_by, '-technical_score')
    
    all_runs = list(PrecisionScanCandidate.objects.filter(user=request.user, market='US').values_list('scan_run', flat=True).order_by('-scan_run').distinct())
    try: run_idx = int(request.GET.get('run_idx', 0))
    except: run_idx = 0
    run_idx = max(0, min(run_idx, len(all_runs)-1)) if all_runs else 0
    
    candidates = []
    scanned_at = None
    top5_buy = []
    top5_qualified = []
    top_sectors = []
    scan_insights = []

    if all_runs:
        sel_run = all_runs[run_idx]
        candidates = list(PrecisionScanCandidate.objects.filter(user=request.user, market='US', scan_run=sel_run).order_by(order))
        scanned_at = sel_run
        
        # Live prices
        from datetime import datetime as _ldt
        from datetime import time as _ldtime

        import pytz as _lpytz
        _lny = _lpytz.timezone('America/New_York')
        _lnow = _ldt.now(_lny)
        _lt = _lnow.time()
        _lmarket_open = _lnow.weekday()<5 and _ldtime(9,30)<=_lt<=_ldtime(16,0)
        
        lp_map = {}
        lpc_map = {}
        if candidates:
            try:
                # แคชผล fetch ไว้ - กันยิง yfinance เท่าจำนวนหุ้นทุกครั้งที่ refresh หน้า
                # ตลาดเปิด: 60s (ราคาขยับ), ตลาดปิด: 10 นาที (ราคา close ไม่เปลี่ยน)
                from django.core.cache import cache as _lp_cache
                _lp_key = f'precision_live_us_{request.user.id}_{run_idx}'
                _lp_cached = _lp_cache.get(_lp_key)
                if _lp_cached:
                    if isinstance(_lp_cached, tuple) and len(_lp_cached) == 2:
                        lp_map, lpc_map = _lp_cached
                    elif isinstance(_lp_cached, dict):
                        lp_map = _lp_cached
                        lpc_map = {}
                    else:
                        lp_map, lpc_map = {}, {}
                else:
                    import concurrent.futures as lcf
                    def _glp(s):
                        try:
                            fi = yf.Ticker(s).fast_info
                            p = getattr(fi, 'last_price', None)
                            pc = getattr(fi, 'regular_market_previous_close', getattr(fi, 'previous_close', None))
                            return s, (float(p) if p else None), (float(pc) if pc else None)
                        except: return s, None, None
                    with lcf.ThreadPoolExecutor(max_workers=10) as lex:
                        for s, p, pc in lex.map(_glp, [c.symbol for c in candidates]):
                            if p: lp_map[s] = p
                            if pc: lpc_map[s] = pc
                    if lp_map:
                        _lp_cache.set(_lp_key, (lp_map, lpc_map), 60 if _lmarket_open else 600)
            except: pass
        
        for c in candidates:
            lp = lp_map.get(c.symbol)
            pc = lpc_map.get(c.symbol) or c.price
            c.live_price = lp; c.is_live = _lmarket_open and lp is not None
            if lp and c.demand_zone_start: c.live_zone_prox = 0.0 if lp <= c.demand_zone_start else round((lp-c.demand_zone_start)/c.demand_zone_start*100, 1)
            if lp and pc and float(pc) > 0: c.live_change_pct = round((lp-float(pc))/float(pc)*100, 2)
            else: c.live_change_pct = None
            
            sigs = _compute_signals(c)
            c.buy_score = sigs['buy_score']; c.sell_score = sigs['sell_score']; c.exit_signal = sigs['exit_signal']
            c.reversal_score = sigs['reversal_score']
            c.reversal_alert = sigs['reversal_alert']
            c.reversal_color = sigs['reversal_color']

            # Reasons logic
            reasons = []
            if c.demand_zone_start and c.demand_zone_end and c.price <= c.demand_zone_start and c.price >= c.demand_zone_end: reasons.append("In Entry Zone")
            elif (c.zone_proximity or 999) <= 10: reasons.append(f"Near Zone {c.zone_proximity:.0f}%")
            if c.rvol_bullish and c.rvol >= 1.0: reasons.append(f"RVOL {c.rvol:.1f}x Bull")
            if (c.risk_reward_ratio or 0) >= 2: reasons.append(f"RR 1:{c.risk_reward_ratio:.1f} Good")
            if c.adx >= 25: reasons.append(f"ADX {c.adx:.0f} Trendy")
            if c.rs_rating >= 85: reasons.insert(0, f"RS {c.rs_rating} Leader")
            c.top_reasons = reasons[:4]

        # Top 5 Buy
        top5_buy = sorted([c for c in candidates if c.buy_score >= 50], key=lambda x: x.buy_score, reverse=True)[:5]
        # Top 5 Qualified
        top5_qualified = sorted([c for c in candidates if c.buy_score >= 65 and (c.risk_reward_ratio or 0) >= 1.5], key=lambda x: x.buy_score, reverse=True)[:5]
        
        # Sectors
        sec_counts = {}
        for c in candidates:
            if c.buy_score >= 65:
                s = c.sector or 'Unknown'
                sec_counts[s] = sec_counts.get(s, 0) + 1
        top_sectors = sorted([{'name': k, 'count': v} for k, v in sec_counts.items()], key=lambda x: x['count'], reverse=True)[:5]

        # Insights
        if top5_qualified:
            b = top5_qualified[0]
            scan_insights.append({'icon': '🏆', 'title': f'Best Setup: {b.symbol}', 'desc': f'RS {b.rs_rating}, RR 1:{b.risk_reward_ratio or 0:.1f}. Strong technical structure in entry zone.'})
        elif top5_buy:
            scan_insights.append({'icon': '💡', 'title': f'Watchlist: {top5_buy[0].symbol}', 'desc': 'High momentum buy score. Watch for price consolidation.'})

    from .models import ScanWatchlistItem
    watchlist_symbols = set(ScanWatchlistItem.objects.filter(user=request.user).values_list('symbol', flat=True))

    scan_data_date = None
    if scanned_at:
        import pytz as _sddtz
        _ny = _sddtz.timezone('America/New_York')
        _st = scanned_at.astimezone(_ny) if hasattr(scanned_at, 'astimezone') else scanned_at
        from datetime import time as _t
        from datetime import timedelta as _tdd
        _in_mkt = (_st.weekday() < 5 and _t(9, 30) <= _st.time() <= _t(16, 0))
        scan_data_date = (_st.date() - _tdd(days=1)) if _in_mkt else _st.date()

    import json as _scan_json
    def _ser_c_us(c):
        return {
            "symbol": c.symbol, "price": c.price, "buy_score": c.buy_score, "rs_rating": c.rs_rating,
            "rsi": round(c.rsi, 1), "adx": round(c.adx, 1), "rvol": round(c.rvol, 2),
            "rvol_bullish": c.rvol_bullish, "risk_reward_ratio": c.risk_reward_ratio,
            "sector": c.sector, "exit_signal": c.exit_signal, "top_reasons": getattr(c, 'top_reasons', []),
        }

    ai_scan_json = _scan_json.dumps({
        "scan_date": str(scan_data_date),
        "qualified_stocks": [_ser_c_us(c) for c in top5_qualified],
        "top_buy_stocks": [_ser_c_us(c) for c in top5_buy],
        "total_passed": len(candidates),
        "top_sectors": top_sectors,
    }, ensure_ascii=False, default=str).replace('</script>', '<\\/script>')

    # Fetch latest Cup & Handle and Turtle breakout symbols for US
    from .models import CupHandleCandidate, TurtleScanCandidate, Portfolio as _PortfolioUS
    latest_ch_run = CupHandleCandidate.objects.filter(user=request.user, market='US').values_list('scan_run', flat=True).order_by('-scan_run').first()
    ch_symbols = set(CupHandleCandidate.objects.filter(user=request.user, market='US', scan_run=latest_ch_run).values_list('symbol', flat=True)) if latest_ch_run else set()

    latest_turtle_run = TurtleScanCandidate.objects.filter(user=request.user, market='US').values_list('scan_run', flat=True).order_by('-scan_run').first()
    turtle_symbols = set(TurtleScanCandidate.objects.filter(user=request.user, market='US', scan_run=latest_turtle_run).values_list('symbol', flat=True)) if latest_turtle_run else set()

    # ── Pyramid Alert (US) ─────────────────────────────────────────────
    _port_entry_us = {}
    for p in _PortfolioUS.objects.filter(user=request.user, market='US'):
        ep = float(p.entry_price or 0)
        if ep > 0:
            _port_entry_us[p.symbol.upper()] = ep

    pyramid_ready_us = set()
    for _c in candidates:
        _entry = _port_entry_us.get(_c.symbol.upper(), 0)
        if _entry <= 0:
            continue
        _curr = float(getattr(_c, 'live_price', None) or _c.price or 0)
        if _curr <= 0:
            continue
        _gain = (_curr - _entry) / _entry * 100
        if (
            _gain >= 3.0 and
            getattr(_c, 'exit_signal', '') not in ('EXIT', 'STRONG EXIT') and
            float(getattr(_c, 'volume_surge', 0) or 0) >= 1.5 and
            float(getattr(_c, 'upside_to_tp', 0) or 0) >= 5
        ):
            pyramid_ready_us.add(_c.symbol)

    return render(request, 'stocks/us_precision_scan.html', {
        'title': 'US Precision Momentum Scanner - Nasdaq & S&P 500',
        'candidates': candidates, 'scanned_at': scanned_at, 'current_sort': sort_by,
        'all_runs': all_runs, 'selected_run_idx': run_idx,
        'has_scanned': bool(all_runs), 'top5_buy': top5_buy, 'top5_qualified': top5_qualified,
        'scan_total': len(scan_symbols), 'scan_passed': len(candidates),
        'top_sectors': top_sectors, 'scan_insights': scan_insights,
        'scan_data_date': scan_data_date, 'watchlist_symbols': watchlist_symbols,
        'ai_scan_json': ai_scan_json,
        'cup_handle_symbols': ch_symbols,
        'turtle_symbols': turtle_symbols,
        'pyramid_ready': pyramid_ready_us,
    })


# ======================================================================
# US PRECISION SCAN AI ANALYSIS
# ======================================================================


@login_required
def us_value_scanner(request):
    """
    US Value Stock Scanner - fundamental quality + cheap valuation.
    P/E < 25 across all sectors (Financials, Energy, Healthcare, Tech, etc.)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    import pandas_ta as ta

    run_scan = request.GET.get('scan') == 'true'
    current_sort = request.GET.get('sort', 'score')

    sort_map = {
        'score': '-total_score', 'val': '-valuation_score',
        'qual': '-quality_score', 'pe': 'pe_ratio',
        'pb': 'pb_ratio',        'div': '-dividend_yield',
        'roe': '-roe',           'symbol': 'symbol',
        'price': '-price',       'rsi': 'rsi',
    }

    # ── Load from DB (display mode) ───────────────────────
    if not run_scan:
        all_runs = list(
            ValueScanCandidate.objects
            .filter(user=request.user)
            .values_list('scan_run', flat=True)
            .order_by('-scan_run').distinct()
        )
        has_scanned = bool(all_runs)
        candidates = []
        scanned_at = None

        try:
            run_idx = int(request.GET.get('run_idx', 0))
        except (ValueError, TypeError):
            run_idx = 0
        run_idx = max(0, min(run_idx, len(all_runs) - 1)) if all_runs else 0

        if has_scanned:
            selected_run = all_runs[run_idx]
            scanned_at   = selected_run
            qs = (ValueScanCandidate.objects
                  .filter(user=request.user, scan_run=selected_run)
                  .order_by(sort_map.get(current_sort, '-total_score')))
            candidates = list(qs)

            # Live prices (fast_info)
            live_prices = {}
            try:
                import concurrent.futures as _lcf
                def _get_live_val(sym):
                    try:
                        fi = yf.Ticker(sym).fast_info
                        p = getattr(fi, 'last_price', None)
                        return sym, round(float(p), 2) if p else None
                    except Exception:
                        return sym, None
                with _lcf.ThreadPoolExecutor(max_workers=12) as ex:
                    for sym, p in ex.map(_get_live_val, [c.symbol for c in candidates]):
                        if p:
                            live_prices[sym] = p
            except Exception:
                pass
            for c in candidates:
                c.live_price = live_prices.get(c.symbol)

        return render(request, 'stocks/us_value_scan.html', {
            'candidates':       candidates,
            'has_scanned':      has_scanned,
            'scanned_at':       scanned_at,
            'all_runs':         all_runs,
            'selected_run_idx': run_idx,
            'current_sort':     current_sort,
        })

    # ── RUN SCAN ──────────────────────────────────────────
    symbols = _seed_value_symbols()
    scan_time = _dt.now(_tz.utc)
    results = []

    def _process_value_symbol(sym):
        try:
            ticker = yf.Ticker(sym)
            info   = ticker.info or {}

            price = info.get('regularMarketPrice') or info.get('currentPrice') or 0
            if not price:
                fi = getattr(ticker, 'fast_info', None)
                price = getattr(fi, 'last_price', 0) or 0
            if not price or price <= 0:
                return None

            # P/E filter - skip pure growth stocks (P/E > 30)
            pe = info.get('trailingPE') or info.get('forwardPE')
            if pe and pe > 30:
                return None

            # Market cap filter - at least $2B (mid/large cap)
            mkt_cap = (info.get('marketCap') or 0) / 1e9
            if mkt_cap < 2:
                return None

            # Download 1-year price history for technical indicators
            df = yf.download(sym, period='1y', progress=False, auto_adjust=True)
            if df is None or len(df) < 50:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)

            val_score, qual_score, price_score, total = _score_value_candidate(info, df)

            # Minimum quality threshold
            if total < 20:
                return None

            # Compute additional price stats
            close = df['Close']
            rsi14  = ta.rsi(close, length=14)
            rsi_val = float(rsi14.dropna().iloc[-1]) if rsi14 is not None and not rsi14.dropna().empty else 50
            y_high = float(df['High'].max())
            y_low  = float(df['Low'].min())
            pct_from_high = ((y_high - float(close.iloc[-1])) / y_high * 100) if y_high > 0 else 0

            ema200 = ta.ema(close, length=200)
            above_ema200 = False
            if ema200 is not None and not ema200.dropna().empty:
                above_ema200 = float(close.iloc[-1]) > float(ema200.dropna().iloc[-1])

            div = (info.get('dividendYield') or 0) * 100
            roe = (info.get('returnOnEquity') or 0) * 100
            margin = (info.get('profitMargins') or 0) * 100
            de_raw = info.get('debtToEquity')
            de  = (de_raw / 100) if de_raw is not None else None
            fcf_raw = info.get('freeCashflow') or 0
            fcf_yield = (fcf_raw / (info.get('marketCap') or 1)) * 100 if fcf_raw and mkt_cap > 0 else 0

            return {
                'symbol':       sym,
                'name':         info.get('longName') or info.get('shortName') or sym,
                'sector':       info.get('sector') or 'Unknown',
                'price':        round(float(price), 2),
                'market_cap':   round(mkt_cap, 2),
                'pe_ratio':     round(float(pe), 2) if pe and pe > 0 else None,
                'forward_pe':   round(float(info.get('forwardPE') or 0), 2) or None,
                'pb_ratio':     round(float(info.get('priceToBook') or 0), 2) or None,
                'peg_ratio':    round(float(info.get('pegRatio') or 0), 2) or None,
                'ps_ratio':     round(float(info.get('priceToSalesTrailing12Months') or 0), 2) or None,
                'dividend_yield': round(div, 2),
                'roe':          round(roe, 1) if roe else None,
                'profit_margin': round(margin, 1) if margin else None,
                'debt_equity':  round(de, 2) if de is not None else None,
                'current_ratio': round(float(info.get('currentRatio') or 0), 2) or None,
                'revenue_growth': round((info.get('revenueGrowth') or 0) * 100, 1),
                'fcf_yield':    round(fcf_yield, 1),
                'rsi':          round(rsi_val, 1),
                'year_high':    round(y_high, 2),
                'year_low':     round(y_low, 2),
                'pct_from_high': round(pct_from_high, 1),
                'above_ema200': above_ema200,
                'valuation_score':    val_score,
                'quality_score':      qual_score,
                'price_action_score': price_score,
                'total_score':        total,
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_process_value_symbol, sym): sym for sym in symbols}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)

    results.sort(key=lambda x: -x['total_score'])

    # Fetch previous symbols for new-entry flag
    prev_run_q = (ValueScanCandidate.objects
                  .filter(user=request.user)
                  .order_by('-scan_run')
                  .values_list('scan_run', flat=True)
                  .distinct()[:1])
    prev_symbols = set()
    if prev_run_q:
        prev_symbols = set(
            ValueScanCandidate.objects.filter(user=request.user, scan_run=prev_run_q[0])
            .values_list('symbol', flat=True)
        )

    # Save new results FIRST
    to_create = []
    for r in results:
        to_create.append(ValueScanCandidate(
            user=request.user, scan_run=scan_time,
            symbol=r['symbol'], name=r['name'], sector=r['sector'],
            price=r['price'], market_cap=r['market_cap'],
            pe_ratio=r['pe_ratio'], forward_pe=r['forward_pe'],
            pb_ratio=r['pb_ratio'], peg_ratio=r['peg_ratio'],
            ps_ratio=r['ps_ratio'], dividend_yield=r['dividend_yield'],
            roe=r['roe'], profit_margin=r['profit_margin'],
            debt_equity=r['debt_equity'], current_ratio=r['current_ratio'],
            revenue_growth=r['revenue_growth'], fcf_yield=r['fcf_yield'],
            rsi=r['rsi'], year_high=r['year_high'], year_low=r['year_low'],
            pct_from_high=r['pct_from_high'], above_ema200=r['above_ema200'],
            valuation_score=r['valuation_score'],
            quality_score=r['quality_score'],
            price_action_score=r['price_action_score'],
            total_score=r['total_score'],
            is_new_entry=(r['symbol'] not in prev_symbols),
        ))
    ValueScanCandidate.objects.bulk_create(to_create)

    # THEN delete old runs (keep last 3)
    distinct_runs = list(
        ValueScanCandidate.objects
        .filter(user=request.user)
        .values_list('scan_run', flat=True)
        .order_by('-scan_run').distinct()
    )
    if len(distinct_runs) > 3:
        ValueScanCandidate.objects.filter(
            user=request.user, scan_run__in=distinct_runs[3:]
        ).delete()

    return redirect(f'/stocks/value/us-value/?sort={current_sort}&run_idx=0')


# ======================================================================
# US SEPA SCANNER - แยกต่างหากจาก US Precision Scanner
# Model: USSepaCandidate (ไม่แตะ PrecisionScanCandidate เลย)
# ======================================================================

@login_required
def us_sepa_scanner(request):
    """
    US SEPA Scanner - Stage 2 + VCP + RS ≥70 สำหรับหุ้น Nasdaq/S&P500
    ใช้ USSepaCandidate (แยกต่างหากจาก PrecisionScanCandidate อย่างสมบูรณ์)
    """
    import pandas as pd
    import yfinance as yf

    from .models import ScannableSymbol, ScanWatchlistItem, USSepaCandidate

    # AJAX scan status
    if request.GET.get('scan_status') == '1':
        from django.core.cache import cache as _cp
        from django.http import JsonResponse as _JR
        _key = f'us_sepa_scan_{request.user.id}'
        st = _cp.get(_key, {'state': 'idle'})
        if st.get('state') == 'done':
            _cp.delete(_key)
        return _JR(st)

    # ── Trigger background scan ────────────────────────────────────
    if request.method == 'POST' or request.GET.get('scan') == 'true':
        import threading

        from django.core.cache import cache as _cache_bg
        user_id   = request.user.id
        cache_key = f'us_sepa_scan_{user_id}'

        if _cache_bg.get(cache_key, {}).get('state') == 'running':
            return redirect('stocks:us_sepa_scanner')

        sym_list = list(ScannableSymbol.objects.filter(is_active=True, market='US').values_list('symbol', flat=True))
        if len(sym_list) < 100:
            _seed_us_symbols()
            sym_list = list(ScannableSymbol.objects.filter(is_active=True, market='US').values_list('symbol', flat=True))

        _cache_bg.set(cache_key, {'state': 'running', 'progress': 0, 'total': len(sym_list), 'phase': 'Starting US SEPA scan…'}, timeout=1200)

        def _run_bg(uid, ckey, syms):
            try:
                import django; django.setup()
                import concurrent.futures
                from datetime import datetime as _dt
                from datetime import timedelta as _td

                import pandas_ta as ta
                import pytz as _pytz
                from django.contrib.auth import get_user_model
                from django.core.cache import cache as _c
                from django.utils import timezone as tz

                from .models import ScannableSymbol
                from .models import USSepaCandidate as _USC
                from .utils import detect_vcp_pattern

                User = get_user_model()
                user = User.objects.get(pk=uid)
                _ny  = _pytz.timezone('America/New_York')
                now  = _dt.now(_ny)
                end_str   = (now.date() + _td(days=1)).strftime('%Y-%m-%d')
                start_str = (now.date() - _td(days=600)).strftime('%Y-%m-%d')
                scan_run  = tz.now()

                # Keep only 3 latest runs
                old_runs = list(_USC.objects.filter(user=user).values_list('scan_run', flat=True).distinct().order_by('-scan_run')[3:])
                if old_runs:
                    _USC.objects.filter(user=user, scan_run__in=old_runs).delete()

                # ── Step 1: Compute RS Rating ─────────────────────────────
                _c.set(ckey, {'state': 'running', 'progress': 0, 'total': len(syms), 'phase': 'Computing RS Ratings…'}, timeout=1200)

                import logging as _log
                _sepa_log = _log.getLogger('stocks.us_sepa')

                def _fetch_rs(s):
                    try:
                        d = yf.Ticker(s).history(start=start_str, end=end_str, interval='1d')
                        if d is None or d.empty: return s, None
                        if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.droplevel(1)
                        cl = d['Close'].dropna()
                        if len(cl) < 252: return s, None
                        r = float(
                            (cl.iloc[-1]-cl.iloc[-64])/abs(cl.iloc[-64])*0.4 +
                            (cl.iloc[-64]-cl.iloc[-127])/abs(cl.iloc[-127])*0.2 +
                            (cl.iloc[-127]-cl.iloc[-190])/abs(cl.iloc[-190])*0.2 +
                            (cl.iloc[-190]-cl.iloc[-253])/abs(cl.iloc[-253])*0.2
                        ) * 100
                        return s, r
                    except Exception as _e:
                        _sepa_log.debug(f'[US SEPA] RS fetch {s}: {_e}')
                        return s, None

                rs_raw = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                    for s, r in ex.map(_fetch_rs, syms):
                        if r is not None: rs_raw[s] = r
                rs_map = {}
                if rs_raw:
                    ser = pd.Series(rs_raw)
                    rs_map = (ser.rank(pct=True) * 99).clip(0, 99).astype(int).to_dict()

                # ── Step 2: SEPA Technical Scan ───────────────────────────
                _c.set(ckey, {'state': 'running', 'progress': 0, 'total': len(syms), 'phase': 'SEPA Technical Scan…'}, timeout=1200)

                results = []
                def _scan_one(symbol):
                    try:
                        rs_v = rs_map.get(symbol, 0)
                        if rs_v < 60: return None  # pre-filter; display shows ≥70

                        df = yf.Ticker(symbol).history(start=start_str, end=end_str, interval='1d')
                        if df is None or df.empty: return None
                        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
                        df = df.dropna(subset=['Close', 'High', 'Low'])
                        if len(df) < 200: return None

                        # Liquidity: avg daily volume ≥ 500K shares
                        if float(df['Volume'].tail(20).mean()) < 500_000: return None

                        curr = float(df['Close'].iloc[-1])
                        year_h = float(df['High'].tail(252).max())

                        # Stage 2: price > SMA150 AND SMA150 trending up
                        s2 = False
                        try:
                            s150 = ta.sma(df['Close'], 150)
                            if s150 is not None and pd.notna(s150.iloc[-1]) and pd.notna(s150.iloc[-20]):
                                s2 = (curr > float(s150.iloc[-1])) and (float(s150.iloc[-1]) > float(s150.iloc[-20]))
                        except Exception as _e:
                            _sepa_log.debug(f'[US SEPA] SMA150 {symbol}: {_e}')
                        if not s2: return None

                        # ADX
                        adx_v = 0.0
                        try:
                            adx_df = ta.adx(df['High'], df['Low'], df['Close'], 14)
                            if adx_df is not None:
                                col = [c for c in adx_df.columns if c.startswith('ADX_')]
                                if col and pd.notna(adx_df[col[0]].iloc[-1]):
                                    adx_v = float(adx_df[col[0]].iloc[-1])
                        except Exception as _e:
                            _sepa_log.debug(f'[US SEPA] ADX {symbol}: {_e}')

                        # RSI
                        rsi_v = 50.0
                        try:
                            r = ta.rsi(df['Close'], 14)
                            if r is not None and pd.notna(r.iloc[-1]):
                                rsi_v = float(r.iloc[-1])
                        except Exception as _e:
                            _sepa_log.debug(f'[US SEPA] RSI {symbol}: {_e}')

                        # RVOL
                        rvol_v = 1.0
                        try:
                            avg20 = float(df['Volume'].tail(20).mean())
                            if avg20 > 0:
                                rvol_v = round(float(df['Volume'].iloc[-1]) / avg20, 2)
                        except Exception as _e:
                            _sepa_log.debug(f'[US SEPA] RVOL {symbol}: {_e}')

                        # VCP
                        vcp = detect_vcp_pattern(df)

                        # VDU (Volume Dry-Up near zone)
                        vdu_near = False
                        try:
                            rv5 = float(df['Volume'].tail(5).mean())
                            rv50 = float(df['Volume'].tail(50).mean())
                            vdu_near = (rv5 < rv50 * 0.70) and (curr >= year_h * 0.88)
                        except Exception as _e:
                            _sepa_log.debug(f'[US SEPA] VDU {symbol}: {_e}')

                        # Pocket Pivot
                        pp = False
                        try:
                            vols = df['Volume'].values
                            closes = df['Close'].values
                            if len(vols) >= 12:
                                today_vol = vols[-1]
                                today_up  = closes[-1] > closes[-2]
                                dn_vols   = [vols[-(i+2)] for i in range(10) if closes[-(i+2)] < closes[-(i+3)]]
                                if today_up and dn_vols and today_vol > max(dn_vols):
                                    pp = True
                        except Exception as _e:
                            _sepa_log.debug(f'[US SEPA] PocketPivot {symbol}: {_e}')

                        # ── Minervini Earnings Criteria ────────────────────
                        eps_g = 0.0
                        rev_g = 0.0
                        roe_v = 0.0
                        eps_accel = False
                        earnings_pass = False
                        try:
                            _info = yf.Ticker(symbol).info
                            eps_g = float(_info.get('earningsQuarterlyGrowth', 0) or 0) * 100
                            rev_g = float(_info.get('revenueGrowth', 0) or 0) * 100
                            roe_v = float(_info.get('returnOnEquity', 0) or 0) * 100
                            # EPS Acceleration: check trailing EPS vs forward EPS estimate
                            eps_trailing = float(_info.get('trailingEps', 0) or 0)
                            eps_forward  = float(_info.get('forwardEps', 0) or 0)
                            if eps_trailing > 0 and eps_forward > eps_trailing:
                                eps_accel = True
                            earnings_pass = (eps_g >= 25) or (rev_g >= 25)
                        except Exception as _e:
                            _sepa_log.debug(f'[US SEPA] Earnings {symbol}: {_e}')

                        return {
                            'symbol': symbol,
                            'price': round(curr, 2),
                            'stage2': True,
                            'rs_rating': rs_v,
                            'vcp_setup': vcp.get('setup', False),
                            'vcp_contractions': vcp.get('contractions', 0),
                            'vcp_tightness': vcp.get('tightness', 0.0),
                            'vcp_vdu': vcp.get('vdu_confirmed', False),
                            'pocket_pivot': pp,
                            'vdu_near_zone': vdu_near,
                            'adx': round(adx_v, 1),
                            'rsi': round(rsi_v, 1),
                            'rvol': rvol_v,
                            'year_high': round(year_h, 2),
                            'upside_to_high': round((year_h - curr) / curr * 100, 2),
                            'eps_growth': round(eps_g, 1),
                            'rev_growth': round(rev_g, 1),
                            'roe': round(roe_v, 1),
                            'eps_accel': eps_accel,
                            'earnings_pass': earnings_pass,
                        }
                    except Exception as _e:
                        _sepa_log.debug(f'[US SEPA] scan {symbol}: {_e}')
                        return None

                done = 0
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                    futs = {ex.submit(_scan_one, s): s for s in syms}
                    for fut in concurrent.futures.as_completed(futs):
                        done += 1
                        if done % 15 == 0:
                            _c.set(ckey, {'state': 'running', 'progress': done, 'total': len(syms), 'phase': f'Scanning {done}/{len(syms)}…'}, timeout=1200)
                        r = fut.result()
                        if r: results.append(r)

                # ── Step 3: Enrich sector names ───────────────────────────
                if results:
                    _c.set(ckey, {'state': 'running', 'progress': done, 'total': len(syms), 'phase': 'Fetching sector data…'}, timeout=1200)
                    from yahooquery import Ticker as YQT
                    sector_map = {}
                    name_map   = {}
                    try:
                        yqa = YQT([r['symbol'] for r in results])
                        mods = yqa.get_modules('summaryProfile quoteType')
                        for k, d in mods.items():
                            if isinstance(d, dict):
                                sp = d.get('summaryProfile', {})
                                qt = d.get('quoteType', {})
                                sector_map[k.upper()] = sp.get('sector', 'Unknown') or 'Unknown'
                                name_map[k.upper()]   = qt.get('shortName', '') or ''
                    except Exception as _e:
                        _sepa_log.warning(f'[US SEPA] sector fetch error: {_e}')

                    bulk = [_USC(
                        user=user, scan_run=scan_run,
                        symbol=r['symbol'],
                        name=name_map.get(r['symbol'], ''),
                        sector=sector_map.get(r['symbol'], 'Unknown'),
                        price=r['price'],
                        stage2=r['stage2'],
                        rs_rating=r['rs_rating'],
                        vcp_setup=r['vcp_setup'],
                        vcp_contractions=r['vcp_contractions'],
                        vcp_tightness=r['vcp_tightness'],
                        vcp_vdu=r['vcp_vdu'],
                        pocket_pivot=r['pocket_pivot'],
                        vdu_near_zone=r['vdu_near_zone'],
                        adx=r['adx'],
                        rsi=r['rsi'],
                        rvol=r['rvol'],
                        year_high=r['year_high'],
                        upside_to_high=r['upside_to_high'],
                        eps_growth=r.get('eps_growth', 0.0),
                        rev_growth=r.get('rev_growth', 0.0),
                        roe=r.get('roe', 0.0),
                        eps_accel=r.get('eps_accel', False),
                        earnings_pass=r.get('earnings_pass', False),
                    ) for r in results]
                    _USC.objects.bulk_create(bulk)

                _c.set(ckey, {'state': 'done'}, timeout=300)
            except Exception as exc:
                import logging
                logging.getLogger('stocks').exception(f'[US SEPA] bg scan error: {exc}')
                from django.core.cache import cache as _c2
                _c2.set(ckey, {'state': 'done'}, timeout=300)

        import threading as _thr
        _thr.Thread(target=_run_bg, args=(request.user.id, cache_key, sym_list), daemon=True).start()
        return redirect('stocks:us_sepa_scanner')

    # ── Display ────────────────────────────────────────────────────
    all_runs = list(
        USSepaCandidate.objects.filter(user=request.user)
        .values_list('scan_run', flat=True).distinct().order_by('-scan_run')
    )
    try:
        run_idx = max(0, min(int(request.GET.get('run_idx', 0)), len(all_runs) - 1)) if all_runs else 0
    except (ValueError, TypeError):
        run_idx = 0

    candidates  = []
    last_updated = None
    if all_runs:
        run_time    = all_runs[run_idx]
        candidates  = list(USSepaCandidate.objects.filter(user=request.user, scan_run=run_time).order_by('-vcp_setup', '-rs_rating'))
        last_updated = run_time

    # Filters
    vcp_only        = request.GET.get('vcp_only') == '1'
    hide_at_tp      = request.GET.get('hide_at_tp', '1') == '1'
    earnings_filter = request.GET.get('earnings_filter') == '1'

    if vcp_only:
        candidates = [c for c in candidates if c.vcp_setup]
    if hide_at_tp:
        candidates = [c for c in candidates if c.upside_to_high >= 10.0]

    # RS filter: enforce ≥70 (scan saves down to 60 for flexibility)
    candidates = [c for c in candidates if c.rs_rating >= 70]

    # Earnings filter: EPS Growth ≥ 25% หรือ Revenue Growth ≥ 25% (Minervini criteria)
    if earnings_filter:
        candidates = [c for c in candidates if getattr(c, 'earnings_pass', False) or getattr(c, 'eps_growth', 0) >= 25 or getattr(c, 'rev_growth', 0) >= 25]

    # Computed display fields + SEPA Score
    for c in candidates:
        c.dist_from_pivot = round(c.upside_to_high, 1)
        if c.upside_to_high < 5:
            c.tp_status = 'at_tp'
        elif c.upside_to_high < 10:
            c.tp_status = 'near_tp'
        else:
            c.tp_status = None

        # Earnings badge helper attrs
        eps_g = getattr(c, 'eps_growth', 0.0) or 0.0
        rev_g = getattr(c, 'rev_growth', 0.0) or 0.0
        roe_v = getattr(c, 'roe', 0.0) or 0.0
        c.eps_badge = 'strong' if eps_g >= 50 else ('pass' if eps_g >= 25 else ('warn' if eps_g >= 0 else 'fail'))
        c.rev_badge = 'strong' if rev_g >= 50 else ('pass' if rev_g >= 25 else ('warn' if rev_g >= 0 else 'fail'))
        c.roe_badge = 'pass' if roe_v >= 17 else 'warn'

        # ── SEPA Score (0-220 incl. earnings bonus) ────────────
        sc = 0
        if c.vcp_setup:
            sc += 30
            sc += int(max(0, (10 - min(c.vcp_tightness, 10)) * 2))
            sc += min(c.vcp_contractions, 5) * 3
        if c.vcp_vdu or c.vdu_near_zone:
            sc += 20
        if c.pocket_pivot:
            sc += 10
        sc += int(c.rs_rating * 0.7)
        if c.adx >= 25:
            sc += 10
        elif c.adx >= 15:
            sc += 5
        if c.vcp_setup:
            dist = c.dist_from_pivot
            if dist <= 5:
                sc += 10
            elif dist <= 10:
                sc += 5
            elif dist > 15:
                sc -= 5
        # ── Earnings bonus (Minervini) ──────────────────────────
        if eps_g >= 50:  sc += 20
        elif eps_g >= 25: sc += 12
        elif eps_g >= 10: sc += 5
        if rev_g >= 50:  sc += 10
        elif rev_g >= 25: sc += 6
        if roe_v >= 17:   sc += 8
        elif roe_v >= 10: sc += 3
        if getattr(c, 'eps_accel', False): sc += 10
        c.sepa_score = sc

    # Sort by SEPA Score descending
    candidates.sort(key=lambda c: c.sepa_score, reverse=True)

    # Assign rank
    for i, c in enumerate(candidates, 1):
        c.sepa_rank = i

    watchlist_symbols = set(ScanWatchlistItem.objects.filter(user=request.user).values_list('symbol', flat=True))

    context = {
        'candidates':       candidates,
        'last_updated':     last_updated,
        'all_runs':         all_runs,
        'selected_run_idx': run_idx,
        'vcp_only':         vcp_only,
        'hide_at_tp':       hide_at_tp,
        'earnings_filter':  earnings_filter,
        'watchlist_symbols': watchlist_symbols,
    }
    return render(request, 'stocks/us_sepa_scanner.html', context)


@login_required
def cup_handle_scanner(request):
    import threading as _th

    from django.core.cache import cache as _cp
    from django.http import JsonResponse as _JR

    user_id   = request.user.id
    cache_key = f'cup_handle_scan_{user_id}'

    if request.GET.get('scan_status') == '1':
        st = _cp.get(cache_key, {'state': 'idle'})
        if st.get('state') == 'done':
            _cp.delete(cache_key)
        return _JR(st)

    if request.GET.get('scan') == 'true' or request.method == 'POST':

        from .utils import refresh_all_thai_symbols, get_top_ranked_symbols
        scan_symbols = get_top_ranked_symbols(market='SET', limit=300, auto_refresh=True)

        from .utils import get_top_ranked_symbols, refresh_all_thai_symbols
        scan_symbols = get_top_ranked_symbols(market='SET', limit=400, auto_refresh=True)


        if not scan_symbols:
            refresh_all_thai_symbols()
            scan_symbols = get_top_ranked_symbols(market='SET', limit=300, auto_refresh=True)

        already = _cp.get(cache_key, {})
        if already.get('state') != 'running':
            _cp.set(cache_key, {'state': 'running', 'progress': 0, 'total': len(scan_symbols), 'phase': 'เริ่มสแกน Cup & Handle...'}, timeout=900)

            def _run_cup_handle_bg(uid, ckey, sym_list):
                try:
                    import concurrent.futures as _cf
                    import logging as _log
                    from datetime import datetime as _dt
                    from datetime import timedelta as _td

                    import pandas as _pd
                    import pandas_ta as _ta
                    import pytz as _pytz
                    import yfinance as _yf
                    from django.contrib.auth import get_user_model
                    from django.core.cache import cache as _c
                    from django.utils import timezone as tz
                    from yahooquery import Ticker as _TQ

                    from .models import CupHandleCandidate as _CHC
                    from .utils import detect_cup_and_handle
                    from .utils import get_top_ranked_symbols as _GTRS
                    _ch_log = _log.getLogger('stocks.cup_handle')
                    sym_list = _GTRS(market='SET', limit=300, auto_refresh=True)

                    User      = get_user_model()
                    user      = User.objects.get(pk=uid)
                    _bkk      = _pytz.timezone('Asia/Bangkok')
                    _now      = _dt.now(_bkk)
                    _end_str  = (_now.date() + _td(days=1)).strftime('%Y-%m-%d')
                    _start    = (_now.date() - _td(days=600)).strftime('%Y-%m-%d')
                    _scan_run = tz.now()

                    # 1. ลบข้อมูลเก่าที่เกิน 3 รอบ
                    old_runs = list(_CHC.objects.filter(user=user).values_list('scan_run', flat=True).distinct().order_by('-scan_run'))
                    if len(old_runs) >= 3:
                        _CHC.objects.filter(user=user, scan_run__in=old_runs[2:]).delete()

                    _CHC.objects.filter(user=user, scan_run=_scan_run).delete()

                    total = len(sym_list)
                    results = []

                    # --- STAGE 1: Bulk Screening (Fast) ---
                    _c.set(ckey, {'state': 'running', 'progress': 5, 'total': total, 'phase': 'Stage 1: 🔎 กรองสุขภาพคล่อง (Bulk)...'}, timeout=900)
                    chunk_size = 100
                    candidates = []
                    for i in range(0, total, chunk_size):
                        chunk = sym_list[i : i + chunk_size]
                        chunk_bk = [f"{s}.BK" for s in chunk]
                        try:
                            tq = _TQ(chunk_bk, timeout=60)
                            # summary_detail has 'averageVolume' (3-month) which is more stable for screening
                            details = tq.summary_detail
                            for symbol in chunk:
                                s_bk = f"{symbol}.BK"
                                if isinstance(details, dict) and s_bk in details:
                                    d_data = details[s_bk]
                                    if isinstance(d_data, dict):
                                        vol_avg = d_data.get('averageVolume', 0) or 0
                                        price   = d_data.get('previousClose', 0) or 0
                                        # Liquidity filter: Value > 1,000,000 THB/day
                                        if (vol_avg * price) >= 1_000_000:
                                            candidates.append(symbol)
                        except Exception as _e:
                            _ch_log.warning(f'[Cup&Handle SET] bulk screen chunk failed: {_e}, adding chunk as fallback')
                            candidates.extend(chunk)

                    # --- STAGE 2: Pattern Analysis (Threaded) ---
                    total_cand = len(candidates)
                    _c.set(ckey, {'state': 'running', 'progress': 20, 'total': total_cand, 'phase': f'Stage 2: ☕ วิเคราะห์รูปแบบ {total_cand} ตัว...'}, timeout=900)

                    def _scan_one(symbol):
                        try:
                            s_bk = f'{symbol}.BK'
                            ticker_obj = _yf.Ticker(s_bk)
                            df = ticker_obj.history(start=_start, end=_end_str, interval="1d")
                            if df is None or df.empty or len(df) < 80:
                                return None
                            if isinstance(df.columns, _pd.MultiIndex):
                                df.columns = df.columns.droplevel(1)
                            df = df.dropna(subset=['Close', 'High', 'Low'])
                            
                            pat = detect_cup_and_handle(df)
                            if pat is None: return None

                            # RS return (3M)
                            close_s = df['Close'].dropna()
                            rs_return = None
                            if len(close_s) >= 66:
                                rs_return = float((close_s.iloc[-1] - close_s.iloc[-66]) / abs(close_s.iloc[-66]) * 100)

                            # ADX & RSI
                            adx_val, rsi_val = 0.0, 50.0
                            try:
                                adx_df = _ta.adx(df['High'], df['Low'], df['Close'], length=14)
                                if adx_df is not None and not adx_df.empty:
                                    col = [c for c in adx_df.columns if c.startswith('ADX_')]
                                    if col: adx_val = float(adx_df[col[0]].iloc[-1])
                                rsi_s = _ta.rsi(df['Close'], length=14)
                                if rsi_s is not None: rsi_val = float(rsi_s.iloc[-1])
                            except Exception as _e:
                                _ch_log.debug(f'[Cup&Handle SET] ADX/RSI {symbol}: {_e}')

                            return {'symbol': symbol, 'pat': pat, 'rs_return': rs_return,
                                    'adx': adx_val, 'rsi': rsi_val, 'avg_vol': float(df['Volume'].tail(20).mean())}
                        except Exception as _e:
                            _ch_log.debug(f'[Cup&Handle SET] scan {symbol}: {_e}')
                            return None

                    with _cf.ThreadPoolExecutor(max_workers=5) as ex:
                        futs = {ex.submit(_scan_one, s): s for s in candidates}
                        done = 0
                        for fut in _cf.as_completed(futs):
                            done += 1
                            if done % 5 == 0:
                                _c.set(ckey, {'state': 'running', 'progress': 20 + int((done/total_cand)*75), 'total': total_cand,
                                              'phase': f'วิเคราะห์ {done}/{total_cand}...'}, timeout=900)
                            try:
                                res = fut.result()
                                if res: results.append(res)
                            except Exception as _e:
                                _ch_log.debug(f'[Cup&Handle SET] future error {futs[fut]}: {_e}')
                    
                    # RS Percentile
                    rs_map = {}
                    rs_vals = {r['symbol']: r['rs_return'] for r in results if r['rs_return'] is not None}
                    if rs_vals:
                        rs_ser = _pd.Series(rs_vals)
                        rs_map = (rs_ser.rank(pct=True) * 99).clip(0, 99).astype(int).to_dict()

                    # Save to DB
                    objs = []
                    for r in results:
                        pat = dict(r['pat'])
                        price_val = pat.pop('current_price', 0.0)
                        objs.append(_CHC(
                            user=user, scan_run=_scan_run, symbol=r['symbol'],
                            price=price_val,
                            market='SET',
                            rs_rating=rs_map.get(r['symbol'], 0),
                            adx=r['adx'], rsi=r['rsi'], avg_vol_20d=r['avg_vol'],
                            **pat
                        ))
                    _CHC.objects.bulk_create(objs)
                    _c.set(ckey, {'state': 'done', 'progress': 100}, timeout=300)
                except Exception as exc:
                    import logging
                    logging.getLogger('stocks').exception(f'[Cup&Handle] bg scan error: {exc}')
                    from django.core.cache import cache as _c2
                    _c2.set(ckey, {'state': 'done'}, timeout=300)

            _th.Thread(target=_run_cup_handle_bg, args=(user_id, cache_key, scan_symbols), daemon=True).start()

        from django.shortcuts import redirect as _redir
        return _redir('stocks:cup_handle_scanner')

    # ── Display results ───────────────────────────────────────────
    from .models import CupHandleCandidate as _CHC
    from .models import ScanWatchlistItem as _SWI

    all_runs = list(
        _CHC.objects.filter(user=request.user, market='SET')
        .values_list('scan_run', flat=True)
        .distinct().order_by('-scan_run')
    )

    try:
        run_idx = int(request.GET.get('run_idx', 0))
    except (ValueError, TypeError):
        run_idx = 0
    run_idx = max(0, min(run_idx, len(all_runs) - 1)) if all_runs else 0

    candidates = []
    scanned_at = None
    if all_runs:
        selected_run = all_runs[run_idx]
        candidates   = list(_CHC.objects.filter(user=request.user, scan_run=selected_run, market='SET'))
        scanned_at   = selected_run

    # เรียงตาม Stage Priority → Confidence เสมอ
    stage_order = {'breakout': 0, 'ready': 1, 'handle': 2, 'forming': 3}
    candidates.sort(key=lambda c: (stage_order.get(c.stage, 9), -c.confidence_score))

    # Stage counts (ก่อน filter เพื่อแสดงใน summary cards)
    stage_counts = {
        'breakout': sum(1 for c in candidates if c.stage == 'breakout'),
        'ready':    sum(1 for c in candidates if c.stage == 'ready'),
        'handle':   sum(1 for c in candidates if c.stage == 'handle'),
        'forming':  sum(1 for c in candidates if c.stage == 'forming'),
    }

    # ── Filters ───────────────────────────────────────────────────
    stage_filter = request.GET.get('stage', 'all')
    try:
        min_conf = int(request.GET.get('min_conf', 0))
    except (ValueError, TypeError):
        min_conf = 0
    rs_only = request.GET.get('rs_only') == '1'

    if stage_filter != 'all':
        candidates = [c for c in candidates if c.stage == stage_filter]
    if min_conf > 0:
        candidates = [c for c in candidates if c.confidence_score >= min_conf]
    if rs_only:
        candidates = [c for c in candidates if c.rs_rating >= 70]

    # ── Computed fields ───────────────────────────────────────────
    for c in candidates:
        # % ห่างจาก Breakout Price
        if c.breakout_price > 0 and c.price > 0:
            c.pct_to_breakout = round((c.breakout_price - c.price) / c.price * 100, 1)
            c.pct_to_breakout = max(0.0, c.pct_to_breakout)
        else:
            c.pct_to_breakout = 0.0
        # Recovery % (ใช้แสดง progress bar สำหรับ Forming)
        if c.cup_high > c.cup_low:
            raw = (c.price - c.cup_low) / (c.cup_high - c.cup_low) * 100
            c.recovery_pct = round(min(100.0, max(0.0, raw)), 1)
        else:
            c.recovery_pct = 0.0

    # หุ้น Forming ที่ฟื้นตัวมากที่สุด (สำหรับ smart summary)
    forming_list = [c for c in candidates if c.stage == 'forming']
    closest_forming = max(forming_list, key=lambda c: c.recovery_pct, default=None)

    # Watchlist symbols ของ user
    watchlist_symbols = set(
        _SWI.objects.filter(user=request.user, market='SET').values_list('symbol', flat=True)
    )

    context = {
        'candidates':       candidates,
        'has_scanned':      bool(all_runs),
        'scanned_at':       scanned_at,
        'all_runs':         all_runs,
        'selected_run_idx': run_idx,
        'current_sort':     request.GET.get('sort', 'stage'),
        'stage_counts':     stage_counts,
        'stage_filter':     stage_filter,
        'min_conf':         min_conf,
        'rs_only':          rs_only,
        'closest_forming':  closest_forming,
        'watchlist_symbols': watchlist_symbols,
        'stage_labels': {
            'breakout': ('Breakout',       '#16a34a'),
            'ready':    ('Ready to Break', '#2563eb'),
            'handle':   ('Handle Forming', '#d97706'),
            'forming':  ('Cup Forming',    '#64748b'),
        },
    }
    return render(request, 'stocks/cup_handle_scan.html', context)


# ====== US Cup & Handle Scanner ======

@login_required
def us_cup_handle_scanner(request):
    """
    US Cup & Handle Scanner - สแกน หุ้น US จาก _US_MOMENTUM_SYMBOLS universe
    ใช้ logic เดียวกับ SET scanner แต่:
    - ไม่เติม .BK suffix
    - liquidity filter เป็น USD (avg_vol * avg_price >= 1,000,000 USD)
    - บันทึก market='US' แยกต่างหาก
    - ตรวจ breakout_vol_ok (volume ≥1.5x avg on breakout bar) - O'Neil rule
    """
    import threading as _th

    from django.core.cache import cache as _cp
    from django.http import JsonResponse as _JR

    user_id   = request.user.id
    cache_key = f'us_cup_handle_scan_{user_id}'

    if request.GET.get('scan_status') == '1':
        st = _cp.get(cache_key, {'state': 'idle'})
        if st.get('state') == 'done':
            _cp.delete(cache_key)
        return _JR(st)

    if request.GET.get('scan') == 'true' or request.method == 'POST':
        from .models import ScannableSymbol as _SS
        scan_symbols = list(_SS.objects.filter(is_active=True, market='US').values_list('symbol', flat=True))
        if len(scan_symbols) < 100:
            _seed_us_symbols()
            scan_symbols = list(_SS.objects.filter(is_active=True, market='US').values_list('symbol', flat=True))
        scan_symbols = [s for s in scan_symbols if s not in ('SPY', 'QQQ', 'IWM')]

        already = _cp.get(cache_key, {})
        if already.get('state') != 'running':
            _cp.set(cache_key, {
                'state': 'running', 'progress': 0,
                'total': len(scan_symbols), 'phase': 'เริ่มสแกน US Cup & Handle...'
            }, timeout=900)

            def _run_us_cup_handle_bg(uid, ckey, sym_list):
                try:
                    import concurrent.futures as _cf
                    import logging as _log
                    from datetime import datetime as _dt
                    from datetime import timedelta as _td

                    import pandas as _pd
                    import pandas_ta as _ta
                    import pytz as _pytz
                    import yfinance as _yf
                    from django.contrib.auth import get_user_model
                    from django.core.cache import cache as _c

                    from .models import CupHandleCandidate as _CHC
                    from .utils import detect_cup_and_handle
                    _uch_log = _log.getLogger('stocks.us_cup_handle')

                    User      = get_user_model()
                    user      = User.objects.get(pk=uid)
                    _now      = _dt.now(_pytz.utc)
                    _end_str  = _now.date().strftime('%Y-%m-%d')
                    _start    = (_now.date() - _td(days=600)).strftime('%Y-%m-%d')
                    _scan_run = _dt.now(_pytz.utc)

                    # เก็บ 3 รอบล่าสุด ลบเก่า
                    old_runs = list(
                        _CHC.objects.filter(user=user, market='US')
                        .values_list('scan_run', flat=True)
                        .distinct().order_by('-scan_run')[2:]
                    )
                    if old_runs:
                        _CHC.objects.filter(user=user, market='US', scan_run__in=old_runs).delete()

                    total   = len(sym_list)
                    results = []

                    def _scan_one(symbol):
                        try:
                            df = _yf.Ticker(symbol).history(start=_start, end=_end_str, interval='1d')
                            if df is None or df.empty or len(df) < 60:
                                return None
                            if isinstance(df.columns, _pd.MultiIndex):
                                df.columns = df.columns.droplevel(1)
                            df = df.dropna(subset=['Close', 'High', 'Low'])

                            # Liquidity filter - USD (≥$1M daily turnover)
                            avg_vol   = float(df['Volume'].tail(20).mean())
                            avg_price = float(df['Close'].tail(20).mean())
                            if avg_vol * avg_price < 1_000_000:
                                return None

                            pat = detect_cup_and_handle(df)
                            if pat is None:
                                return None

                            # Breakout volume confirmation (O'Neil rule: ≥1.5x avg on breakout day)
                            breakout_vol_ok = False
                            if pat['stage'] == 'breakout':
                                last_vol = float(df['Volume'].iloc[-1])
                                breakout_vol_ok = last_vol >= avg_vol * 1.5

                            # RS return (3M)
                            close_s   = df['Close'].dropna()
                            rs_return = None
                            if len(close_s) >= 66:
                                rs_return = float(
                                    (close_s.iloc[-1] - close_s.iloc[-66]) / abs(close_s.iloc[-66]) * 100
                                )

                            # ADX & RSI
                            adx_val = 0.0
                            rsi_val = 50.0
                            try:
                                adx_df = _ta.adx(df['High'], df['Low'], df['Close'], length=14)
                                if adx_df is not None and not adx_df.empty:
                                    col = [c for c in adx_df.columns if c.startswith('ADX_')]
                                    if col and _pd.notna(adx_df[col[0]].iloc[-1]):
                                        adx_val = float(adx_df[col[0]].iloc[-1])
                                rsi_s = _ta.rsi(df['Close'], length=14)
                                if rsi_s is not None and _pd.notna(rsi_s.iloc[-1]):
                                    rsi_val = float(rsi_s.iloc[-1])
                            except Exception as _e:
                                _uch_log.debug(f'[US Cup&Handle] ADX/RSI {symbol}: {_e}')

                            return {
                                'symbol': symbol, 'pat': pat,
                                'rs_return': rs_return, 'adx': adx_val,
                                'rsi': rsi_val, 'avg_vol': avg_vol,
                                'breakout_vol_ok': breakout_vol_ok,
                            }
                        except Exception as _e:
                            _uch_log.debug(f'[US Cup&Handle] scan {symbol}: {_e}')
                            return None

                    with _cf.ThreadPoolExecutor(max_workers=5) as ex:
                        futs = {ex.submit(_scan_one, s): s for s in sym_list}
                        done = 0
                        for fut in _cf.as_completed(futs):
                            done += 1
                            _c.set(ckey, {
                                'state': 'running', 'progress': done,
                                'total': total, 'phase': f'สแกน {done}/{total}...'
                            }, timeout=900)
                            try:
                                res = fut.result()
                                if res:
                                    results.append(res)
                            except Exception as _e:
                                _uch_log.debug(f'[US Cup&Handle] future error {futs[fut]}: {_e}')

                    # RS percentile rank
                    rs_vals = {r['symbol']: r['rs_return'] for r in results if r['rs_return'] is not None}
                    rs_map  = {}
                    if rs_vals:
                        rs_ser = _pd.Series(rs_vals)
                        rs_map = (rs_ser.rank(pct=True) * 99).clip(0, 99).astype(int).to_dict()

                    # Save to DB
                    for res in results:
                        pat = res['pat']
                        _CHC.objects.create(
                            user=user, scan_run=_scan_run, market='US',
                            symbol=res['symbol'],
                            price=pat['current_price'],
                            cup_high=pat['cup_high'],
                            cup_low=pat['cup_low'],
                            cup_depth_pct=pat['cup_depth_pct'],
                            cup_length_days=pat['cup_length_days'],
                            cup_start_date=pat['cup_start_date'],
                            cup_end_date=pat['cup_end_date'],
                            handle_high=pat['handle_high'],
                            handle_low=pat['handle_low'],
                            handle_depth_pct=pat['handle_depth_pct'],
                            handle_length_days=pat['handle_length_days'],
                            handle_start_date=pat['handle_start_date'],
                            breakout_price=pat['breakout_price'],
                            target_price=pat['target_price'],
                            stop_loss=pat['stop_loss'],
                            risk_reward=pat['risk_reward'],
                            avg_vol_20d=res['avg_vol'],
                            cup_vol_confirmed=pat['cup_vol_confirmed'],
                            handle_vol_dry=pat['handle_vol_dry'],
                            breakout_vol_ok=res['breakout_vol_ok'],
                            stage=pat['stage'],
                            confidence_score=pat['confidence_score'],
                            rs_rating=rs_map.get(res['symbol'], 0),
                            adx=res['adx'],
                            rsi=res['rsi'],
                        )

                    _c.set(ckey, {'state': 'done'}, timeout=300)
                except Exception as exc:
                    import logging
                    logging.getLogger('stocks').exception(f'[US Cup&Handle] bg scan error: {exc}')
                    from django.core.cache import cache as _c2
                    _c2.set(ckey, {'state': 'done'}, timeout=300)

            _th.Thread(
                target=_run_us_cup_handle_bg,
                args=(user_id, cache_key, scan_symbols),
                daemon=True
            ).start()

        from django.shortcuts import redirect as _redir
        return _redir('stocks:us_cup_handle_scanner')

    # ── Display results ───────────────────────────────────────────
    from .models import CupHandleCandidate as _CHC

    all_runs = list(
        _CHC.objects.filter(user=request.user, market='US')
        .values_list('scan_run', flat=True)
        .distinct().order_by('-scan_run')
    )

    try:
        run_idx = int(request.GET.get('run_idx', 0))
    except (ValueError, TypeError):
        run_idx = 0
    run_idx = max(0, min(run_idx, len(all_runs) - 1)) if all_runs else 0

    candidates = []
    scanned_at = None
    if all_runs:
        selected_run = all_runs[run_idx]
        candidates   = list(_CHC.objects.filter(user=request.user, market='US', scan_run=selected_run))
        scanned_at   = selected_run

    stage_order = {'breakout': 0, 'ready': 1, 'handle': 2, 'forming': 3}
    candidates.sort(key=lambda c: (stage_order.get(c.stage, 9), -c.confidence_score))

    stage_counts = {
        'breakout': sum(1 for c in candidates if c.stage == 'breakout'),
        'ready':    sum(1 for c in candidates if c.stage == 'ready'),
        'handle':   sum(1 for c in candidates if c.stage == 'handle'),
        'forming':  sum(1 for c in candidates if c.stage == 'forming'),
    }

    stage_filter = request.GET.get('stage', 'all')
    try:
        min_conf = int(request.GET.get('min_conf', 0))
    except (ValueError, TypeError):
        min_conf = 0
    rs_only = request.GET.get('rs_only') == '1'

    if stage_filter != 'all':
        candidates = [c for c in candidates if c.stage == stage_filter]
    if min_conf > 0:
        candidates = [c for c in candidates if c.confidence_score >= min_conf]
    if rs_only:
        candidates = [c for c in candidates if c.rs_rating >= 70]

    for c in candidates:
        if c.breakout_price > 0 and c.price > 0:
            c.pct_to_breakout = round((c.breakout_price - c.price) / c.price * 100, 1)
            c.pct_to_breakout = max(0.0, c.pct_to_breakout)
        else:
            c.pct_to_breakout = 0.0
        if c.cup_high > c.cup_low:
            raw = (c.price - c.cup_low) / (c.cup_high - c.cup_low) * 100
            c.recovery_pct = round(min(100.0, max(0.0, raw)), 1)
        else:
            c.recovery_pct = 0.0

    forming_list    = [c for c in candidates if c.stage == 'forming']
    closest_forming = max(forming_list, key=lambda c: c.recovery_pct, default=None)

    context = {
        'candidates':        candidates,
        'has_scanned':       bool(all_runs),
        'scanned_at':        scanned_at,
        'all_runs':          all_runs,
        'selected_run_idx':  run_idx,
        'current_sort':      request.GET.get('sort', 'stage'),
        'stage_counts':      stage_counts,
        'stage_filter':      stage_filter,
        'min_conf':          min_conf,
        'rs_only':           rs_only,
        'closest_forming':   closest_forming,
        'stage_labels': {
            'breakout': ('Breakout',       '#16a34a'),
            'ready':    ('Ready to Break', '#2563eb'),
            'handle':   ('Handle Forming', '#d97706'),
            'forming':  ('Cup Forming',    '#64748b'),
        },
        'total_symbols': len(_US_MOMENTUM_SYMBOLS),
    }
    return render(request, 'stocks/us_cup_handle_scan.html', context)


@login_required
def scanner_guide(request):
    """
    แสดงคู่มือการใช้งานและการทำงานของ Scanner ทั้ง 3 รูปแบบ
    (Precision Momentum, Cup & Handle, Standard Momentum)
    """
    return render(request, 'stocks/scanner_guide.html')


@login_required
def turtle_scanner(request):
    """
    หน้าแสดงผลการสแกนด้วยระบบ Turtle Trading
    - System 1: Breakout 20-day high (Exit: 10-day low)
    - System 2: Breakout 55-day high (Exit: 20-day low)
    """
    from .models import PrecisionScanCandidate, TurtleScanCandidate
    
    market = request.GET.get('market', 'SET')
    candidates_qs = TurtleScanCandidate.objects.filter(user=request.user, market=market)
    
    candidates = []
    if candidates_qs.exists():
        latest_run = candidates_qs.order_by('-scan_run').values_list('scan_run', flat=True).first()
        candidates = list(candidates_qs.filter(scan_run=latest_run).order_by('symbol'))
        last_updated = latest_run
        
        prec_qs = PrecisionScanCandidate.objects.filter(user=request.user, market=market)
        latest_prec_run = prec_qs.values_list('scan_run', flat=True).order_by('-scan_run').first()
        if latest_prec_run:
            prec_dict = {p.symbol: p for p in prec_qs.filter(scan_run=latest_prec_run)}
            for c in candidates:
                p_match = prec_dict.get(c.symbol)
                if p_match:
                    c.technical_score = p_match.technical_score
                    c.rs_rating = p_match.rs_rating
                    c.launcher_score = p_match.launcher_score
                else:
                    c.technical_score = None
                    c.rs_rating = None
                    c.launcher_score = None
        last_updated = None

    # --- Markov Market Regime Pulse ---
    from django.core.cache import cache

    from .utils import calculate_markov_regime
    regime_cache_key = f'markov_regime_{market}'
    regime = cache.get(regime_cache_key)
    if not regime:
        index_sym = '^SET.BK' if market == 'SET' else '^GSPC'
        regime = calculate_markov_regime(index_sym)
        cache.set(regime_cache_key, regime, timeout=1800) # 30 mins

    context = {
        'candidates': candidates,
        'last_updated': last_updated,
        'selected_market': market,
        'market_regime': regime,
        'title': "Turtle Trader Scanner"
    }
    return render(request, 'stocks/turtle_scanner.html', context)


@login_required
def turtle_scanner_run_ajax(request):
    """
    รัน Turtle Scanner เบื้องหลัง 
    (ดึงข้อมูลย้อนหลัง 3-6 เดือนเพื่อหาสถิติ 20-day, 55-day High/Low)
    """
    import concurrent.futures as _cf
    import random as _random
    import threading as _th
    import time as _time

    import pandas as _pd
    import yfinance as _yf
    from django.core.cache import cache as _cp
    from django.http import JsonResponse as _JR
    from django.utils import timezone as _tz

    from .models import ScannableSymbol, TurtleScanCandidate

    user_id = request.user.id
    market_param = request.GET.get('market', 'SET')
    ckey = f'turtle_scan_{user_id}_{market_param}'

    c_state = _cp.get(ckey, {'state': 'idle'})
    if request.GET.get('status_check') == '1':
        return _JR(c_state)

    if c_state.get('state') == 'running' and request.GET.get('force') != '1':
        return _JR({'status': 'started'})

    # Get symbols
    precision_only = request.GET.get('precision_only') == 'true'
    
    if precision_only:
        from .models import PrecisionScanCandidate
        # Get latest precision run
        latest_prec = PrecisionScanCandidate.objects.filter(user=request.user, market=market_param).order_by('-scan_run').first()
        if not latest_prec:
            return _JR({'state': 'done', 'error': 'ไม่พบข้อมุลจากหน้า Precision Scan กรุณาสแกน Precision ก่อนเปิดโหมดกรองคุณภาพ'})
        
        sym_list = list(PrecisionScanCandidate.objects.filter(
            user=request.user, 
            market=market_param, 
            scan_run=latest_prec.scan_run,
            technical_score__gte=75
        ).values_list('symbol', flat=True))
        
        if not sym_list:
            return _JR({'state': 'done', 'error': 'ไม่พบหุ้นที่มีคะแนน > 75 ในฐานข้อมูล Precision ล่าสุด'})
    else:
        from .utils import get_top_ranked_symbols
        sym_list = get_top_ranked_symbols(market=market_param, limit=300)
        
    if not sym_list:
        return _JR({'state': 'done', 'error': f'ไม่พบหุ้นใน watchlist สำหรับตลาด {market_param}'})

    def _bg_task(syms, market):
        from django.contrib.auth import get_user_model as _GUM

        from .models import PrecisionScanCandidate  # ย้ายมาไว้ตรงนี้เพื่อให้ใน Thread มองเห็น
        user = _GUM().objects.get(pk=user_id)

        # Auto-refresh market cap rankings daily (SET only)
        if market == 'SET':
            try:
                from .utils import get_top_ranked_symbols as _GTRS
                new_syms = _GTRS(market='SET', limit=300, auto_refresh=True)
                if new_syms: # ป้องกันกรณี refresh แล้วได้ค่าว่าง
                    syms = new_syms
            except Exception:
                pass 

        scan_time = _tz.now()
        total_syms = len(syms)
        _cp.set(ckey, {'state': 'running', 'progress': 0, 'total': total_syms}, timeout=3600)
        
        results = []
        processed = 0

        # --- STAGE 1: Systematic Analysis (Detailed Scan) ---
        # ข้าม Stage 1 (YahooQuery) เพื่อความเร็วและป้องกันการค้าง
        candidates = [{'symbol': s} for s in syms]
        total_cand = len(candidates)
        _cp.set(ckey, {'state': 'running', 'progress': 0, 'total': total_cand, 'phase': f'🐢 กำลังเริ่มวิเคราะห์หุ้น {total_cand} ตัว...'}, timeout=3600)
        # กำหนดขนาดกลุ่มข้อมูลตามตลาด
        c_size = 20 if market == 'US' else 50
        for i in range(0, len(candidates), c_size):
            chunk = candidates[i : i + c_size]
            chunk_syms = [c['symbol'] for c in chunk]
            
            # ปรับปรุง Logic: ถ้าเป็นตลาด SET ให้เติม .BK เฉพาะหุ้นไทยปกติ 
            # แต่ถ้าเป็นหุ้นที่ดูเหมือนหุ้น US (เช่น AMAT, AMD, ETN) ให้ลองดึงแบบไม่มี .BK หรือข้ามไปถ้าไม่ใช่หุ้นไทย
            chunk_bk = []
            for s in chunk_syms:
                if market == 'SET':
                    if '.' in s:
                        chunk_bk.append(s)
                    else:
                        # ถ้าเป็นหุ้นไทยแท้ (มักมี 3-5 ตัวอักษร) หรือ DR (มีตัวเลข)
                        # แต่ถ้าเป็นชื่อหุ้นนอกเพียวๆ ที่หลุดมาใน List SET จะถูกจัดการที่นี่
                        chunk_bk.append(f"{s}.BK")
                else:
                    chunk_bk.append(s)
            
            _cp.set(ckey, {'state': 'running', 'progress': i, 'total': total_cand, 'phase': f'กำลังวิเคราะห์กลุ่มที่ {i//c_size + 1}...'}, timeout=3600)
            
            try:
                # Use yfinance with auto_adjust
                data = yf.download(chunk_bk, period="1y", interval="1d", progress=False, group_by='ticker', threads=True, timeout=30, auto_adjust=True)
                
                for symbol in chunk_syms:
                    try:
                        s_bk = f"{symbol}.BK" if market == 'SET' and '.' not in symbol else symbol
                        
                        # เพิ่มการตรวจสอบพิเศษ: ถ้าเป็นตลาด SET แต่สัญลักษณ์ดูเหมือนหุ้น US (เช่น AMAT, AMD) 
                        # ให้ข้ามไปเลยถ้า Yahoo หา .BK ไม่เจอ เพราะมักจะเป็นการปนกันของรายชื่อ
                        df = None
                        if s_bk in data and not data[s_bk].empty:
                            df = data[s_bk].dropna(subset=['Close'])
                        
                        # Fallback & Sanitization
                        if df is None or df.empty:
                            # ถ้าเป็นหุ้นไทย (.BK) แล้วหาไม่พบ ให้ลองเช็คว่าเป็นหุ้น US ที่หลงมาหรือไม่
                            if market == 'SET' and symbol.isupper() and len(symbol) <= 5:
                                # อาจจะเป็นหุ้น US ที่หลงมาใน List SET -> ข้ามไปเลยเพื่อลด Error
                                continue

                            try:
                                t_obj = yf.Ticker(s_bk)
                                df = t_obj.history(period="1y", interval="1d")
                                if df is not None and not df.empty:
                                    df = df.dropna(subset=['Close'])
                            except Exception: pass

                        if df is None or df.empty or len(df) < 55: 
                            continue
                        
                        # Debug: เห็นกันชัดๆ ว่าหุ้นตัวไหนกำลังถูกตรวจ
                        # print(f"--- Analyzing {symbol} ---")
                        
                        avg_vol = float(df['Volume'].tail(20).mean())
                        avg_val = (df['Close'] * df['Volume']).tail(20).mean()
                        
                        # ยกเลิก Liquidity filter ชั่วคราว หรือปรับให้ต่ำสุดๆ เพื่อเช็คผล
                        if market == 'SET' and avg_val < 100_000: continue 
                        
                        # Calculate Turtle
                        df['High_20'] = df['High'].rolling(20).max().shift(1)
                        df['Low_10'] = df['Low'].rolling(10).min().shift(1)
                        df['High_55'] = df['High'].rolling(55).max().shift(1)
                        df['Low_20'] = df['Low'].rolling(20).min().shift(1)
                        
                        # -- Stage 2 Analysis (v2) --
                        df['SMA150'] = df['Close'].rolling(150).mean()
                        df['SMA200'] = df['Close'].rolling(200).mean()
                        
                        # -- ADX & ATR Calculation (Real) --
                        try:
                            # คำนวณ ADX
                            adx_data = df.ta.adx(length=14)
                            if adx_data is not None and not adx_data.empty:
                                df['ADX_14'] = adx_data['ADX_14']
                            else:
                                df['ADX_14'] = 0.0
                            
                            # คำนวณ ATR (ค่า N ของ Turtle)
                            atr_data = df.ta.atr(length=20)
                            if atr_data is not None:
                                df['ATR_20'] = atr_data
                            else:
                                df['ATR_20'] = 0.0
                        except Exception:
                            df['ADX_14'] = 0.0
                            df['ATR_20'] = 0.0

                        # Weinsteins Stage 2
                        last_row = df.iloc[-1]
                        current_close = float(last_row['Close'])
                        h20 = float(last_row.get('High_20', 0) or 0)
                        h55 = float(last_row.get('High_55', 0) or 0)
                        atr = float(last_row.get('ATR_20', 0) or 0)
                        l10 = float(last_row.get('Low_10', 0) or 0)
                        l20 = float(last_row.get('Low_20', 0) or 0)
                        sma150 = float(last_row.get('SMA150', 0) or 0)
                        sma200 = float(last_row.get('SMA200', 0) or 0)
                        adx_val = float(last_row.get('ADX_14', 0) or 0)
                        
                        is_stage2 = current_close > sma150 and sma150 > sma200

                        # --- Just Broke (Expanded window to 10 days) ---
                        window = df.tail(10)
                        sys1_days_ago = None
                        sys2_days_ago = None
                        for d_ago, (_, row) in enumerate(window.iloc[::-1].iterrows()):
                            rh20 = float(row.get('High_20', 0) or 0)
                            rh55 = float(row.get('High_55', 0) or 0)
                            rc   = float(row['Close'])
                            if sys1_days_ago is None and rh20 > 0 and rc >= rh20:
                                sys1_days_ago = d_ago
                            if sys2_days_ago is None and rh55 > 0 and rc >= rh55:
                                sys2_days_ago = d_ago

                        sys1 = sys1_days_ago is not None
                        sys2 = sys2_days_ago is not None
                        sys1_near = (not sys1) and h20 > 0 and current_close >= h20 * 0.97
                        sys2_near = (not sys2) and h55 > 0 and current_close >= h55 * 0.97

                        pct_to_20d = round((current_close - h20) / h20 * 100, 2) if h20 > 0 else None
                        pct_to_55d = round((current_close - h55) / h55 * 100, 2) if h55 > 0 else None

                        if sys1 or sys2 or sys1_near or sys2_near:
                            p_score = None
                            rs_rat = None
                            p_match = PrecisionScanCandidate.objects.filter(user=user, symbol=symbol, market=market).order_by('-scan_run').first()
                            if p_match:
                                p_score = p_match.technical_score
                                rs_rat = p_match.rs_rating
                            
                            # -- ปรับเกณฑ์ Elite ให้เข้มงวดขึ้น (โดยเฉพาะ US) --
                            ps_val = p_score if p_score is not None else 0
                            rs_val = rs_rat if rs_rat is not None else 0
                            
                            if market == 'US':
                                # US: ต้องผ่านเกณฑ์ทั้ง RS >= 85 และ Score >= 80 (AND)
                                is_elite = is_stage2 and (rs_val >= 85 and ps_val >= 80)
                            else:
                                # SET: ต้องผ่านเกณฑ์ทั้ง RS >= 80 และ Score >= 75 (AND)
                                is_elite = is_stage2 and (rs_val >= 80 and ps_val >= 75)

                            results.append(TurtleScanCandidate(
                                user=user, scan_run=scan_time, symbol=symbol, market=market,
                                price=current_close,
                                sys1_breakout=sys1, sys1_days_ago=sys1_days_ago,
                                high_20d=round(h20, 2), low_10d=round(l10, 2),
                                sys2_breakout=sys2, sys2_days_ago=sys2_days_ago,
                                high_55d=round(h55, 2), low_20d=round(l20, 2),
                                sys1_near=sys1_near, sys2_near=sys2_near,
                                pct_to_20d=pct_to_20d, pct_to_55d=pct_to_55d,
                                avg_vol_20d=avg_vol, atr_20d=round(atr, 4),
                                adx=round(adx_val, 2),
                                stage2=is_stage2,
                                technical_score=p_score, rs_rating=rs_rat,
                                is_elite=is_elite
                            ))
                    except Exception as e: 
                        print(f"Error analyzing {symbol}: {e}")
                        continue
            except Exception as e: 
                print(f"Chunk Error: {e}")
                continue

        # Save to DB — always delete old + save new so scan_run timestamp always updates
        TurtleScanCandidate.objects.filter(user=user, market=market).delete()
        if results:
            TurtleScanCandidate.objects.bulk_create(results)

        _cp.set(ckey, {'state': 'done', 'found': len(results)}, timeout=3600)

    _cp.set(ckey, {'state': 'running', 'progress': 0, 'total': len(sym_list)}, timeout=3600)
    _th.Thread(target=_bg_task, args=(sym_list, market_param), daemon=True).start()

    return _JR({'status': 'started'})


# ---------------------------------------------------------------------------
# Stock Chart View - Turtle Breakout + Momentum
# ---------------------------------------------------------------------------

@login_required
def debug_scan_symbol(request, symbol):
    """
    Debug endpoint — fetch data for one symbol and return full breakdown.
    Call: /stocks/debug-scan/CK/
    Shows exactly what the scanner computes (RSI, RVOL, ADX, score breakdown).
    Staff-only for safety.
    """
    from django.http import JsonResponse
    if not request.user.is_staff:
        return JsonResponse({'error': 'staff only'}, status=403)

    import pandas as pd
    import pandas_ta as ta
    import yfinance as yf

    from .utils import (
        analyze_momentum_technical_v2,
        find_supply_demand_zones,
        find_supply_demand_zones_v2,
    )

    sym_bk = f"{symbol.upper()}.BK"
    result = {'symbol': symbol, 'sym_bk': sym_bk}

    try:
        df = yf.download(sym_bk, period='1y', interval='1d', progress=False, timeout=20)
        result['rows_fetched'] = len(df)
        result['is_multindex'] = isinstance(df.columns, pd.MultiIndex)

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)

        if df.empty or len(df) < 55:
            result['error'] = f'Not enough data: {len(df)} rows'
            return JsonResponse(result)

        # Raw last bar
        result['last_close'] = float(df['Close'].iloc[-1])
        result['last_open']  = float(df['Open'].iloc[-1])
        result['last_vol']   = float(df['Volume'].iloc[-1])
        result['avg_vol_20'] = float(df['Volume'].tail(20).mean())
        result['rvol_raw']   = round(result['last_vol'] / result['avg_vol_20'], 3) if result['avg_vol_20'] > 0 else 0

        # Compute indicators
        df['EMA50']  = ta.ema(df['Close'], length=50)
        df['EMA200'] = ta.ema(df['Close'], length=200)
        df['EMA20']  = ta.ema(df['Close'], length=20)
        df['RSI']    = ta.rsi(df['Close'], length=14)
        adx_df = ta.adx(df['High'], df['Low'], df['Close'], length=14)
        if adx_df is not None:
            df = pd.concat([df, adx_df], axis=1)
        df['MFI'] = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)

        result['rsi']    = round(float(df['RSI'].iloc[-1]), 2) if pd.notna(df['RSI'].iloc[-1]) else None
        result['ema20']  = round(float(df['EMA20'].iloc[-1]), 2) if pd.notna(df['EMA20'].iloc[-1]) else None
        result['ema50']  = round(float(df['EMA50'].iloc[-1]), 2) if pd.notna(df['EMA50'].iloc[-1]) else None
        result['ema200'] = round(float(df['EMA200'].iloc[-1]), 2) if pd.notna(df['EMA200'].iloc[-1]) else None
        result['adx']    = round(float(df['ADX_14'].iloc[-1]), 2) if 'ADX_14' in df.columns and pd.notna(df['ADX_14'].iloc[-1]) else None
        result['mfi']    = round(float(df['MFI'].iloc[-1]), 2) if pd.notna(df['MFI'].iloc[-1]) else None
        result['year_high'] = round(float(df['High'].tail(252).max()), 2)

        # Score conditions breakdown
        p = result['last_close']
        result['cond_above_ema200']   = bool(p > result['ema200']) if result['ema200'] else False
        result['cond_above_ema50']    = bool(p > result['ema50']) if result['ema50'] else False
        result['cond_golden_cross']   = bool(result['ema50'] > result['ema200']) if (result['ema50'] and result['ema200']) else False
        result['cond_ema20_aligned']  = bool(p > result['ema20'] > result['ema50'] > result['ema200']) if all([result['ema20'], result['ema50'], result['ema200']]) else False
        result['cond_rsi_ok']         = bool(55 <= (result['rsi'] or 0) <= 75)
        result['cond_near_52w_high']  = bool(p >= result['year_high'] * 0.85)
        result['cond_52w_breakout']   = bool(p >= result['year_high'] * 0.99)
        result['rvol_bullish']        = bool(p >= result['last_open'])

        # Full v2 score
        tech = analyze_momentum_technical_v2(df)
        result['v2_score'] = tech.get('score')
        result['v2_rvol']  = tech.get('rvol')
        result['v2_rsi']   = tech.get('rsi')

    except Exception as e:
        result['exception'] = str(e)

    return JsonResponse(result, json_dumps_params={'indent': 2})


