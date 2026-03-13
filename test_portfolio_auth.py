
import os
import sys
import django

# Setup path and environment
sys.path.insert(0, r'd:\DjangoProjects\contracts')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth.models import User

# Get user
try:
    user = User.objects.get(username='songsak')
    print(f"Logged in as {user.username}")
except User.DoesNotExist:
    print("User 'songsak' not found")
    sys.exit(1)

client = Client()
client.force_login(user)

# Execute request
print("Requesting portfolio page...")
response = client.get('/stocks/portfolio/')

print(f"Status Code: {response.status_code}")
if response.status_code == 200:
    print("Success! Checking for log file...")
    log_path = os.path.join(os.getcwd(), 'portfolio_debug.log')
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            print("\n--- LOG CONTENT ---")
            print(f.read())
            print("--- END LOG ---")
    else:
        print(f"Log file NOT found at {log_path}")
else:
    print("Response content snippet:")
    print(response.content[:1000].decode('utf-8'))
