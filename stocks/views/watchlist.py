from .base import * 

from .base import (
    _get_usd_thb, _compute_signals, _get_market_condition, _get_precision_scan_data,
    _US_SECTOR_MAP, _US_MOMENTUM_SYMBOLS, _build_us_symbol_set, _is_us_symbol,
    _seed_us_symbols, _seed_value_symbols, _score_value_candidate, _check_rate_limit
)

@login_required
def add_to_watchlist(request):
    """รับ POST form เพิ่ม symbol เข้า Watchlist ของ user ปัจจุบัน"""
    if request.method == 'POST':
        form = AddWatchlistForm(request.POST)
        if form.is_valid():
            symbol = form.cleaned_data['symbol']
            Watchlist.objects.get_or_create(
                user=request.user,
                symbol=symbol,
                defaults={
                    'name': form.cleaned_data['name'],
                    'category': form.cleaned_data['category'],
                }
            )
            messages.success(request, f"เพิ่ม {symbol} เข้าใน Watchlist แล้ว")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{error}")

    return redirect('stocks:dashboard')

@login_required
def delete_from_watchlist(request, pk):
    """ลบรายการ Watchlist ตาม pk (เฉพาะของ user ปัจจุบันเท่านั้น)"""
    item = get_object_or_404(Watchlist, pk=pk, user=request.user)
    symbol = item.symbol
    item.delete()
    messages.success(request, f"ลบ {symbol} ออกจาก Watchlist แล้ว")
    return redirect('stocks:dashboard')

# ====== Portfolio - แสดงพอร์ตการลงทุนพร้อมวิเคราะห์ AI ======

@login_required
def watchlist_item_toggle(request):
    """AJAX POST - เพิ่ม/ลบหุ้นออกจาก ScanWatchlistItem และส่งไปที่ Market Watchlist (สำหรับรับ Alert เข้า Telegram)"""
    import json

    from django.http import JsonResponse

    from stocks.models import ScanWatchlistItem, Watchlist
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    try:
        data = json.loads(request.body)
    except (ValueError, KeyError):
        return JsonResponse({'error': 'invalid JSON'}, status=400)
    symbol   = data.get('symbol', '').strip().upper()
    sector   = data.get('sector', 'Unknown')
    market   = data.get('market', 'SET')
    strategy = data.get('strategy', 'PRECISION')
    note     = data.get('note', '')

    if not symbol:
        return JsonResponse({'error': 'symbol required'}, status=400)
        
    obj, created = ScanWatchlistItem.objects.get_or_create(
        user=request.user, symbol=symbol, market=market,
        defaults={'sector': sector, 'strategy': strategy, 'note': note}
    )
    
    if not created:
        # หากมีอยู่แล้ว ให้ลบออก (Un-toggle)
        obj.delete()
        if market == 'SET':
            Watchlist.objects.filter(user=request.user, symbol=symbol).delete()
        return JsonResponse({'status': 'removed', 'symbol': symbol})
        
    # หากเพิ่มใหม่ ให้อัปเดตค่าหากมีการส่งมา (กรณี get_or_create ใช้ defaults แค่ตอนสร้าง)
    obj.strategy = strategy
    obj.note     = note
    obj.save()

    # สำหรับ SET สั่งให้เพิ่มเข้าไปที่ฝั่ง Market Watchlist ด้วย
    if market == 'SET':
        # เราเก็บข้อมูล Pattern/Strategy ลงในฟิลด์ strategy ของ Portfolio ได้ แต่ Watchlist ปกติไม่มี
        # ดังนั้นจะเน้นเก็บใน ScanWatchlistItem เป็นหลัก
        Watchlist.objects.get_or_create(user=request.user, symbol=symbol)
    
    return JsonResponse({'status': 'added', 'symbol': symbol})


