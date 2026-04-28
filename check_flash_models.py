import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

try:
    models = [m.name for m in genai.list_models() if 'flash' in m.name.lower() and 'generateContent' in m.supported_generation_methods]
    print("Available Flash Models:")
    for m in models:
        print(m)
except Exception as e:
    print(f"Error: {e}")
