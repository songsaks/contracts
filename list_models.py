import os
from google import genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.environ.get('GEMINI_API_KEY')
client = genai.Client(api_key=api_key)

for m in client.models.list():
    print(f"Name: {m.name}, Display Name: {m.display_name}")
