# ====== models.py — ระบบซ่อมบำรุง (Repair Management) ======
# กำหนดโครงสร้างข้อมูลหลักของระบบ ได้แก่
#   - Customer     : ลูกค้าที่นำเครื่องมาซ่อม
#   - DeviceType   : ประเภทอุปกรณ์ (Notebook, Printer ฯลฯ)
#   - Brand        : ยี่ห้อสินค้า
#   - Device       : ข้อมูลอุปกรณ์/สินค้าของลูกค้า
#   - Technician   : ช่างซ่อมในระบบ
#   - RepairType   : ประเภทงานซ่อม (Outsourcing, In-house ฯลฯ)
#   - RepairJob    : ใบรับงานซ่อม (Job)
#   - RepairItem   : รายการซ่อมแต่ละชิ้น พร้อม workflow สถานะ
#   - OutsourceLog : บันทึกการส่งซ่อมภายนอก
#   - RepairStatusHistory : ประวัติการเปลี่ยนสถานะงานซ่อม

from django.db import models
from django.utils import timezone
from django.conf import settings
import datetime
import uuid


# ====== Customer — ข้อมูลลูกค้า ======

class Customer(models.Model):
    """โมเดลลูกค้าที่นำอุปกรณ์มาซ่อม

    รหัสลูกค้า (customer_code) สร้างอัตโนมัติในรูปแบบ C<วันที่><ลำดับ 3 หลัก>
    ตัวอย่าง: C20240101001
    """
    name = models.CharField(max_length=255)               # ชื่อลูกค้าหรือบริษัท
    customer_code = models.CharField(max_length=50, unique=True, editable=False)  # รหัสลูกค้า (สร้างอัตโนมัติ)
    contact_number = models.CharField(max_length=50)      # เบอร์โทรศัพท์
    address = models.TextField(blank=True)                # ที่อยู่ (ไม่บังคับ)
    created_at = models.DateTimeField(auto_now_add=True)  # วันที่สร้าง

    def save(self, *args, **kwargs):
        """สร้างรหัสลูกค้าอัตโนมัติหากยังไม่มี โดยใช้วันที่ปัจจุบันและลำดับรันนิ่ง"""
        if not self.customer_code:
            today = timezone.now()
            date_str = today.strftime("C%Y%m%d")
            # Get last code for today
            last_customer = Customer.objects.filter(customer_code__startswith=date_str).order_by('customer_code').last()
            if last_customer:
                last_seq = int(last_customer.customer_code[-3:])
                new_seq = last_seq + 1
            else:
                new_seq = 1
            self.customer_code = f"{date_str}{new_seq:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.customer_code})"


# ====== DeviceType — ประเภทอุปกรณ์ ======

class DeviceType(models.Model):
    """ประเภทของอุปกรณ์ที่รับซ่อม เช่น Notebook, Printer, Desktop, Tablet"""
    name = models.CharField(max_length=100, unique=True)  # ชื่อประเภท (ต้องไม่ซ้ำ)
    description = models.TextField(blank=True)            # คำอธิบายเพิ่มเติม
    created_at = models.DateTimeField(auto_now_add=True)  # วันที่สร้าง

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']  # เรียงตามชื่อ


# ====== Brand — ยี่ห้อสินค้า ======

class Brand(models.Model):
    """ยี่ห้อสินค้า/อุปกรณ์ เช่น HP, Dell, Samsung, Apple"""
    name = models.CharField(max_length=100, unique=True)  # ชื่อยี่ห้อ (ต้องไม่ซ้ำ)
    created_at = models.DateTimeField(auto_now_add=True)  # วันที่สร้าง

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']  # เรียงตามชื่อ


# ====== Device — อุปกรณ์/สินค้าของลูกค้า ======

class Device(models.Model):
    """อุปกรณ์ที่ลูกค้านำมาซ่อม เชื่อมโยงกับลูกค้า ยี่ห้อ และประเภทอุปกรณ์"""
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='devices')       # เจ้าของอุปกรณ์
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name='devices')             # ยี่ห้อสินค้า
    model = models.CharField(max_length=100)                                                        # รุ่น (Model)
    serial_number = models.CharField(max_length=100, blank=True)                                   # หมายเลขเครื่อง Serial Number
    device_type = models.ForeignKey('DeviceType', on_delete=models.PROTECT, related_name='devices') # ประเภทอุปกรณ์
    created_at = models.DateTimeField(auto_now_add=True)                                           # วันที่บันทึก

    def __str__(self):
        return f"{self.brand} {self.model} - {self.customer.name}"


# ====== Technician — ช่างซ่อม ======

