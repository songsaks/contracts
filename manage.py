#!/usr/bin/env python
# ====== manage.py ======
# ไฟล์หลักสำหรับจัดการโปรเจกต์ Django ผ่าน Command Line
# ใช้รันคำสั่งต่าง ๆ เช่น runserver, migrate, createsuperuser เป็นต้น

"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """
    ฟังก์ชันหลักสำหรับรันคำสั่ง Django Management Commands
    - กำหนด settings module ที่จะใช้งาน (config.settings)
    - โหลด Django และเรียกใช้คำสั่งที่ส่งมาจาก command line
    - หาก import Django ไม่ได้ จะแสดงข้อความแนะนำการติดตั้ง
    """
    # กำหนดค่า default ให้ตัวแปรแวดล้อม DJANGO_SETTINGS_MODULE ชี้ไปที่ config.settings
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        # นำเข้าฟังก์ชันสำหรับรัน management commands จาก Django
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        # หาก import ไม่ได้ แสดงว่า Django ยังไม่ได้ติดตั้ง หรือยังไม่ได้เปิด virtual environment
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # รันคำสั่งที่รับมาจาก argument ของ command line (เช่น python manage.py runserver)
    execute_from_command_line(sys.argv)


# ====== Entry Point ======
# รันฟังก์ชัน main() เมื่อเรียกไฟล์นี้โดยตรง (ไม่ใช่ import เป็น module)
if __name__ == '__main__':
    main()
