# ====== Views สำหรับแอป Landing Page ======
# ไฟล์นี้จัดการ logic การแสดงผลหน้าหลักของ 9Com Portal

from django.shortcuts import render

# ====== View: หน้าหลัก (Landing Page) ======
def index(request):
    """แสดงหน้า Landing Page หลักของ 9Com Portal

    รับ request แล้ว render template 'landing/index.html'
    โดยไม่ต้องส่ง context เพิ่มเติม เพราะ template ใช้ {{ user }} จาก request โดยตรง
    """
    return render(request, 'landing/index.html')
