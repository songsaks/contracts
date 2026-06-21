from .base import * 

@login_required
def crypto_hub(request):
    """
    หน้าต่างศูนย์กลางการวิเคราะห์ Cryptocurrency
    ดึงข้อมูลจาก Alternative.me (Fear & Greed Index) และข้อมูลราคา Real-time เบื้องต้น
    """
    import json
    import urllib.request
    
    # ── Fetch Fear & Greed Index ──
    fng_value = 50
    fng_value_classification = "Neutral"
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if data and "data" in data and len(data["data"]) > 0:
                fng_value = int(data["data"][0]["value"])
                fng_value_classification = data["data"][0]["value_classification"]
    except Exception as e:
        print(f"Error fetching Fear and Greed Index: {e}")

    # กำหนดเหรียญสำคัญ
    crypto_symbols = [
        {'symbol': 'BTC-USD', 'name': 'Bitcoin'},
        {'symbol': 'ETH-USD', 'name': 'Ethereum'},
        {'symbol': 'SOL-USD', 'name': 'Solana'}
    ]

    context = {
        'fng_value': fng_value,
        'fng_classification': fng_value_classification,
        'crypto_symbols': crypto_symbols
    }
    
    return render(request, 'stocks/crypto_hub.html', context)


@login_required
def get_gold_positions_ajax(request):
    """
    ดึงรายการออเดอร์ทองที่เปิดอยู่
    """
    from .trading_bridge import RobotBridge
    bridge = RobotBridge(user=request.user)
    try:
        positions = bridge.get_open_positions()
        return JsonResponse({'success': True, 'positions': positions})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
@login_required
def close_all_gold_positions_ajax(request):
    """
    สั่งปิดออเดอร์ทองทั้งหมด
    """
    from .trading_bridge import RobotBridge
    bridge = RobotBridge(user=request.user)
    try:
        success = bridge.close_all_positions()
        return JsonResponse({'success': success})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
