import os
import sys
import django
from django.utils import timezone
from django.core.cache import cache

# Add project root
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from stocks.views import _run_ai_manual_scan_bg
from stocks.models import AIManualScanResult

def test_run():
    User = get_user_model()
    user = User.objects.first()
    if not user:
        print("No users found.")
        return
        
    market = 'SET'
    cache_key = f'ai_manual_scan_{user.id}_{market}'
    # Clear cache first
    cache.delete(cache_key)
    
    print(f"Running synchronous AI manual scan for user {user.username}...")
    scan_run_time = timezone.now()
    
    # Run the function synchronously
    _run_ai_manual_scan_bg(user.id, cache_key, market, scan_run_time)
    
    # Read status from cache
    status = cache.get(cache_key)
    print("\n--- Cache Status After Execution ---")
    print(status)
    
    # Check if results were created
    new_results = AIManualScanResult.objects.filter(user=user, scan_run=scan_run_time)
    print(f"\nCreated {new_results.count()} results in this run:")
    for r in new_results:
        print(f"- {r.symbol}: Grade {r.grade}, Rank {r.rank}")

if __name__ == '__main__':
    test_run()
