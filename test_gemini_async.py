import os
import django
import asyncio
import sys

# Set encoding for Windows shell
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chatbot.services.gemini import gemini_chat_async

async def test_async_gemini():
    print("Testing Async Gemini (Non-streaming but yielding once)...")
    q1 = "มีงานซ่อมอะไรบ้างตอนนี้"
    print(f"User: {q1}")
    async for chunk in gemini_chat_async(q1):
        print(f"Result: {chunk}", flush=True)
    print("\n" + "-" * 20)
    
    q2 = "สรุปยอดโครงการให้หน่อย"
    print(f"User: {q2}")
    async for chunk in gemini_chat_async(q2):
        print(f"Result: {chunk}", flush=True)
    print("\nDone.")

if __name__ == "__main__":
    asyncio.run(test_async_gemini())
