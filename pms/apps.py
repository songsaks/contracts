from django.apps import AppConfig


# ไฟล์ตั้งค่าแอปพลิเคชัน PMS (Project Management System)
class PmsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pms'
    verbose_name = 'ระบบบริหารจัดการโครงการ (PMS)'
