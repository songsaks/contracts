"""
# ====== AI Service Queue Manager ======
ระบบจัดการคิวงานบริการโดยใช้ AI (Gemini) ช่วยในการแนะนำทีม
หน้าที่หลัก:
- ดึงข้อมูล Projects ที่มีสถานะเฉพาะเจาะจงมาสร้างเป็น ServiceQueueItem
- ใช้ AI (Gemini) แนะนำทีมที่เหมาะสมตามประเภทงาน
- จัดกลุ่มงานตามวันที่นัดหมายและคำนวณช่วงเวลา
- ส่งการแจ้งเตือนไปยัง Google Chat และ LINE
"""
import logging
import datetime
from django.utils import timezone
from django.db import models, transaction
from django.conf import settings
import requests
import json

# ใช้ logger เพื่อบันทึกข้อความ error/warning ของ module นี้
logger = logging.getLogger(__name__)


# ====== ส่วนแนะนำทีมด้วย AI ======

def get_ai_team_suggestion(task_type, teams):
    """
    ฟังก์ชันหลักสำหรับแนะนำทีมที่เหมาะสมตามประเภทงาน
    โดยจะพยายามใช้ Gemini AI ก่อน หากล้มเหลวจะ fallback ไปใช้ logic ปกติ

    Args:
        task_type (str): ประเภทงาน เช่น 'INSTALLATION', 'REPAIR', 'DELIVERY'
        teams (list): รายการ ServiceTeam ที่มีอยู่ในระบบ

    Returns:
        ServiceTeam หรือ None หากไม่พบทีมที่เหมาะสม
    """
    try:
        # ตรวจสอบว่ามี GEMINI_API_KEY ที่ถูกต้องใน settings หรือไม่
        api_key = getattr(settings, 'GEMINI_API_KEY', None)
        if api_key and api_key != 'YOUR_API_KEY_HERE':
            # ถ้ามี API key ที่ valid ให้ใช้ Gemini AI แนะนำทีม
            return _ai_suggest_team(task_type, teams)
    except Exception as e:
        # หาก Gemini ล้มเหลว ให้ log warning และ fallback ไปใช้ logic ปกติ
        logger.warning(f"AI team suggestion failed: {e}")

    # Fallback: ใช้การจับคู่ทักษะ (skill matching) แทน AI
    return _fallback_suggest_team(task_type, teams)


def _ai_suggest_team(task_type, teams):
    """
    ใช้ Gemini AI เพื่อเลือกทีมที่เหมาะสมที่สุดสำหรับงาน

    กระบวนการ:
    1. สร้าง prompt ที่มีข้อมูลทีมทั้งหมด (ทักษะ + ภาระงานปัจจุบัน)
    2. ส่ง prompt ไปยัง Gemini API (model: gemini-2.0-flash)
    3. รับชื่อทีมที่ AI แนะนำมา แล้วจับคู่กับ object ทีมในระบบ
    4. หาก Gemini ล้มเหลว ให้ fallback ไปใช้ _fallback_suggest_team

    Args:
        task_type (str): ประเภทงาน
        teams (list): รายการทีมที่ active อยู่ในระบบ

    Returns:
        ServiceTeam ที่ AI แนะนำ หรือผลลัพธ์จาก _fallback_suggest_team
    """
    try:
        from google import genai
        api_key = settings.GEMINI_API_KEY
        # สร้าง Gemini client ด้วย API key จาก settings
        client = genai.Client(api_key=api_key)

        # สร้างข้อมูลสรุปของทีมแต่ละทีม รวมถึงทักษะและภาระงานที่มีอยู่
        team_info = "\n".join([
            f"- Team '{t.name}': skills={t.skills}, current load={t.tasks.filter(status__in=['SCHEDULED','IN_PROGRESS']).count()}/{t.max_tasks_per_day}"
            for t in teams
        ])

        # สร้าง prompt ที่ระบุให้ Gemini ตอบเฉพาะชื่อทีมเท่านั้น
        # เพื่อให้ parse ผลลัพธ์ได้ง่าย
        prompt = f"""You are scheduling tasks for a service company.
Task type: {task_type}
Available teams:
{team_info}

Pick the best team name. Reply with ONLY the team name, nothing else."""

        response = client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt
        )
        # ดึงชื่อทีมจาก response และตัดช่องว่างออก
        suggested_name = response.text.strip()

        # จับคู่ชื่อทีมที่ AI แนะนำกับ object ทีมในระบบ
        # ใช้การเปรียบเทียบแบบ case-insensitive และรองรับทั้ง substring matching
        for t in teams:
            if t.name.lower() in suggested_name.lower() or suggested_name.lower() in t.name.lower():
                return t
    except Exception as e:
        # หาก Gemini API ล้มเหลวไม่ว่าด้วยสาเหตุใด ให้ log และ fallback
        logger.warning(f"Gemini team suggestion failed: {e}")

    # ถ้าจับคู่ชื่อทีมไม่ได้ หรือ API ล้มเหลว ให้ใช้ fallback logic
    return _fallback_suggest_team(task_type, teams)


