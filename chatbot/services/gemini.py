import os
import google.generativeai as genai
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.db.models import Q, Count
import json

# Configure Gemini
api_key = getattr(settings, 'GEMINI_API_KEY', os.environ.get('GEMINI_API_KEY'))
genai.configure(api_key=api_key)

# --- ADVANCED STATS TOOLS ---

def get_detailed_system_stats():
    """
    วิเคราะห์ข้อมูลเชิงลึก: จำนวนงานแยกประเภท (โครงการ, เช่า, ซ่อม, ขาย)
    และตรวจหางานที่ตอบสนองช้า (Stale Jobs) ที่ค้างสถานะเดิมนานเกินไป
    """
    from pms.models import Project
    from repairs.models import RepairItem

    now = timezone.now()
    stale_threshold = now - timedelta(days=3) # นิยาม: ไม่เปลี่ยนสถานะเกิน 3 วัน

    # 1. PMS Stats (แยกตาม Job Type)
    pms_stats = Project.objects.exclude(status__in=['CLOSED', 'CANCELLED']).values('job_type').annotate(count=Count('id'))
    pms_mapping = {
        'PROJECT': 'งานโครงการ',
        'RENTAL': 'งานเช่า',
        'SERVICE': 'งานบริการ/ขาย',
    }
    pms_breakdown = {pms_mapping.get(s['job_type'], s['job_type']): s['count'] for s in pms_stats}

    # 2. Repair Stats
    repair_active_count = RepairItem.objects.exclude(status__in=['FINISHED', 'COMPLETED', 'CANCELLED']).count()

    # 3. Detect Stale/Slow Response Jobs (งานที่ตอบสนองช้า)
    stale_repairs = RepairItem.objects.filter(
        status__in=['RECEIVED', 'FIXING'],
        updated_at__lt=stale_threshold
    ).select_related('job', 'device')

    stale_pms = Project.objects.exclude(status__in=['CLOSED', 'CANCELLED']).filter(
        updated_at__lt=stale_threshold
    )

    slow_jobs_list = []
    for item in stale_repairs[:5]:
        slow_jobs_list.append(f"งานซ่อม {item.job.job_code}: {item.device} (ค้างสถานะ {item.get_status_display()} ตั้งแต่ {item.updated_at.strftime('%d/%m')})")

    for p in stale_pms[:5]:
        slow_jobs_list.append(f"PMS {p.name}: (ไม่เคลื่อนไหวตั้งแต่ {p.updated_at.strftime('%d/%m')})")

    return {
        "pms_breakdown": pms_breakdown,
        "repair_active": repair_active_count,
        "slow_response_count": len(stale_repairs) + len(stale_pms),
        "slow_jobs_examples": slow_jobs_list,
        "threshold_days": 3
    }

# --- EXISTING TOOLS ---

def search_pms_projects(query=None, customer_name=None):
    """ค้นหาโครงการ, งานบริการ, งานเช่า ในระบบ PMS"""
    from pms.models import Project

    qs = Project.objects.all()
    if query: qs = qs.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if customer_name: qs = qs.filter(customer__name__icontains=customer_name)
    results = []
    for p in qs[:5]:
        results.append({
            'name': p.name, 'customer': p.customer.name, 'type': p.get_job_type_display(), 'status': p.get_job_status_display
        })
    return results

def search_repair_jobs(query=None, customer_name=None):
    """ค้นหางานแจ้งซ่อม (Repair Jobs)"""
    from repairs.models import RepairJob

    qs = RepairJob.objects.all()
    if customer_name: qs = qs.filter(customer__name__icontains=customer_name)
    if query: qs = qs.filter(Q(job_code__icontains=query) | Q(items__issue_description__icontains=query)).distinct()
    results = []
    for job in qs[:5]:
        results.append({'job_code': job.job_code, 'customer': job.customer.name, 'status': [i.get_status_display() for i in job.items.all()]})
    return results

def get_stock_recommendations():
    """หุ้นแนะนำจากระบบวิเคราะห์ Stocks"""
    from stocks.models import MomentumCandidate

    candidates = MomentumCandidate.objects.all().order_by('-technical_score')[:5]
    return [{'symbol': c.symbol, 'score': c.technical_score, 'strategy': c.entry_strategy} for c in candidates]

# All tools
all_tools = [
    get_detailed_system_stats,
    search_pms_projects,
    search_repair_jobs,
    get_stock_recommendations
]

def gemini_chat_sync(user_text, user=None):
    """9Com Intelligence Logic with Stale Job Detection"""
    model = genai.GenerativeModel(
        model_name='gemini-2.0-flash',
        tools=all_tools
    )
    chat = model.start_chat(history=[], enable_automatic_function_calling=True)

    system_instruction = (
        "คุณคือ '9Com Intelligence' ผู้ช่วย AI อัจฉริยะ. "
        "คุณมีความสามารถในการวิเคราะห์ประเภทงานและ 'ความเร็วในการตอบสนอง' (Response Time) ของทีมงาน.\n\n"

        "ความรู้เกี่ยวกับประเภทงาน:\n"
        "- งานโครงการ (Project): งานติดตั้งระบบใหญ่\n"
        "- งานเช่า (Rental): สัญญาเช่าอุปกรณ์\n"
        "- งานขาย/บริการ (Service): งานขายสินค้าพร้อมบริการ\n"
        "- งานซ่อม (Repair): งานรับซ่อมเครื่องรายชิ้น\n\n"

        "การตรวจหางานที่ 'ตอบสนองช้า' (Stale Jobs):\n"
        "- คือโครงการหรือใบซ่อมที่ 'ไม่เปลี่ยนสถานะ' หรือไม่มีการอัปเดตนานเกิน 3 วัน.\n"
        "- หากผู้ใช้ถามว่า 'งานไหนช้า', 'งานค้างนาน', หรือ 'ขอดูงานที่ตอบสนองช้า' -> ให้ใช้ get_detailed_system_stats.\n"
        "- รายงานจำนวนงานแยกมอดูลและยกตัวอย่างงานที่ค้างให้ชัดเจน.\n\n"

        "ตอบเป็นภาษาไทยอย่างเป็นกันเองและเป็นมืออาชีพ วันนี้: " + timezone.now().strftime('%d/%m/%Y %H:%M')
    )

    if user:
        system_instruction += f"\nผู้ใช้: {user.username}"

    full_prompt = f"{system_instruction}\n\nคำถาม: {user_text}"

    try:
        response = chat.send_message(full_prompt)
        return response.text
    except Exception as e:
        return f"ขออภัยครับ เกิดข้อผิดพลาด: {str(e)}"