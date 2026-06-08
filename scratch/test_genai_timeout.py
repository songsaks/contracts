import os
import django
import google.genai as genai
from google.genai import types
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

def test_client_timeout():
    api_key = settings.GEMINI_API_KEY
    print("Testing client with timeout config...")
    try:
        # 30 seconds timeout (30,000 milliseconds)
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=30_000)
        )
        print("Client initialized successfully.")
        # Try a quick call
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='Hello, respond in one word.'
        )
        print(f"Response: {response.text.strip()}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == '__main__':
    test_client_timeout()
