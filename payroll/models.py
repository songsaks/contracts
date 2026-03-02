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
    
    # รายจ่ายและรายการหัก (พนักงานกรอกแผนผังเบื้องต้น)
    absent_days = models.DecimalField(max_digits=5, decimal_places=1, default=0, verbose_name="จำนวนวันที่ขาดงาน (วัน)")
    absent_deduction_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="เงินหักจากการขาดงาน (บาท)")
    advance_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="เงินเบิกล่วงหน้า (บาท)")
    savings = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="เงินออมสะสม (บาท)")
    lost_equipment_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="ค่าของหาย (บาท)")
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
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ฐานเงินเดือน")
    ot_rate_per_hour = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="อัตรา OT (บาท/ชั่วโมง)")
    social_security_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5, verbose_name="อัตราประกันสังคม (%)")
    social_security_cap = models.DecimalField(max_digits=10, decimal_places=2, default=750, verbose_name="เพดานประกันสังคม (บาท)")
    tax_withholding = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="หักภาษี ณ ที่จ่าย (บาท)")
    
    bank_account_number = models.CharField(max_length=50, blank=True, verbose_name="เลขบัญชีธนาคาร")
    bank_name = models.CharField(max_length=100, blank=True, verbose_name="ชื่อธนาคาร")

    def __str__(self):
        return f"Config: {self.user.username}"

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