def _fallback_suggest_team(task_type, teams):
    """
    Fallback logic สำหรับกรณีที่ AI ไม่พร้อมใช้งาน
    เลือกทีมโดยใช้เกณฑ์ 2 ข้อ:
    1. ทีมที่มีทักษะตรงกับประเภทงาน จะได้คะแนนเพิ่ม +10
    2. ทีมที่มีภาระงานน้อยกว่า (slot ว่างมากกว่า) จะได้คะแนนสูงกว่า
    เลือกทีมที่ได้คะแนนรวมสูงสุด

    Args:
        task_type (str): ประเภทงานที่ต้องการจับคู่กับทักษะทีม
        teams (list): รายการทีมทั้งหมด

    Returns:
        ServiceTeam ที่มีคะแนนสูงสุด หรือ None หากไม่มีทีมที่ active
    """
    best = None
    best_score = -1

    for team in teams:
        # ข้ามทีมที่ถูก deactivate แล้ว
        if not team.is_active:
            continue
        # คำนวณคะแนนเริ่มต้นจากจำนวน slot ที่ยังว่างอยู่
        score = team.max_tasks_per_day - team.tasks.filter(status__in=['SCHEDULED', 'IN_PROGRESS']).count()
        # ถ้าทีมมีทักษะตรงกับประเภทงาน ให้คะแนนโบนัสเพิ่ม 10 คะแนน
        if task_type in team.skill_list():
            score += 10
        # อัปเดตทีมที่ดีที่สุดหากพบทีมที่มีคะแนนสูงกว่า
        if score > best_score:
            best_score = score
            best = team

    return best


# ====== ส่วนซิงค์ Project เข้า Service Queue ======

