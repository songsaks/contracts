from django.urls import path
from .views import chatbot_message

app_name = 'chatbot'

urlpatterns = [
    path('api/message/', chatbot_message, name='chatbot_message'),
]
