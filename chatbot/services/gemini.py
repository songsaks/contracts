# ====== Gemini AI Service ======
# ไฟล์นี้เป็น service layer สำหรับการติดต่อกับ Google Gemini AI
# รับผิดชอบ: การตั้งค่า API, การกำหนด system instruction, การเรียก function tools
# และการประมวลผลคำถาม-คำตอบระหว่างผู้ใช้กับ AI

import os
from google import genai                  # Google GenAI SDK สำหรับเรียกใช้ Gemini API
from google.genai import types            # types สำหรับกำหนด config ของ Gemini
from django.conf import settings          # อ่านค่า config จาก Django settings
from django.utils import timezone         # utility สำหรับจัดการเวลาใน timezone ที่ถูกต้อง
from datetime import timedelta            # สำหรับคำนวณช่วงเวลา เช่น 3 วันที่ผ่านมา
from django.db.models import Q, Count     # Q สำหรับ complex query, Count สำหรับนับจำนวน
import json

# ====== API Key Configuration ======
# อ่าน Gemini API Key จาก Django settings ก่อน ถ้าไม่มีให้อ่านจาก environment variable
api_key = getattr(settings, 'GEMINI_API_KEY', os.environ.get('GEMINI_API_KEY'))

# ====== Advanced Stats Tools ======
# เครื่องมือวิเคราะห์สถิติเชิงลึกของระบบ

def get_detailed_system_stats():
    """
    วิเคราะห์ข้อมูลเชิงลึก: จำนวนงานแยกประเภท (โครงการ, เช่า, ซ่อม, ขาย)
    และตรวจหางานที่ตอบสนองช้า (Stale Jobs) ที่ค้างสถานะเดิมนานเกินไป

    Function นี้ถูก Gemini AI เรียกอัตโนมัติผ่าน Function Calling
    เมื่อผู้ใช้ถามเกี่ยวกับ "งานช้า", "งานค้าง", หรือ "สถิติระบบ"

    Returns:
        dict: ข้อมูลสถิติรวมถึง pms_breakdown, repair_active,
              slow_response_count, slow_jobs_examples, threshold_days
    """
    from pms.models import Project
    from repairs.models import RepairItem

    now = timezone.now()
    stale_threshold = now - timedelta(days=3) # นิยาม: ไม่เปลี่ยนสถานะเกิน 3 วัน

    # 1. PMS Stats (แยกตาม Job Type)
    # ดึงสถิติโครงการที่ยังเปิดอยู่ แยกตามประเภทงาน
    pms_stats = Project.objects.exclude(status__in=['CLOSED', 'CANCELLED']).values('job_type').annotate(count=Count('id'))

    # แปลง job_type code เป็นชื่อภาษาไทยที่อ่านเข้าใจง่าย
    pms_mapping = {
        'PROJECT': 'งานโครงการ',
        'RENTAL': 'งานเช่า',
        'SERVICE': 'งานบริการ/ขาย',
    }
    pms_breakdown = {pms_mapping.get(s['job_type'], s['job_type']): s['count'] for s in pms_stats}

    # 2. Repair Stats
    # นับจำนวนงานซ่อมที่ยังไม่เสร็จสิ้น (ไม่รวมสถานะ FINISHED, COMPLETED, CANCELLED)
    repair_active_count = RepairItem.objects.exclude(status__in=['FINISHED', 'COMPLETED', 'CANCELLED']).count()

    # 3. Detect Stale/Slow Response Jobs (งานที่ตอบสนองช้า)
    # ค้นหางานซ่อมที่อยู่ในสถานะ RECEIVED หรือ FIXING และไม่มีการอัปเดตนานกว่า threshold
    stale_repairs = RepairItem.objects.filter(
        status__in=['RECEIVED', 'FIXING'],
        updated_at__lt=stale_threshold
    ).select_related('job', 'device')

    # ค้นหาโครงการ PMS ที่ไม่มีการเคลื่อนไหวนานกว่า threshold
    stale_pms = Project.objects.exclude(status__in=['CLOSED', 'CANCELLED']).filter(
        updated_at__lt=stale_threshold
    )

    # สร้างรายการตัวอย่างงานที่ค้างอยู่ (จำกัดแค่ 5 รายการต่อประเภท)
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

# ====== Existing Tools ======
# เครื่องมือค้นหาข้อมูลพื้นฐานจากระบบต่างๆ ในโปรเจกต์

def search_pms_projects(query: str = None, customer_name: str = None):
    """
    ค้นหาโครงการ, งานบริการ, งานเช่า ในระบบ PMS

    Function นี้ถูก Gemini AI เรียกอัตโนมัติเมื่อผู้ใช้ถามเกี่ยวกับโครงการ

    Args:
        query (str): คำค้นหาจากชื่อหรือคำอธิบายโครงการ
        customer_name (str): กรองตามชื่อลูกค้า

    Returns:
        list: รายการโครงการที่ตรงกับเงื่อนไข (สูงสุด 5 รายการ)
    """
    from pms.models import Project

    qs = Project.objects.all()
    # กรองตาม query ถ้ามี (ค้นในชื่อและคำอธิบาย)
    if query: qs = qs.filter(Q(name__icontains=query) | Q(description__icontains=query))
    # กรองตามชื่อลูกค้าถ้ามี
    if customer_name: qs = qs.filter(customer__name__icontains=customer_name)
    results = []
    for p in qs[:5]:
        results.append({
            'name': p.name, 'customer': p.customer.name, 'type': p.get_job_type_display(), 'status': str(p.get_job_status_display())
        })
    return results

