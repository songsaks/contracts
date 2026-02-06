from django.db import models
from django.utils import timezone
from decimal import Decimal

class Customer(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class Supplier(models.Model):
    name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class ProjectOwner(models.Model):
    name = models.CharField(max_length=255, verbose_name="ชื่อเจ้าของโครงการ")
    email = models.EmailField(blank=True, verbose_name="อีเมล")
    phone = models.CharField(max_length=50, blank=True, verbose_name="เบอร์โทรศัพท์")
    position = models.CharField(max_length=255, blank=True, verbose_name="ตำแหน่ง")

    def __str__(self):
        return self.name

class Project(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'รวบรวม'
        SOURCING = 'SOURCING', 'จัดหา'
        SUPPLIER_CHECK = 'SUPPLIER_CHECK', 'เช็คราคา'
        QUOTED = 'QUOTED', 'เสนอราคา'
        CONTRACTED = 'CONTRACTED', 'ทำสัญญา'
        ORDERING = 'ORDERING', 'สั่งซื้อ'
        RECEIVED_QC = 'RECEIVED_QC', 'รับของ/QC'
        DELIVERY = 'DELIVERY', 'ส่งมอบ (รอคิว)'
        ACCEPTED = 'ACCEPTED', 'ตรวจรับ'
        BILLING = 'BILLING', 'วางบิล'
        CLOSED = 'CLOSED', 'ปิดจบ'
        CANCELLED = 'CANCELLED', 'ยกเลิก'

    class JobType(models.TextChoices):
        PROJECT = 'PROJECT', 'โครงการ (Project)'
        SERVICE = 'SERVICE', 'งานบริการขาย (Sales Service)'
        REPAIR = 'REPAIR', 'งานแจ้งซ่อม (Repair Service)'

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='projects', verbose_name="ลูกค้า")
    owner = models.ForeignKey(ProjectOwner, on_delete=models.SET_NULL, null=True, blank=True, related_name='projects', verbose_name="เจ้าของโครงการ")
    name = models.CharField(max_length=255, verbose_name="ชื่อโครงการ")
    job_type = models.CharField(
        max_length=20,
        choices=JobType.choices,
        default=JobType.PROJECT,
        verbose_name="ประเภทงาน"
    )
    description = models.TextField(blank=True, verbose_name="รายละเอียดเพิ่มเติม")
    start_date = models.DateField(default=timezone.now, verbose_name="วันเริ่มโครงการ")
    deadline = models.DateField(null=True, blank=True, verbose_name="กำหนดส่งมอบ")
    status = models.CharField(
        max_length=20, 
        choices=Status.choices, 
        default=Status.DRAFT, 
        verbose_name="สถานะ"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "โครงการ"
        verbose_name_plural = "โครงการ"

    def __str__(self):
        return self.name

    @property
    def total_value(self):
        return sum(item.total_price for item in self.items.all())

    @property
    def get_job_status_display(self):
        if self.job_type == self.JobType.REPAIR:
            mapping = {
                self.Status.SOURCING: 'รับแจ้งซ่อม',
                self.Status.ORDERING: 'จัดคิวซ่อม',
                self.Status.DELIVERY: 'ซ่อม',
                self.Status.ACCEPTED: 'รอ',
                self.Status.CLOSED: 'ปิดงานซ่อม',
            }
            return mapping.get(self.status, self.get_status_display())
        
        elif self.job_type == self.JobType.SERVICE:
            mapping = {
                self.Status.SOURCING: 'จัดหา',
                self.Status.QUOTED: 'เสนอราคา',
                self.Status.ORDERING: 'สั่งซื้อ',
                self.Status.RECEIVED_QC: 'รับของ/QC',
                self.Status.DELIVERY: 'ส่งมอบ',
                self.Status.ACCEPTED: 'ตรวจรับ',
                self.Status.CLOSED: 'ปิดจบ',
            }
            return mapping.get(self.status, self.get_status_display())
            
        return self.get_status_display()

class ProductItem(models.Model):
    class ItemType(models.TextChoices):
        PRODUCT = 'PRODUCT', 'สินค้า (Physical Goods)'
        SERVICE = 'SERVICE', 'บริการ / ค่าแรง (Service)'

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='items')
    item_type = models.CharField(
        max_length=10, 
        choices=ItemType.choices, 
        default=ItemType.PRODUCT,
        verbose_name="ประเภท"
    )
    name = models.CharField(max_length=255, verbose_name="ชื่อรายการ")
    description = models.TextField(blank=True, verbose_name="รายละเอียด")
    quantity = models.PositiveIntegerField(default=1, verbose_name="จำนวน")
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="ต้นทุนต่อหน่วย")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="ราคาขายต่อหน่วย")
    supplier = models.ForeignKey(
        Supplier, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        verbose_name="ซัพพลายเออร์",
        help_text="ระบุหากเป็นสินค้า"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "รายการสินค้า/บริการ"
        verbose_name_plural = "รายการสินค้า/บริการ"

    def __str__(self):
        return self.name

    @property
    def total_price(self):
        return self.quantity * self.unit_price

    @property
    def total_cost(self):
        return self.quantity * self.unit_cost
        
    @property
    def margin(self):
        return self.total_price - self.total_cost

class CustomerRequirement(models.Model):
    content = models.TextField(verbose_name="รายละเอียดความต้องการ (Voice/Text)")
    project = models.OneToOneField(
        Project, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='requirement_source',
        verbose_name="โครงการที่สร้าง"
    )
    is_converted = models.BooleanField(default=False, verbose_name="สร้างเป็นโครงการแล้ว")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ความต้องการลูกค้า (Lead)"
        verbose_name_plural = "ความต้องการลูกค้า (Leads)"

    def __str__(self):
        return f"Requirement {self.pk} - {self.created_at.strftime('%d/%m/%Y')}"
