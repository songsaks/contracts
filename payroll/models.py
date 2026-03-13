# ====== models.py — โมเดลหลักของระบบ Payroll ======
# ไฟล์นี้กำหนดโครงสร้างฐานข้อมูลทั้งหมดของระบบเงินเดือน
# ประกอบด้วย: SSOBracket, WorkReport, EmployeeSalaryConfig, PayrollRecord

from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

# ====== Helper Functions — ค่าเริ่มต้นเดือน/ปีปัจจุบัน ======

def get_current_month():
    # คืนค่าเดือนปัจจุบัน ใช้เป็น default ของ field month ใน WorkReport
    return timezone.now().month

def get_current_year():
    # คืนค่าปีปัจจุบัน ใช้เป็น default ของ field year ใน WorkReport
    return timezone.now().year

# ====== PayrollStatus — สถานะของรายงานผลงาน ======
# ระบบมี 4 สถานะ: DRAFT → SUBMITTED → APPROVED หรือ REJECTED → (แก้ไข) → SUBMITTED อีกครั้ง

class PayrollStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'แบบร่าง (Draft)'
    SUBMITTED = 'SUBMITTED', 'รอการตรวจสอบ (Waiting)'
    APPROVED = 'APPROVED', 'อนุมัติแล้ว (Approved)'
    REJECTED = 'REJECTED', 'ส่งกลับเพื่อแก้ไข (Rejected)'

# ====== SSOBracket — ตารางอัตราประกันสังคมแบบขั้นบันได ======

class SSOBracket(models.Model):
    """
    ประกันสังคม — อัตราขั้นบันได (ตามช่วงเงินเดือน)
    HR/Admin กำหนดได้เอง ใช้ร่วมกันทุกคน

    วิธีทำงาน:
    - กำหนดช่วงเงินเดือน (min_salary ถึง max_salary)
    - หากเงินเดือนอยู่ในช่วงนี้ จะใช้ rate_percent คำนวณ SSO
    - salary_cap กำหนดเพดานฐานสูงสุดที่ใช้คำนวณ (0 = ไม่มีเพดาน)
    """
    min_salary  = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="เงินเดือนขั้นต่ำ (≥)")
    max_salary  = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                      verbose_name="เงินเดือนสูงสุด (≤, ว่าง = ไม่จำกัด)")
    rate_percent = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="อัตรา %")
    salary_cap  = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'),
                                      verbose_name="เพดานฐานคำนวณ (บาท, 0 = ไม่มี)")
    description = models.CharField(max_length=100, blank=True, verbose_name="คำอธิบาย")
    is_active   = models.BooleanField(default=True, verbose_name="ใช้งาน")

    class Meta:
        ordering = ['min_salary']
        verbose_name = "อัตราประกันสังคม (ขั้นบันได)"
        verbose_name_plural = "อัตราประกันสังคม (ขั้นบันได)"

    def __str__(self):
        max_s = f"–{self.max_salary:,.0f}" if self.max_salary else "+"
        return f"{self.min_salary:,.0f}{max_s} บาท → {self.rate_percent}%"

    def compute_for(self, base_salary):
        """คำนวณจำนวนเงินประกันสังคมจาก base_salary

        ถ้ามี salary_cap จะใช้ min(base_salary, salary_cap) เป็นฐาน
        จากนั้นคูณด้วย rate_percent แล้วหาร 100 และปัดทศนิยม 2 ตำแหน่ง
        """
        cap_base = min(base_salary, self.salary_cap) if self.salary_cap else base_salary
        return (cap_base * self.rate_percent / Decimal('100')).quantize(Decimal('0.01'))


# ====== WorkReport — รายงานผลงานประจำเดือนของพนักงาน ======

