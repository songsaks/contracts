# ====== นำเข้า Library ที่จำเป็น ======
from django.db import models
from django.utils import timezone
from decimal import Decimal

# ====== โมเดลหมวดหมู่สินค้า ======

class Category(models.Model):
    """
    โมเดลหมวดหมู่สินค้า
    ใช้จัดกลุ่มสินค้าเพื่อให้ง่ายต่อการค้นหาและกรองในหน้า POS
    """
    name = models.CharField(max_length=100)  # ชื่อหมวดหมู่ เช่น "นม", "น้ำผลไม้"

    class Meta:
        verbose_name_plural = "Categories"  # ชื่อพหูพจน์สำหรับแสดงใน Admin

    def __str__(self):
        # แสดงชื่อหมวดหมู่เมื่อเรียกดู object
        return self.name


# ====== โมเดลสินค้า ======

class Product(models.Model):
    """
    โมเดลสินค้าหลักของระบบ POS
    เก็บข้อมูลสินค้าทั้งหมด รวมถึงราคา จำนวนสต็อก และรูปภาพ
    """
    name = models.CharField(max_length=200)  # ชื่อสินค้า
    code = models.CharField(
        max_length=50, unique=True, blank=True, null=True,
        help_text="Barcode or Product Code"  # รหัสสินค้า หรือ บาร์โค้ด (ไม่บังคับ)
    )
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='products'  # ความสัมพันธ์กับหมวดหมู่ ถ้าลบหมวดหมู่จะตั้งค่าเป็น NULL
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)  # ราคาขาย (บาท)
    stock = models.IntegerField(default=0)  # จำนวนสินค้าในสต็อก
    image = models.ImageField(upload_to='products/', blank=True, null=True)  # รูปภาพสินค้า (ไม่บังคับ)
    is_active = models.BooleanField(default=True)  # สถานะสินค้า: True = แสดงใน POS, False = ซ่อน
    created_at = models.DateTimeField(auto_now_add=True)  # วันที่สร้างสินค้า (บันทึกอัตโนมัติ)
    updated_at = models.DateTimeField(auto_now=True)  # วันที่อัปเดตล่าสุด (อัปเดตอัตโนมัติ)

    def __str__(self):
        # แสดงชื่อสินค้าเมื่อเรียกดู object
        return self.name

    def get_image_url(self):
        """
        คืนค่า URL ของรูปภาพสินค้า
        ถ้าไม่มีรูปจะคืนค่า URL รูปภาพ placeholder แทน
        """
        if self.image:
            return self.image.url
        return 'https://via.placeholder.com/150' # รูปภาพ placeholder เมื่อไม่มีรูปสินค้า


# ====== โมเดลคำสั่งซื้อ (ใบขาย) ======

class Order(models.Model):
    """
    โมเดลคำสั่งซื้อ (ใบขาย)
    เก็บข้อมูลการขายแต่ละครั้ง ได้แก่ ยอดรวม, ส่วนลด, วิธีชำระเงิน และสถานะ
    """
    # ตัวเลือกสถานะของคำสั่งซื้อ
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),      # รอดำเนินการ
        ('COMPLETED', 'Completed'),  # ชำระเงินแล้ว/เสร็จสิ้น
        ('CANCELLED', 'Cancelled'),  # ยกเลิก
    ]

    total_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )  # ยอดรวมสุทธิหลังหักส่วนลดแล้ว
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )  # ยอดภาษี (ปัจจุบันยังไม่ได้ใช้งาน)
    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )  # ยอดส่วนลดที่ให้ลูกค้า
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='PENDING'
    )  # สถานะคำสั่งซื้อ
    payment_method = models.CharField(
        max_length=50, default='CASH'
    )  # วิธีชำระเงิน: CASH = เงินสด, CARD = บัตร, QR = สแกน QR
    created_at = models.DateTimeField(auto_now_add=True)  # วันเวลาที่สร้างคำสั่งซื้อ

    def __str__(self):
        # แสดงหมายเลขคำสั่งซื้อและสถานะ
        return f"Order #{self.id} - {self.status}"


# ====== โมเดลรายการสินค้าในคำสั่งซื้อ ======

class OrderItem(models.Model):
    """
    โมเดลรายการสินค้าในคำสั่งซื้อ (Order Line Item)
    แต่ละ Order จะมีหลาย OrderItem ตามจำนวนประเภทสินค้าที่ซื้อ
    ราคาที่บันทึกเป็น snapshot ณ เวลาที่ขาย ป้องกันราคาเปลี่ยนย้อนหลัง
    """
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='items'
    )  # ความสัมพันธ์กับคำสั่งซื้อ ถ้าลบ Order จะลบรายการนี้ด้วย
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE
    )  # สินค้าที่ขาย
    quantity = models.IntegerField(default=1)  # จำนวนที่ขาย
    price = models.DecimalField(max_digits=10, decimal_places=2)  # ราคา ณ เวลาที่ขาย (snapshot price)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)  # ยอดรวมของรายการนี้ = price × quantity

    def save(self, *args, **kwargs):
        """
        คำนวณ subtotal อัตโนมัติก่อนบันทึก
        subtotal = ราคาต่อชิ้น × จำนวน
        """
        self.subtotal = self.price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        # แสดงจำนวนและชื่อสินค้า เช่น "2 x นมสด"
        return f"{self.quantity} x {self.product.name}"
