"""
รายได้จากพอร์ตรายเดือน — กำไรจากการขาย (หักค่าคอม) + เงินปันผลสุทธิ

แยกออกมาเป็นโมดูลกลางเพราะทั้งหน้า Dashboard และหน้าทศางค์ต้องใช้ตัวเลขชุดเดียวกัน
ถ้าคำนวณแยกกันสองที่ ตัวเลขจะเริ่มไม่ตรงกันทันทีที่ฝั่งใดฝั่งหนึ่งถูกแก้
"""

import calendar
from collections import defaultdict
from decimal import Decimal

from stocks.models import DividendRecord, MarketType, SoldStock

# ค่าคอมฯ หุ้นไทย: 0.157% ของมูลค่าซื้อขาย ขั้นต่ำ 50 บาทต่อวัน แล้วบวก VAT 7%
TH_COMMISSION_RATE = Decimal('0.00157')
TH_COMMISSION_MIN = Decimal('50.0')
TH_VAT_RATE = Decimal('0.07')


def monthly_income(user, usd_thb, us_symbol_set=None, is_us_symbol=None):
    """
    รวมรายได้รายเดือนของผู้ใช้

    usd_thb        : อัตราแลกเปลี่ยนปัจจุบัน (ใช้เฉพาะกับรายการที่ไม่ได้บันทึกยอดบาทไว้)
    us_symbol_set  : ชุดสัญลักษณ์หุ้น US ของผู้ใช้ (ใช้เดาตลาดของรายการเก่าที่ไม่มีฟิลด์ market)
    is_us_symbol   : ฟังก์ชันเดาตลาดจากชื่อ ส่งเข้ามาเพื่อไม่ให้โมดูลนี้ผูกกับ views

    คืน dict:
      months      - เรียงจากเก่าไปใหม่ แต่ละตัวมี year/month/label/realized/dividend/total
      totals      - ยอดรวมทั้งหมด
      by_symbol   - เงินปันผลสะสมรายหุ้น เรียงจากมากไปน้อย
    """
    usd_thb_d = Decimal(str(round(float(usd_thb or 1), 4)))

    realized = defaultdict(Decimal)
    dividend = defaultdict(Decimal)
    thai_daily_trades = defaultdict(Decimal)

    for s in SoldStock.objects.filter(user=user).order_by('sold_at'):
        if s.market and s.market != MarketType.SET:
            is_us = s.market == MarketType.US
        elif is_us_symbol and us_symbol_set is not None:
            is_us = is_us_symbol(s.symbol, us_symbol_set)
        else:
            is_us = False

        # ยอดบาทที่บันทึกไว้ ณ วันขายแม่นกว่าการแปลงด้วยเรตวันนี้ — ใช้ก่อนเสมอ
        if getattr(s, 'profit_loss_thb', None):
            pl_thb = Decimal(str(s.profit_loss_thb))
        else:
            pl_raw = Decimal(str(s.profit_loss or 0))
            pl_thb = pl_raw * usd_thb_d if is_us else pl_raw

        realized[(s.sold_at.year, s.sold_at.month)] += pl_thb

        if not is_us:
            trade_val = Decimal(str(s.quantity)) * (Decimal(str(s.buy_price)) + Decimal(str(s.sell_price)))
            thai_daily_trades[s.sold_at.date()] += trade_val

    # ค่าคอมฯ คิดเป็นรายวัน (ขั้นต่ำ 50 บาท/วัน) ไม่ใช่รายรายการ
    for day, trade_val in thai_daily_trades.items():
        if trade_val <= 0:
            continue
        comm = max(trade_val * TH_COMMISSION_RATE, TH_COMMISSION_MIN)
        realized[(day.year, day.month)] -= comm * (1 + TH_VAT_RATE)

    by_symbol = defaultdict(Decimal)
    for d in DividendRecord.objects.filter(user=user):
        net = d.net_amount * usd_thb_d if d.market == MarketType.US else d.net_amount
        dividend[(d.dividend_date.year, d.dividend_date.month)] += net
        by_symbol[d.symbol] += net

    months = []
    for key in sorted(set(realized) | set(dividend)):
        yr, mo = key
        r = realized.get(key, Decimal('0')).quantize(Decimal('0.01'))
        dv = dividend.get(key, Decimal('0')).quantize(Decimal('0.01'))
        months.append({
            'year': yr, 'month': mo,
            'label': f"{calendar.month_abbr[mo]} {str(yr)[-2:]}",
            'realized': float(r), 'dividend': float(dv), 'total': float(r + dv),
        })

    total_realized = sum(m['realized'] for m in months)
    total_dividend = sum(m['dividend'] for m in months)
    wins = [m for m in months if m['total'] > 0]

    return {
        'months': months,
        'totals': {
            'realized': round(total_realized, 2),
            'dividend': round(total_dividend, 2),
            'net': round(total_realized + total_dividend, 2),
            'months_count': len(months),
            'win_months': len(wins),
            'win_rate': round(len(wins) / len(months) * 100, 1) if months else 0.0,
            'best_month': max(months, key=lambda m: m['total']) if months else None,
            'worst_month': min(months, key=lambda m: m['total']) if months else None,
            'avg_month': round((total_realized + total_dividend) / len(months), 2) if months else 0.0,
        },
        'by_symbol': [{'symbol': k, 'amount': float(v)}
                      for k, v in sorted(by_symbol.items(), key=lambda x: -x[1])],
    }
