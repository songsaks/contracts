import os
import sys

# Add the project root to python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.test import RequestFactory
from stocks.views import api_ai_manual_scan
import json

User = get_user_model()
user = User.objects.first() # Get the first user

if not user:
    print("No users found in database.")
    sys.exit(1)

print(f"Running debug for user: {user.username} (ID: {user.id})")

# Create a mock POST request
factory = RequestFactory()
request = factory.post('/stocks/api/ai-manual-scan/', 
                       data=json.dumps({'market': 'SET'}),
                       content_type='application/json')
request.user = user

# Call the view directly
try:
    response = api_ai_manual_scan(request)
    print("Response Status Code:", response.status_code)
    print("Response Content (first 500 chars):")
    print(response.content[:1000].decode('utf-8'))
except Exception as e:
    import traceback
    print("Exception occurred:")
    traceback.print_exc()
