import os
import django
from django.test import Client

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

client = Client(HTTP_HOST='127.0.0.1')

print("--- Test Unauthenticated Post ---")
response = client.post('/stocks/api/ai-manual-scan/', data='{"market":"SET"}', content_type='application/json')
print('Status Code:', response.status_code)
print('Redirect URL:', response.get('Location'))
print('Content (first 500 chars):', response.content[:500])

print("\n--- Test Authenticated Post ---")
from django.contrib.auth.models import User
import time
import json
from django.core.cache import cache

user = User.objects.filter(is_superuser=True).first() or User.objects.first()
print('Logged in user:', user)
client.force_login(user)

# Clear old cache state to ensure clean run
cache.delete(f'ai_manual_scan_{user.id}_SET')

response = client.post('/stocks/api/ai-manual-scan/', data='{"market":"SET"}', content_type='application/json')
print('Status Code:', response.status_code)
print('Content (first 500 chars):', response.content[:500])

print("\n--- Polling Scan Status ---")
time.sleep(0.5) # Let the background thread spin up and set status to running
for i in range(30):
    status_resp = client.get('/stocks/api/ai-manual-scan/?market=SET')
    status_data = status_resp.json()
    print(f"Poll {i+1}: {status_data}")
    if status_data.get('state') in ['done', 'failed']:
        break
    time.sleep(2.0)

