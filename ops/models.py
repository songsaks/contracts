from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Department(models.Model):
    name = models.CharField(max_length=100, verbose_name="ชื่อฝ่าย")
    description = models.TextField(blank=True, null=True, verbose_name="รายละเอียด")

    def __str__(self):
        return self.name

class Employee(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee_profile')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name='employees')
    phone = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.department}"

class WeeklyGoal(models.Model):
    title = models.CharField(max_length=200, verbose_name="หัวข้อเป้าหมาย")
    description = models.TextField(blank=True, verbose_name="รายละเอียด/วิธีปฏิบัติ")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='weekly_goals')
    start_date = models.DateField(verbose_name="วันที่เริ่ม (จันทร์)")
    end_date = models.DateField(verbose_name="วันที่สิ้นสุด (เสาร์)")
    target_value = models.FloatField(default=0, verbose_name="ตัวเลขเป้าหมาย (Target)")
    unit = models.CharField(max_length=20, default='งาน', verbose_name="หน่วยวัด")
    
    STATUS_CHOICES = (
        ('todo', 'รอดำเนินการ (To Do)'),
        ('doing', 'กำลังทำ (In Progress)'),
        ('done', 'เสร็จสิ้น (Done)'),
        ('blocked', 'ติดปัญหา (Blocked)'),
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='todo', verbose_name="สถานะ")
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total_actual(self):
        return self.daily_progresses.aggregate(total=models.Sum('actual_value'))['total'] or 0

    @property
    def success_percentage(self):
        if self.target_value <= 0: return 0
        return min((self.total_actual / self.target_value) * 100, 100)

    @property
    def status_color(self):
        pct = self.success_percentage
        if pct >= 80: return "success"  # เขียว
        if pct >= 50: return "warning"  # เหลือง
        return "danger"  # แดง

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return f"[{self.department}] {self.title} ({self.start_date})"

class DailyProgress(models.Model):
    goal = models.ForeignKey(WeeklyGoal, on_delete=models.CASCADE, related_name='daily_progresses')
    employee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="ผู้บันทึก")
    date = models.DateField(default=timezone.now, verbose_name="วันที่รายงาน")
    actual_value = models.FloatField(default=0, verbose_name="จำนวนที่ทำได้จริง")
    note = models.TextField(blank=True, verbose_name="หมายเหตุ/อุปสรรค")
    image = models.ImageField(upload_to='ops/progress/', blank=True, null=True, verbose_name="รูปภาพหน้างาน")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.date} - {self.goal.title}: {self.actual_value}"