@login_required
def modify_gold_position_ajax(request):
    """แก้ไข SL/TP ของ position ที่เปิดอยู่"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)
    import json

    from .trading_bridge import RobotBridge
    try:
        data = json.loads(request.body)
        position_id = data.get('position_id')
        sl = data.get('sl')
        tp = data.get('tp')
        if not position_id:
            return JsonResponse({'success': False, 'error': 'position_id required'})
        # Basic sanity: SL and TP must be positive numbers
        if sl is not None and float(sl) <= 0:
            return JsonResponse({'success': False, 'error': 'SL must be > 0'})
        if tp is not None and float(tp) <= 0:
            return JsonResponse({'success': False, 'error': 'TP must be > 0'})
        bridge = RobotBridge(user=request.user)
        success, err = bridge.modify_position(position_id=str(position_id), sl=sl, tp=tp)
        if success:
            return JsonResponse({'success': True})
        return JsonResponse({'success': False, 'error': err or 'MetaApi rejected the request'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@csrf_exempt
@login_required
def execute_gold_trade_ajax(request):
    """
    รับคำสั่งจากปุ่มเทรดในหน้า Gold Command Center
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Post required'}, status=400)
    if _check_rate_limit(request.user.id, 'gold_execute', limit=10, window=60):
        return JsonResponse({'success': False, 'error': 'Rate limit: max 10 trades/minute'}, status=429)
    import json

    from .trading_bridge import RobotBridge
    
    try:
        data = json.loads(request.body)
        symbol = data.get('symbol', 'GC=F')
        side   = data.get('side', 'BUY')
        price  = data.get('price')
        sl     = data.get('sl')
        tp     = data.get('tp')
        volume = data.get('volume', 0.01)
        strategy = data.get('strategy', 'Manual')

        # ==========================================
        # 🚨 SERVER-SIDE CIRCUIT BREAKER (MT5 Safety)
        # ==========================================
        try:
            vol_float = float(volume)
            # Hard-Cap ที่ 0.05 Lots ป้องกันพอร์ตระเบิดจากการคำนวณผิดพลาด
            # หากต้องการเพิ่ม ให้แก้ไขค่านี้ (เช่น 0.1 หรือ 0.5) แต่ต้องมั่นใจในความเสี่ยง
            MAX_ALLOWED_LOT = 0.05 
            if vol_float > MAX_ALLOWED_LOT:
                return JsonResponse({
                    'success': False, 
                    'error': f'🚨 CIRCUIT BREAKER: ระบบระงับคำสั่งอัตโนมัติ! ขนาด {vol_float} Lots ใหญ่เกินขีดจำกัดความปลอดภัยที่ {MAX_ALLOWED_LOT} Lots'
                })
            
            # บังคับขั้นต่ำสำหรับ MT5 คือ 0.01
            if vol_float < 0.01:
                vol_float = 0.01
                
            volume = vol_float
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Invalid volume format'})
        # ==========================================

        # เรียกใช้ RobotBridge
        bridge = RobotBridge(user=request.user)
        order = bridge.execute_trade(
            symbol=symbol,
            side=side,
            volume=volume,
            price=price,
            sl=sl,
            tp=tp,
            strategy=strategy
        )

        # บันทึกรายละเอียดเพิ่มเติมที่ execute_trade ยังไม่ได้บันทึก
        try:
            from decimal import Decimal
            signal_source = data.get('signal_source', strategy)
            capital       = data.get('capital', 0)
            risk_pct_val  = data.get('risk_pct', 1)

            if sl and price:
                risk_pts = abs(float(price) - float(sl))
                risk_usd = round(risk_pts * float(volume) * 100, 2)
            else:
                risk_usd = 0

            update_fields = ['signal_source', 'risk_usd']
            order.signal_source = signal_source
            order.risk_usd      = Decimal(str(risk_usd))

            if capital and float(capital) > 0:
                order.risk_pct = Decimal(str(round(risk_usd / float(capital) * 100, 3)))
                update_fields.append('risk_pct')

            order.save(update_fields=update_fields)
        except Exception as ex:
            print(f"Extra detail save error: {ex}")

        return JsonResponse({
            'success': True,
            'order_id': order.order_id,
            'message': f'ส่งคำสั่ง {side} เรียบร้อยแล้ว (ID: {order.order_id})'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def crypto_trading(request):
    """
    Crypto Trading Command Center (BTC/USD).
    """
    from .models import TradingAccount, UserTradingConfig
    account = TradingAccount.objects.filter(user=request.user, is_active=True).first()
    capital = float(account.equity or account.balance) if account else 100.0
    symbol = "BTC-USD"
    
    # ดึงค่าการตั้งค่าล่าสุดของผู้ใช้ (เพื่อ Sync ระหว่างอุปกรณ์)
    config, created = UserTradingConfig.objects.get_or_create(user=request.user)
    
    return render(request, 'stocks/crypto_trading.html', {
        'symbol': symbol,
        'title': 'Crypto Tactical Command Center',
        'capital': capital,
        'account_id': account.id if account else None,
        'config': config,
    })


def get_crypto_pid_file(user_id):
    """สร้างชื่อไฟล์ PID ที่แยกตาม User ID สำหรับบอทคริปโต"""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), f'crypto_bot_{user_id}.pid')


@login_required
def get_crypto_positions_ajax(request):
    """
    ดึงรายการออเดอร์คริปโตที่เปิดอยู่
    """
    from .trading_bridge import RobotBridge
    bridge = RobotBridge(user=request.user)
    try:
        positions = bridge.get_open_positions()
        # กรองเฉพาะ BTCUSD หรือ BTC-USD
        crypto_positions = [pos for pos in positions if pos.get('symbol') in ['BTCUSD', 'BTC-USD']]
        return JsonResponse({'success': True, 'positions': crypto_positions})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@login_required
def close_all_crypto_positions_ajax(request):
    """
    สั่งปิดออเดอร์คริปโตทั้งหมด
    """
    from .trading_bridge import RobotBridge
    bridge = RobotBridge(user=request.user)
    try:
        # ปิดเฉพาะออเดอร์ BTC-USD / BTCUSD
        success = bridge.close_all_positions(symbol='BTC-USD')
        return JsonResponse({'success': success})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@login_required
