from django.db import models
from django.utils import timezone
from django.conf import settings
from decimal import Decimal

class SLAPlan(models.Model):
    name = models.CharField(max_length=100, verbose_name="ชื่อแพ็กเกจ SLA")
    response_time_hours = models.PositiveIntegerField(default=4, verbose_name="เวลาตอบกลับ (ชม.)")
    resolution_time_hours = models.PositiveIntegerField(default=24, verbose_name="เวลาแก้ไข (ชม.)")
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True, verbose_name="รายละเอียดเงื่อนไข")

    class Meta:
        verbose_name = "แผน SLA"
        verbose_name_plural = "แผน SLA"

    def __str__(self):
        return f"{self.name} (Res: {self.response_time_hours}h / Fix: {self.resolution_time_hours}h)"

class Customer(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True, verbose_name="ที่อยู่")
    
    # CRM & Financial Fields (Optional)
    tax_id = models.CharField(max_length=20, blank=True, verbose_name="เลขประจำตัวผู้เสียภาษี")
    branch = models.CharField(max_length=100, blank=True, verbose_name="สาขา", help_text="เช่น สำนักงานใหญ่, สาขา 001")
    
    industry = models.CharField(max_length=100, blank=True, verbose_name="ประเภทธุรกิจ", help_text="เช่น โรงแรม, โรงงาน, หน่วยงานรัฐ")
    segment = models.CharField(max_length=50, blank=True, verbose_name="กลุ่มลูกค้า", choices=[
        ('PROSPECT', 'ลูกค้ามุ่งหวัง'),
        ('REGULAR', 'ลูกค้าประจำ'),
        ('VIP', 'ลูกค้า VIP'),
        ('GOVERNMENT', 'หน่วยงานรัฐ'),
        ('ENTERPRISE', 'องค์กรขนาดใหญ่'),
    ])
    
    source = models.CharField(max_length=100, blank=True, verbose_name="ช่องทางที่รู้จักเรา", help_text="เช่น Facebook, Website, คนแนะนำ")
    
    # Communication & Location
    line_id = models.CharField(max_length=100, blank=True, verbose_name="Line ID")
    facebook = models.CharField(max_length=255, blank=True, verbose_name="Facebook Page/Profile")
    map_url = models.URLField(blank=True, verbose_name="ลิงก์ Google Maps", help_text="เพื่อความสะดวกในการเดินทาง")
    
    notes = models.TextField(blank=True, verbose_name="หมายเหตุพิเศษ/นิสัยลูกค้า", help_text="เช่น เงื่อนไขการเข้าพื้นที่ หรือพฤติกรรมการซื้อ")

    sla_plan = models.ForeignKey(
        SLAPlan, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='customers',
        verbose_name="ระดับการให้บริการ (SLA)"
    )
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
        INSTALLATION = 'INSTALLATION', 'ติดตั้ง'
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
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="วันที่ปิดจบงาน")

    # SLA Tracking (Starts from project creation)
    sla_response_deadline = models.DateTimeField(null=True, blank=True, verbose_name="เส้นตายการตอบกลับ")
    sla_resolution_deadline = models.DateTimeField(null=True, blank=True, verbose_name="เส้นตายการแก้ไข")
    responded_at = models.DateTimeField(null=True, blank=True, verbose_name="เวลาที่ตอบกลับจริง")

    class Meta:
        verbose_name = "โครงการ"
        verbose_name_plural = "โครงการ"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # 1. Initialize SLA Deadlines if missing and customer has a plan
        if self.customer.sla_plan and not self.sla_response_deadline:
            now = timezone.now()
            self.sla_response_deadline = now + timezone.timedelta(hours=self.customer.sla_plan.response_time_hours)
            self.sla_resolution_deadline = now + timezone.timedelta(hours=self.customer.sla_plan.resolution_time_hours)

        # 2. Handle Closing
        if self.status in [self.Status.CLOSED, self.Status.CANCELLED] and not self.closed_at:
            self.closed_at = timezone.now()
        elif self.status not in [self.Status.CLOSED, self.Status.CANCELLED]:
            self.closed_at = None
        super().save(*args, **kwargs)

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