def search_repair_jobs(query: str = None, customer_name: str = None):
    """
    ค้นหางานแจ้งซ่อม (Repair Jobs)

    Function นี้ถูก Gemini AI เรียกอัตโนมัติเมื่อผู้ใช้ถามเกี่ยวกับงานซ่อม

    Args:
        query (str): คำค้นหาจาก job code หรือคำอธิบายปัญหา
        customer_name (str): กรองตามชื่อลูกค้า

    Returns:
        list: รายการงานซ่อมที่ตรงกับเงื่อนไข (สูงสุด 5 รายการ) พร้อมสถานะแต่ละรายการ
    """
    from repairs.models import RepairJob

    qs = RepairJob.objects.all()
    # กรองตามชื่อลูกค้าถ้ามี
    if customer_name: qs = qs.filter(customer__name__icontains=customer_name)
    # กรองตาม job code หรือคำอธิบายปัญหา และใช้ distinct() เพื่อกำจัด duplicate จาก JOIN
    if query: qs = qs.filter(Q(job_code__icontains=query) | Q(items__issue_description__icontains=query)).distinct()
    results = []
    for job in qs[:5]:
        results.append({'job_code': job.job_code, 'customer': job.customer.name, 'status': [i.get_status_display() for i in job.items.all()]})
    return results

def get_stock_recommendations():
    """
    หุ้นแนะนำจากระบบวิเคราะห์ Stocks

    Function นี้ถูก Gemini AI เรียกอัตโนมัติเมื่อผู้ใช้ถามเกี่ยวกับหุ้นหรือการลงทุน

    Returns:
        list: รายการหุ้นแนะนำเรียงตาม technical_score จากสูงไปต่ำ (สูงสุด 5 ตัว)
    """
    from stocks.models import MomentumCandidate

    # ดึงหุ้นที่มีคะแนน technical score สูงสุด 5 อันดับ
    candidates = MomentumCandidate.objects.all().order_by('-technical_score')[:5]
    return [{'symbol': c.symbol, 'score': c.technical_score, 'strategy': c.entry_strategy} for c in candidates]

# ====== Tool Registry ======
# รายการ function tools ทั้งหมดที่ Gemini AI สามารถเรียกใช้ได้อัตโนมัติ (Automatic Function Calling)
# Gemini จะเลือก tool ที่เหมาะสมตาม context ของคำถามผู้ใช้
all_tools = [
    get_detailed_system_stats,   # สถิติเชิงลึกและงานที่ตอบสนองช้า
    search_pms_projects,         # ค้นหาโครงการ PMS
    search_repair_jobs,          # ค้นหางานซ่อม
    get_stock_recommendations    # หุ้นแนะนำ
]

# ====== Main Gemini Chat Function ======

def gemini_chat_sync(user_text, user=None):
    """
    ฟังก์ชันหลักสำหรับส่งข้อความไปยัง Gemini AI และรับคำตอบกลับมา (Synchronous)

    9Com Intelligence Logic using google-genai SDK

    ขั้นตอนการทำงาน:
    1. สร้าง Gemini client ด้วย API key
    2. กำหนด system instruction ที่บอก AI ว่าเป็นใครและมีความสามารถอะไร
    3. ส่งข้อความผู้ใช้พร้อม tools ไปให้ Gemini ประมวลผล
    4. Gemini อาจเรียก function tools อัตโนมัติเพื่อดึงข้อมูลจากระบบ
    5. คืนค่าข้อความคำตอบกลับมา

    Args:
        user_text (str): ข้อความคำถามจากผู้ใช้
        user (User, optional): Django user object สำหรับ personalization

    Returns:
        str: คำตอบจาก Gemini AI หรือข้อความ error หากเกิดปัญหา
    """
    # สร้าง Gemini client instance ด้วย API key ที่กำหนดไว้
    client = genai.Client(api_key=api_key)

    # กำหนด system instruction: บอก AI ว่าเป็น "9Com Intelligence"
    # พร้อมอธิบายประเภทงาน, วิธีตรวจหางานช้า, และวิธีตอบ
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

    # เพิ่มชื่อผู้ใช้ใน system instruction เพื่อให้ AI ตอบแบบ personalized
    if user:
        system_instruction += f"\nผู้ใช้: {user.username}"

    try:
        # ส่งข้อความไปยัง Gemini API พร้อม:
        # - model: ใช้ gemini-3.0-flash (Preview) ซึ่งรวดเร็วและประหยัดที่สุดตัวล่าสุด
        # - contents: ข้อความจากผู้ใช้
        # - system_instruction: คำสั่งบทบาทของ AI
        # - tools: รายการ function ที่ AI เรียกใช้ได้
        # - automatic_function_calling: เปิดให้ AI เรียก function อัตโนมัติโดยไม่ต้องรอ
        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=user_text,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=all_tools,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=False)
            )
        )
        # คืนค่าข้อความคำตอบจาก Gemini
        return response.text
    except Exception as e:
        # หากเกิด error ในการเรียก API ให้ส่งข้อความแจ้งผู้ใช้เป็นภาษาไทย
        return f"ขออภัยครับ เกิดข้อผิดพลาด: {str(e)}"