@login_required
def scan_watchlist_view(request):
    """แสดง Scan Watchlist พร้อม score ปัจจุบัน / รอบก่อน / delta / alert"""
    from stocks.models import PrecisionScanCandidate, ScanWatchlistItem
    
    market = request.GET.get('market', 'SET')
    items = ScanWatchlistItem.objects.filter(user=request.user, market=market)

    runs = list(
        PrecisionScanCandidate.objects
        .filter(user=request.user, market=market)
        .values_list('scan_run', flat=True)
        .order_by('-scan_run')
        .distinct()[:2]
    )
    latest_run = runs[0] if len(runs) >= 1 else None
    prev_run   = runs[1] if len(runs) >= 2 else None

    latest_map = {c.symbol: c for c in PrecisionScanCandidate.objects.filter(user=request.user, market=market, scan_run=latest_run)} if latest_run else {}
    prev_map   = {c.symbol: c for c in PrecisionScanCandidate.objects.filter(user=request.user, market=market, scan_run=prev_run)}   if prev_run   else {}

    # ดึง Markov Regime ครั้งเดียวนอกลูป - DatabaseCache get = 1 DB query ไม่ควรทำซ้ำต่อ item
    from django.core.cache import cache as _regime_cache

    from stocks.utils import calculate_markov_regime

    _regime_key = 'markov_regime_set' if market == 'SET' else 'markov_regime_us'
    markov_regime = _regime_cache.get(_regime_key)
    if not markov_regime:
        index_symbol = '^SET.BK' if market == 'SET' else '^GSPC'
        markov_regime = calculate_markov_regime(index_symbol, window=60)
        _regime_cache.set(_regime_key, markov_regime, 1800) # 30 min cache
    m_state = markov_regime.get('state', 'UNKNOWN')
    m_prob = markov_regime.get('prob', 0) / 100.0

    enriched = []
    for item in items:
        latest = latest_map.get(item.symbol)
        prev   = prev_map.get(item.symbol)
        cur_score  = latest.technical_score if latest else None
        prev_score = prev.technical_score   if prev   else None
        delta = (cur_score - prev_score) if (cur_score is not None and prev_score is not None) else None
        
        # Calculate tactical action signals
        in_buy_zone = False
        near_buy_zone = False
        at_tp = False
        buy_score = 0
        sell_score = 0
        win_prob = 35.0
        zone_prox = 999.0
        
        if latest:
            # 1. Compute dynamic Buy/Sell/Exit signals
            sigs = _compute_signals(latest)
            buy_score = sigs['buy_score']
            sell_score = sigs['sell_score']
            
            # Attach dynamically so template and properties access work cleanly
            latest.buy_score = buy_score
            latest.sell_score = sell_score

            # 2. Calculate Win Probability (markov regime ดึงไว้แล้วนอกลูป)
            score = 35.0
            rs_val = getattr(latest, 'rs_rating', 0) or 0
            score += (rs_val / 99.0) * 25.0
            tech_val = getattr(latest, 'technical_score', 0) or 0
            score += (min(tech_val, 100) / 100.0) * 15.0
            adx_val = getattr(latest, 'adx', 0) or 0
            score += (min(adx_val, 50) / 50.0) * 10.0
            cmf_val = getattr(latest, 'cmf', 0) or 0
            vol_surge = getattr(latest, 'volume_surge', 1.0) or 1.0
            if cmf_val > 0.15: score += 10.0
            elif cmf_val > 0: score += 5.0
            if vol_surge >= 1.5: score += 5.0
            elif vol_surge >= 1.2: score += 2.0
            if m_state == 'TRENDING': score += 10.0 * (0.5 + 0.5 * m_prob)
            elif m_state == 'CHOPPY': score += 4.0
            elif m_state == 'UNKNOWN' and m_prob == 0: score += 5.0
            
            prox = getattr(latest, 'zone_proximity', 99)
            if prox > 15 and prox < 100: score -= 10.0
            elif prox > 10 and prox < 100: score -= 5.0
            win_prob = round(max(min(score, 98.2), 30.0), 1)
            
            latest.win_probability = win_prob
            zone_prox = latest.zone_proximity if latest.zone_proximity is not None else 999.0
            
            price_val = latest.price
            if latest.demand_zone_start and latest.demand_zone_end:
                in_buy_zone = (price_val <= latest.demand_zone_start) and (price_val >= latest.demand_zone_end)
                near_buy_zone = (not in_buy_zone) and (latest.zone_proximity is not None and latest.zone_proximity <= 5.0)
            if latest.supply_zone_start:
                at_tp = (price_val >= latest.supply_zone_start)

        enriched.append({
            'watchlist':   item,
            'scan_data':   latest,
            'delta':       delta,
            'triggered':   cur_score is not None and cur_score >= item.alert_threshold,
            'in_buy_zone': in_buy_zone,
            'near_buy_zone': near_buy_zone,
            'at_tp': at_tp,
            'buy_score': buy_score,
            'win_probability': win_prob,
            'zone_proximity': zone_prox,
        })

    # Sort results
    sort_by = request.GET.get('sort', 'actionable')
    if sort_by == 'actionable':
        # In Buy Zone first, then Near Zone, then highest Buy Score, then highest Win Probability
        enriched.sort(key=lambda x: (
            -int(x['in_buy_zone']),
            -int(x['near_buy_zone']),
            -(x['buy_score'] or 0),
            -(x['win_probability'] or 0),
            x['watchlist'].symbol
        ))
    elif sort_by == 'buy_score':
        enriched.sort(key=lambda x: (
            -(x['buy_score'] or 0),
            -(x['win_probability'] or 0),
            x['watchlist'].symbol
        ))
    elif sort_by == 'win_prob':
        enriched.sort(key=lambda x: (
            -(x['win_probability'] or 0),
            -(x['buy_score'] or 0),
            x['watchlist'].symbol
        ))
    elif sort_by == 'prox':
        enriched.sort(key=lambda x: (
            (x['zone_proximity'] if x['zone_proximity'] is not None else 999.0),
            -(x['buy_score'] or 0),
            x['watchlist'].symbol
        ))
    elif sort_by == 'symbol':
        enriched.sort(key=lambda x: x['watchlist'].symbol)

    return render(request, 'stocks/scan_watchlist.html', {
        'items':       enriched,
        'latest_run':  latest_run,
        'market':      market,
        'current_sort': sort_by,
    })


