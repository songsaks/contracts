# ====== URL Configuration สำหรับแอป Landing Page ======
# ไฟล์นี้กำหนด URL patterns ของแอป landing
# ถูก include เข้าใน urls.py หลักของโปรเจกต์

from django.urls import path
from . import views

# ชื่อ namespace ของแอปนี้ — ใช้อ้างอิง URL ด้วย {% url 'landing:index' %} ใน template
app_name = 'landing'

urlpatterns = [
    # URL หน้าหลัก (root path) — แสดง Landing Page เพื่อให้ผู้ใช้เลือกระบบ
    path('', views.index, name='index'),
]
