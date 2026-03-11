from django.urls import path
from . import views

app_name = 'chat'

# เส้นทางการเข้าถึงระบบแชท
urlpatterns = [
    # หน้าแรก: เลือกห้องแชท
    path('', views.chat_index, name='index'),
    # หน้าแชทในแต่ละห้องตามไอดี
    path('<int:room_id>/', views.chat_room, name='room'),
    # อัปโหลดไฟล์และรูปภาพเข้าห้องแชท
    path('<int:room_id>/upload/', views.upload_file, name='upload_file'),
    # ทางลัด: เข้าห้องแชทจาก PMS (Project ID)
    path('project/<int:project_id>/', views.project_chat, name='project_chat'),
]
