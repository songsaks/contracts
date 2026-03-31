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
    from pms.models import Project, ServiceQueueItem, ServiceTeam, JobStatus
    from django.db.models import Q

    active_statuses = ['PENDING', 'SCHEDULED', 'IN_PROGRESS', 'INCOMPLETE']
    teams = list(ServiceTeam.objects.filter(is_active=True))
    count = 0

    # Convention: any project whose status_key starts with QUEUE_ enters the AI Queue
    ready_projects = Project.objects.select_for_update().filter(status__startswith='QUEUE_')

    if not ready_projects.exists():
        return 0

    # Map job_type → ServiceQueueItem.TaskType for the queue card label
    _task_type_map = {
        'PROJECT': 'INSTALLATION',
        'REPAIR':  'REPAIR',
        'SERVICE': 'DELIVERY',
    }

    for proj in ready_projects:
        active_tasks = ServiceQueueItem.objects.filter(
            project=proj,
            status__in=active_statuses
        ).order_by('-updated_at')

        if active_tasks.exists():
            if active_tasks.count() > 1:
                for t_del in active_tasks[1:]:
                    t_del.delete()
            continue

        task_type = _task_type_map.get(proj.job_type, 'OTHER')
        # Use the JobStatus label as the queue card title
        js = JobStatus.objects.filter(
            job_type=proj.job_type, status_key=proj.status, is_active=True
        ).first()
        label = js.label if js else proj.status

        # ขอคำแนะนำทีมจาก AI (หรือ fallback logic) เฉพาะเมื่อมีทีมในระบบ
        suggested_team = get_ai_team_suggestion(task_type, teams) if teams else None

        # สร้าง ServiceQueueItem ใหม่พร้อมข้อมูลครบถ้วน
        item = ServiceQueueItem.objects.create(
            title=f"{label} · {proj.name}",
            description=f"ลูกค้า: {proj.customer.name}\n{proj.description or ''}".strip(),
            project=proj,
            task_type=task_type,
            priority='NORMAL',
            deadline=proj.deadline,
            status='PENDING',
        )
        # assigned_teams เป็น M2M — ต้อง set หลัง create()
        if suggested_team:
            item.assigned_teams.set([suggested_team])
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
    # ดึงงานที่รอการ schedule: ต้องมี scheduled_date และมีทีมอย่างน้อย 1 ทีม
    items = ServiceQueueItem.objects.filter(
        status__in=['PENDING', 'INCOMPLETE'],
        scheduled_date__isnull=False,
        assigned_teams__isnull=False,
    ).prefetch_related('assigned_teams').distinct()

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
        teams = list(item.assigned_teams.all())
        if not teams:
            continue

        # ประมาณการชั่วโมงทำงานตามประเภทงาน (ชั่วโมง)
        # REPAIR=2h, INSTALLATION=3h, DELIVERY=1.5h, OTHER=1h
        est_hours = {'REPAIR': 2.0, 'INSTALLATION': 3.0, 'DELIVERY': 1.5, 'OTHER': 1.0}.get(item.task_type, 1.0)

        # คำนวณ time slot สำหรับทุกทีม — ใช้เวลาเร็วที่สุด (ทีมแรก) เป็น scheduled_time ของงาน
        first_slot_time = None
        for team in teams:
            key = (team.id, item.scheduled_date)
            slot = team_date_slots[key]
            if first_slot_time is None:
                first_slot_time = datetime.time(slot['hour'], slot['min'])
            # เลื่อน time slot ของทีมนี้ไปข้างหน้า
            total_mins = int(est_hours * 60)
            slot['min'] += total_mins
            while slot['min'] >= 60:
                slot['min'] -= 60
                slot['hour'] += 1

        # กำหนดเวลาเริ่มงานและประมาณการชั่วโมง แล้วบันทึก
        item.scheduled_time = first_slot_time
        item.estimated_hours = est_hours
        item.status = 'SCHEDULED'
        item.save()

    # ส่งข้อความแจ้งเตือนไปยังทีมทั้งหมดที่ได้รับมอบหมายงาน
    # Send team messages grouped by date
    _send_schedule_messages(items)

    return count


# ====== ส่วนส่งข้อความแจ้งเตือน ======

