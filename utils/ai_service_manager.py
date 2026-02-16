"""
AI Service Queue Manager
- Syncs tasks from Projects based on specific statuses
- AI suggests team assignments based on task type
- Groups tasks by scheduled date
"""
import logging
import datetime
from django.utils import timezone
from django.db import models
from django.conf import settings

logger = logging.getLogger(__name__)


def get_ai_team_suggestion(task_type, teams):
    """
    AI suggests the best team based on task type and team skills.
    Returns the suggested team or None.
    """
    try:
        api_key = getattr(settings, 'GEMINI_API_KEY', None)
        if api_key and api_key != 'YOUR_API_KEY_HERE':
            return _ai_suggest_team(task_type, teams)
    except Exception as e:
        logger.warning(f"AI team suggestion failed: {e}")

    # Fallback: match by skill
    return _fallback_suggest_team(task_type, teams)


def _ai_suggest_team(task_type, teams):
    """Use Gemini to pick the best team."""
    try:
        import google.generativeai as genai
        api_key = settings.GEMINI_API_KEY
        genai.configure(api_key=api_key, transport='rest')

        team_info = "\n".join([
            f"- Team '{t.name}': skills={t.skills}, current load={t.tasks.filter(status__in=['SCHEDULED','IN_PROGRESS']).count()}/{t.max_tasks_per_day}"
            for t in teams
        ])

        prompt = f"""You are scheduling tasks for a service company.
Task type: {task_type}
Available teams:
{team_info}

Pick the best team name. Reply with ONLY the team name, nothing else."""

        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        suggested_name = response.text.strip()

        for t in teams:
            if t.name.lower() in suggested_name.lower() or suggested_name.lower() in t.name.lower():
                return t
    except Exception as e:
        logger.warning(f"Gemini team suggestion failed: {e}")

    return _fallback_suggest_team(task_type, teams)


def _fallback_suggest_team(task_type, teams):
    """Fallback: match team by skills, prefer less loaded teams."""
    best = None
    best_score = -1

    for team in teams:
        if not team.is_active:
            continue
        score = team.max_tasks_per_day - team.tasks.filter(status__in=['SCHEDULED', 'IN_PROGRESS']).count()
        if task_type in team.skill_list():
            score += 10
        if score > best_score:
            best_score = score
            best = team

    return best


def sync_projects_to_queue():
    """
    Pull Projects into ServiceQueueItem with robust rules:
    1. DELETE items that are orphaned (no project) or projects moved out of trigger statuses
       Unless they are ALREADY COMPLETED or CANCELLED.
    2. Ensure only ONE active queue item per project.
    """
    from pms.models import Project, ServiceQueueItem, ServiceTeam
    from django.db.models import Q

    # 1. Cleanup: Delete queue items that shouldn't be here
    # - Orphaned items
    # - Items where project status changed away from trigger statuses (and not finished in queue)
    trigger_q = (
        Q(project__status='INSTALLATION') |
        Q(project__job_type='REPAIR', project__status='ORDERING') |
        Q(project__job_type='SERVICE', project__status='DELIVERY')
    )
    
    ServiceQueueItem.objects.filter(
        ~trigger_q | Q(project__isnull=True)
    ).exclude(
        status__in=['COMPLETED']
    ).delete()

    # 2. Sync new items
    teams = list(ServiceTeam.objects.filter(is_active=True))
    count = 0

    ready_projects = Project.objects.filter(
        Q(status='INSTALLATION') |
        Q(job_type='REPAIR', status='ORDERING') |
        Q(job_type='SERVICE', status='DELIVERY')
    ).exclude(
        service_tasks__status__in=['PENDING', 'SCHEDULED', 'IN_PROGRESS', 'COMPLETED']
    )

    for proj in ready_projects:
        if proj.status == 'INSTALLATION':
            task_type, label = 'INSTALLATION', 'ติดตั้ง'
        elif proj.job_type == 'REPAIR':
            task_type, label = 'REPAIR', 'ซ่อม'
        else:
            task_type, label = 'DELIVERY', 'ส่งของ (งานขาย)'

        suggested_team = get_ai_team_suggestion(task_type, teams) if teams else None

        ServiceQueueItem.objects.create(
            title=f"{label}: {proj.name}",
            description=f"ลูกค้า: {proj.customer.name}\n{proj.description or ''}".strip(),
            project=proj,
            task_type=task_type,
            priority='NORMAL',
            assigned_team=suggested_team,
            deadline=proj.deadline,
            status='PENDING',
            ai_urgency_reason=f"AI แนะนำทีม: {suggested_team.name}" if suggested_team else "ไม่มีทีมในระบบ",
        )
        count += 1

    return count





def schedule_queue_items():
    """
    Schedule PENDING items that have a scheduled_date set by admin.
    Groups them and sets status to SCHEDULED.
    Returns count of scheduled items.
    """
    from pms.models import ServiceQueueItem, TeamMessage

    # Get pending items that admin has set a date for
    items = ServiceQueueItem.objects.filter(
        status='PENDING',
        scheduled_date__isnull=False,
        assigned_team__isnull=False,
    )

    if not items.exists():
        return 0

    count = items.count()

    # Auto-assign time slots per team per date
    from collections import defaultdict
    team_date_slots = defaultdict(lambda: {'hour': 8, 'min': 30})

    for item in items.order_by('scheduled_date', 'deadline', 'created_at'):
        key = (item.assigned_team_id, item.scheduled_date)
        slot = team_date_slots[key]

        est_hours = {'REPAIR': 2.0, 'INSTALLATION': 3.0, 'DELIVERY': 1.5, 'OTHER': 1.0}.get(item.task_type, 1.0)

        item.scheduled_time = datetime.time(slot['hour'], slot['min'])
        item.estimated_hours = est_hours
        item.status = 'SCHEDULED'
        item.save()

        # Advance time
        total_mins = int(est_hours * 60)
        slot['min'] += total_mins
        while slot['min'] >= 60:
            slot['min'] -= 60
            slot['hour'] += 1

    # Send team messages grouped by date
    _send_schedule_messages(items)

    return count


def _send_schedule_messages(items):
    """Send notification messages to teams about their scheduled tasks."""
    from pms.models import ServiceTeam, TeamMessage
    from collections import defaultdict

    # Group by team + date
    groups = defaultdict(list)
    for item in items:
        if item.assigned_team:
            groups[(item.assigned_team_id, item.scheduled_date)].append(item)

    for (team_id, date), tasks in groups.items():
        team = ServiceTeam.objects.get(id=team_id)

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
                lines.append(f"   {task.description[:80]}")

        lines.append("\n" + "=" * 40)

        msg = TeamMessage.objects.create(
            team=team,
            subject=f"📋 คิวงาน {date.strftime('%d/%m/%Y')} ({len(tasks)} งาน)",
            content="\n".join(lines),
        )
        msg.related_tasks.set(tasks)
