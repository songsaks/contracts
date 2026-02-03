from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

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

class Project(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('รวบรวมความต้องการ')
        SOURCING = 'SOURCING', _('จัดหาของ')
        SUPPLIER_CHECK = 'SUPPLIER_CHECK', _('เช็คราคาจากซัพพลายเออร์')
        QUOTED = 'QUOTED', _('ออกใบเสนอราคา')
        CONTRACTED = 'CONTRACTED', _('ทำสัญญา')
        ORDERING = 'ORDERING', _('สั่งซื้อของ')
        RECEIVED_QC = 'RECEIVED_QC', _('รับของ / ตรวจเช็ค')
        DELIVERY = 'DELIVERY', _('ส่งมอบงาน')
        ACCEPTED = 'ACCEPTED', _('ลูกค้าตรวจรับ')
        BILLING = 'BILLING', _('วางบิล / เก็บเงิน')
        CLOSED = 'CLOSED', _('ปิดโครงการ')
        CANCELLED = 'CANCELLED', _('ยกเลิก')

    name = models.CharField(max_length=255, verbose_name="ชื่อโครงการ")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='projects', verbose_name="ลูกค้า")
    description = models.TextField(blank=True, verbose_name="รายละเอียดเพิ่มเติม")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="สถานะ"
    )
    start_date = models.DateField(default=timezone.now, verbose_name="วันเริ่มโครงการ")
    deadline = models.DateField(null=True, blank=True, verbose_name="กำหนดส่งมอบ")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"
    
    @property
    def total_cost(self):
        return sum(item.total_cost for item in self.items.all())

    @property
    def total_value(self):
        """Total Project Value (Selling Price)"""
        return sum(item.total_price for item in self.items.all())
        
    @property
    def total_profit(self):
        return self.total_value - self.total_cost
    
    class Meta:
        verbose_name = "โครงการ"
        verbose_name_plural = "โครงการ"

class ProductItem(models.Model):
    class ItemType(models.TextChoices):
        PRODUCT = 'PRODUCT', _('สินค้า (Physical Goods)')
        SERVICE = 'SERVICE', _('บริการ / ค่าแรง (Service)')

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=255, verbose_name="ชื่อรายการ")
    description = models.TextField(blank=True, verbose_name="รายละเอียด")
    item_type = models.CharField(
        max_length=10,
        choices=ItemType.choices,
        default=ItemType.PRODUCT,
        verbose_name="ประเภท"
    )
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, help_text="ระบุหากเป็นสินค้า", verbose_name="ซัพพลายเออร์")
    
    quantity = models.PositiveIntegerField(default=1, verbose_name="จำนวน")
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="ต้นทุนต่อหน่วย")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="ราคาขายต่อหน่วย")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.get_item_type_display()})"

    @property
    def total_cost(self):
        return self.unit_cost * self.quantity

    @property
    def total_price(self):
        return self.unit_price * self.quantity

    class Meta:
        verbose_name = "รายการสินค้า/บริการ"
        verbose_name_plural = "รายการสินค้า/บริการ"
