import os
import django
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from ops.models import WeeklyGoal

def sync_statuses():
    today = timezone.now().date()
    goals = WeeklyGoal.objects.all()
    count = 0
    for g in goals:
        progress = g.success_percentage
        if progress >= 100:
            g.status = 'done'
        elif progress > 0 or (g.start_date <= today <= g.end_date):
            g.status = 'doing'
        else:
            g.status = 'todo'
        g.save()
        print(f"Updated: {g.title} -> {g.status}")
        count += 1
    print(f"Finished syncing {count} goals.")

if __name__ == "__main__":
    sync_statuses()
