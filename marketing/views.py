# ====== marketing/views.py ======
# View Controllers สำหรับระบบ AI Marketing & Growth OS

import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from pathlib import Path

from .models import (
    MarketingCampaign,
    AdCreative,
    DailyMetric,
    AIActionPlan,
    CreativeIdea,
    CompetitorIntel,
)
from .services.metrics import get_marketing_summary
from .services.gemini_agent import (
    generate_daily_action_plan,
    generate_creative_content,
    analyze_competitor_intel,
)


@login_required
def dashboard(request):
    """
    หน้า Executive Growth Command Center
    แสดง KPI หลัก (ยอดขาย, ค่าแอด, ROAS, กำไรสุทธิ), กราฟประสิทธิภาพ,
    แผนปฏิบัติการ AI ล่าสุด พร้อม Checklist และรายชื่อแอดตัวทำเงิน / ตัวควรปิด
    """
    days = int(request.GET.get('days', 7))
    summary = get_marketing_summary(days=days)
    
    # ดึง Action Plan ล่าสุด
    latest_plan = AIActionPlan.objects.first()

    # ดึงแคมเปญทั้งหมดที่กำลังรันอยู่
    active_campaigns = MarketingCampaign.objects.filter(status='active').prefetch_related('creatives')[:6]

    context = {
        'summary': summary,
        'latest_plan': latest_plan,
        'active_campaigns': active_campaigns,
        'current_days': days,
    }
    return render(request, 'marketing/dashboard.html', context)


@login_required
def campaign_list(request):
    """หน้ารายการแคมเปญและชิ้นงานโฆษณา (Campaign & Creative Manager)"""
    platform = request.GET.get('platform', '')
    status = request.GET.get('status', '')

    campaigns = MarketingCampaign.objects.all()
    if platform:
        campaigns = campaigns.filter(platform=platform)
    if status:
        campaigns = campaigns.filter(status=status)

    creatives = AdCreative.objects.select_related('campaign').all()
    
    context = {
        'campaigns': campaigns,
        'creatives': creatives,
        'selected_platform': platform,
        'selected_status': status,
    }
    return render(request, 'marketing/campaigns.html', context)


