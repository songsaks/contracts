# ====== Chatbot URL Patterns ======
# ไฟล์นี้กำหนด URL routing สำหรับ app chatbot
# ทุก URL ใน app นี้จะถูก prefix ด้วย chatbot/ จาก main urls.py

from django.urls import path
from .views import chatbot_message  # นำเข้า view function สำหรับรับข้อความ chatbot

# กำหนด namespace ของ app เพื่อใช้อ้างอิงใน template เช่น {% url 'chatbot:chatbot_message' %}
app_name = 'chatbot'

urlpatterns = [
    # POST /chatbot/api/message/ -> chatbot_message view
    # endpoint นี้รับข้อความจาก frontend และส่งคืนคำตอบจาก Gemini AI
    path('api/message/', chatbot_message, name='chatbot_message'),
]