class Technician(models.Model):
    """ข้อมูลช่างซ่อมในระบบ ใช้มอบหมายงานให้ช่างแต่ละคน"""
    name = models.CharField(max_length=255)              # ชื่อช่าง
    expertise = models.CharField(max_length=255, blank=True)  # ความเชี่ยวชาญ (เช่น Notebook, Printer)

    def __str__(self):
        return self.name


# ====== RepairType — ประเภทงานซ่อม ======

class RepairType(models.Model):
    """ประเภทหรือแหล่งที่มาของงานซ่อม เช่น Outsourcing, Walk-in, Contract

    มีการกำหนดสีและไอคอนเพื่อแสดงผลบน Dashboard
    """
    name = models.CharField(max_length=100, unique=True)  # ชื่อประเภทงาน (ต้องไม่ซ้ำ)
    description = models.TextField(blank=True)            # คำอธิบาย
    color = models.CharField(max_length=20, default='#6366f1', help_text="Hex color code (e.g. #6366f1)")   # สีแสดงผล (Hex)
    icon = models.CharField(max_length=50, default='fas fa-briefcase', help_text="FontAwesome icon class")  # ไอคอน FontAwesome
    created_at = models.DateTimeField(auto_now_add=True)  # วันที่สร้าง

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']  # เรียงตามชื่อ


# ====== RepairJob — ใบรับงานซ่อม ======

class RepairJob(models.Model):
    """ใบรับงานซ่อม (Job) แต่ละใบอาจมีหลายรายการ (RepairItem)

    รหัสงาน (job_code) สร้างอัตโนมัติในรูปแบบ J<วันที่><ลำดับ 3 หลัก>
    ตัวอย่าง: J20240101001

    มี tracking_id แบบ UUID สำหรับให้ลูกค้าติดตามสถานะผ่าน QR Code
    """
    job_code = models.CharField(max_length=50, unique=True, editable=False)  # รหัสงาน (สร้างอัตโนมัติ)
    repair_type = models.ForeignKey(RepairType, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs', verbose_name="ประเภทงานซ่อม")  # ประเภทงาน
    tracking_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)  # UUID สำหรับ QR Tracking
    fix_id = models.CharField(max_length=50, blank=True, null=True, help_text="Manual Fix ID if needed")  # รหัสงานเพิ่มเติม (กรอกเอง)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='jobs')  # ลูกค้าเจ้าของงาน
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_repair_jobs')  # ผู้สร้างใบงาน (พนักงาน)
    created_at = models.DateTimeField(default=timezone.now)   # วันที่รับงาน
    updated_at = models.DateTimeField(auto_now=True)          # วันที่แก้ไขล่าสุด

    def save(self, *args, **kwargs):
        """สร้างรหัสงานอัตโนมัติหากยังไม่มี โดยใช้วันที่ปัจจุบันและลำดับรันนิ่ง"""
        if not self.job_code:
            today = timezone.now()
            date_str = today.strftime("J%Y%m%d")
            last_job = RepairJob.objects.filter(job_code__startswith=date_str).order_by('job_code').last()
            if last_job:
                last_seq = int(last_job.job_code[-3:])
                new_seq = last_seq + 1
            else:
                new_seq = 1
            self.job_code = f"{date_str}{new_seq:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.job_code

    def get_overall_status_bg_light(self):
        """คำนวณสีพื้นหลัง (Tailwind class) ของ Job ตามสถานะรวมของรายการซ่อมทั้งหมด

        ลำดับความสำคัญ: FIXING > WAITING > RECEIVED > FINISHED/COMPLETED/CANCELLED
        """
        # Determine overall status based on items
        # Priority: FIXING > WAITING > RECEIVED > FINISHED (if all finished)
        items = self.items.all()
        if not items:
            return 'bg-gray-100'

        statuses = [item.status for item in items]

        if 'FIXING' in statuses:
            return 'bg-orange-50'
        if 'WAITING_APPROVAL' in statuses:
            return 'bg-purple-50'
        if 'WAITING' in statuses:
            return 'bg-yellow-50'

        # If all are finished or cancelled
        if all(s in ['FINISHED', 'COMPLETED', 'CANCELLED'] for s in statuses):
             return 'bg-green-50'

        return 'bg-red-50'


# ====== RepairItem — รายการซ่อมแต่ละชิ้น ======

