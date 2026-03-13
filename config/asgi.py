"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""
# ====== ASGI Configuration ======
# ไฟล์นี้กำหนดค่า ASGI (Asynchronous Server Gateway Interface)
# ใช้สำหรับรองรับ WebSocket และ HTTP แบบ async ผ่าน Django Channels
# Daphne หรือ ASGI server อื่น ๆ จะอ่านไฟล์นี้เพื่อรู้ว่าต้องเรียกใช้ application ใด

import os
from django.core.asgi import get_asgi_application

# กำหนด settings module ที่จะใช้งาน (ต้องทำก่อนการ import อื่น ๆ ที่เกี่ยวกับ Django)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# กำหนดสิทธิ์และเตรียม Django แอพหลักให้พร้อมทำงานก่อนที่จะเรียกใช้งานแอพย่อยอื่น ๆ
# การเรียก get_asgi_application() ที่นี่จะ initialize Django app registry
# ต้องทำก่อน import Channels routing เพื่อหลีกเลี่ยง AppRegistryNotReady Error
django_asgi_app = get_asgi_application()

# ตอนนี้นำเข้า Routing ของ Channels ได้เพื่อหลีกเลี่ยง AppRegistryNotReady Error
# นำเข้า Channels routing และ middleware หลังจาก Django พร้อมแล้ว
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack  # Middleware สำหรับ authenticate WebSocket connections
import pms.routing   # URL patterns สำหรับ WebSocket ของแอป PMS
import chat.routing  # URL patterns สำหรับ WebSocket ของแอป Chat

# ====== รวม WebSocket URL Patterns ======
# รวมเส้นทาง WebSocket จากทุกแอปเข้าด้วยกัน
combined_websocket_urls = (
    pms.routing.websocket_urlpatterns +   # WebSocket routes ของ PMS (เช่น real-time notifications)
    chat.routing.websocket_urlpatterns    # WebSocket routes ของ Chat (real-time messaging)
)

# ====== ASGI Application ======
# กำหนด application หลักที่ ASGI server จะเรียกใช้
# ProtocolTypeRouter แยกประเภทการเชื่อมต่อและส่งไปยัง handler ที่เหมาะสม
application = ProtocolTypeRouter({
    # HTTP requests ส่งไปยัง Django ASGI application ปกติ
    "http": django_asgi_app,
    # WebSocket connections ผ่าน AuthMiddlewareStack (ตรวจสอบ session/user)
    # แล้วส่งต่อไปยัง URLRouter ที่รู้จัก path ของ WebSocket แต่ละตัว
    "websocket": AuthMiddlewareStack(
        URLRouter(
            combined_websocket_urls
        )
    ),
})
