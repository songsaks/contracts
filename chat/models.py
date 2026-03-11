import os
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models.signals import post_delete
from django.dispatch import receiver

# โมเดลสำหรับห้องแชท (Chat Room)
class ChatRoom(models.Model):
    APP_CHOICES = (
        ('general', 'ส่วนกลาง (General)'),
        ('rentals', 'ระบบสัญญาเช่า (Rentals)'),
        ('repairs', 'ระบบงานซ่อม (Repairs)'),
        ('pms', 'ระบบบริหารโครงการ (PMS)'),
        ('payroll', 'ระบบเงินเดือน (Payroll)'),
    )

    # ชื่อห้องแชท
    name = models.CharField(max_length=255, unique=True, verbose_name="ชื่อห้อง")
    # หมวดหมู่ระบบแอปพลิเคชัน
    app_category = models.CharField(max_length=20, choices=APP_CHOICES, default='general', verbose_name="หมวดหมู่ระบบ")
    # คำอธิบายห้องแชท (ตัวเลือก)
    description = models.TextField(blank=True, verbose_name="คำอธิบาย")
    # ลิงก์ไปยังโครงการ (ถ้ามี - สำหรับแชทเฉพาะโปรเจกต์)
    project = models.ForeignKey(
        'pms.Project', on_delete=models.SET_NULL, null=True, blank=True, 
        related_name='chat_rooms', verbose_name="โครงการที่เกี่ยวข้อง"
    )
    # ไอคอนหรือสีประจำห้อง (สำหรับแสดงผล UI)
    color_hex = models.CharField(max_length=7, default="#3b82f6", verbose_name="สีประจำห้อง (Hex)")
    
    # ระบบความเป็นส่วนตัวและการจำกัดการเข้าถึง (Access Control)
    is_private = models.BooleanField(default=False, verbose_name="ห้องส่วนตัว (จำกัดสิทธิ์)")
    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='allowed_chat_rooms', 
        verbose_name="ผู้ใช้ที่ได้รับอนุญาต"
    )

    # วันที่สร้างห้อง
    created_at = models.DateTimeField(auto_now_add=True)
    # สถานะการเปิดใช้งาน
    is_active = models.BooleanField(default=True, verbose_name="เปิดใช้งาน")

    class Meta:
        verbose_name = "ห้องแชท"
        verbose_name_plural = "ห้องแชท"
        permissions = [
            ("can_chat", "สามารถเข้าใช้งานระบบแชทกลาง"),
        ]

    def __str__(self):
        return self.name

# โมเดลสำหรับข้อความในแชท (Chat Message)
class ChatMessage(models.Model):
    # ห้องแชทที่ข้อความนี้สังกัดอยู่
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages', verbose_name="ห้องแชท")
    # ผู้ส่งข้อความ
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="ผู้ส่ง")
    # เนื้อหาข้อความ (ตัวอักษร)
    content = models.TextField(blank=True, verbose_name="ข้อความ")
    # ไฟล์ภาพ (ตัวเลือก)
    image = models.ImageField(upload_to='chat/images/%Y/%m/', blank=True, null=True, verbose_name="รูปภาพ")
    # ไฟล์เอกสารอื่นๆ (ตัวเลือก)
    file = models.FileField(upload_to='chat/files/%Y/%m/', blank=True, null=True, verbose_name="ไฟล์แนบ")
    
    # ข้อมูลพิกัดตำแหน่ง (Check-in)
    latitude = models.DecimalField(max_digits=12, decimal_places=9, blank=True, null=True, verbose_name="ละติจูด")
    longitude = models.DecimalField(max_digits=12, decimal_places=9, blank=True, null=True, verbose_name="ลองจิจูด")
    location_name = models.CharField(max_length=255, blank=True, verbose_name="ชื่อสถานที่")

    # วันเวลาที่ส่ง
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="เวลาส่ง")
    # ระบุว่าเป็นข้อความที่แปลมาจากเสียง (Speech-to-Text) หรือไม่
    is_speech_to_text = models.BooleanField(default=False, verbose_name="ส่งด้วยเสียง")

    class Meta:
        verbose_name = "ข้อความแชท"
        verbose_name_plural = "ข้อความแชท"
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.user.username}: {self.content[:30]}..."

# ระบบทำความสะอาดไฟล์ (Cleanup) เมื่อข้อความถูกลบ เพื่อไม่ให้เปลืองพื้นที่ Server
@receiver(post_delete, sender=ChatMessage)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """ลบไฟล์ภาพหรือไฟล์แนบออกจากเครื่องทันทีที่ผู้ดูแลกดลบข้อความในฐานข้อมูล"""
    if instance.image:
        if os.path.isfile(instance.image.path):
            os.remove(instance.image.path)
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)