class RepairItem(models.Model):
    """รายการซ่อมแต่ละชิ้นภายใน RepairJob

    workflow สถานะ:
        RECEIVED -> FIXING -> WAITING_APPROVAL -> WAITING -> (OUTSOURCE) -> RECEIVED_FROM_VENDOR
                                                          -> FINISHED -> COMPLETED
                                                          -> CANCELLED

    - status_note : บันทึกเหตุผลหรือรายละเอียดสถานะปัจจุบัน
    - price       : ราคาประเมินเบื้องต้น
    - final_cost  : ค่าใช้จ่ายจริงที่เรียกเก็บ (กรอกตอน COMPLETED)
    - closed_at   : วันที่ปิดงาน (เมื่อสถานะเป็น FINISHED/COMPLETED/CANCELLED)
    """
    STATUS_CHOICES = [
        ('RECEIVED', 'รับแจ้ง'),                              # รับเครื่องเข้าซ่อมแล้ว รอตรวจสอบ
        ('FIXING', 'คิว'),                                     # อยู่ระหว่างซ่อม/ตรวจเช็ค
        ('WAITING_APPROVAL', 'รออนุมัติงานซ่อม'),             # รอลูกค้าอนุมัติราคาหรืองาน
        ('WAITING', 'รออะไหล่'),                               # รอชิ้นส่วนอะไหล่
        ('OUTSOURCE', 'ส่งซ่อมศูนย์/ภายนอก'),                  # ส่งซ่อมที่ศูนย์บริการหรือภายนอก
        ('RECEIVED_FROM_VENDOR', 'รอตรวจรับกลับ'),            # ได้รับเครื่องคืนจากศูนย์ รอตรวจสอบ
        ('CANCELLED', 'ยกเลิก'),                               # ยกเลิกการซ่อม
        ('FINISHED', 'ซ่อมเสร็จ'),                             # ซ่อมเสร็จแล้ว รอส่งคืนลูกค้า
        ('COMPLETED', 'ส่งคืนแล้ว'),                           # ส่งคืนเครื่องให้ลูกค้าเรียบร้อย
    ]

    job = models.ForeignKey(RepairJob, on_delete=models.CASCADE, related_name='items')            # ใบงานที่สังกัด
    device = models.ForeignKey(Device, on_delete=models.CASCADE)                                  # อุปกรณ์ที่ซ่อม
    technicians = models.ManyToManyField(Technician, blank=True)                                  # ช่างผู้รับผิดชอบ (หลายคนได้)
    issue_description = models.TextField()                                                        # อาการเสียที่ลูกค้าแจ้ง
    accessories = models.CharField(max_length=255, blank=True, verbose_name="อุปกรณ์ที่นำมาด้วย", help_text="เช่น สายชาร์จ, กระเป๋า, เมาส์")  # อุปกรณ์เสริมที่นำมาด้วย
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='RECEIVED')          # สถานะปัจจุบัน
    status_note = models.TextField(blank=True, help_text="Reason for waiting or other status details")  # หมายเหตุสถานะ
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="ราคาประเมิน")  # ราคาประเมิน
    final_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="ค่าใช้จ่ายจริง")  # ค่าใช้จ่ายจริงที่เรียกเก็บ
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_repair_items')  # ผู้รับงาน/สร้างรายการ

    created_at = models.DateTimeField(auto_now_add=True)       # วันที่รับงาน
    updated_at = models.DateTimeField(auto_now=True)           # วันที่แก้ไขล่าสุด
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="วันที่ซ่อมเสร็จ/คืนเครื่อง")  # วันที่ปิดงาน

    def get_status_color(self):
        """คืนค่า CSS class (Tailwind) สำหรับสีแบดจ์ของสถานะปัจจุบัน"""
        colors = {
            'RECEIVED': 'bg-red-500 text-white',
            'FIXING': 'bg-orange-500 text-white',
            'WAITING_APPROVAL': 'bg-secondary text-white',
            'WAITING': 'bg-yellow-400 text-black',
            'OUTSOURCE': 'bg-indigo-500 text-white',
            'RECEIVED_FROM_VENDOR': 'bg-blue-400 text-white',
            'FINISHED': 'bg-green-500 text-white',
            'CANCELLED': 'bg-gray-500 text-white',
            'COMPLETED': 'bg-secondary text-white',
        }
        return colors.get(self.status, 'bg-gray-500 text-white')

    def get_status_bg_light(self):
        """คืนค่า CSS class (Tailwind) สำหรับสีพื้นหลังอ่อนของแถวตามสถานะ"""
        colors = {
            'RECEIVED': 'bg-red-50',
            'FIXING': 'bg-orange-50',
            'WAITING_APPROVAL': 'bg-purple-50',
            'WAITING': 'bg-yellow-50',
            'OUTSOURCE': 'bg-indigo-50',
            'RECEIVED_FROM_VENDOR': 'bg-blue-50',
            'FINISHED': 'bg-green-50',
            'CANCELLED': 'bg-gray-50',
            'COMPLETED': 'bg-secondary-subtle',
        }
        return colors.get(self.status, 'bg-gray-50')

    def clean(self):
        """ตรวจสอบ validation พิเศษ:

        - หากสถานะปัจจุบันเป็น OUTSOURCE จะเปลี่ยนสถานะได้เฉพาะ RECEIVED_FROM_VENDOR เท่านั้น
        - ขณะส่งซ่อมภายนอก ห้ามแก้ไขข้อมูลหลักของรายการ (อาการ, อุปกรณ์, ราคา)
        """
        from django.core.exceptions import ValidationError
        if self.pk:
            old_instance = RepairItem.objects.get(pk=self.pk)
            # If currently OUTSOURCE, only allow status change to RECEIVED_FROM_VENDOR
            if old_instance.status == 'OUTSOURCE':
                if self.status != 'RECEIVED_FROM_VENDOR' and self.status != 'OUTSOURCE':
                    raise ValidationError("สินค้าอยู่ในระหว่างส่งซ่อมภายนอก ไม่สามารถเปลี่ยนสถานะเป็นอย่างอื่นได้นอกจาก 'รอตรวจรับกลับ'")

                # Check for other field changes
                if (old_instance.issue_description != self.issue_description or
                    old_instance.accessories != self.accessories or
                    old_instance.device != self.device or
                    old_instance.price != self.price):
                    raise ValidationError("ไม่สามารถแก้ไขรายละเอียดสินค้าได้ในระหว่างที่ส่งซ่อมภายนอก")

    def save(self, *args, **kwargs):
        """บันทึกข้อมูลพร้อม:
        - รัน full_clean() ก่อนบันทึกเสมอ
        - ตั้งค่า closed_at อัตโนมัติเมื่อสถานะเป็น FINISHED/COMPLETED/CANCELLED
        - ล้างค่า closed_at หากสถานะถอยกลับมาเป็น active
        """
        self.full_clean()
        if self.status in ['FINISHED', 'COMPLETED', 'CANCELLED'] and not self.closed_at:
            self.closed_at = timezone.now()
        elif self.status not in ['FINISHED', 'COMPLETED', 'CANCELLED']:
            self.closed_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.device} - {self.get_status_display()}"