def modify_crypto_position_ajax(request):
    """แก้ไข SL/TP ของ position คริปโตที่เปิดอยู่"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=400)
    import json

    from .trading_bridge import RobotBridge
    try:
        data = json.loads(request.body)
        position_id = data.get('position_id')
        sl = data.get('sl')
        tp = data.get('tp')
        if not position_id:
            return JsonResponse({'success': False, 'error': 'position_id required'})
        if sl is not None and float(sl) <= 0:
            return JsonResponse({'success': False, 'error': 'SL must be > 0'})
        if tp is not None and float(tp) <= 0:
            return JsonResponse({'success': False, 'error': 'TP must be > 0'})
        bridge = RobotBridge(user=request.user)
        success, err = bridge.modify_position(position_id=str(position_id), sl=sl, tp=tp)
        if success:
            return JsonResponse({'success': True})
        return JsonResponse({'success': False, 'error': err or 'MetaApi rejected the request'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@login_required
def execute_crypto_trade_ajax(request):
    """
    รับคำสั่งจากปุ่มเทรดในหน้า Crypto Command Center
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Post required'}, status=400)
    if _check_rate_limit(request.user.id, 'crypto_execute', limit=10, window=60):
        return JsonResponse({'success': False, 'error': 'Rate limit: max 10 trades/minute'}, status=429)
    import json

    from .trading_bridge import RobotBridge
    
    try:
        data = json.loads(request.body)
        symbol = data.get('symbol', 'BTC-USD')
        side   = data.get('side', 'BUY')
        price  = data.get('price')
        sl     = data.get('sl')
        tp     = data.get('tp')
        volume = data.get('volume', 0.01)
        strategy = data.get('strategy', 'Manual')

        # ==========================================
        # 🚨 SERVER-SIDE CIRCUIT BREAKER (Crypto Safety)
        # ==========================================
        try:
            vol_float = float(volume)
            # Cap ที่ 0.5 Lots สำหรับ Crypto
            MAX_ALLOWED_LOT = 0.5 
            if vol_float > MAX_ALLOWED_LOT:
                return JsonResponse({
                    'success': False, 
                    'error': f'🚨 CIRCUIT BREAKER: ระบบระงับคำสั่งอัตโนมัติ! ขนาด {vol_float} Lots ใหญ่เกินขีดจำกัดความปลอดภัยคริปโตที่ {MAX_ALLOWED_LOT} Lots'
                })
            
            if vol_float < 0.01:
                vol_float = 0.01
                
            volume = vol_float
        except (ValueError, TypeError):
            return JsonResponse({'success': False, 'error': 'Invalid volume format'})
        # ==========================================

        bridge = RobotBridge(user=request.user)
        order = bridge.execute_trade(
            symbol=symbol,
            side=side,
            volume=volume,
            price=price,
            sl=sl,
            tp=tp,
            strategy=strategy
        )

        try:
            from decimal import Decimal
            signal_source = data.get('signal_source', strategy)
            capital       = data.get('capital', 0)

            # Crypto (BTC-USD): point multiplier = 1
            if sl and price:
                risk_pts = abs(float(price) - float(sl))
                risk_usd = round(risk_pts * float(volume) * 1.0, 2)
            else:
                risk_usd = 0

            update_fields = ['signal_source', 'risk_usd']
            order.signal_source = signal_source
            order.risk_usd      = Decimal(str(risk_usd))

            if capital and float(capital) > 0:
                order.risk_pct = Decimal(str(round(risk_usd / float(capital) * 100, 3)))
                update_fields.append('risk_pct')

            order.save(update_fields=update_fields)
        except Exception as ex:
            print(f"Extra detail save error: {ex}")

        return JsonResponse({
            'success': True,
            'order_id': order.order_id,
            'message': f'ส่งคำสั่ง {side} เรียบร้อยแล้ว (ID: {order.order_id})'
        })

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def crypto_price_tick_ajax(request):
    """
    Lightweight endpoint — returns only the current BTC-USD price tick.
    Used by the frontend for fast 2-second price updates.
    """
    import yfinance as _yf
    from django.http import JsonResponse as _JR
    try:
        ticker = _yf.Ticker('BTC-USD')
        fi = ticker.fast_info
        price = float(fi.get('last_price') or fi.get('regularMarketPrice') or 0)
        prev  = float(fi.get('previous_close') or fi.get('regularMarketPreviousClose') or price)
        if price == 0:
            hist = ticker.history(period='1d', interval='1m')
            if not hist.empty:
                price = float(hist['Close'].iloc[-1])
                prev  = float(hist['Close'].iloc[0])
        change     = round(price - prev, 2)
        change_pct = round((change / prev) * 100, 3) if prev else 0.0
        return _JR({'price': round(price, 2), 'change': change, 'change_pct': change_pct, 'ok': True})
    except Exception as e:
        return _JR({'ok': False, 'error': str(e)}, status=500)


