from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/pms/chat/", consumers.PmsChatConsumer.as_asgi()),
]