@transaction.atomic
def sync_projects_to_queue():
    """
    ซิงค์ข้อมูล Projects ที่พร้อมเข้าสู่ระบบคิวงาน (ServiceQueueItem)
    ใช้ @transaction.atomic เพื่อให้การทำงานทั้งหมดเป็น atomic (ถ้าล้มเหลวจะ rollback ทั้งหมด)

    กฎการซิงค์:
    1. ลบ ServiceQueueItem ที่ไม่มี project แล้ว หรือ project ออกจาก trigger statuses
       ยกเว้น item ที่มีสถานะ COMPLETED หรือ CANCELLED แล้ว
    2. สร้าง ServiceQueueItem ใหม่สำหรับ project ที่ยังไม่มีใน queue

    Trigger Statuses (สถานะที่กระตุ้นให้สร้างคิวงาน):
    - PROJECT + INSTALLATION
    - SERVICE + DELIVERY
    - REPAIR + DELIVERY

    Returns:
        int: จำนวน ServiceQueueItem ที่สร้างใหม่
    """
    from pms.models import Project, ServiceQueueItem, ServiceTeam
    from django.db.models import Q

    # 1. Cleanup duplicates that might have slipped through (just in case)
    # We keep the one that is most advanced or most recently updated.
    # สถานะที่ถือว่า "active" (ยังอยู่ในกระบวนการ ยังไม่จบ)
    active_statuses = ['PENDING', 'SCHEDULED', 'IN_PROGRESS', 'INCOMPLETE']

    # 2. Sync new items based on TRIGGER STATUSES
    # ดึงทีมที่ active ทั้งหมดมาใช้สำหรับการแนะนำทีม
    teams = list(ServiceTeam.objects.filter(is_active=True))
    count = 0

    # ONLY trigger tasks for these specific statuses (The "Queue" stage)
    # กำหนด Q object สำหรับ filter เฉพาะ project ที่อยู่ใน trigger stage
    trigger_q = (
        Q(job_type='PROJECT', status='INSTALLATION') |
        Q(job_type='SERVICE', status='DELIVERY') |
        Q(job_type='REPAIR', status='DELIVERY')
    )

    # ใช้ select_for_update เพื่อ lock rows ระหว่างการซิงค์
    # ป้องกัน race condition เมื่อมีหลาย process รันพร้อมกัน
    ready_projects = Project.objects.select_for_update().filter(trigger_q)

    for proj in ready_projects:
        # Loop Check: Look for an ACTIVE task (not completed/cancelled)
        # We include INCOMPLETE because it's still alive in the queue for re-scheduling.
        # ตรวจสอบว่า project นี้มี active queue item อยู่แล้วหรือไม่
        active_tasks = ServiceQueueItem.objects.filter(
            project=proj,
            status__in=active_statuses
        ).order_by('-updated_at')

        if active_tasks.exists():
            # If accidentally duplicated, cleanup here
            # ถ้าเกิด duplicate (มีมากกว่า 1 item) ให้ลบอันที่เก่ากว่าออก
            if active_tasks.count() > 1:
                for t_del in active_tasks[1:]:
                    t_del.delete()
            continue # Already locked/tracking this stage

        # กำหนดประเภทงานและ label ภาษาไทยตาม job_type ของ project
        # Determine Task Type & Label based on Job Type
        if proj.job_type == 'PROJECT':
            task_type, label = 'INSTALLATION', 'คิว (ติดตั้ง)'
        elif proj.job_type == 'REPAIR':
            task_type, label = 'REPAIR', 'คิว (ซ่อม)'
        elif proj.job_type == 'SERVICE':
            task_type, label = 'DELIVERY', 'คิว (ส่งของ)'
        else:
            task_type, label = 'OTHER', 'คิว'

        # ขอคำแนะนำทีมจาก AI (หรือ fallback logic) เฉพาะเมื่อมีทีมในระบบ
        suggested_team = get_ai_team_suggestion(task_type, teams) if teams else None

        # สร้าง ServiceQueueItem ใหม่พร้อมข้อมูลครบถ้วน
        ServiceQueueItem.objects.create(
            title=f"{label}: {proj.name}",
            description=f"ลูกค้า: {proj.customer.name}\n{proj.description or ''}".strip(),
            project=proj,
            task_type=task_type,
            priority='NORMAL',
            assigned_team=suggested_team,
            deadline=proj.deadline,
            status='PENDING',
            # บันทึกเหตุผลของ AI หรือข้อความแจ้งเตือนเมื่อไม่มีทีม
            ai_urgency_reason=f"AI แนะนำทีม: {suggested_team.name}" if suggested_team else "ไม่มีทีมในระบบ",
        )
        count += 1

    return count


# ====== ส่วนจัดตารางเวลางาน (Scheduling) ======

