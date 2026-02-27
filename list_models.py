import os
from google import genai
from django.conf import settings
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

client = genai.Client(api_key=settings.GEMINI_API_KEY)

print("Listing available models...")
try:
    models = client.models.list()
    for m in models:
        print(f"Model: {m.name}")
except Exception as e:
    print(f"Error listing models: {e}")