# ====== OutsourceLog — บันทึกการส่งซ่อมภายนอก ======

class OutsourceLog(models.Model):
    """บันทึกรายละเอียดการส่งซ่อมให้ศูนย์บริการหรือร้านซ่อมภายนอก

    ผูกแบบ OneToOne กับ RepairItem เพราะแต่ละรายการซ่อมส่งภายนอกได้ครั้งเดียว
    """
    repair_item = models.OneToOneField(RepairItem, on_delete=models.CASCADE, related_name='outsource_details')  # รายการซ่อมที่ส่งออก
    vendor_name = models.CharField(max_length=255, verbose_name="ชื่อร้าน/ศูนย์ที่ส่งซ่อม")        # ชื่อร้านหรือศูนย์
    tracking_no = models.CharField(max_length=100, blank=True, verbose_name="เลข Tracking/เลขรับงานศูนย์")  # เลขติดตามพัสดุหรือเลขที่บิล
    sent_date = models.DateField(default=timezone.now, verbose_name="วันที่ส่ง")                    # วันที่ส่งซ่อม
    expected_return = models.DateField(null=True, blank=True, verbose_name="วันที่คาดว่าจะได้รับ")  # วันที่คาดจะรับกลับ
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="ค่าซ่อมจากศูนย์")  # ค่าซ่อมที่ศูนย์เรียกเก็บ
    note = models.TextField(blank=True, verbose_name="หมายเหตุ")                                    # บันทึกเพิ่มเติม
    created_at = models.DateTimeField(auto_now_add=True)                                           # วันที่สร้าง

    def __str__(self):
        return f"Outsource: {self.repair_item.job.job_code} to {self.vendor_name}"


# ====== RepairStatusHistory — ประวัติการเปลี่ยนสถานะ ======

class RepairStatusHistory(models.Model):
    """บันทึก audit trail ของการเปลี่ยนสถานะงานซ่อมแต่ละครั้ง

    ใช้แสดง timeline ในหน้ารายละเอียดงานซ่อม และหน้า tracking ของลูกค้า
    """
    repair_item = models.ForeignKey(RepairItem, on_delete=models.CASCADE, related_name='status_history')  # รายการซ่อมที่เกี่ยวข้อง
    status = models.CharField(max_length=50, choices=RepairItem.STATUS_CHOICES)                           # สถานะที่เปลี่ยนไป
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)  # ผู้เปลี่ยนสถานะ
    changed_at = models.DateTimeField(auto_now_add=True)                                                  # เวลาที่เปลี่ยน
    note = models.TextField(blank=True)                                                                   # หมายเหตุประกอบ

    def __str__(self):
        return f"{self.repair_item.job.job_code} -> {self.status} at {self.changed_at}"

    class Meta:
        ordering = ['-changed_at']          # เรียงจากใหม่ไปเก่า
        verbose_name_plural = "Repair Status Histories"