class WorkReport(models.Model):
    """
    บันทึกข้อมูลผลงาน/รายรับ/รายหักของพนักงานแต่ละเดือน
    พนักงานสร้างเองและส่งให้ HR อนุมัติ หรือ HR/ผู้บริหารสร้างแทนได้
    unique_together = (user, month, year) — 1 คน 1 รายงาน ต่อ 1 เดือน
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='work_reports')
    month = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 13)], default=get_current_month)
    year = models.PositiveSmallIntegerField(default=get_current_year)

    # พนักงานกรอก — ข้อมูลรายได้
    working_days = models.DecimalField(max_digits=5, decimal_places=1, default=0, verbose_name="วันทำงานจริง (วัน)")
    ot_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="OT (ชั่วโมง)")
    team_mgmt_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="ค่าบริหารทีม (บาท)")
    professional_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="ค่าวิชาชีพ (บาท)")
    commissions = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ค่าคอมมิชชัน (บาท)")
    incentives = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Incentives (บาท)")
    pb_liva_score = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="PB&Livascore")
    customer_evaluation = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ค่าประเมินจากลูกค้า (บาท)")

    # รายจ่ายและรายการหัก (พนักงานกรอกแผนผังเบื้องต้น)
    absent_days = models.DecimalField(max_digits=5, decimal_places=1, default=0, verbose_name="จำนวนวันที่ขาดงาน (วัน)")
    absent_deduction_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="เงินหักจากการขาดงาน (บาท)")
    advance_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="เงินเบิกล่วงหน้า (บาท)")
    savings = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="เงินออมสะสม (บาท)")
    lost_equipment_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="ค่าของหาย (บาท)")
    monthly_tax_withholding = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ภาษีหัก ณ ที่จ่าย (บาท)")
    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="รายการหักอื่นๆ (บาท)")

    # สถานะ Workflow และหมายเหตุ
    status = models.CharField(max_length=20, choices=PayrollStatus.choices, default=PayrollStatus.DRAFT)
    remarks = models.TextField(blank=True, verbose_name="พนักงาน: หมายเหตุ")
    admin_remarks = models.TextField(blank=True, verbose_name="ผู้บริหาร: ข้อเสนอแนะ/เหตุผลที่ตีกลับ")

    # Timestamps — บันทึกอัตโนมัติ
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "รายงานผลงานพนักงาน"
        verbose_name_plural = "รายงานผลงานพนักงาน"
        # ป้องกันการสร้างรายงานซ้ำสำหรับพนักงานคนเดิมในเดือนเดียวกัน
        unique_together = ('user', 'month', 'year')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"Report: {self.user.username} - {self.month}/{self.year}"

# ====== EmployeeSalaryConfig — ข้อมูลโครงสร้างเงินเดือนของพนักงานแต่ละคน ======

class EmployeeSalaryConfig(models.Model):
    """
    เก็บข้อมูลที่ใช้คำนวณเงินเดือนของพนักงานแต่ละคน
    - ฐานเงินเดือน, อัตรา OT
    - การตั้งค่าประกันสังคม (SSO) แบบขั้นบันได หรือ กำหนดเองต่อคน
    - เลขบัญชีธนาคารสำหรับโอนเงิน
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='salary_config')

    # ── Employee Identity ────────────────────────────────────
    employee_code = models.CharField(
        max_length=7, unique=True, null=True, blank=True,
        verbose_name="รหัสพนักงาน (7 หลัก)"
    )
    national_id = models.CharField(
        max_length=13, blank=True,
        verbose_name="เลขบัตรประชาชน"
    )

    # ── Payroll membership ──────────────────────────────────
    is_payroll_member = models.BooleanField(
        default=False,
        verbose_name="เป็นพนักงานในระบบ Payroll",
        help_text="ถ้า False = user นี้ไม่ปรากฏในระบบ Payroll"
    )

    # ── Salary & rates ──────────────────────────────────────
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ฐานเงินเดือน")
    ot_rate_per_hour = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="อัตรา OT (บาท/ชั่วโมง)")

    # ── Social Security (SSO) ────────────────────────────────
    # ถ้า use_sso_bracket=True → ดูจาก SSOBracket table (ขั้นบันได)
    # ถ้า False → ใช้ rate/cap ที่กำหนดต่อคน (social_security_rate / social_security_cap)
    use_sso_bracket = models.BooleanField(
        default=True,
        verbose_name="ใช้อัตราประกันสังคมแบบขั้นบันได",
        help_text="ถ้าปิด จะใช้อัตราที่กำหนดเฉพาะคนนี้"
    )
    social_security_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('5.00'),
        verbose_name="อัตราประกันสังคมเฉพาะคน (%)"
    )
    social_security_cap = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('750'),
        verbose_name="เพดานประกันสังคมเฉพาะคน (บาท)"
    )
    # ภาษีหัก ณ ที่จ่าย รายเดือน (ค่าคงที่ กำหนดโดย HR)
    tax_withholding = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="หักภาษี ณ ที่จ่าย (บาท)")

    # ── Bank account — สำหรับโอนเงินเดือน ───────────────────
    bank_account_number = models.CharField(max_length=50, blank=True, verbose_name="เลขบัญชีธนาคาร")
    bank_name = models.CharField(max_length=100, blank=True, verbose_name="ชื่อธนาคาร")

    def __str__(self):
        code = self.employee_code or "—"
        return f"[{code}] {self.user.username}"

    @classmethod
    def generate_employee_code(cls):
        """Auto-generate next 7-digit employee code.

        ค้นหารหัสพนักงานสูงสุดในระบบ แล้ว +1
        ถ้ายังไม่มีรหัสใดเลย จะเริ่มที่ '0000001'
        """
        last = cls.objects.filter(
            employee_code__isnull=False
        ).exclude(employee_code='').order_by('-employee_code').first()
        if last and last.employee_code and last.employee_code.isdigit():
            return str(int(last.employee_code) + 1).zfill(7)
        return '0000001'

    def get_sso_amount(self):
        """คํานวณประกันสังคมตาม bracket หรือ per-employee rate

        ลำดับความสำคัญ:
        1. ถ้า use_sso_bracket=True → ค้นหา SSOBracket ที่ตรงกับ base_salary
           แล้วเรียก bracket.compute_for(base) เพื่อคำนวณ
        2. Fallback → ใช้สูตร: min(base * rate%, cap)
        """
        base = self.base_salary
        if self.use_sso_bracket:
            from django.db.models import Q
            # ค้นหา bracket ที่ใช้งานอยู่และครอบคลุมช่วงเงินเดือนนี้
            bracket = SSOBracket.objects.filter(
                min_salary__lte=base,
                is_active=True
            ).filter(
                Q(max_salary__isnull=True) | Q(max_salary__gte=base)
            ).order_by('min_salary').last()
            if bracket:
                return bracket.compute_for(base)
        # Fallback: per-employee rate — ใช้อัตราที่กำหนดเฉพาะคน
        return min(
            base * self.social_security_rate / Decimal('100'),
            self.social_security_cap
        ).quantize(Decimal('0.01'))