def schedule_queue_items():
    """
    จัดตารางเวลาสำหรับงานที่ admin ได้กำหนดวันที่ไว้แล้ว (scheduled_date)
    เปลี่ยนสถานะจาก PENDING/INCOMPLETE เป็น SCHEDULED
    พร้อมคำนวณช่วงเวลาทำงานโดยอัตโนมัติตามทีมและวันที่

    กระบวนการ:
    1. ดึง item ที่มี scheduled_date และ assigned_team แล้ว
    2. จัดสรร time slot ให้แต่ละทีมในแต่ละวัน (เริ่มที่ 08:30)
    3. คำนวณเวลาสิ้นสุดตามประมาณการชั่วโมงทำงานของแต่ละประเภทงาน
    4. ส่งข้อความแจ้งเตือนไปยังทีม

    Returns:
        int: จำนวนงานที่ถูก schedule ในครั้งนี้ (0 หากไม่มีงานที่ต้อง schedule)
    """
    from pms.models import ServiceQueueItem, TeamMessage

    # Get pending items that admin has set a date for
    # ดึงงานที่รอการ schedule: ต้องมี scheduled_date และ assigned_team ครบ
    items = ServiceQueueItem.objects.filter(
        status__in=['PENDING', 'INCOMPLETE'],
        scheduled_date__isnull=False,
        assigned_team__isnull=False,
    )

    if not items.exists():
        return 0

    count = items.count()

    # Auto-assign time slots per team per date
    # ใช้ defaultdict เพื่อติดตาม time slot ของแต่ละทีมในแต่ละวัน
    # key = (team_id, date), value = {'hour': ชั่วโมงปัจจุบัน, 'min': นาทีปัจจุบัน}
    # เริ่มต้น slot แรกของทุกทีมที่ 08:30
    from collections import defaultdict
    team_date_slots = defaultdict(lambda: {'hour': 8, 'min': 30})

    # เรียงลำดับงานตามวันที่ > deadline > วันที่สร้าง เพื่อจัดลำดับความสำคัญ
    for item in items.order_by('scheduled_date', 'deadline', 'created_at'):
        # key สำหรับ lookup time slot ของทีมนี้ในวันนี้
        key = (item.assigned_team_id, item.scheduled_date)
        slot = team_date_slots[key]

        # ประมาณการชั่วโมงทำงานตามประเภทงาน (ชั่วโมง)
        # REPAIR=2h, INSTALLATION=3h, DELIVERY=1.5h, OTHER=1h
        est_hours = {'REPAIR': 2.0, 'INSTALLATION': 3.0, 'DELIVERY': 1.5, 'OTHER': 1.0}.get(item.task_type, 1.0)

        # กำหนดเวลาเริ่มงานและประมาณการชั่วโมง แล้วบันทึก
        item.scheduled_time = datetime.time(slot['hour'], slot['min'])
        item.estimated_hours = est_hours
        item.status = 'SCHEDULED'
        item.save()

        # Advance time: คำนวณ time slot ถัดไปโดยบวกเวลาที่ใช้ทำงาน
        total_mins = int(est_hours * 60)
        slot['min'] += total_mins
        # แปลงนาทีที่เกิน 60 ให้เป็นชั่วโมง (carry-over)
        while slot['min'] >= 60:
            slot['min'] -= 60
            slot['hour'] += 1

    # ส่งข้อความแจ้งเตือนไปยังทีมทั้งหมดที่ได้รับมอบหมายงาน
    # Send team messages grouped by date
    _send_schedule_messages(items)

    return count


# ====== ส่วนส่งข้อความแจ้งเตือน ======

