import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from stocks.models import PrecisionScanCandidate, AIManualScanResult

User = get_user_model()
user = User.objects.first()

if not user:
    print("No users found.")
    sys.exit(0)

print(f"User: {user.username}")
markets = ['SET', 'US']
for market in markets:
    latest_run = PrecisionScanCandidate.objects.filter(
        user=user,
        market=market
    ).order_by('-scan_run').values_list('scan_run', flat=True).first()
    
    print(f"\nMarket: {market}")
    print(f"Latest Run: {latest_run}")
    
    if latest_run:
        total = PrecisionScanCandidate.objects.filter(user=user, market=market, scan_run=latest_run).count()
        filtered = PrecisionScanCandidate.objects.filter(
            user=user, 
            market=market,
            scan_run=latest_run,
            rs_rating__gte=60,
            stage2=True
        ).count()
        print(f"Total candidates in latest run: {total}")
        print(f"Candidates with RS >= 60 and Stage 2: {filtered}")
        
    ai_results = AIManualScanResult.objects.filter(user=user, market=market).count()
    print(f"AI Manual Scan Results: {ai_results}")