# ====== PayrollRecord — ผลการคำนวณเงินเดือน (สร้างอัตโนมัติตอนอนุมัติ) ======

class PayrollRecord(models.Model):
    """
    เก็บผลการคำนวณเงินเดือนหลังจาก HR/ผู้บริหารอนุมัติ WorkReport
    สร้างโดย _calculate_and_save_payroll() ใน views.py

    - OneToOne กับ WorkReport → 1 รายงาน มี 1 ผลคำนวณ
    - base_salary_snapshot: snapshot ฐานเงินเดือน ณ เวลาคำนวณ (ป้องกันผลกระทบเมื่อแก้ไข config)
    - total_income = base + OT + commissions + incentives + team_mgmt_fee + professional_fee + customer_evaluation
    - total_deductions = SSO + tax + absent_deduction + advance_pay + savings + lost_equipment + other
    - net_pay = total_income - total_deductions
    """
    report = models.OneToOneField(WorkReport, on_delete=models.CASCADE, related_name='payroll_record')
    # Snapshot ฐานเงินเดือน ณ เวลาที่อนุมัติ (ไม่เปลี่ยนแม้ config จะถูกแก้ไขทีหลัง)
    base_salary_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    ot_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    social_security_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ยอดสรุปการคำนวณ
    total_income = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    # ผู้อนุมัติและเวลาที่ประมวลผล
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='processed_payrolls')
    processed_at = models.DateTimeField(auto_now_add=True)

    # สถานะการจ่ายเงิน (สำหรับ Bank Export)
    is_paid = models.BooleanField(default=False)
    payment_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Payroll: {self.report.user.username} - {self.report.month}/{self.report.year}"
