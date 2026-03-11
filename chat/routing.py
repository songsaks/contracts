from django.urls import re_path
from . import consumers

# เส้นทางการเข้าถึง WebSocket สำหรับระบบแชท
websocket_urlpatterns = [
    # ตั้งค่าเส้นทางด้วย regex: /ws/chat/<room_id>/
    re_path(r'ws/chat/(?P<room_id>\d+)/$', consumers.ChatConsumer.as_asgi()),
]
