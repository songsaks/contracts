import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from chatbot.services.gemini import gemini_reply

def test_gemini():
    print("Testing Gemini directly...")
    # Test project search
    q1 = "มีโครงการอะไรบ้างตอนนี้"
    print(f"User: {q1}")
    r1 = gemini_reply(q1)
    print(f"Bot: {r1}")
    
    print("-" * 20)
    
    # Test task creation
    q2 = "สร้างงานซ่อมก๊อกน้ำให้หน่อย ด่วน"
    print(f"User: {q2}")
    r2 = gemini_reply(q2)
    print(f"Bot: {r2}")

if __name__ == "__main__":
    test_gemini()
