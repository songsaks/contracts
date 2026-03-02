from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

def get_current_month():
    return timezone.now().month

def get_current_year():
    return timezone.now().year

class PayrollStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'แบบร่าง (Draft)'
    SUBMITTED = 'SUBMITTED', 'รอการตรวจสอบ (Waiting)'
    APPROVED = 'APPROVED', 'อนุมัติแล้ว (Approved)'
    REJECTED = 'REJECTED', 'ส่งกลับเพื่อแก้ไข (Rejected)'

class SSOBracket(models.Model):
    """
    ประกันสังคม — อัตราขั้นบันได (ตามช่วงเงินเดือน)
    HR/Admin กำหนดได้เอง ใช้ร่วมกันทุกคน
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
        """คำนวณจำนวนเงินประกันสังคมจาก base_salary"""
        cap_base = min(base_salary, self.salary_cap) if self.salary_cap else base_salary
        return (cap_base * self.rate_percent / Decimal('100')).quantize(Decimal('0.01'))


class WorkReport(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='work_reports')
    month = models.PositiveSmallIntegerField(choices=[(i, str(i)) for i in range(1, 13)], default=get_current_month)
    year = models.PositiveSmallIntegerField(default=get_current_year)
    
    # พนักงานกรอก
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
    
    status = models.CharField(max_length=20, choices=PayrollStatus.choices, default=PayrollStatus.DRAFT)
    remarks = models.TextField(blank=True, verbose_name="พนักงาน: หมายเหตุ")
    admin_remarks = models.TextField(blank=True, verbose_name="ผู้บริหาร: ข้อเสนอแนะ/เหตุผลที่ตีกลับ")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "รายงานผลงานพนักงาน"
        verbose_name_plural = "รายงานผลงานพนักงาน"
        unique_together = ('user', 'month', 'year')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"Report: {self.user.username} - {self.month}/{self.year}"

class EmployeeSalaryConfig(models.Model):
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

    # ── Social Security ─────────────────────────────────────
    # ถ้า use_sso_bracket=True → ดูจาก SSOBracket table
    # ถ้า False → ใช้ rate/cap ที่กำหนดต่อคน
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
    tax_withholding = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="หักภาษี ณ ที่จ่าย (บาท)")

    # ── Bank account ─────────────────────────────────────────
    bank_account_number = models.CharField(max_length=50, blank=True, verbose_name="เลขบัญชีธนาคาร")
    bank_name = models.CharField(max_length=100, blank=True, verbose_name="ชื่อธนาคาร")

    def __str__(self):
        code = self.employee_code or "—"
        return f"[{code}] {self.user.username}"

    @classmethod
    def generate_employee_code(cls):
        """Auto-generate next 7-digit employee code."""
        last = cls.objects.filter(
            employee_code__isnull=False
        ).exclude(employee_code='').order_by('-employee_code').first()
        if last and last.employee_code and last.employee_code.isdigit():
            return str(int(last.employee_code) + 1).zfill(7)
        return '0000001'

    def get_sso_amount(self):
        """คํานวณประกันสังคมตาม bracket หรือ per-employee rate"""
        base = self.base_salary
        if self.use_sso_bracket:
            from django.db.models import Q
            bracket = SSOBracket.objects.filter(
                min_salary__lte=base,
                is_active=True
            ).filter(
                Q(max_salary__isnull=True) | Q(max_salary__gte=base)
            ).order_by('min_salary').last()
            if bracket:
                return bracket.compute_for(base)
        # Fallback: per-employee rate
        return min(
            base * self.social_security_rate / Decimal('100'),
            self.social_security_cap
        ).quantize(Decimal('0.01'))


class PayrollRecord(models.Model):
    report = models.OneToOneField(WorkReport, on_delete=models.CASCADE, related_name='payroll_record')
    base_salary_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    ot_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    social_security_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    total_income = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='processed_payrolls')
    processed_at = models.DateTimeField(auto_now_add=True)
    
    is_paid = models.BooleanField(default=False)
    payment_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"Payroll: {self.report.user.username} - {self.report.month}/{self.report.year}"
