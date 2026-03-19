from django.urls import path
from . import consumers

# เส้นทาง (Route) สำหรับการรับส่งข้อมูลผ่าน WebSocket ของระบบ PMS
# ใช้สำหรับการสื่อสารแบบ Real-time เช่น ระบบ Chatbot ของ PMS
websocket_urlpatterns = [
    path("ws/pms/chat/", consumers.PmsChatConsumer.as_asgi()),
]
