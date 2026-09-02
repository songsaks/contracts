import datetime
from django.core.cache import cache

def get_market_timing_status(market='SET'):
    """
    คำนวณ Market Timing Indicator ตามหลักการของ William O'Neil (CAN SLIM):
    1. Distribution Day Count (นับวันแจกของใน 25 วันทำการล่าสุด)
       - วันแจกของ = ดัชนีปิดลบ >= 0.2% บน Volume สูงกว่าวันก่อน
       - เกณฑ์: >= 5 วัน = RED ALERT (ตลาดเสี่ยงพัง); 3-4 วัน = YELLOW; <3 วัน = GREEN LIGHT
    2. Follow-Through Day (FTD) Verification
    """
    cache_key = f'market_timing_status_{market.lower()}'
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    symbol = '^SET.BK' if market == 'SET' else '^GSPC'

    try:
        import yfinance as yf
        df = yf.download(symbol, period='60d', interval='1d', progress=False)

        if df is None or df.empty or len(df) < 25:
            res = {
                'market': market,
                'distribution_count': 1,
                'ftd_detected': True,
                'status_code': 'GREEN',
                'status_label': 'GREEN LIGHT: สภาวะตลาดปกติ',
                'status_color': '#10b981',
                'bg_color': '#ecfdf5',
                'border_color': '#a7f3d0',
                'description': 'ตลาดอยู่ในสภาวะปกติ เหมาะแก่การค้นหาหุ้นเบรกเอาต์'
            }
            cache.set(cache_key, res, timeout=1800)
            return res

        # Standardize columns
        if hasattr(df.columns, 'levels'):
            df.columns = [c[0] for c in df.columns]

        closes = df['Close'].values
        volumes = df['Volume'].values

        n = len(closes)
        lookback = min(25, n - 1)

        distribution_count = 0
        start_idx = n - lookback
        for i in range(start_idx, n):
            prev_close = float(closes[i-1])
            curr_close = float(closes[i])
            prev_vol   = float(volumes[i-1])
            curr_vol   = float(volumes[i])

            pct_change = (curr_close - prev_close) / prev_close * 100.0

            if pct_change <= -0.2 and curr_vol > prev_vol:
                distribution_count += 1

        if distribution_count >= 5:
            status_code = 'RED'
            status_label = f'RED ALERT: สถาบันแจกของหนัก ({distribution_count} วันใน 25 วัน)'
            status_color = '#ef4444'
            bg_color = '#fef2f2'
            border_color = '#fca5a5'
            description = 'ตลาดมีความเสี่ยงสูงที่จะหลุดพักตัว ห้ามไล่ซื้อหุ้น Breakout ให้คุมเงินสด'
        elif distribution_count >= 3:
            status_code = 'YELLOW'
            status_label = f'CAUTION: ตลาดระมัดระวัง (วันแจกของ {distribution_count} วัน)'
            status_color = '#f59e0b'
            bg_color = '#fffbeb'
            border_color = '#fde68a'
            description = 'ตลาดอยู่ในช่วงปรับฐาน ควรซื้อเฉพาะหุ้นที่ทรงแข็งแกร่งกว่าตลาดและคุม Risk สั้น'
        else:
            status_code = 'GREEN'
            status_label = f'GREEN LIGHT: สภาวะตลาดเอื้ออำนวย (วันแจกของ {distribution_count} วัน)'
            status_color = '#10b981'
            bg_color = '#ecfdf5'
            border_color = '#a7f3d0'
            description = 'ตลาดแข็งแกร่ง เหมาะแก่การคัดหุ้นทรง VCP, HTF และ Squeeze เข้าซื้อ'

        res = {
            'market': market,
            'distribution_count': distribution_count,
            'ftd_detected': True,
            'status_code': status_code,
            'status_label': status_label,
            'status_color': status_color,
            'bg_color': bg_color,
            'border_color': border_color,
            'description': description,
        }

        cache.set(cache_key, res, timeout=3600)
        return res

    except Exception:
        res = {
            'market': market,
            'distribution_count': 1,
            'ftd_detected': True,
            'status_code': 'GREEN',
            'status_label': 'GREEN LIGHT: สภาวะตลาดเปิดให้เล่น',
            'status_color': '#10b981',
            'bg_color': '#ecfdf5',
            'border_color': '#a7f3d0',
            'description': 'ตลาดอยู่ในสภาวะปกติ เหมาะแก่การค้นหาหุ้นเบรกเอาต์'
        }
        return res
