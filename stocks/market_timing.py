import datetime
from django.core.cache import cache


def _detect_follow_through_day(closes, volumes, lookback_low=50):
    """
    Follow-Through Day (FTD) ตามหลัก William O'Neil:
    1. หา "Day 1" ของความพยายามฟื้นตัว (rally attempt) = วันแรกที่ดัชนีปิดบวก
       หลังจากทำจุดต่ำสุดใน lookback_low วันล่าสุด
    2. นับจาก Day 1 เป็นต้นไป ถ้ามีวันใดในช่วง Day 4-11 ที่ดัชนีปิดบวก >= 1.25%
       ด้วยวอลุ่มมากกว่าวันก่อนหน้า -> ยืนยัน Follow-Through Day (ตลาดกลับตัวขึ้นจริง)

    คืนค่า: ftd_detected, ftd_idx (index ใน array), day1_idx, days_since_ftd
    """
    n = len(closes)
    if n < 10:
        return {'ftd_detected': False, 'ftd_idx': None, 'day1_idx': None, 'days_since_ftd': None}

    window_start = max(0, n - lookback_low)
    low_idx = window_start + int(_argmin(closes[window_start:n]))

    # หา Day 1: วันแรกหลังจุดต่ำสุดที่ปิดบวก (ต้องมีอย่างน้อย 1 วันถัดจาก low ให้ตรวจ)
    day1_idx = None
    for i in range(low_idx + 1, n):
        if closes[i] > closes[i - 1]:
            day1_idx = i
            break

    if day1_idx is None:
        return {'ftd_detected': False, 'ftd_idx': None, 'day1_idx': None, 'days_since_ftd': None}

    ftd_idx = None
    # Day 4 ถึง Day 11 นับจาก Day 1 (รวม Day 1 เป็นวันที่ 1)
    for i in range(day1_idx + 3, min(day1_idx + 11, n)):
        day_ret = (closes[i] - closes[i - 1]) / closes[i - 1] * 100.0
        if day_ret >= 1.25 and volumes[i] > volumes[i - 1]:
            ftd_idx = i
            break

    if ftd_idx is None:
        return {'ftd_detected': False, 'ftd_idx': None, 'day1_idx': day1_idx, 'days_since_ftd': None}

    return {
        'ftd_detected': True,
        'ftd_idx': ftd_idx,
        'day1_idx': day1_idx,
        'days_since_ftd': (n - 1) - ftd_idx,
    }


def _argmin(arr):
    lo = 0
    for i in range(1, len(arr)):
        if arr[i] < arr[lo]:
            lo = i
    return lo


def get_market_timing_status(market='SET'):
    """
    คำนวณ Market Timing Indicator ตามหลักการของ William O'Neil (CAN SLIM):
    1. Distribution Day Count (นับวันแจกของใน 25 วันทำการล่าสุด)
       - วันแจกของ = ดัชนีปิดลบ >= 0.2% บน Volume สูงกว่าวันก่อน
       - เกณฑ์: >= 5 วัน = RED ALERT (ตลาดเสี่ยงพัง); 3-4 วัน = YELLOW; <3 วัน = GREEN LIGHT
    2. Follow-Through Day (FTD) Verification — หลังยืนยัน FTD จริง ระบบจะนับ
       Distribution Day ใหม่เฉพาะวันหลัง FTD เท่านั้น (ของก่อนหน้าถือว่า "ล้าง" แล้ว
       ตามหลัก IBD ว่าการฟื้นตัวที่ยืนยันแล้วทำให้แรงขายสถาบันก่อนหน้าหมดความหมาย)
    """
    cache_key = f'market_timing_status_{market.lower()}'
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    symbol = '^SET.BK' if market == 'SET' else '^GSPC'

    try:
        import yfinance as yf
        df = yf.download(symbol, period='90d', interval='1d', progress=False)

        if df is None or df.empty or len(df) < 25:
            res = {
                'market': market,
                'distribution_count': 1,
                'ftd_detected': False,
                'days_since_ftd': None,
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

        ftd = _detect_follow_through_day(closes, volumes)

        lookback = min(25, n - 1)
        start_idx = n - lookback
        # หลัง FTD ยืนยันแล้ว นับ Distribution Day ใหม่เฉพาะตั้งแต่วันถัดจาก FTD
        if ftd['ftd_detected'] and ftd['ftd_idx'] + 1 > start_idx:
            start_idx = ftd['ftd_idx'] + 1

        distribution_count = 0
        for i in range(max(start_idx, 1), n):
            prev_close = float(closes[i - 1])
            curr_close = float(closes[i])
            prev_vol = float(volumes[i - 1])
            curr_vol = float(volumes[i])

            pct_change = (curr_close - prev_close) / prev_close * 100.0

            if pct_change <= -0.2 and curr_vol > prev_vol:
                distribution_count += 1

        ftd_note = ''
        if ftd['ftd_detected']:
            ftd_note = f" · ✅ Follow-Through Day ยืนยันแล้วเมื่อ {ftd['days_since_ftd']} วันก่อน"

        if distribution_count >= 5:
            status_code = 'RED'
            status_label = f'RED ALERT: สถาบันแจกของหนัก ({distribution_count} วันใน 25 วัน)'
            status_color = '#ef4444'
            bg_color = '#fef2f2'
            border_color = '#fca5a5'
            description = 'ตลาดมีความเสี่ยงสูงที่จะหลุดพักตัว ห้ามไล่ซื้อหุ้น Breakout ให้คุมเงินสด' + ftd_note
        elif distribution_count >= 3:
            status_code = 'YELLOW'
            status_label = f'CAUTION: ตลาดระมัดระวัง (วันแจกของ {distribution_count} วัน)'
            status_color = '#f59e0b'
            bg_color = '#fffbeb'
            border_color = '#fde68a'
            description = 'ตลาดอยู่ในช่วงปรับฐาน ควรซื้อเฉพาะหุ้นที่ทรงแข็งแกร่งกว่าตลาดและคุม Risk สั้น' + ftd_note
        else:
            status_code = 'GREEN'
            status_label = f'GREEN LIGHT: สภาวะตลาดเอื้ออำนวย (วันแจกของ {distribution_count} วัน)'
            status_color = '#10b981'
            bg_color = '#ecfdf5'
            border_color = '#a7f3d0'
            description = 'ตลาดแข็งแกร่ง เหมาะแก่การคัดหุ้นทรง VCP, HTF และ Squeeze เข้าซื้อ' + ftd_note

        res = {
            'market': market,
            'distribution_count': distribution_count,
            'ftd_detected': ftd['ftd_detected'],
            'days_since_ftd': ftd['days_since_ftd'],
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
            'ftd_detected': False,
            'days_since_ftd': None,
            'status_code': 'GREEN',
            'status_label': 'GREEN LIGHT: สภาวะตลาดเปิดให้เล่น',
            'status_color': '#10b981',
            'bg_color': '#ecfdf5',
            'border_color': '#a7f3d0',
            'description': 'ตลาดอยู่ในสภาวะปกติ เหมาะแก่การค้นหาหุ้นเบรกเอาต์'
        }
        return res