def _send_schedule_messages(items):
    """
    สร้างและส่ง TeamMessage เพื่อแจ้งรายการงานประจำวันให้แต่ละทีม
    จัดกลุ่มงานตาม (team, date) เพื่อส่งข้อความรวมครั้งเดียวต่อทีมต่อวัน

    Args:
        items (QuerySet): ServiceQueueItem ที่เพิ่งถูก schedule
    """
    from pms.models import ServiceTeam, TeamMessage
    from collections import defaultdict

    # Group by team + date
    # จัดกลุ่มงานตาม (team_id, scheduled_date) เพื่อส่ง message รวม
    groups = defaultdict(list)
    for item in items:
        if item.assigned_team:
            groups[(item.assigned_team_id, item.scheduled_date)].append(item)

    # สร้าง message สำหรับแต่ละกลุ่ม (ทีม + วัน)
    for (team_id, date), tasks in groups.items():
        team = ServiceTeam.objects.get(id=team_id)

        # สร้างเนื้อหา message แบบ text ที่มีรายละเอียดงานแต่ละชิ้น
        lines = [f"📋 คิวงานวันที่ {date.strftime('%d/%m/%Y')}"]
        lines.append(f"ทีม: {team.name} | จำนวน: {len(tasks)} งาน")
        lines.append("=" * 40)

        for i, task in enumerate(tasks, 1):
            time_str = task.scheduled_time.strftime('%H:%M') if task.scheduled_time else '-'
            lines.append(f"\n{i}. [{time_str}] {task.title}")
            lines.append(f"   ประเภท: {task.get_task_type_display()}")
            if task.deadline:
                lines.append(f"   กำหนดส่ง: {task.deadline.strftime('%d/%m/%Y')}")
            if task.description:
                # ตัดคำอธิบายให้ไม่เกิน 80 ตัวอักษรเพื่อไม่ให้ message ยาวเกินไป
                lines.append(f"   {task.description[:80]}")

        lines.append("\n" + "=" * 40)

        # บันทึก TeamMessage ในฐานข้อมูลและเชื่อมโยงกับงานที่เกี่ยวข้อง
        msg = TeamMessage.objects.create(
            team=team,
            subject=f"📋 คิวงาน {date.strftime('%d/%m/%Y')} ({len(tasks)} งาน)",
            content="\n".join(lines),
        )
        # เชื่อมโยง message กับ task ทั้งหมดในกลุ่มนี้ (many-to-many)
        msg.related_tasks.set(tasks)

        # External Notifications (Google Chat / LINE)
        # ส่งการแจ้งเตือนภายนอก (ถ้าล้มเหลวไม่ให้หยุดการทำงาน)
        try:
            _post_external_notifications(team, msg.subject, msg.content)
        except Exception as e:
            logger.error(f"Failed to post external notifications: {e}")


def _post_external_notifications(team, subject, content):
    """
    ส่งการแจ้งเตือนไปยัง platform ภายนอกที่ทีมกำหนดไว้
    รองรับ 2 platform:
    - Google Chat: ใช้ Webhook URL ของทีม
    - LINE Notify: ใช้ LINE Token ของทีม
    ถ้าทีมไม่ได้กำหนด webhook/token ไว้ จะข้ามการส่งไป

    Args:
        team (ServiceTeam): ทีมที่ต้องการส่งการแจ้งเตือน
        subject (str): หัวข้อ message
        content (str): เนื้อหา message
    """

    # Send to Google Chat
    # ส่งไปยัง Google Chat ถ้าทีมมี webhook URL กำหนดไว้
    if team.google_chat_webhook:
        try:
            # Google Chat Card format is a bit complex, but simple text works too
            # ใช้รูปแบบ simple text message (ไม่ใช้ Card format เพื่อความเรียบง่าย)
            payload = {
                "text": f"*{subject}*\n{content}"
            }
            requests.post(
                team.google_chat_webhook,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"}
            )
            logger.info(f"Notification sent to Google Chat for team {team.name}")
        except Exception as e:
            logger.warning(f"Google Chat notify failed: {e}")

    # Send to LINE Notify
    # ส่งไปยัง LINE Notify ถ้าทีมมี LINE Token กำหนดไว้
    if team.line_token:
        try:
            line_url = "https://notify-api.line.me/api/notify"
            # ใส่ Bearer token ใน Authorization header ตาม LINE Notify API spec
            headers = {"Authorization": f"Bearer {team.line_token}"}
            data = {"message": f"\n{subject}\n{content}"}
            requests.post(line_url, headers=headers, data=data)
            logger.info(f"Notification sent to LINE for team {team.name}")
        except Exception as e:
            logger.warning(f"LINE notify failed: {e}")
