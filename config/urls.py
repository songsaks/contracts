"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# ====== URL Configuration หลักของโปรเจกต์ ======
# ไฟล์นี้เป็นจุดรวม URL ทั้งหมดของโปรเจกต์
# แต่ละแอปจะมีไฟล์ urls.py ของตัวเอง และถูก include เข้ามาที่นี่

from django.contrib import admin
from django.urls import path, include

# ====== URL Patterns หลัก ======
# รายการ URL ทั้งหมดของโปรเจกต์ แบ่งตามแอป
urlpatterns = [
    path('admin/', admin.site.urls),                           # หน้า Django Admin
    path('accounts/', include('accounts.urls')),               # URL ของระบบ accounts (custom)
    path('accounts/', include('django.contrib.auth.urls')),    # URL ของ Django auth (login, logout, password reset)
    path('contracts/', include('rentals.urls')),               # URL ของระบบสัญญาเช่า
    path('repairs/', include('repairs.urls')),                 # URL ของระบบแจ้งซ่อม
    path('pos/', include('pos.urls')),                         # URL ของระบบ Point of Sale
    path('pms/', include('pms.urls')),                         # URL ของระบบ Property Management
    path('stocks/', include('stocks.urls')),                   # URL ของระบบสต็อกสินค้า
    path('payroll/', include('payroll.urls')),                 # URL ของระบบเงินเดือน
    path('chatbot/', include('chatbot.urls')),                 # URL ของระบบ Chatbot
    path('chat/', include('chat.urls')),                       # URL ของระบบแชท Real-time
    path('', include('landing.urls')),                        # URL ของหน้าแรก (root path)
]

# ====== การนำเข้า Library สำหรับ Static/Media Files ======
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView

# ====== Static และ Media Files (เฉพาะ Development Mode) ======
# ในโหมด DEBUG ให้ Django จัดการ serve ไฟล์ static และ media เอง
# บน Production ควรให้ Web Server (Nginx/Apache) จัดการแทนเพื่อประสิทธิภาพที่ดีกว่า
if settings.DEBUG:
    if settings.STATIC_URL:
        # Use first entry of STATICFILES_DIRS if available, else fallback to something safe
        # เสิร์ฟไฟล์ static จากโฟลเดอร์แรกใน STATICFILES_DIRS หรือ STATIC_ROOT หากไม่มี
        root = settings.STATICFILES_DIRS[0] if settings.STATICFILES_DIRS else settings.STATIC_ROOT
        urlpatterns += static(settings.STATIC_URL, document_root=root)
    if settings.MEDIA_URL:
        # เสิร์ฟไฟล์ media (ไฟล์ที่ผู้ใช้อัปโหลด) จากโฟลเดอร์ MEDIA_ROOT
        urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# ====== Favicon Redirect ======
# Redirect คำขอ favicon.ico ไปยังไฟล์ SVG จริงใน static files
# ป้องกัน 404 error ที่เกิดจาก browser พยายามโหลด favicon โดยอัตโนมัติ
# Add favicon.ico redirect for better browser compatibility
urlpatterns += [
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'images/favicon.svg')),
]
