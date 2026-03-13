# ====== models.py - โมเดลหลักของระบบสัญญาเช่า (Rental Contracts System) ======
# ไฟล์นี้กำหนดโครงสร้างฐานข้อมูลสำหรับ 3 โมเดลหลัก:
#   Asset   = ทรัพย์สิน/อุปกรณ์ที่ให้เช่า
#   Tenant  = ผู้เช่า (บุคคลหรือหน่วยงาน)
#   Contract = สัญญาเช่าที่เชื่อม Tenant กับ Asset

from django.db import models
from django.utils import timezone
from decimal import Decimal

# ====== โมเดล Asset - ทรัพย์สินที่ให้เช่า ======
class Asset(models.Model):
    """
    โมเดลสำหรับทรัพย์สิน/อุปกรณ์ที่บริษัทนำออกให้เช่า
    เช่น เครื่องจักร, ยานพาหนะ, อุปกรณ์ก่อสร้าง ฯลฯ
    """

    # ตัวเลือกสถานะของทรัพย์สิน
    STATUS_CHOICES = [
        ('AVAILABLE', 'Available'),    # พร้อมให้เช่า
        ('MAINTENANCE', 'Maintenance'), # อยู่ระหว่างซ่อมบำรุง
        ('RENTED', 'Rented'),          # ถูกเช่าอยู่ในปัจจุบัน
    ]

    name = models.CharField(max_length=100)  # ชื่อทรัพย์สิน
    serial_number = models.CharField(max_length=100, blank=True, null=True, unique=True, help_text="Asset Serial Number")  # หมายเลขซีเรียล (ไม่ซ้ำกัน)
    description = models.TextField(blank=True)  # รายละเอียดเพิ่มเติม
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AVAILABLE')  # สถานะปัจจุบัน
    monthly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))  # ค่าเช่าต่อเดือน (บาท)
    created_at = models.DateTimeField(auto_now_add=True)  # วันที่เพิ่มข้อมูล
    updated_at = models.DateTimeField(auto_now=True)  # วันที่แก้ไขล่าสุด

    def __str__(self):
        # แสดงชื่อและสถานะทรัพย์สิน เช่น "รถแบคโฮ (Available)"
        return f"{self.name} ({self.get_status_display()})"

# ====== โมเดล Tenant - ผู้เช่า/หน่วยงานที่เช่า ======
class Tenant(models.Model):
    """
    โมเดลสำหรับผู้เช่า ซึ่งอาจเป็นบุคคลธรรมดาหรือนิติบุคคล (บริษัท/หน่วยงาน)
    แต่ละผู้เช่าสามารถมีสัญญาเช่าได้หลายฉบับ
    """

    agency_name = models.CharField(max_length=100, help_text="Company or Agency Name")  # ชื่อบริษัท/หน่วยงาน
    contact_person = models.CharField(max_length=100, help_text="Name of the contact person")  # ชื่อผู้ติดต่อ
    document_id = models.CharField(max_length=50, blank=True, help_text="ID Card or Passport Number")  # เลขบัตรประชาชน หรือ พาสปอร์ต
    email = models.EmailField(unique=True)  # อีเมล (ไม่ซ้ำกัน ใช้เป็น identifier)
    phone = models.CharField(max_length=20)  # เบอร์โทรศัพท์
    address = models.TextField(blank=True)  # ที่อยู่
    created_at = models.DateTimeField(auto_now_add=True)  # วันที่ลงทะเบียน

    def __str__(self):
        # แสดงชื่อหน่วยงานและผู้ติดต่อ เช่น "บริษัท ABC (สมชาย)"
        return f"{self.agency_name} ({self.contact_person})"

# ====== โมเดล Contract - สัญญาเช่า ======
class Contract(models.Model):
    """
    โมเดลสัญญาเช่า เชื่อมโยงผู้เช่า (Tenant) กับทรัพย์สิน (Asset) หลายรายการ
    บันทึกข้อมูลทางการเงิน วันที่ และสถานะของสัญญา
    """

    # ตัวเลือกสถานะสัญญา
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),         # สัญญากำลังดำเนินอยู่
        ('COMPLETED', 'Completed'),   # สัญญาสิ้นสุดแล้ว (ครบกำหนด)
        ('CANCELLED', 'Cancelled'),   # สัญญาถูกยกเลิก
    ]

    # ตัวเลือกความถี่การชำระเงิน
    PAYMENT_FREQUENCY_CHOICES = [
        ('MONTHLY', 'Every Month'),         # รายเดือน
        ('QUARTERLY', 'Every 3 Months'),    # ราย 3 เดือน
        ('SEMI_ANNUAL', 'Every 6 Months'),  # ราย 6 เดือน
        ('ANNUAL', 'Every Year'),           # รายปี
        ('ONE_TIME', 'One Time Payment'),   # ชำระครั้งเดียว
    ]

    # ความสัมพันธ์กับโมเดลอื่น
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='contracts')  # ผู้เช่า (ถ้าลบผู้เช่า สัญญาจะถูกลบด้วย)
    assets = models.ManyToManyField(Asset, related_name='contracts')  # ทรัพย์สินที่เช่า (หนึ่งสัญญามีได้หลายรายการ)

    # ช่วงเวลาของสัญญา
    start_date = models.DateField(default=timezone.now)  # วันเริ่มต้นสัญญา
    end_date = models.DateField()  # วันสิ้นสุดสัญญา

    # ====== ข้อมูลทางการเงิน ======
    payment_frequency = models.CharField(max_length=20, choices=PAYMENT_FREQUENCY_CHOICES, default='MONTHLY')  # ความถี่การชำระเงิน
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Total calculated rent")  # ยอดรวมค่าเช่าทั้งหมดที่ต้องชำระ
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Amount paid so far")  # ยอดที่ชำระแล้ว

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')  # สถานะสัญญา
    created_at = models.DateTimeField(auto_now_add=True)  # วันที่สร้างสัญญา
    updated_at = models.DateTimeField(auto_now=True)  # วันที่แก้ไขล่าสุด

    @property
    def remaining_amount(self):
        """คำนวณยอดค้างชำระ = ยอดรวม - ยอดที่ชำระแล้ว"""
        return self.total_amount - self.paid_amount

    @property
    def contract_number(self):
        """สร้างเลขที่สัญญาในรูปแบบ YYYYMMDD-XXXX เช่น 20240101-0001"""
        return f"{self.created_at.strftime('%Y%m%d')}-{self.id:04d}"

    def __str__(self):
        # แสดงเลขที่สัญญาและผู้เช่า เช่น "Contract 20240101-0001 - บริษัท ABC"
        return f"Contract {self.contract_number} - {self.tenant}"
