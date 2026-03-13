# ====== accounts/models.py ======
# กำหนด Model หลักของแอป Accounts สำหรับจัดเก็บข้อมูลโปรไฟล์พนักงาน
# และควบคุมสิทธิ์การเข้าถึงระบบย่อยต่าง ๆ

from django.db import models
from django.conf import settings

# ====== ตัวเลือกตำแหน่งงาน (Role) ======
# กำหนดบทบาทที่พนักงานแต่ละคนสามารถมีได้ในระบบ
ROLE_CHOICES = (
    ('admin', 'ผู้ดูแลระบบ (Admin)'),
    ('manager', 'ผู้บริหาร (Manager)'),
    ('reception', 'แอดมินรับงาน (Reception)'),
    ('technician_lead', 'หัวหน้าช่าง (Lead Technician)'),
    ('technician', 'ช่างเทคนิค (Technician)'),
    ('sale', 'พนักงานขาย (Sale)'),
    ('hr_payroll', 'ฝ่ายบุคคล/เงินเดือน (HR/Payroll)'),
)

# ====== Model: UserProfile ======
class UserProfile(models.Model):
    """
    โปรไฟล์เพิ่มเติมของพนักงาน (ต่อขยายจาก Django User ด้วย OneToOne)
    เก็บข้อมูลตำแหน่ง เบอร์โทร รูปโปรไฟล์ และสิทธิ์เข้าระบบย่อยแต่ละระบบ
    """
    # ลิงก์กลับไปยัง User หลักของ Django แบบ One-to-One
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile', verbose_name="ผู้ใช้")
    # ตำแหน่ง/บทบาทของพนักงาน เลือกจาก ROLE_CHOICES
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='technician', verbose_name="ตำแหน่ง/บทบาท")
    phone_number = models.CharField(max_length=20, blank=True, verbose_name="เบอร์โทรศัพท์")
    # รูปโปรไฟล์ อัปโหลดไปยังโฟลเดอร์ avatars/
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True, verbose_name="รูปโปรไฟล์")

    # ====== สิทธิ์การเข้าถึงระบบย่อย (App Access Controls) ======
    # BooleanField แต่ละตัวควบคุมว่าพนักงานคนนี้มีสิทธิ์เข้าระบบนั้น ๆ หรือไม่
    access_rentals = models.BooleanField(default=False, verbose_name="เข้าใช้ระบบสัญญาเช่า")
    access_repairs = models.BooleanField(default=True, verbose_name="เข้าใช้ระบบซ่อมบำรุง")
    access_pos = models.BooleanField(default=False, verbose_name="เข้าใช้ระบบขายสินค้า (POS)")
    access_pms = models.BooleanField(default=False, verbose_name="เข้าใช้ระบบจัดการโครงการ (PMS)")
    access_chat = models.BooleanField(default=True, verbose_name="เข้าใช้ศูนย์แชทกลาง")
    access_payroll = models.BooleanField(default=False, verbose_name="เข้าใช้ระบบเงินเดือน")
    access_stocks = models.BooleanField(default=False, verbose_name="เข้าใช้ระบบวิเคราะห์หุ้น AI")
    access_accounts = models.BooleanField(default=False, verbose_name="เข้าใช้ระบบจัดการพนักงาน (User Management)")

    class Meta:
        verbose_name = "โปรไฟล์พนักงาน"
        verbose_name_plural = "โปรไฟล์พนักงาน"

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"

    def get_role_badge_color(self):
        """คืนค่า CSS class สำหรับแสดงสีของ Badge ตาม Role ของพนักงาน"""
        colors = {
            'admin': 'bg-red-100 text-red-800 border-red-200',
            'manager': 'bg-purple-100 text-purple-800 border-purple-200',
            'reception': 'bg-pink-100 text-pink-800 border-pink-200',
            'technician_lead': 'bg-blue-100 text-blue-800 border-blue-200',
            'technician': 'bg-cyan-100 text-cyan-800 border-cyan-200',
            'sale': 'bg-green-100 text-green-800 border-green-200',
            'hr_payroll': 'bg-orange-100 text-orange-800 border-orange-200',
        }
        # ถ้าไม่มี Role ที่ตรงกัน ใช้สีเทาเป็น Default
        return colors.get(self.role, 'bg-slate-100 text-slate-800 border-slate-200')

    def sync_groups(self):
        """ซิงค์สิทธิ์จาก Checkbox ไปยัง Django Groups อัตโนมัติ"""
        from django.contrib.auth.models import Group

        # Mapping ระหว่าง Field ในโปรไฟล์ กับ ชื่อกลุ่มในระบบ
        mapping = {
            'access_rentals': 'Rentals',
            'access_repairs': 'Repairs',
            'access_pos': 'POS',
            'access_pms': 'PMS',
            'access_chat': 'Chat',
            'access_payroll': 'Payroll',
            'access_stocks': 'Stocks',
            'access_accounts': 'Accounts',
        }

        # วนลูปทุก Field ใน Mapping เพื่อเพิ่ม/ลบ User ออกจาก Group ตามสิทธิ์
        for field, group_name in mapping.items():
            is_allowed = getattr(self, field)
            # สร้าง Group อัตโนมัติหากยังไม่มีในระบบ
            group, created = Group.objects.get_or_create(name=group_name)

            if is_allowed:
                self.user.groups.add(group)
            else:
                self.user.groups.remove(group)

    def save(self, *args, **kwargs):
        # บันทึกข้อมูลโปรไฟล์ก่อน
        super().save(*args, **kwargs)
        # ทำการซิงค์ Group ตามสิทธิ์ที่ติ๊กไว้
        self.sync_groups()
