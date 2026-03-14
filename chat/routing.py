from django.urls import re_path
from . import consumers

# เส้นทางการเข้าถึง WebSocket สำหรับระบบแชท
websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<room_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
    re_path(r'ws/chat/notify/$', consumers.NotificationConsumer.as_asgi()),
]
