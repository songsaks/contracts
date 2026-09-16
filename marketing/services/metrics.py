# ====== marketing/services/metrics.py ======
# บริการคำนวณและสรุปข้อมูลตัวเลขทางการตลาดและผลกำไร (Analytics & KPI Engine)

from decimal import Decimal
from datetime import timedelta
from django.db.models import Sum, Count, Avg
from django.utils import timezone
from marketing.models import DailyMetric, MarketingCampaign, AdCreative


def get_marketing_summary(days=7):
    """
    สรุปตัวเลขภาพรวมตามช่วงเวลาที่กำหนด (ค่าเริ่มต้น: 7 วันย้อนหลัง)
    """
    today = timezone.now().date()
    start_date = today - timedelta(days=days - 1)

    # 1. ข้อมูลช่วงเวลาปัจจุบัน
    metrics_qs = DailyMetric.objects.filter(date__gte=start_date, date__lte=today)
    
    total_spend = Decimal('0.00')
    total_revenue = Decimal('0.00')
    total_conversions = 0
    total_cogs = Decimal('0.00')
    total_fees = Decimal('0.00')
    total_clicks = 0
    total_impressions = 0

    for m in metrics_qs:
        total_spend += m.ad_spend
        total_revenue += m.revenue
        total_conversions += m.conversions
        total_cogs += m.cogs
        total_fees += m.other_fees
        total_clicks += m.clicks
        total_impressions += m.impressions

    # คำนวณ KPIs สำคัญ
    overall_roas = (total_revenue / total_spend) if total_spend > 0 else Decimal('0.00')
    net_profit = total_revenue - (total_spend + total_cogs + total_fees)
    profit_margin = ((net_profit / total_revenue) * Decimal('100.0')) if total_revenue > 0 else Decimal('0.0')
    avg_cpa = (total_spend / Decimal(str(total_conversions))) if total_conversions > 0 else Decimal('0.00')
    avg_ctr = ((Decimal(str(total_clicks)) / Decimal(str(total_impressions))) * Decimal('100.0')) if total_impressions > 0 else Decimal('0.00')

    # 2. เปรียบเทียบกับช่วงเวลาก่อนหน้า (Previous Period)
    prev_start_date = start_date - timedelta(days=days)
    prev_end_date = start_date - timedelta(days=1)
    prev_qs = DailyMetric.objects.filter(date__gte=prev_start_date, date__lte=prev_end_date)
    
    prev_revenue = Decimal('0.00')
    prev_spend = Decimal('0.00')
    for pm in prev_qs:
        prev_revenue += pm.revenue
        prev_spend += pm.ad_spend

    revenue_growth_pct = 0.0
    if prev_revenue > 0:
        revenue_growth_pct = float(round(((total_revenue - prev_revenue) / prev_revenue) * Decimal('100.0'), 1))

    # 3. จัดกลุ่มตามช่องทาง (Platform Breakdown)
    platforms_raw = {}
    for m in metrics_qs:
        p = m.get_platform_display()
        if p not in platforms_raw:
            platforms_raw[p] = {'spend': Decimal('0.00'), 'revenue': Decimal('0.00'), 'orders': 0}
        platforms_raw[p]['spend'] += m.ad_spend
        platforms_raw[p]['revenue'] += m.revenue
        platforms_raw[p]['orders'] += m.conversions

    platform_breakdown = []
    for p_name, data in platforms_raw.items():
        p_roas = (data['revenue'] / data['spend']) if data['spend'] > 0 else Decimal('0.00')
        platform_breakdown.append({
            'name': p_name,
            'spend': float(data['spend']),
            'revenue': float(data['revenue']),
            'orders': data['orders'],
            'roas': float(round(p_roas, 2)),
        })

    # 4. ข้อมูลรายวันสำหรับวาดกราฟ (Daily Chart Data)
    daily_chart_labels = []
    daily_spend_data = []
    daily_revenue_data = []
    daily_profit_data = []

    for i in range(days):
        cur_date = start_date + timedelta(days=i)
        day_metrics = [m for m in metrics_qs if m.date == cur_date]
        
        day_spend = sum([m.ad_spend for m in day_metrics]) if day_metrics else Decimal('0.00')
        day_rev = sum([m.revenue for m in day_metrics]) if day_metrics else Decimal('0.00')
        day_cogs = sum([m.cogs for m in day_metrics]) if day_metrics else Decimal('0.00')
        day_fees = sum([m.other_fees for m in day_metrics]) if day_metrics else Decimal('0.00')
        day_profit = day_rev - (day_spend + day_cogs + day_fees)

        daily_chart_labels.append(cur_date.strftime('%d/%m'))
        daily_spend_data.append(float(day_spend))
        daily_revenue_data.append(float(day_rev))
        daily_profit_data.append(float(day_profit))

    # 5. สรุปสถานะแอด Winner vs Kill
    active_campaigns_count = MarketingCampaign.objects.filter(status='active').count()
    winning_creatives = AdCreative.objects.filter(status='winner')[:5]
    fatigued_creatives = AdCreative.objects.filter(status='fatigued')[:5]
    killed_creatives = AdCreative.objects.filter(status='killed')[:5]

    return {
        'days': days,
        'start_date': start_date,
        'end_date': today,
        'total_spend': total_spend,
        'total_revenue': total_revenue,
        'overall_roas': round(overall_roas, 2),
        'net_profit': net_profit,
        'profit_margin': round(profit_margin, 1),
        'total_conversions': total_conversions,
        'avg_cpa': round(avg_cpa, 2),
        'avg_ctr': round(avg_ctr, 2),
        'revenue_growth_pct': revenue_growth_pct,
        'platform_breakdown': platform_breakdown,
        'chart_labels': daily_chart_labels,
        'chart_spend': daily_spend_data,
        'chart_revenue': daily_revenue_data,
        'chart_profit': daily_profit_data,
        'active_campaigns_count': active_campaigns_count,
        'winning_creatives': winning_creatives,
        'fatigued_creatives': fatigued_creatives,
        'killed_creatives': killed_creatives,
    }