# ==============================================================================
# AI Manual Scanner (SEPA & Scanner Guide)
# ==============================================================================

@login_required
def get_crypto_bot_status_ajax(request):
    """
    ดึงสถานะล่าสุดของบอทคริปโตที่แยกตาม User
    """
    from django.utils import timezone

    from .models import BotActivity
    
    user_pid_file = get_crypto_pid_file(request.user.id)
    bot_display_name = f"Crypto Bot (User: {request.user.username})"
    
    is_process_alive = False
    if os.path.exists(user_pid_file):
        try:
            with open(user_pid_file, 'r') as f:
                pid = int(f.read().strip())
            if os.name == 'nt':
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
                if handle:
                    is_process_alive = True
                    ctypes.windll.kernel32.CloseHandle(handle)
            else:
                os.kill(pid, 0)
                is_process_alive = True
        except:
            is_process_alive = False

    try:
        activity = BotActivity.objects.get(bot_name=bot_display_name)
        diff = timezone.now() - activity.last_heartbeat
        is_active = (activity.status == "ACTIVE" and diff.total_seconds() < 300) or is_process_alive
        
        return JsonResponse({
            'status': "ACTIVE" if is_active else "OFFLINE",
            'last_heartbeat': activity.last_heartbeat.strftime('%H:%M:%S'),
            'message': activity.message,
            'is_alive': is_active,
            'process_running': is_process_alive
        })
    except BotActivity.DoesNotExist:
        return JsonResponse({
            'status': "ACTIVE" if is_process_alive else "OFFLINE",
            'is_alive': is_process_alive,
            'process_running': is_process_alive
        })


