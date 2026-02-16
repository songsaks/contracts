import os
import google.generativeai as genai
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
        genai.configure(api_key=api_key, transport='rest')
        print("Listing models...")
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(m.name)
        
        model_name = 'gemini-2.0-flash'
        print(f"Trying with {model_name}...")
        model = genai.GenerativeModel(model_name)
        response = model.generate_content("Hello")
        print(f"Result: {response.text}")
    except Exception as e:
        print(f"Connection Error: {e}")
