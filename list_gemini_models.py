import os
import django
from google import genai
from django.conf import settings

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

def list_models():
    api_key = settings.GEMINI_API_KEY
    if not api_key or api_key == 'YOUR_API_KEY_HERE':
        print("API Key is missing or invalid in settings.")
        return
        
    client = genai.Client(api_key=api_key)
    
    print(f"Listing models for API Key: {api_key[:5]}...{api_key[-5:]}")
    try:
        for model in client.models.list():
            print(f"- {model.name}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_models()
