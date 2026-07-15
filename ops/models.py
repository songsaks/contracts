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
    strategy = models.TextField(blank=True, verbose_name="กลยุทธ์หลัก (Action Plan)")
    expected_challenges = models.TextField(blank=True, verbose_name="อุปสรรคความเสี่ยงที่คาดการณ์")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='weekly_goals')
    start_date = models.DateField(verbose_name="วันที่เริ่ม (จันทร์)")
    end_date = models.DateField(verbose_name="วันที่สิ้นสุด (เสาร์)")
    target_value = models.FloatField(default=0, verbose_name="ตัวเลขเป้าหมาย (Target)")
    unit = models.CharField(max_length=20, default='งาน', verbose_name="หน่วยวัด")
    
    STATUS_CHOICES = (
        ('todo', 'รอดำเนินการ (To Do)'),
        ('doing', 'กำลังทำ (In Progress)'),
        ('reviewing', 'รอตรวจสอบ (Reviewing)'),
        ('done', 'เสร็จสิ้น (Done)'),
        ('blocked', 'ติดปัญหา (Blocked)'),
    )
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='todo', verbose_name="สถานะ")
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

class Meeting(models.Model):
    STATUS_CHOICES = (
        ('scheduled', 'นัดหมายแล้ว'),
        ('in_progress', 'กำลังประชุม'),
        ('completed', 'เสร็จสิ้น'),
        ('cancelled', 'ยกเลิก'),
    )
    title = models.CharField(max_length=200, verbose_name="หัวข้อการประชุม")
    agenda = models.TextField(verbose_name="วาระการประชุม")
    date = models.DateField(verbose_name="วันที่ประชุม")
    start_time = models.TimeField(verbose_name="เวลาเริ่ม")
    end_time = models.TimeField(verbose_name="เวลาสิ้นสุด", blank=True, null=True)
    location = models.CharField(max_length=200, blank=True, verbose_name="สถานที่/ห้องประชุม")
    organizer = models.ForeignKey(User, on_delete=models.CASCADE, related_name='organized_meetings', verbose_name="ผู้จัดประชุม")
    minutes = models.TextField(blank=True, verbose_name="บันทึกมติที่ประชุม (Real-time Minutes)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled', verbose_name="สถานะ")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.date})"

class MeetingParticipant(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_attended = models.BooleanField(default=False, verbose_name="เข้าประชุม")

class MeetingIdea(models.Model):
    STATUS_CHOICES = (
        ('proposed', 'เสนอไอเดีย'),
        ('under_review', 'กำลังพิจารณา'),
        ('approved', 'อนุมัติ (เป็นงาน)'),
        ('rejected', 'ปฏิเสธ'),
    )
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='ideas', verbose_name="การประชุม")
    proposer = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="ผู้เสนอไอเดีย")
    title = models.CharField(max_length=200, verbose_name="หัวข้อไอเดีย")
    description = models.TextField(verbose_name="รายละเอียดไอเดีย")
    
    # Scoring
    impact_score = models.IntegerField(default=0, verbose_name="คะแนนผลกระทบ (1-10)")
    feasibility_score = models.IntegerField(default=0, verbose_name="คะแนนความเป็นไปได้ (1-10)")
    total_score = models.IntegerField(default=0, verbose_name="คะแนนรวม")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='proposed', verbose_name="สถานะ")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_ideas')
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.total_score = self.impact_score + self.feasibility_score
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

class TaskTag(models.Model):
    name = models.CharField(max_length=50, verbose_name="ชื่อป้ายกำกับ")
    color = models.CharField(max_length=20, default="primary", verbose_name="สี (Bootstrap class)")

    def __str__(self):
        return self.name

