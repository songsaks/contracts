import os
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models.signals import post_delete
from django.dispatch import receiver

# ====== โมเดลข้อมูลระบบแชท (Chat Data Models) ======


# โมเดลสำหรับห้องแชท (Chat Room)
class ChatRoom(models.Model):
    """
    เก็บข้อมูลห้องแชทแต่ละห้อง รองรับทั้งห้องสาธารณะและห้องส่วนตัว
    สามารถเชื่อมโยงกับโครงการใน PMS เพื่อสร้างห้องแชทเฉพาะโครงการได้
    """
    APP_CHOICES = (
        ('general', 'ส่วนกลาง (General)'),
        ('rentals', 'ระบบสัญญาเช่า (Rentals)'),
        ('repairs', 'ระบบงานซ่อม (Repairs)'),
        ('pms', 'ระบบบริหารโครงการ (PMS)'),
        ('payroll', 'ระบบเงินเดือน (Payroll)'),
    )

    # ชื่อห้องแชท (ต้องไม่ซ้ำกันในระบบ)
    name = models.CharField(max_length=255, unique=True, verbose_name="ชื่อห้อง")
    # หมวดหมู่ระบบแอปพลิเคชันที่ห้องนี้สังกัด
    app_category = models.CharField(max_length=20, choices=APP_CHOICES, default='general', verbose_name="หมวดหมู่ระบบ")
    # คำอธิบายห้องแชท (ตัวเลือก)
    description = models.TextField(blank=True, verbose_name="คำอธิบาย")
    # ลิงก์ไปยังโครงการ (ถ้ามี - สำหรับแชทเฉพาะโปรเจกต์)
    project = models.ForeignKey(
        'pms.Project', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='chat_rooms', verbose_name="โครงการที่เกี่ยวข้อง"
    )
    # ไอคอนหรือสีประจำห้อง (สำหรับแสดงผล UI) รูปแบบ HEX เช่น #3b82f6
    color_hex = models.CharField(max_length=7, default="#3b82f6", verbose_name="สีประจำห้อง (Hex)")

    # ====== ระบบควบคุมการเข้าถึง (Access Control) ======
    # สถานะห้องส่วนตัว: True = จำกัดเฉพาะผู้ใช้ที่ได้รับอนุญาต
    is_private = models.BooleanField(default=False, verbose_name="ห้องส่วนตัว (จำกัดสิทธิ์)")
    # รายชื่อผู้ใช้ที่ได้รับอนุญาตเข้าห้องส่วนตัว (ManyToMany)
    allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='allowed_chat_rooms',
        verbose_name="ผู้ใช้ที่ได้รับอนุญาต"
    )

    # วันที่สร้างห้อง (กำหนดอัตโนมัติ)
    created_at = models.DateTimeField(auto_now_add=True)
    # สถานะการเปิดใช้งาน: False = ซ่อนจากรายการ
    is_active = models.BooleanField(default=True, verbose_name="เปิดใช้งาน")

    class Meta:
        verbose_name = "ห้องแชท"
        verbose_name_plural = "ห้องแชท"
        permissions = [
            ("can_chat", "สามารถเข้าใช้งานระบบแชทกลาง"),
        ]

    def __str__(self):
        return self.name


# ====== โมเดลข้อความในแชท (Chat Message) ======

class ChatMessage(models.Model):
    """
    เก็บข้อความแต่ละข้อความในห้องแชท รองรับข้อความตัวอักษร รูปภาพ ไฟล์แนบ
    และการเช็คอินพิกัดตำแหน่ง GPS รวมถึงการส่งข้อความด้วยเสียง (Speech-to-Text)
    """
    # ห้องแชทที่ข้อความนี้สังกัดอยู่ (ลบห้องแล้วข้อความจะถูกลบตาม)
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages', verbose_name="ห้องแชท")
    # ผู้ส่งข้อความ (ลบ User แล้วข้อความจะถูกลบตาม)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, verbose_name="ผู้ส่ง")
    # เนื้อหาข้อความ (อาจว่างได้ถ้าส่งเป็นรูปหรือไฟล์เท่านั้น)
    content = models.TextField(blank=True, verbose_name="ข้อความ")
    # ไฟล์ภาพ (ตัวเลือก) จัดเก็บในโฟลเดอร์แยกตามปีและเดือน
    image = models.ImageField(upload_to='chat/images/%Y/%m/', blank=True, null=True, verbose_name="รูปภาพ")
    # ไฟล์เอกสารอื่นๆ (ตัวเลือก) เช่น PDF, Word
    file = models.FileField(upload_to='chat/files/%Y/%m/', blank=True, null=True, verbose_name="ไฟล์แนบ")

    # ====== ข้อมูลพิกัดตำแหน่ง (GPS Check-in) ======
    # ละติจูดและลองจิจูดจาก GPS ของผู้ส่ง (ความแม่นยำสูงสุด 9 ตำแหน่ง)
    latitude = models.DecimalField(max_digits=12, decimal_places=9, blank=True, null=True, verbose_name="ละติจูด")
    longitude = models.DecimalField(max_digits=12, decimal_places=9, blank=True, null=True, verbose_name="ลองจิจูด")
    # ชื่อสถานที่ที่ผู้ส่งระบุ (Optional Label)
    location_name = models.CharField(max_length=255, blank=True, verbose_name="ชื่อสถานที่")

    # วันเวลาที่ส่งข้อความ (กำหนดอัตโนมัติ ไม่สามารถแก้ไขได้)
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="เวลาส่ง")
    # ระบุว่าข้อความนี้มาจาก Speech-to-Text หรือไม่ (แสดงไอคอนไมโครโฟนใน UI)
    is_speech_to_text = models.BooleanField(default=False, verbose_name="ส่งด้วยเสียง")

    class Meta:
        verbose_name = "ข้อความแชท"
        verbose_name_plural = "ข้อความแชท"
        # เรียงข้อความจากเก่าไปใหม่ตามเวลา
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.user.username}: {self.content[:30]}..."


# ====== ระบบทำความสะอาดไฟล์อัตโนมัติ (Auto File Cleanup) ======

@receiver(post_delete, sender=ChatMessage)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """
    Signal: ลบไฟล์จริงบน Server ทันทีเมื่อข้อความถูกลบออกจากฐานข้อมูล
    ป้องกันไฟล์ขยะสะสมบน Storage โดยตรวจสอบทั้งรูปภาพและไฟล์แนบ
    """
    # ลบไฟล์ภาพถ้ามีอยู่จริงบน Disk
    if instance.image:
        if os.path.isfile(instance.image.path):
            os.remove(instance.image.path)
    # ลบไฟล์แนบถ้ามีอยู่จริงบน Disk
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)
