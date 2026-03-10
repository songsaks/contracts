"""
AI Service Queue Manager
- Syncs tasks from Projects based on specific statuses
- AI suggests team assignments based on task type
- Groups tasks by scheduled date
"""
import logging
import datetime
from django.utils import timezone
from django.db import models, transaction
from django.conf import settings
import requests
import json

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
        from google import genai
        api_key = settings.GEMINI_API_KEY
        client = genai.Client(api_key=api_key)

        team_info = "\n".join([
            f"- Team '{t.name}': skills={t.skills}, current load={t.tasks.filter(status__in=['SCHEDULED','IN_PROGRESS']).count()}/{t.max_tasks_per_day}"
            for t in teams
        ])

        prompt = f"""You are scheduling tasks for a service company.
Task type: {task_type}
Available teams:
{team_info}

Pick the best team name. Reply with ONLY the team name, nothing else."""

        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
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


@transaction.atomic
def sync_projects_to_queue():
    """
    Pull Projects into ServiceQueueItem with robust rules:
    1. DELETE items that are orphaned (no project) or projects moved out of trigger statuses
       Unless they are ALREADY COMPLETED or CANCELLED.
    2. Ensure only ONE active queue item per project using locking to prevent race conditions.
    """
    from pms.models import Project, ServiceQueueItem, ServiceTeam
    from django.db.models import Q

    # 1. Cleanup duplicates that might have slipped through (just in case)
    # We keep the one that is most advanced or most recently updated.
    active_statuses = ['PENDING', 'SCHEDULED', 'IN_PROGRESS', 'INCOMPLETE']
    
    # 2. Sync new items based on TRIGGER STATUSES
    teams = list(ServiceTeam.objects.filter(is_active=True))
    count = 0

    # ONLY trigger tasks for these specific statuses (The "Queue" stage)
    trigger_q = (
        Q(job_type='PROJECT', status='INSTALLATION') |
        Q(job_type='SERVICE', status='DELIVERY') |
        Q(job_type='REPAIR', status='DELIVERY')
    )

    # Use select_for_update to lock these projects during sync to prevent race conditions
    ready_projects = Project.objects.select_for_update().filter(trigger_q)

    for proj in ready_projects:
        # Loop Check: Look for an ACTIVE task (not completed/cancelled)
        # We include INCOMPLETE because it's still alive in the queue for re-scheduling.
        active_tasks = ServiceQueueItem.objects.filter(
            project=proj,
            status__in=active_statuses
        ).order_by('-updated_at')

        if active_tasks.exists():
            # If accidentally duplicated, cleanup here
            if active_tasks.count() > 1:
                for t_del in active_tasks[1:]:
                    t_del.delete()
            continue # Already locked/tracking this stage

        # Determine Task Type & Label based on Job Type
        if proj.job_type == 'PROJECT':
            task_type, label = 'INSTALLATION', 'คิว (ติดตั้ง)'
        elif proj.job_type == 'REPAIR':
            task_type, label = 'REPAIR', 'คิว (ซ่อม)'
        elif proj.job_type == 'SERVICE':
            task_type, label = 'DELIVERY', 'คิว (ส่งของ)'
        else:
            task_type, label = 'OTHER', 'คิว'

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
        status__in=['PENDING', 'INCOMPLETE'],
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

        # External Notifications (Google Chat / LINE)
        try:
            _post_external_notifications(team, msg.subject, msg.content)
        except Exception as e:
            logger.error(f"Failed to post external notifications: {e}")


def _post_external_notifications(team, subject, content):
    """Notify Google Chat and LINE if configured."""
    
    # Send to Google Chat
    if team.google_chat_webhook:
        try:
            # Google Chat Card format is a bit complex, but simple text works too
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
    if team.line_token:
        try:
            line_url = "https://notify-api.line.me/api/notify"
            headers = {"Authorization": f"Bearer {team.line_token}"}
            data = {"message": f"\n{subject}\n{content}"}
            requests.post(line_url, headers=headers, data=data)
            logger.info(f"Notification sent to LINE for team {team.name}")
        except Exception as e:
            logger.warning(f"LINE notify failed: {e}")
