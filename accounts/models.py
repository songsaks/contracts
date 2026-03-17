# ====== accounts/models.py ======
# กำหนด Model หลักของแอป Accounts สำหรับจัดเก็บข้อมูลโปรไฟล์พนักงาน
# และควบคุมสิทธิ์การเข้าถึงระบบย่อยต่าง ๆ

from django.db import models
from django.conf import settings

# ====== ตัวเลือกตำแหน่งงาน (Role) — fallback เมื่อ DB ยังไม่มีข้อมูล ======
ROLE_CHOICES = (
    ('admin', 'ผู้ดูแลระบบ (Admin)'),
    ('manager', 'ผู้บริหาร (Manager)'),
    ('reception', 'แอดมินรับงาน (Reception)'),
    ('technician_lead', 'หัวหน้าช่าง (Lead Technician)'),
    ('technician', 'ช่างเทคนิค (Technician)'),
    ('sale', 'พนักงานขาย (Sale)'),
    ('hr_payroll', 'ฝ่ายบุคคล/เงินเดือน (HR/Payroll)'),
)


def get_role_choices():
    """โหลด Role choices จาก DB (ใช้ใน forms) — fallback เป็น ROLE_CHOICES"""
    try:
        return [(r.code, r.name) for r in Role.objects.order_by('order', 'name')]
    except Exception:
        return list(ROLE_CHOICES)


def user_can_view_all(user):
    """ตรวจสอบว่า user มีสิทธิ์ดูรายงาน/ข้อมูลของพนักงานทุกคน
    → True ถ้า: superuser, is_staff, is_staff_role หรือ can_view_all_reports บน Role
    ใช้แทน `user.is_staff` ในทุก view รายงาน
    """
    if user.is_superuser or user.is_staff:
        return True
    try:
        return user.profile.can_view_all()
    except Exception:
        return False


# ====== Model: Role — ตำแหน่ง/บทบาท จัดการได้จากหน้า UI ======
class Role(models.Model):
    code = models.CharField(max_length=30, unique=True, verbose_name="รหัสตำแหน่ง",
                            help_text="ตัวพิมพ์เล็ก ไม่มีช่องว่าง เช่น technician, manager")
    name = models.CharField(max_length=100, verbose_name="ชื่อตำแหน่ง")
    is_staff_role = models.BooleanField(default=False, verbose_name="สิทธิ์ดูแลระบบ (Staff)",
                                        help_text="เปิดใช้: เห็นข้อมูลทุกคนในรายงาน + เข้า /admin ได้")
    is_technician_role = models.BooleanField(default=False, verbose_name="เป็นตำแหน่งช่าง (GPS)",
                                             help_text="เปิดใช้: แสดงปุ่ม GPS ในห้องแชท")
    can_view_all_reports = models.BooleanField(default=False, verbose_name="ดูรายงานของทุกคนได้",
                                               help_text="เปิดใช้: ดูข้อมูล/รายงานของพนักงานทุกคนได้ (ไม่จำเป็นต้องเข้า /admin)")
    badge_color = models.CharField(max_length=200,
                                   default='bg-slate-100 text-slate-800 border-slate-200',
                                   verbose_name="CSS Badge (Tailwind classes)")
    order = models.IntegerField(default=0, verbose_name="ลำดับการแสดง")

    class Meta:
        ordering = ['order', 'name']
        verbose_name = "ตำแหน่ง/บทบาท"
        verbose_name_plural = "ตำแหน่ง/บทบาท"

    def __str__(self):
        return self.name

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

    def get_role_obj(self):
        """ดึง Role object จาก DB ตาม role code ปัจจุบัน"""
        try:
            return Role.objects.get(code=self.role)
        except Role.DoesNotExist:
            return None

    def get_role_display(self):
        """แสดงชื่อตำแหน่งจาก Role model (override Django default)"""
        role_obj = self.get_role_obj()
        if role_obj:
            return role_obj.name
        # fallback จาก ROLE_CHOICES
        return dict(ROLE_CHOICES).get(self.role, self.role)

    def get_role_badge_color(self):
        """คืนค่า CSS class สำหรับแสดงสีของ Badge ตาม Role"""
        role_obj = self.get_role_obj()
        if role_obj:
            return role_obj.badge_color
        return 'bg-slate-100 text-slate-800 border-slate-200'

    def is_admin_role(self):
        """คืนค่า True ถ้า role มี is_staff_role=True (เข้า /admin ได้)"""
        role_obj = self.get_role_obj()
        if role_obj:
            return role_obj.is_staff_role
        return self.role in ('admin', 'manager')  # fallback

    def can_view_all(self):
        """คืนค่า True ถ้า role มี is_staff_role หรือ can_view_all_reports=True
           → ดูรายงาน/ข้อมูลของพนักงานทุกคนได้"""
        if self.user.is_superuser or self.user.is_staff:
            return True
        role_obj = self.get_role_obj()
        if role_obj:
            return role_obj.is_staff_role or role_obj.can_view_all_reports
        return self.role in ('admin', 'manager')  # fallback

    def sync_groups(self):
        """ซิงค์สิทธิ์จาก Checkbox ไปยัง Django Groups อัตโนมัติ
           และ sync is_staff จาก role (admin/manager → is_staff=True)
        """
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

        # ─── Sync is_staff จาก Role model ──────────────────────────
        if not self.user.is_superuser:
            should_be_staff = self.is_admin_role()
            if self.user.is_staff != should_be_staff:
                self.user.is_staff = should_be_staff
                self.user.save(update_fields=['is_staff'])

    def save(self, *args, **kwargs):
        # บันทึกข้อมูลโปรไฟล์ก่อน
        super().save(*args, **kwargs)
        # ทำการซิงค์ Group ตามสิทธิ์ที่ติ๊กไว้
        self.sync_groups()