class ActionTask(models.Model):
    STATUS_CHOICES = (
        ('todo', 'To Do'),
        ('doing', 'In Progress'),
        ('reviewing', 'Reviewing'),
        ('done', 'Done'),
        ('blocked', 'Blocked'),
    )
    PRIORITY_CHOICES = (
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    )
    idea = models.OneToOneField(MeetingIdea, on_delete=models.CASCADE, related_name='action_task', verbose_name="ไอเดียต้นฉบับ", null=True, blank=True)
    goal = models.ForeignKey(WeeklyGoal, on_delete=models.CASCADE, related_name='action_tasks', verbose_name="เป้าหมาย (Goal)", null=True, blank=True)
    title = models.CharField(max_length=200, verbose_name="ชื่องาน")
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='action_tasks', verbose_name="ผู้รับผิดชอบ")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, verbose_name="ฝ่าย")
    start_date = models.DateField(verbose_name="วันที่เริ่ม")
    due_date = models.DateField(verbose_name="วันครบกำหนด")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='todo', verbose_name="สถานะ")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium', verbose_name="ความสำคัญ")
    reviewer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_tasks', verbose_name="ผู้ตรวจสอบ (QA)")
    dependencies = models.ManyToManyField('self', symmetrical=False, blank=True, related_name='dependents', verbose_name="งานที่ต้องทำก่อน")
    tags = models.ManyToManyField(TaskTag, blank=True, related_name='tasks', verbose_name="ป้ายกำกับ")
    estimated_hours = models.FloatField(default=0, verbose_name="เวลาที่คาดหวัง (ชั่วโมง)")
    actual_hours = models.FloatField(default=0, verbose_name="เวลาที่ใช้จริง (ชั่วโมง)")
    progress_pct = models.IntegerField(default=0, verbose_name="ความคืบหน้า (%)")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

class ActionTaskChecklist(models.Model):
    task = models.ForeignKey(ActionTask, on_delete=models.CASCADE, related_name='checklists')
    title = models.CharField(max_length=200, verbose_name="ชื่องานย่อย")
    is_completed = models.BooleanField(default=False, verbose_name="เสร็จสิ้นแล้ว")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{'X' if self.is_completed else ' '}] {self.title}"

class TaskComment(models.Model):
    task = models.ForeignKey(ActionTask, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField(verbose_name="ความคิดเห็น")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} on {self.task.title}"

class TaskAttachment(models.Model):
    task = models.ForeignKey(ActionTask, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='ops/tasks/attachments/', verbose_name="ไฟล์แนบ")
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Attachment for {self.task.title}"


class TaskStep(models.Model):
    STATUS_CHOICES = (
        ('todo', 'รอดำเนินการ (To Do)'),
        ('doing', 'กำลังทำ (In Progress)'),
        ('done', 'เสร็จสิ้น (Done)'),
        ('blocked', 'ติดปัญหา (Blocked)'),
    )
    task = models.ForeignKey(ActionTask, on_delete=models.CASCADE, related_name='steps')
    title = models.CharField(max_length=200, verbose_name="ชื่อขั้นตอน")
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='task_steps', verbose_name="ผู้รับผิดชอบ")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='todo', verbose_name="สถานะ")
    description = models.TextField(blank=True, verbose_name="รายละเอียดขั้นตอน")
    order = models.IntegerField(default=0, verbose_name="ลำดับ")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'created_at']

    def __str__(self):
        return f"{self.task.title} - Step: {self.title} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.update_task_progress()

    def delete(self, *args, **kwargs):
        task = self.task
        super().delete(*args, **kwargs)
        steps = task.steps.all()
        if steps.exists():
            done_steps = steps.filter(status='done').count()
            task.progress_pct = int((done_steps / steps.count()) * 100)
        else:
            task.progress_pct = 0
        task.save()

    def update_task_progress(self):
        task = self.task
        steps = task.steps.all()
        if steps.exists():
            done_steps = steps.filter(status='done').count()
            task.progress_pct = int((done_steps / steps.count()) * 100)
            task.save()



class AICoworkerLog(models.Model):
    AGENT_CHOICES = (
        ('marketing', 'Marketing Automation'),
        ('sales', 'Sales Intelligence'),
        ('executive', 'Executive Reporting'),
    )
    agent_type = models.CharField(max_length=20, choices=AGENT_CHOICES, verbose_name="ประเภทเอเจนต์")
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="ผู้สั่งงาน")
    input_data = models.TextField(verbose_name="ข้อมูลนำเข้า")
    output_data = models.JSONField(verbose_name="ผลลัพธ์การทำงาน", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="วันเวลาที่บันทึก")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "บันทึกประวัติเพื่อนร่วมงาน AI"
        verbose_name_plural = "บันทึกประวัติเพื่อนร่วมงาน AI"

    def __str__(self):
        return f"{self.get_agent_type_display()} - {self.user.username} ({self.created_at.strftime('%d/%m/%Y %H:%M')})"