class CustomerRequest(models.Model):
    class Status(models.TextChoices):
        RECEIVED = 'RECEIVED', 'รับคำขอ'
        PROCESSING = 'PROCESSING', 'กำลังดำเนินการ'
        SENT = 'SENT', 'ส่งคำขอ/ตอบกลับ'
        COMPLETED = 'COMPLETED', 'เสร็จสิ้น'
        CANCELLED = 'CANCELLED', 'ยกเลิก'

    owner = models.ForeignKey('ProjectOwner', on_delete=models.SET_NULL, null=True, blank=True, related_name='requests', verbose_name="ผู้รับผิดชอบ")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='requests', verbose_name="ลูกค้า")
    title = models.CharField(max_length=255, verbose_name="หัวข้อคำขอ")
    description = models.TextField(blank=True, verbose_name="รายละเอียด")
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RECEIVED,
        verbose_name="สถานะ"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "คำขอ (Request)"
        verbose_name_plural = "คำขอ (Requests)"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.customer.name}"


def project_file_upload_path(instance, filename):
    """Upload files to pms/files/<project_id or req_id or cust_req_id>/filename"""
    if instance.project:
        return f'pms/files/project_{instance.project.pk}/{filename}'
    elif instance.requirement:
        return f'pms/files/requirement_{instance.requirement.pk}/{filename}'
    elif instance.customer_request:
        return f'pms/files/request_{instance.customer_request.pk}/{filename}'
    return f'pms/files/misc/{filename}'


class ProjectFile(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, null=True, blank=True,
        related_name='files', verbose_name="โครงการ"
    )
    requirement = models.ForeignKey(
        CustomerRequirement, on_delete=models.CASCADE, null=True, blank=True,
        related_name='files', verbose_name="ความต้องการ"
    )
    customer_request = models.ForeignKey(
        CustomerRequest, on_delete=models.CASCADE, null=True, blank=True,
        related_name='files', verbose_name="คำขอ"
    )
    file = models.FileField(upload_to=project_file_upload_path, verbose_name="ไฟล์")
    original_name = models.CharField(max_length=255, verbose_name="ชื่อไฟล์เดิม")
    description = models.CharField(max_length=255, blank=True, verbose_name="คำอธิบาย")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ไฟล์แนบ"
        verbose_name_plural = "ไฟล์แนบ"
        ordering = ['-uploaded_at']

    def __str__(self):
        return self.original_name

    @property
    def is_image(self):
        ext = self.original_name.lower().rsplit('.', 1)[-1] if '.' in self.original_name else ''
        return ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'heic', 'heif')

    @property
    def file_extension(self):
        return self.original_name.lower().rsplit('.', 1)[-1] if '.' in self.original_name else ''

    @property
    def file_size_display(self):
        try:
            size = self.file.size
            if size < 1024:
                return f"{size} B"
            elif size < 1024 * 1024:
                return f"{size / 1024:.1f} KB"
            else:
                return f"{size / (1024 * 1024):.1f} MB"
        except Exception:
            return "-"


# ===== AI Service Queue Models =====

class ServiceTeam(models.Model):
    name = models.CharField(max_length=100, verbose_name="ชื่อทีม")
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name='service_teams',
        verbose_name="สมาชิก"
    )
    skills = models.CharField(
        max_length=255, blank=True,
        help_text="e.g. REPAIR,INSTALLATION,DELIVERY",
        verbose_name="ทักษะ"
    )
    max_tasks_per_day = models.PositiveIntegerField(default=5, verbose_name="งานสูงสุด/วัน")
    is_active = models.BooleanField(default=True, verbose_name="เปิดใช้งาน")

    class Meta:
        verbose_name = "ทีมบริการ"
        verbose_name_plural = "ทีมบริการ"

    def __str__(self):
        return self.name

    def skill_list(self):
        return [s.strip() for s in self.skills.split(',') if s.strip()]