@login_required
def start_crypto_bot_ajax(request):
    """สั่งเริ่มการทำงานของบอทคริปโต (Isolated by User)"""
    user_pid_file = get_crypto_pid_file(request.user.id)
    bot_display_name = f"Crypto Bot (User: {request.user.username})"

    if _check_rate_limit(request.user.id, 'crypto_bot_start', limit=3, window=60):
        return JsonResponse({'success': False, 'error': 'Rate limit exceeded'})

    if os.path.exists(user_pid_file):
        try:
            with open(user_pid_file, 'r') as f:
                pid = int(f.read().strip())
            if os.name == 'nt':
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return JsonResponse({'success': False, 'error': 'Bot is already running'})
            else:
                os.kill(pid, 0)
                return JsonResponse({'success': False, 'error': 'Bot is already running'})
        except:
            if os.path.exists(user_pid_file): os.remove(user_pid_file)

    try:
        import sys
        python_exe = sys.executable
        log_dir = os.path.dirname(os.path.dirname(__file__))
        strategy = request.GET.get('strategy', 'SNIPER')
        
        cmd_args = [python_exe, 'manage.py', 'run_crypto_bot', 
                    '--strategy', strategy, 
                    '--user_id', str(request.user.id), 
                    '--once']
        
        if os.name == 'nt':
            process = subprocess.Popen(cmd_args, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            stdout_log = open(os.path.join(log_dir, f'crypto_bot_user_{request.user.id}.log'), 'a')
            process = subprocess.Popen(cmd_args, stdout=stdout_log, stderr=stdout_log, start_new_session=True)
        
        with open(user_pid_file, 'w') as f:
            f.write(str(process.pid))
            
        from .models import BotActivity
        BotActivity.objects.update_or_create(
            bot_name=bot_display_name,
            defaults={'status': 'ACTIVE', 'message': f'Running ({strategy})'}
        )
            
        return JsonResponse({'success': True, 'pid': process.pid})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def stop_crypto_bot_ajax(request):
    """สั่งหยุดบอทคริปโต (Isolated by User)"""
    import signal

    from .models import BotActivity
    user_pid_file = get_crypto_pid_file(request.user.id)
    bot_display_name = f"Crypto Bot (User: {request.user.username})"
    
    if not os.path.exists(user_pid_file):
        BotActivity.objects.filter(bot_name=bot_display_name).update(status="STOPPED", message="Bot stopped (PID not found)")
        return JsonResponse({'success': False, 'error': 'No running bot found'})
    
    try:
        with open(user_pid_file, 'r') as f:
            pid = int(f.read())
        
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)
        else:
            try: os.kill(pid, signal.SIGTERM)
            except: pass
            subprocess.run(['pkill', '-f', f'--user_id {request.user.id}'], capture_output=True)

        if os.path.exists(user_pid_file): os.remove(user_pid_file)
        BotActivity.objects.filter(bot_name=bot_display_name).update(status="STOPPED", message="Stopped by user")
        return JsonResponse({'success': True})
    except Exception as e:
        if os.path.exists(user_pid_file): os.remove(user_pid_file)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_crypto_trade_history_ajax(request):
    """ดึงประวัติการเทรดคริปโต พร้อมรายละเอียดครบ + สถิติสรุป"""
    from django.db.models import Sum
    from django.utils import timezone

    from .models import TradeOrder, TradingAccount
    from .trading_bridge import RobotBridge

    # 1. Auto-Sync สถานะออเดอร์ก่อนแสดงผล
    sync_errors = []
    acc = TradingAccount.objects.filter(user=request.user, is_active=True).first()
    if acc:
        try:
            bridge = RobotBridge(account=acc)
            sync_result = bridge.sync_trade_status()
            if isinstance(sync_result, dict) and sync_result.get('errors'):
                sync_errors = sync_result['errors']
        except Exception as e:
            sync_errors.append(str(e))
            print(f"History Sync Error: {e}")

    # 2. รองรับ filter ตามช่วงเวลา
    date_filter = request.GET.get('range', '7d')
    now = timezone.now()
    if date_filter == '1d':
        since = now - timezone.timedelta(days=1)
    elif date_filter == '30d':
        since = now - timezone.timedelta(days=30)
    elif date_filter == 'all':
        since = None
    else:  # default 7d
        since = now - timezone.timedelta(days=7)

    # กรองเฉพาะ BTC-USD หรือ BTCUSD
    qs = TradeOrder.objects.filter(user=request.user, symbol__in=['BTC-USD', 'BTCUSD'])
    if since:
        qs = qs.filter(created_at__gte=since)
    orders = qs.order_by('-opened_at', '-created_at')[:100]

    # 3. สถิติสรุป
    closed_qs = qs.filter(status='CLOSED')
    stats = {
        'total':     qs.count(),
        'closed':    closed_qs.count(),
        'open':      qs.filter(status='OPEN').count(),
        'wins':      closed_qs.filter(profit_loss__gt=0).count(),
        'losses':    closed_qs.filter(profit_loss__lt=0).count(),
        'total_pl':  float(closed_qs.aggregate(s=Sum('profit_loss'))['s'] or 0),
        'total_comm':float(closed_qs.aggregate(s=Sum('commission'))['s'] or 0),
        'total_swap':float(closed_qs.aggregate(s=Sum('swap'))['s'] or 0),
    }
    stats['win_rate'] = round(stats['wins'] / stats['closed'] * 100, 1) if stats['closed'] else 0

    order_list = []
    for o in orders:
        order_list.append({
            'id':          o.id,
            'order_id':    o.order_id,
            'symbol':      o.symbol,
            'order_type':  o.order_type,
            'volume':      float(o.volume or 0),
            'entry_price': float(o.entry_price or 0),
            'exit_price':  float(o.exit_price or 0) if o.exit_price else None,
            'stop_loss':   float(o.stop_loss or 0) if o.stop_loss else None,
            'take_profit': float(o.take_profit or 0) if o.take_profit else None,
            'profit_loss': float(o.profit_loss or 0),
            'status':      o.status,
            'opened_at':   timezone.localtime(o.opened_at).strftime('%Y-%m-%d %H:%M:%S') if o.opened_at else '',
            'closed_at':   timezone.localtime(o.closed_at).strftime('%Y-%m-%d %H:%M:%S') if o.closed_at else '',
            'duration':    o.duration_display if o.opened_at and o.closed_at else '',
            'strategy':    o.signal_source or 'Manual',
            'risk_usd':    float(o.risk_usd or 0),
            'risk_pct':    float(o.risk_pct or 0),
            'rr':          float(o.actual_rr or 0)
        })

    return JsonResponse({
        'success': True,
        'orders': order_list,
        'stats': stats,
        'sync_errors': sync_errors
    }, json_dumps_params={'ensure_ascii': False})

