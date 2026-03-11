"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# กำหนดสิทธิ์และเตรียม Django แอพหลักให้พร้อมทำงานก่อนที่จะเรียกใช้งานแอพย่อยอื่น ๆ
django_asgi_app = get_asgi_application()

# ตอนนี้นำเข้า Routing ของ Channels ได้เพื่อหลีกเลี่ยง AppRegistryNotReady Error
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import pms.routing
import chat.routing

# รวมเส้นทาง WebSocket จากทุกแอปเข้าด้วยกัน
combined_websocket_urls = (
    pms.routing.websocket_urlpatterns + 
    chat.routing.websocket_urlpatterns
)

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            combined_websocket_urls
        )
    ),
})