class ServiceQueueItem(models.Model):
    class Priority(models.TextChoices):
        CRITICAL = 'CRITICAL', 'เร่งด่วนที่สุด'
        HIGH = 'HIGH', 'ด่วน'
        NORMAL = 'NORMAL', 'ปกติ'
        LOW = 'LOW', 'ไม่ด่วน'

    class TaskType(models.TextChoices):
        REPAIR = 'REPAIR', 'งานซ่อม'
        INSTALLATION = 'INSTALLATION', 'งานติดตั้ง'
        DELIVERY = 'DELIVERY', 'งานส่งของ'
        OTHER = 'OTHER', 'อื่นๆ'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'รอจัดคิว'
        SCHEDULED = 'SCHEDULED', 'จัดคิวแล้ว'
        IN_PROGRESS = 'IN_PROGRESS', 'กำลังดำเนินการ'
        COMPLETED = 'COMPLETED', 'เสร็จสิ้น'
        INCOMPLETE = 'INCOMPLETE', 'ไม่เสร็จ (ยกยอด)'

    title = models.CharField(max_length=255, verbose_name="หัวข้องาน")
    description = models.TextField(blank=True, verbose_name="รายละเอียด")
    task_type = models.CharField(max_length=20, choices=TaskType.choices, default=TaskType.OTHER, verbose_name="ประเภทงาน")
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL, verbose_name="ความเร่งด่วน")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="สถานะ")

    # Links
    project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True, blank=True, related_name='service_tasks', verbose_name="โครงการ")
    repair_job = models.ForeignKey('repairs.RepairJob', on_delete=models.SET_NULL, null=True, blank=True, related_name='service_tasks', verbose_name="งานซ่อม")

    # Schedule
    assigned_team = models.ForeignKey(ServiceTeam, on_delete=models.SET_NULL, null=True, blank=True, related_name='tasks', verbose_name="ทีมรับผิดชอบ")
    scheduled_date = models.DateField(null=True, blank=True, verbose_name="วันที่นัดหมาย")
    scheduled_time = models.TimeField(null=True, blank=True, verbose_name="เวลานัดหมาย")
    estimated_hours = models.DecimalField(max_digits=4, decimal_places=1, default=1.0, verbose_name="ชั่วโมงที่คาดว่าจะใช้")
    deadline = models.DateField(null=True, blank=True, verbose_name="วันกำหนดส่ง")

    # AI fields
    ai_urgency_reason = models.TextField(blank=True, verbose_name="เหตุผลความเร่งด่วน (AI)")

    # Completion
    completion_note = models.TextField(blank=True, verbose_name="บันทึกผลงาน")
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "คิวงานบริการ"
        verbose_name_plural = "คิวงานบริการ"
        ordering = ['priority', 'deadline', 'created_at']

    def __str__(self):
        return f"[{self.get_priority_display()}] {self.title}"

    def save(self, *args, **kwargs):
        # 1. Handle Completion
        if self.status == self.Status.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()
        elif self.status != self.Status.COMPLETED:
            self.completed_at = None

        super().save(*args, **kwargs)

    @property
    def is_overdue(self):
        if self.deadline and self.status not in ['COMPLETED']:
            return self.deadline < timezone.now().date()
        return False

    @property
    def days_until_deadline(self):
        if self.deadline:
            return (self.deadline - timezone.now().date()).days
        return None


class TeamMessage(models.Model):
    team = models.ForeignKey(ServiceTeam, on_delete=models.CASCADE, related_name='messages', verbose_name="ทีม")
    subject = models.CharField(max_length=255, verbose_name="หัวข้อ")
    content = models.TextField(verbose_name="เนื้อหา")
    related_tasks = models.ManyToManyField(ServiceQueueItem, blank=True, related_name='notifications', verbose_name="งานที่เกี่ยวข้อง")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ข้อความทีม"
        verbose_name_plural = "ข้อความทีม"
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.team.name}] {self.subject}"


# ===== Signals to automate Sync =====
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Project)
def auto_sync_to_queue(sender, instance, **kwargs):
    """Automatically run sync when a project is saved/updated."""
    try:
        from utils.ai_service_manager import sync_projects_to_queue
        sync_projects_to_queue()
    except Exception:
        pass


