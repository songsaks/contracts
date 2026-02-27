import os
from google import genai
from dotenv import load_dotenv
import warnings

warnings.filterwarnings("ignore")

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
print(f"Testing API Key: {api_key[:5]}...{api_key[-5:] if api_key else ''}")

if not api_key:
    print("Error: GEMINI_API_KEY not found in .env")
else:
    try:
        client = genai.Client(api_key=api_key)
        print("Listing models...")
        for m in client.models.list():
            print(m.name)
        
        model_name = 'gemini-2.0-flash'
        print(f"Trying with {model_name}...")
        response = client.models.generate_content(
            model=model_name,
            contents="Hello"
        )
        print(f"Result: {response.text}")
    except Exception as e:
        print(f"Connection Error: {e}")