@login_required
def gold_price_tick_ajax(request):
    """
    Lightweight endpoint — returns only the current gold price tick.
    Used by the frontend for fast 2-second price updates.
    """
    import yfinance as _yf
    from django.http import JsonResponse as _JR
    try:
        ticker = _yf.Ticker('GC=F')
        fi = ticker.fast_info
        price = float(fi.get('last_price') or fi.get('regularMarketPrice') or 0)
        prev  = float(fi.get('previous_close') or fi.get('regularMarketPreviousClose') or price)
        if price == 0:
            hist = ticker.history(period='1d', interval='1m')
            if not hist.empty:
                price = float(hist['Close'].iloc[-1])
                prev  = float(hist['Close'].iloc[0])
        change     = round(price - prev, 2)
        change_pct = round((change / prev) * 100, 3) if prev else 0.0
        return _JR({'price': round(price, 2), 'change': change, 'change_pct': change_pct, 'ok': True})
    except Exception as e:
        return _JR({'ok': False, 'error': str(e)}, status=500)


@login_required
def gold_trading(request):
    """
    Gold Trading & Robot Command Center (XAU/USD).
    """
    from .models import TradingAccount, UserTradingConfig
    account = TradingAccount.objects.filter(user=request.user, is_active=True).first()
    capital = float(account.equity or account.balance) if account else 100.0
    symbol = "GC=F"
    
    # ดึงค่าการตั้งค่าล่าสุดของผู้ใช้ (เพื่อ Sync ระหว่างอุปกรณ์)
    config, created = UserTradingConfig.objects.get_or_create(user=request.user)
    
    return render(request, 'stocks/gold_trading.html', {
        'symbol': symbol,
        'title': 'Gold Robot Command Center',
        'market': 'US',
        'capital': capital,
        'config': config,
    })


def get_user_pid_file(user_id):
    """สร้างชื่อไฟล์ PID ที่แยกตาม User ID"""
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), f'gold_bot_{user_id}.pid')

@login_required
def get_bot_status_ajax(request):
    """
    ดึงสถานะล่าสุดของบอทที่แยกตาม User
    """
    from django.contrib.auth.models import User
    from django.utils import timezone

    from .models import BotActivity, TradingAccount
    
    user_pid_file = get_user_pid_file(request.user.id)
    bot_display_name = f"Gold Bot (User: {request.user.username})"
    
    # 1. เช็ค Process จริงในเครื่อง (แยกตาม PID ของ User)
    is_process_alive = False
    if os.path.exists(user_pid_file):
        try:
            with open(user_pid_file, 'r') as f:
                pid = int(f.read().strip())
            if os.name == 'nt':
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
                if handle:
                    is_process_alive = True
                    ctypes.windll.kernel32.CloseHandle(handle)
            else:
                os.kill(pid, 0)
                is_process_alive = True
        except:
            is_process_alive = False

    # 2. ดึงข้อมูลจากฐานข้อมูล (BotActivity)
    try:
        activity = BotActivity.objects.get(bot_name=bot_display_name)
        diff = timezone.now() - activity.last_heartbeat
        is_active = (activity.status == "ACTIVE" and diff.total_seconds() < 300) or is_process_alive
        
        return JsonResponse({
            'status': "ACTIVE" if is_active else "OFFLINE",
            'last_heartbeat': activity.last_heartbeat.strftime('%H:%M:%S'),
            'message': activity.message,
            'is_alive': is_active,
            'process_running': is_process_alive
        })
    except BotActivity.DoesNotExist:
        return JsonResponse({
            'status': "ACTIVE" if is_process_alive else "OFFLINE",
            'is_alive': is_process_alive,
            'process_running': is_process_alive
        })