def _clean_description(title: str, description: str, max_len: int = 70) -> str:
    """
    ทำความสะอาด description โดย:
    - ตัดประโยคซ้ำซ้อน (ทั้ง exact-duplicate และ near-duplicate)
    - ลบประโยคที่ซ้ำกับ title
    - ตัดคำ (word boundary) พร้อม '…' อย่างสวยงาม
    """
    import re
    if not description:
        return ''

    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', description.strip())

    # ตรวจ pattern ซ้ำง่ายๆ: "X X" หรือ "X X X" → ลดเหลือ "X"
    half = len(text) // 2
    if half > 15 and text[:half].strip() == text[half:].strip():
        text = text[:half].strip()

    # Sentence-level dedup
    raw_sentences = re.split(r'[.!?\n]+', text)
    seen: set = set()
    unique: list = []
    title_lower = title.lower()
    for s in raw_sentences:
        s = s.strip()
        if not s:
            continue
        s_norm = re.sub(r'\s+', ' ', s.lower()).strip(' .!?')
        if s_norm in seen:
            continue
        seen.add(s_norm)
        # ข้ามประโยคที่เป็น substring ของ title (ซ้ำกับหัวข้อ)
        if s_norm and s_norm in title_lower:
            continue
        unique.append(s)

    text = '  ·  '.join(unique) if unique else text

    # Smart truncation at word boundary
    if len(text) > max_len:
        cut = text[:max_len]
        for sep in (' ', '·', ',', ')', ']'):
            pos = cut.rfind(sep)
            if pos > int(max_len * 0.55):
                text = cut[:pos].rstrip(' ·,') + '…'
                break
        else:
            text = cut.rstrip() + '…'

    return text


def _get_customer_name(task) -> str:
    """ดึงชื่อลูกค้าจาก task อย่างปลอดภัย"""
    try:
        if task.project and task.project.customer:
            return task.project.customer.name
    except Exception:
        pass
    return '—'


def _send_schedule_messages(items):
    """
    สร้างและส่ง TeamMessage เพื่อแจ้งรายการงานประจำวันให้แต่ละทีม
    จัดกลุ่มงานตาม (team, date) เพื่อส่งข้อความรวมครั้งเดียวต่อทีมต่อวัน
    """
    from pms.models import ServiceTeam, TeamMessage
    from collections import defaultdict

    _PRIORITY = {'CRITICAL': ' 🚨', 'HIGH': ' ⚡', 'NORMAL': '', 'LOW': ''}

    # Group by (team_id, scheduled_date)
    groups: dict = defaultdict(list)
    for item in items:
        for team in item.assigned_teams.all():
            groups[(team.id, item.scheduled_date)].append(item)

    for (team_id, date), tasks in groups.items():
        team = ServiceTeam.objects.get(id=team_id)

        SEP = '─' * 32
        lines = [
            f"📋 คิวงานทีม {team.name}",
            f"📅 {date.strftime('%d/%m/%Y')}  ·  {len(tasks)} งาน",
            SEP,
        ]

        for i, task in enumerate(tasks, 1):
            time_str  = task.scheduled_time.strftime('%H:%M') if task.scheduled_time else '—:——'
            priority  = _PRIORITY.get(getattr(task, 'priority', 'NORMAL'), '')
            cust_name = _get_customer_name(task)

            # Type + optional deadline on one line
            meta = task.get_task_type_display()
            if task.deadline:
                meta += f"  ·  กำหนดส่ง {task.deadline.strftime('%d/%m')}"

            desc = _clean_description(task.title, task.description)

            lines.append(f"\n{i}.  {time_str}  {task.title}{priority}")
            lines.append(f"     👤 {cust_name}")
            lines.append(f"     🏷 {meta}")
            if desc:
                lines.append(f"     💬 {desc}")

        lines += [f"\n{SEP}", f"ทีม {team.name}  ·  รวม {len(tasks)} งาน"]

        msg = TeamMessage.objects.create(
            team=team,
            subject=f"📋 คิวงาน {date.strftime('%d/%m/%Y')} · ทีม {team.name} ({len(tasks)} งาน)",
            content="\n".join(lines),
        )
        msg.related_tasks.set(tasks)

        try:
            _post_external_notifications(team, msg.subject, msg.content)
        except Exception as e:
            logger.error(f"Failed to post external notifications: {e}")


def _post_external_notifications(team, subject, content):
    """
    ส่งการแจ้งเตือนไปยัง Google Chat และ LINE Notify
    """
    # ── Google Chat ──────────────────────────────────────────────────────────
    if team.google_chat_webhook:
        try:
            # Google Chat รองรับ *bold* และ _italic_
            gc_text = f"*{subject}*\n\n{content}"
            requests.post(
                team.google_chat_webhook,
                data=json.dumps({"text": gc_text}),
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            logger.info(f"Google Chat notification sent: team={team.name}")
        except Exception as e:
            logger.warning(f"Google Chat notify failed: {e}")

    # ── LINE Notify ───────────────────────────────────────────────────────────
    if team.line_token:
        try:
            # LINE ไม่รองรับ markdown — ส่ง plain text
            line_msg = f"\n{subject}\n\n{content}"
            requests.post(
                "https://notify-api.line.me/api/notify",
                headers={"Authorization": f"Bearer {team.line_token}"},
                data={"message": line_msg},
                timeout=10,
            )
            logger.info(f"LINE notification sent: team={team.name}")
        except Exception as e:
            logger.warning(f"LINE notify failed: {e}")