@login_required
def campaign_create(request):
    """สร้างแคมเปญใหม่"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        platform = request.POST.get('platform', 'meta')
        objective = request.POST.get('objective', 'conversions')
        daily_budget = Decimal(request.POST.get('daily_budget', '0') or '0')
        target_roas = Decimal(request.POST.get('target_roas', '3.0') or '3.0')
        product_focus = request.POST.get('product_focus', '').strip()
        target_audience = request.POST.get('target_audience', '').strip()

        if name:
            MarketingCampaign.objects.create(
                name=name,
                platform=platform,
                objective=objective,
                daily_budget=daily_budget,
                target_roas=target_roas,
                product_focus=product_focus,
                target_audience=target_audience,
            )
            messages.success(request, f"สร้างแคมเปญ '{name}' เรียบร้อยแล้ว")
        return redirect('marketing:campaign_list')
    return redirect('marketing:campaign_list')


@login_required
def creative_create(request):
    """เพิ่มชิ้นงานโฆษณาใหม่ (Creative)"""
    if request.method == 'POST':
        campaign_id = request.POST.get('campaign_id')
        name = request.POST.get('name', '').strip()
        format_type = request.POST.get('format', 'video')
        hook_text = request.POST.get('hook_text', '').strip()
        angle = request.POST.get('angle', '').strip()
        status = request.POST.get('status', 'testing')

        campaign = get_object_or_404(MarketingCampaign, id=campaign_id)
        if name:
            AdCreative.objects.create(
                campaign=campaign,
                name=name,
                format=format_type,
                hook_text=hook_text,
                angle=angle,
                status=status,
            )
            messages.success(request, f"เพิ่มชิ้นงาน '{name}' เรียบร้อยแล้ว")
    return redirect('marketing:campaign_list')


@login_required
def daily_metrics(request):
    """หน้ารายงานและบันทึกสถิติรายวัน (Spend, Revenue, ROAS)"""
    if request.method == 'POST':
        metric_date = request.POST.get('date') or timezone.now().date()
        campaign_id = request.POST.get('campaign_id') or None
        creative_id = request.POST.get('creative_id') or None
        platform = request.POST.get('platform', 'meta')
        ad_spend = Decimal(request.POST.get('ad_spend', '0') or '0')
        revenue = Decimal(request.POST.get('revenue', '0') or '0')
        conversions = int(request.POST.get('conversions', '0') or '0')
        cogs = Decimal(request.POST.get('cogs', '0') or '0')
        other_fees = Decimal(request.POST.get('other_fees', '0') or '0')
        notes = request.POST.get('notes', '').strip()

        campaign = MarketingCampaign.objects.filter(id=campaign_id).first() if campaign_id else None
        creative = AdCreative.objects.filter(id=creative_id).first() if creative_id else None

        DailyMetric.objects.create(
            date=metric_date,
            campaign=campaign,
            creative=creative,
            platform=platform,
            ad_spend=ad_spend,
            revenue=revenue,
            conversions=conversions,
            cogs=cogs,
            other_fees=other_fees,
            notes=notes,
        )
        messages.success(request, f"บันทึกข้อมูลสถิติของวันที่ {metric_date} เรียบร้อยแล้ว")
        return redirect('marketing:daily_metrics')

    metrics_list = DailyMetric.objects.select_related('campaign', 'creative').all()[:50]
    campaigns = MarketingCampaign.objects.filter(status='active')
    creatives = AdCreative.objects.all()

    context = {
        'metrics': metrics_list,
        'campaigns': campaigns,
        'creatives': creatives,
    }
    return render(request, 'marketing/metrics.html', context)


@login_required
def action_plans(request):
    """หน้าศูนย์บัญชาการแผนงาน AI (AI Command Center)"""
    plans = AIActionPlan.objects.all()[:20]
    latest_plan = plans.first() if plans.exists() else None

    context = {
        'plans': plans,
        'latest_plan': latest_plan,
    }
    return render(request, 'marketing/action_plan.html', context)


@login_required
def creative_lab(request):
    """หน้าห้องทดลองไอเดียโฆษณาและสคริปต์ (Creative & Copywriting Lab)"""
    ideas = CreativeIdea.objects.all()[:30]
    context = {
        'ideas': ideas,
    }
    return render(request, 'marketing/creative_lab.html', context)


@login_required
def competitor_radar(request):
    """หน้าสอดส่องคู่แข่ง (Competitor Radar & Strategy)"""
    intels = CompetitorIntel.objects.all()[:30]
    context = {
        'intels': intels,
    }
    return render(request, 'marketing/competitor_radar.html', context)


@login_required
def user_guide(request):
    """หน้าแสดงคู่มือการใช้งานระบบ AI Marketing & Growth OS (Interactive User Manual)"""
    manual_path = Path(settings.BASE_DIR) / 'docs' / 'ai_marketing_os_user_manual.md'
    content = ""
    if manual_path.exists():
        with open(manual_path, 'r', encoding='utf-8') as f:
            content = f.read()
    return render(request, 'marketing/guide.html', {'manual_content': content})


@login_required
@require_POST
def metric_delete(request, pk):
    """ลบรายการสถิติรายวัน"""
    metric = get_object_or_404(DailyMetric, pk=pk)
    d = metric.date
    metric.delete()
    messages.success(request, f"ลบข้อมูลสถิติของวันที่ {d} เรียบร้อยแล้ว")
    return redirect('marketing:daily_metrics')


@login_required
@require_POST
def campaign_delete(request, pk):
    """ลบแคมเปญและชิ้นงานโฆษณาที่เกี่ยวข้อง"""
    campaign = get_object_or_404(MarketingCampaign, pk=pk)
    name = campaign.name
    campaign.delete()
    messages.success(request, f"ลบแคมเปญ '{name}' เรียบร้อยแล้ว")
    return redirect('marketing:campaign_list')


@login_required
@require_POST
def competitor_delete(request, pk):
    """ลบข้อมูลการสอดส่องคู่แข่ง"""
    intel = get_object_or_404(CompetitorIntel, pk=pk)
    brand = intel.brand_name
    intel.delete()
    messages.success(request, f"ลบข้อมูลคู่แข่ง '{brand}' เรียบร้อยแล้ว")
    return redirect('marketing:competitor_radar')


@login_required
@require_POST
def action_plan_delete(request, pk):
    """ลบประวัติแผนงาน AI"""
    plan = get_object_or_404(AIActionPlan, pk=pk)
    plan.delete()
    messages.success(request, "ลบแผนงาน AI เรียบร้อยแล้ว")
    return redirect('marketing:action_plans')


@login_required
@require_POST
def creative_idea_delete(request, pk):
    """ลบไอเดียและสคริปต์โฆษณา"""
    idea = get_object_or_404(CreativeIdea, pk=pk)
    name = idea.product_name
    idea.delete()
    messages.success(request, f"ลบไอเดียสคริปต์ '{name}' เรียบร้อยแล้ว")
    return redirect('marketing:creative_lab')


# ====== AJAX / REST APIs ======

@login_required
@require_POST
def api_generate_action_plan(request):
    """API เรียก AI Gemini เพื่อประมวลผล Action Plan สดๆ"""
    try:
        plan = generate_daily_action_plan()
        return JsonResponse({
            'status': 'success',
            'plan_id': plan.id,
            'title': plan.title,
            'summary': plan.executive_summary,
            'status_level': plan.status_level,
            'roas': float(plan.overall_roas),
            'action_items': plan.action_items,
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
@require_POST
def api_toggle_action_item(request):
    """API กดทำเครื่องหมายเสร็จสิ้นบน Checklist งานของ AI"""
    try:
        data = json.loads(request.body)
        plan_id = data.get('plan_id')
        item_id = int(data.get('item_id'))

        plan = get_object_or_404(AIActionPlan, id=plan_id)
        items = plan.action_items
        for item in items:
            if item.get('id') == item_id:
                item['completed'] = not item.get('completed', False)
                break
        plan.action_items = items
        plan.save()
        return JsonResponse({'status': 'success', 'items': plan.action_items})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_POST
def api_generate_creative(request):
    """API สั่ง AI ให้สร้าง Hook และสคริปต์วิดีโอ"""
    try:
        data = json.loads(request.body)
        product = data.get('product_name', '').strip()
        persona = data.get('target_persona', '').strip()
        angle = data.get('angle_theme', '').strip()
        format_type = data.get('format', 'tiktok_reels')

        if not product or not angle:
            return JsonResponse({'status': 'error', 'message': 'กรุณากรอกชื่อสินค้าและมุมการขาย'}, status=400)

        idea = generate_creative_content(product, persona, angle, format_type)
        return JsonResponse({
            'status': 'success',
            'id': idea.id,
            'hooks': idea.hook_options,
            'script': idea.script_outline,
            'caption': idea.caption_copy,
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@login_required
@require_POST
def api_analyze_competitor(request):
    """API สั่ง AI วิเคราะห์กลยุทธ์แก้เกมคู่แข่ง"""
    try:
        data = json.loads(request.body)
        brand = data.get('brand_name', '').strip()
        platform = data.get('platform', 'Facebook')
        angle = data.get('observed_angle', '').strip()
        promo = data.get('pricing_promotion', '').strip()
        url = data.get('post_url', '').strip()

        if not brand:
            return JsonResponse({'status': 'error', 'message': 'กรุณากรอกชื่อแบรนด์คู่แข่ง'}, status=400)

        intel = analyze_competitor_intel(brand, platform, angle, promo, url)
        return JsonResponse({
            'status': 'success',
            'id': intel.id,
            'brand': intel.brand_name,
            'strategy': intel.ai_counter_strategy,
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
