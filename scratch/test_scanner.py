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
user = User.objects.filter(is_superuser=True).first() or User.objects.first()
print('Logged in user:', user)
client.force_login(user)
response = client.post('/stocks/api/ai-manual-scan/', data='{"market":"SET"}', content_type='application/json')
print('Status Code:', response.status_code)
print('Content (first 500 chars):', response.content[:500])