@login_required
def start_gold_bot_ajax(request):
    """สั่งเริ่มการทำงานของบอท (Isolated by User)"""
    user_pid_file = get_user_pid_file(request.user.id)
    bot_display_name = f"Gold Bot (User: {request.user.username})"

    if _check_rate_limit(request.user.id, 'gold_bot_start', limit=3, window=60):
        return JsonResponse({'success': False, 'error': 'Rate limit exceeded'})

    if os.path.exists(user_pid_file):
        # Cleanup old PID if it's dead
        try:
            with open(user_pid_file, 'r') as f:
                pid = int(f.read().strip())
            if os.name == 'nt':
                import ctypes
                handle = ctypes.windll.kernel32.OpenProcess(0x0400, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return JsonResponse({'success': False, 'error': 'Bot is already running'})
            else:
                os.kill(pid, 0)
                return JsonResponse({'success': False, 'error': 'Bot is already running'})
        except:
            if os.path.exists(user_pid_file): os.remove(user_pid_file)

    try:
        import sys
        python_exe = sys.executable
        log_dir = os.path.dirname(os.path.dirname(__file__))
        strategy = request.GET.get('strategy', 'SNIPER')
        
        # รัน management command พร้อมส่ง --user_id
        cmd_args = [python_exe, 'manage.py', 'run_gold_bot', 
                    '--strategy', strategy, 
                    '--user_id', str(request.user.id), 
                    '--once']
        
        if os.name == 'nt':
            process = subprocess.Popen(cmd_args, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            stdout_log = open(os.path.join(log_dir, f'bot_user_{request.user.id}.log'), 'a')
            process = subprocess.Popen(cmd_args, stdout=stdout_log, stderr=stdout_log, start_new_session=True)
        
        with open(user_pid_file, 'w') as f:
            f.write(str(process.pid))
            
        from .models import BotActivity
        BotActivity.objects.update_or_create(
            bot_name=bot_display_name,
            defaults={'status': 'ACTIVE', 'message': f'Running ({strategy})'}
        )
            
        return JsonResponse({'success': True, 'pid': process.pid})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def save_gold_config_ajax(request):
    """บันทึกการตั้งค่า UI (Alerts, Targets, Risk) ลงฐานข้อมูลเพื่อ Sync ข้ามเครื่อง"""
    import json

    from .models import UserTradingConfig
    try:
        data = json.loads(request.body)
        config, created = UserTradingConfig.objects.get_or_create(user=request.user)
        
        # Smart Alerts
        if 'alert_enabled' in data: config.alert_enabled = bool(data['alert_enabled'])
        if 'alert_high' in data: config.alert_high_target = float(data['alert_high']) if data['alert_high'] else None
        if 'alert_low' in data: config.alert_low_target = float(data['alert_low']) if data['alert_low'] else None
        
        # Risk Management
        if 'capital' in data: config.default_capital = float(data['capital'])
        if 'risk_pct' in data: config.default_risk_pct = float(data['risk_pct'])
        
        config.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def stop_gold_bot_ajax(request):
    """สั่งหยุดบอท (Isolated by User)"""
    import signal

    from .models import BotActivity
    user_pid_file = get_user_pid_file(request.user.id)
    bot_display_name = f"Gold Bot (User: {request.user.username})"
    
    if not os.path.exists(user_pid_file):
        BotActivity.objects.filter(bot_name=bot_display_name).update(status="STOPPED", message="Bot stopped (PID not found)")
        return JsonResponse({'success': False, 'error': 'No running bot found'})
    
    try:
        with open(user_pid_file, 'r') as f:
            pid = int(f.read())
        
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True)
        else:
            try: os.kill(pid, signal.SIGTERM)
            except: pass
            # กวาดล้างเฉพาะ process ที่รันด้วย user_id นี้
            subprocess.run(['pkill', '-f', f'--user_id {request.user.id}'], capture_output=True)

        if os.path.exists(user_pid_file): os.remove(user_pid_file)
        BotActivity.objects.filter(bot_name=bot_display_name).update(status="STOPPED", message="Stopped by user")
        return JsonResponse({'success': True})
    except Exception as e:
        if os.path.exists(user_pid_file): os.remove(user_pid_file)
        return JsonResponse({'success': False, 'error': str(e)})

# ====== Investment Dashboard (Premium Insights) ======

@login_required
def get_gold_trade_history_ajax(request):
    """ดึงประวัติการเทรด พร้อมรายละเอียดครบ + สถิติสรุป"""
    from django.db.models import Count, Q, Sum
    from django.utils import timezone

    from .models import TradeOrder, TradingAccount
    from .trading_bridge import RobotBridge

    # 1. Auto-Sync สถานะออเดอร์ก่อนแสดงผล
    sync_errors = []
    acc = TradingAccount.objects.filter(user=request.user, is_active=True).first()
    if acc:
        try:
            bridge = RobotBridge(account=acc)
            sync_result = bridge.sync_trade_status()
            if isinstance(sync_result, dict) and sync_result.get('errors'):
                sync_errors = sync_result['errors']
        except Exception as e:
            sync_errors.append(str(e))
            print(f"History Sync Error: {e}")

    # 2. รองรับ filter ตามช่วงเวลา
    date_filter = request.GET.get('range', '7d')
    now = timezone.now()
    if date_filter == '1d':
        since = now - timezone.timedelta(days=1)
    elif date_filter == '30d':
        since = now - timezone.timedelta(days=30)
    elif date_filter == 'all':
        since = None
    else:  # default 7d
        since = now - timezone.timedelta(days=7)

    qs = TradeOrder.objects.filter(user=request.user, symbol__in=['GC=F', 'XAUUSD'])
    if since:
        qs = qs.filter(created_at__gte=since)
    orders = qs.order_by('-opened_at', '-created_at')[:100]

    # 3. สถิติสรุป
    closed_qs = qs.filter(status='CLOSED')
    stats = {
        'total':     qs.count(),
        'closed':    closed_qs.count(),
        'open':      qs.filter(status='OPEN').count(),
        'wins':      closed_qs.filter(profit_loss__gt=0).count(),
        'losses':    closed_qs.filter(profit_loss__lt=0).count(),
        'total_pl':  float(closed_qs.aggregate(s=Sum('profit_loss'))['s'] or 0),
        'total_comm':float(closed_qs.aggregate(s=Sum('commission'))['s'] or 0),
        'total_swap':float(closed_qs.aggregate(s=Sum('swap'))['s'] or 0),
    }
    stats['win_rate'] = round(stats['wins'] / stats['closed'] * 100, 1) if stats['closed'] else 0

    def _f(v): return float(v) if v is not None else 0

    data = []
    for o in orders:
        opened = o.opened_at or o.created_at
        closed = o.closed_at
        data.append({
            'id':           o.id,
            'order_id':     o.order_id or '-',
            'symbol':       o.symbol,
            'type':         o.order_type,
            'volume':       _f(o.volume),
            'entry':        _f(o.entry_price),
            'exit':         _f(o.exit_price),
            'sl':           _f(o.stop_loss),
            'tp':           _f(o.take_profit),
            'pl':           _f(o.profit_loss),
            'gross_pl':     _f(o.gross_pl),
            'commission':   _f(o.commission),
            'swap':         _f(o.swap),
            'pips':         _f(o.pips),
            'risk_usd':     _f(o.risk_usd),
            'risk_pct':     _f(o.risk_pct),
            'actual_rr':    _f(o.actual_rr),
            'duration':     o.duration_display,
            'status':       o.status,
            'strategy':     o.strategy or 'Manual',
            'signal_source':o.signal_source or '',
            'exit_reason':  o.exit_reason or '',
            'comment':      o.comment or '',
            'opened_at':    timezone.localtime(opened).strftime('%Y-%m-%d %H:%M') if opened else '-',
            'closed_at':    timezone.localtime(closed).strftime('%Y-%m-%d %H:%M') if closed else '-',
        })

    return JsonResponse({'success': True, 'history': data, 'stats': stats, 'sync_errors': sync_errors})


