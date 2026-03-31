from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings
from decimal import Decimal

# ====== โมเดลหลักของระบบบริหารโครงการ (Project Management System) ======
# ไฟล์นี้ประกอบด้วยโมเดลทั้งหมดสำหรับจัดการ:
#   - ลูกค้า (Customer) และแผน SLA
#   - ซัพพลายเออร์ (Supplier) และเจ้าของโครงการ (ProjectOwner)
#   - โครงการ (Project) พร้อมระบบสถานะแบบ Dynamic (JobStatus)
#   - รายการสินค้า/บริการ (ProductItem)
#   - คิวงานบริการ (ServiceQueueItem) สำหรับ AI Queue
#   - การแจ้งเตือนผู้รับผิดชอบ (UserNotification)
#   - ประวัติการเปลี่ยนสถานะ (ProjectStatusLog, RequestStatusLog)

# ====== SLA (Service Level Agreement) ======
class SLAPlan(models.Model):
    """
    แผนระดับการให้บริการ (Service Level Agreement)
    กำหนดเวลาตอบกลับ (Response Time) และเวลาแก้ไขปัญหา (Resolution Time)
    ที่ลูกค้าแต่ละรายได้รับตามข้อตกลง
    """
    name = models.CharField(max_length=100, verbose_name="ชื่อแพ็กเกจ SLA")
    response_time_hours = models.PositiveIntegerField(default=4, verbose_name="เวลาตอบกลับ (ชม.)")
    resolution_time_hours = models.PositiveIntegerField(default=24, verbose_name="เวลาแก้ไข (ชม.)")
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True, verbose_name="รายละเอียดเงื่อนไข")

    class Meta:
        verbose_name = "แผน SLA"
        verbose_name_plural = "แผน SLA"

    # แสดงชื่อแผน SLA พร้อมรายละเอียดเวลาการทำงาน
    def __str__(self):
        return f"{self.name} (Res: {self.response_time_hours}h / Fix: {self.resolution_time_hours}h)"

# ====== ลูกค้า (Customer) ======
class Customer(models.Model):
    """
    ข้อมูลลูกค้าของบริษัท รองรับทั้งบุคคลทั่วไปและองค์กร
    มีข้อมูล CRM เพิ่มเติม เช่น กลุ่มลูกค้า (Segment), ช่องทางที่รู้จัก (Source)
    และเชื่อมต่อกับแผน SLA เพื่อกำหนดระดับการให้บริการ
    """
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

# ====== ซัพพลายเออร์ (Supplier) ======
class Supplier(models.Model):
    """
    ข้อมูลซัพพลายเออร์ / ร้านค้าที่ใช้จัดซื้อสินค้าสำหรับโครงการ
    เชื่อมโยงกับ ProductItem เพื่อระบุแหล่งที่มาของสินค้า
    """
    name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

# ====== เจ้าของโครงการ (ProjectOwner) ======
class ProjectOwner(models.Model):
    """
    พนักงานหรือตัวแทนขายที่รับผิดชอบโครงการ
    ใช้สำหรับติดตามยอดขายและประเมินผลงานรายบุคคล
    """
    name = models.CharField(max_length=255, verbose_name="ชื่อเจ้าของโครงการ")
    email = models.EmailField(blank=True, verbose_name="อีเมล")
    phone = models.CharField(max_length=50, blank=True, verbose_name="เบอร์โทรศัพท์")
    position = models.CharField(max_length=255, blank=True, verbose_name="ตำแหน่ง")

    def __str__(self):
        return self.name

# ====== โครงการ (Project) — โมเดลหลักของระบบ ======
class Project(models.Model):
    """
    โมเดลหลักของระบบ PMS แทนงานทุกประเภท ได้แก่:
      - PROJECT: โครงการติดตั้งขนาดใหญ่
      - SERVICE: งานบริการขาย
      - REPAIR:  งานแจ้งซ่อม On-site
      - RENTAL:  งานเช่าอุปกรณ์

    มีระบบสถานะแบบ Dynamic (JobStatus) ที่ผู้ดูแลระบบสามารถปรับแต่งได้
    รองรับการล็อกสถานะ (Queue Lock) เมื่อมีงานใน AI Service Queue อยู่
    และบันทึกประวัติการเปลี่ยนสถานะ (ProjectStatusLog) ทุกครั้ง
    """
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'รวบรวม'
        SOURCING = 'SOURCING', 'จัดหา'
        SUPPLIER_CHECK = 'SUPPLIER_CHECK', 'เช็คราคา'
        QUOTED = 'QUOTED', 'เสนอราคา'
        CONTRACTED = 'CONTRACTED', 'ทำสัญญา'
        ORDERING = 'ORDERING', 'สั่งซื้อ'
        RECEIVED_QC = 'RECEIVED_QC', 'รับของ/QC'
        REPAIRING = 'REPAIRING', 'ซ่อม'
        REQUESTING_ACTION = 'REQUESTING_ACTION', 'ขอดำเนินการ'
        INSTALLATION = 'INSTALLATION', 'คิว'
        DELIVERY = 'DELIVERY', 'คิว'
        PREPARING_DOCS = 'PREPARING_DOCS', 'เตรียมเอกสารใบส่งสินค้า'

        ACCEPTED = 'ACCEPTED', 'ตรวจรับ'
        BILLING = 'BILLING', 'วางบิล'
        WAITING_FOR_SALE_KEY = 'WAITING_FOR_SALE_KEY', 'รอคีย์ขาย'
        RENTING = 'RENTING', 'เช่า'
        CLOSED = 'CLOSED', 'ปิดจบ'
        CANCELLED = 'CANCELLED', 'ยกเลิก'

    class JobType(models.TextChoices):
        PROJECT = 'PROJECT', 'โครงการ (Project)'
        SERVICE = 'SERVICE', 'งานบริการขาย (Sales Service)'
        REPAIR = 'REPAIR', 'งานแจ้งซ่อม (Repair Service)'
        RENTAL = 'RENTAL', 'งานเช่า (Rental Service)'

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
    remarks = models.TextField(blank=True, verbose_name="หมายเหตุ")
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

    # เก็บค่าสถานะเดิมไว้ตรวจสอบการเปลี่ยนแปลง
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._old_status = self.status

    def __str__(self):
        return self.name

    # จัดการตรรกะการบันทึกข้อมูลโครงการ รวมถึง SLA, การปิดงาน, การล็อกสถานะ AI Queue และการแจ้งเตือน
    def save(self, *args, **kwargs):
        # 1. กำหนดเส้นตาย SLA หากลูกค้ามีแผน SLA และยังไม่มีข้อมูล
        if self.customer.sla_plan and not self.sla_response_deadline:
            now = timezone.now()
            self.sla_response_deadline = now + timezone.timedelta(hours=self.customer.sla_plan.response_time_hours)
            self.sla_resolution_deadline = now + timezone.timedelta(hours=self.customer.sla_plan.resolution_time_hours)

        # 2. จัดการข้อมูลสถานะการปิดงาน
        if self.status in [self.Status.CLOSED, self.Status.CANCELLED] and not self.closed_at:
            self.closed_at = timezone.now()
        elif self.status not in [self.Status.CLOSED, self.Status.CANCELLED]:
            self.closed_at = None
            
        is_new = self.pk is None
        old_status = getattr(self, '_old_status', self.status)

        # 3. กลไกการล็อกสถานะสำหรับ AI Queue (ป้องกันการเปลี่ยนสถานะหากงานในคิวยังไม่เสร็จ)
        if not is_new and old_status != self.status:
            is_queue_status = False
            if self.job_type == self.JobType.PROJECT and old_status == self.Status.INSTALLATION:
                is_queue_status = True
            elif self.job_type in [self.JobType.SERVICE, self.JobType.REPAIR] and old_status == self.Status.DELIVERY:
                is_queue_status = True

            if is_queue_status and not getattr(self, '_changed_by_ai', False):
                active_task = self.service_tasks.filter(
                    status__in=['PENDING', 'SCHEDULED', 'IN_PROGRESS', 'INCOMPLETE']
                ).exists()
                if active_task:
                    raise ValidationError(f"สถานะ '{self.get_status_display()}' ถูกล็อกจนกว่างานใน AI Queue จะเสร็จสิ้นหรือยกเลิก")

        super().save(*args, **kwargs)
        self._old_status = self.status
        
        # บันทึกประวัติการเปลี่ยนสถานะ (Status Log)
        try:
            user = getattr(self, '_changed_by_user', None)
                
            if not is_new and self.status != old_status:
                ProjectStatusLog.objects.create(
                    project=self,
                    old_status=old_status,
                    new_status=self.status,
                    changed_by=user
                )
            elif is_new:
                ProjectStatusLog.objects.create(
                    project=self,
                    old_status='NEW',
                    new_status=self.status,
                    changed_by=user
                )

            # ตรรกะการส่งการแจ้งเตือนไปยังผู้รับผิดชอบเมื่อมีการเปลี่ยนสถานะ
            if is_new or self.status != old_status:
                try:
                    status_label = self.status
                    js = JobStatus.objects.filter(job_type=self.job_type, status_key=self.status, is_active=True).first()
                    if js:
                        status_label = js.label

                    # รวบรวมรายชื่อผู้รับผิดชอบ (เป้าหมาย)
                    target_users = []
                    
                    # 1. ค้นหาผู้รับผิดชอบเฉพาะโครงการ (ลำดับแรก)
                    ps_assignment = ProjectStatusAssignment.objects.filter(project=self, status_key=self.status).first()
                    if ps_assignment and ps_assignment.responsible_users.exists():
                        target_users = list(ps_assignment.responsible_users.all())
                    
                    # 2. ค้นหาผู้รับผิดชอบตามประเภทงานเริ่มต้น (ลำดับที่สอง)
                    elif js and hasattr(js, 'assignment') and js.assignment.responsible_users.exists():
                        target_users = list(js.assignment.responsible_users.all())

                    for target_user in target_users:
                        UserNotification.objects.create(
                            user=target_user,
                            project=self,
                            subject=f"🔔 ความคืบหน้าโครงการ: {self.name}",
                            content=f"งาน '{self.name}' ({self.get_job_type_display()}) เปลี่ยนสถานะเป็น '{status_label}' ซึ่งคุณเป็นผู้รับผิดชอบ"
                        )
                except Exception as e:
                    print(f"Notification Error: {e}")
        except Exception:
            pass
            
        self._old_status = self.status

    # คืนค่ามูลค่ารวมของโครงการ (ผลรวมของยอดขายแต่ละรายการ)
    @property
    def total_value(self):
        return sum(item.total_price for item in self.items.all())

    # คืนค่าชื่อสถานะที่แสดงผล โดยดึงจากฐานข้อมูล (dynamic) หรือค่าทางเลือกที่กำหนดไว้
    @property
    def get_job_status_display(self):
        # ค้นหาจากตาราง JobStatus ที่ตั้งค่าไว้
        try:
            dynamic_status = JobStatus.objects.filter(
                job_type=self.job_type, 
                status_key=self.status,
                is_active=True
            ).first()
            if dynamic_status:
                return dynamic_status.label
        except Exception:
            pass

        # หากไม่มีในฐานข้อมูล ให้ใช้ค่า Mapping เริ่มต้นของแต่ละประเภทงาน
        if self.job_type == self.JobType.REPAIR:
            mapping = {
                self.Status.DRAFT: 'รวบรวม',
                self.Status.QUOTED: 'เสนอราคา',
                self.Status.ORDERING: 'สั่งซื้อ',
                self.Status.RECEIVED_QC: 'รับของ/QC',
                self.Status.REPAIRING: 'ซ่อม',
                self.Status.DELIVERY: 'คิว',
                self.Status.WAITING_FOR_SALE_KEY: 'รอคีย์ขาย',
                self.Status.CLOSED: 'ปิดจบ',
                self.Status.CANCELLED: 'ยกเลิก',
            }
            return mapping.get(self.status, self.get_status_display())
        
        elif self.job_type == self.JobType.SERVICE:
            mapping = {
                self.Status.DRAFT: 'รวบรวม',
                self.Status.QUOTED: 'เสนอราคา',
                self.Status.ORDERING: 'สั่งซื้อ',
                self.Status.RECEIVED_QC: 'รับของ/QC',
                self.Status.DELIVERY: 'คิว',
                self.Status.WAITING_FOR_SALE_KEY: 'รอคีย์ขาย',
                self.Status.CLOSED: 'ปิดจบ',
                self.Status.CANCELLED: 'ยกเลิก',
            }
            return mapping.get(self.status, self.get_status_display())
        
        elif self.job_type == self.JobType.PROJECT:
             mapping = {
                self.Status.DRAFT: 'รวบรวม',
                self.Status.QUOTED: 'เสนอราคา',
                self.Status.CONTRACTED: 'ทำสัญญา',
                self.Status.ORDERING: 'สั่งซื้อ',
                self.Status.RECEIVED_QC: 'รับของ/QC',
                self.Status.REQUESTING_ACTION: 'ขอดำเนินการ',
                self.Status.INSTALLATION: 'คิว',
                self.Status.WAITING_FOR_SALE_KEY: 'รอคีย์ขาย',
                self.Status.CLOSED: 'ปิดจบ',
                self.Status.CANCELLED: 'ยกเลิก',
            }
             return mapping.get(self.status, self.get_status_display())

        elif self.job_type == self.JobType.RENTAL:
            mapping = {
                self.Status.SOURCING: 'จัดหา',
                self.Status.CONTRACTED: 'ทำสัญญา',
                self.Status.RENTING: 'เช่า',
                self.Status.CLOSED: 'ปิดจบ',
            }
            return mapping.get(self.status, self.get_status_display())
            
        return self.get_status_display()

    # ค้นหาสถานะถัดไปของโครงการตามลำดับ (sort_order) ที่ตั้งไว้ใน JobStatus
    def get_next_status(self):
        """
        ค้นหาสถานะลำดับถัดไปสำหรับประเภทงานนี้
        """
        try:
            current_job_status = JobStatus.objects.filter(
                job_type=self.job_type, 
                status_key=self.status,
                is_active=True
            ).first()
            
            if not current_job_status:
                return None
                
            next_job_status = JobStatus.objects.filter(
                job_type=self.job_type,
                is_active=True,
                sort_order__gt=current_job_status.sort_order
            ).order_by('sort_order').first()
            
            return next_job_status
        except Exception:
            return None
...

class JobStatus(models.Model):
    job_type = models.CharField(max_length=20, choices=Project.JobType.choices)
    status_key = models.CharField(max_length=50) # DRAFT, SOURCING, etc.
    label = models.CharField(max_length=100)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['job_type', 'sort_order']
        verbose_name = "สถานะงาน (Dynamic)"
        verbose_name_plural = "สถานะงาน (Dynamic)"
        unique_together = ['job_type', 'status_key']

    # คืนค่าตัวเลือกสถานะงานสำหรับ Job Type ที่ระบุ โดยดึงจากฐานข้อมูล
    @staticmethod
    def get_choices(job_type):
        try:
            qs = JobStatus.objects.filter(job_type=job_type, is_active=True).order_by('sort_order')
            if qs.exists():
                return [(s.status_key, s.label) for s in qs]
        except Exception:
            pass
        return None

    # แสดงชื่อประเภทงานและชื่อสถานะ
    def __str__(self):
        jt_display = dict(Project.JobType.choices).get(self.job_type, self.job_type)
        return f"[{jt_display}] {self.status_key} -> {self.label}"

class JobStatusAssignment(models.Model):
    job_status = models.OneToOneField(JobStatus, on_delete=models.CASCADE, related_name='assignment', verbose_name="สถานะงาน")
    responsible_users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, verbose_name="ผู้รับผิดชอบ (ดึงจากระบบ)")
    
    class Meta:
        verbose_name = "ผู้รับผิดชอบตามสถานะ"
        verbose_name_plural = "ผู้รับผิดชอบตามสถานะ"

    # แสดงชื่อสถานะโครงการและจำนวนผู้รับผิดชอบ
    def __str__(self):
        users_count = self.responsible_users.count()
        return f"{self.job_status} -> {users_count} Users"

class ProjectStatusAssignment(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='status_assignments', verbose_name="โครงการ")
    status_key = models.CharField(max_length=50, verbose_name="รหัสสถานะ")
    responsible_users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, verbose_name="ผู้รับผิดชอบ")
    
    class Meta:
        verbose_name = "ผู้รับผิดชอบงานตามโครงการ"
        verbose_name_plural = "ผู้รับผิดชอบงานตามโครงการ"
        unique_together = ['project', 'status_key']

    # แสดงชื่อโครงการและจำนวนผู้รับผิดชอบในแต่ละสถานะ
    def __str__(self):
        users_count = self.responsible_users.count()
        return f"{self.project.name} [{self.status_key}] -> {users_count} Users"

# ====== รายการสินค้า/บริการในโครงการ (ProductItem) ======
class ProductItem(models.Model):
    """
    รายการสินค้าหรือบริการที่อยู่ภายใต้โครงการ
    ใช้คำนวณยอดขาย ต้นทุน และกำไรเบื้องต้น (Margin)
    ประเภท PRODUCT = สินค้าจริง, SERVICE = ค่าแรง/บริการ
    """
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

    # แสดงชื่อรายการสินค้า
    def __str__(self):
        return self.name

    # คำนวณราคารวม (จำนวน x ราคาขายตัวหน่วย)
    @property
    def total_price(self):
        return self.quantity * self.unit_price

    # คำนวณต้นทุนรวม (จำนวน x ต้นทุนต่อหน่วย)
    @property
    def total_cost(self):
        return self.quantity * self.unit_cost
        
    # คำนวณกำไรเบื้องต้น
    @property
    def margin(self):
        return self.total_price - self.total_cost

# ====== ความต้องการลูกค้า / Lead ======
class CustomerRequirement(models.Model):
    """
    บันทึกความต้องการเบื้องต้นของลูกค้า (Lead) ที่ยังไม่ได้สร้างเป็นโครงการ
    รองรับการบันทึกจากเสียง (Voice) หรือข้อความ (Text)
    เมื่อ is_converted=True หมายความว่าถูกแปลงเป็นโครงการแล้ว
    """
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

    # แสดงรหัสความต้องการและวันที่สร้าง
    def __str__(self):
        return f"Requirement {self.pk} - {self.created_at.strftime('%d/%m/%Y')}"


# ====== คำขอจากลูกค้า (CustomerRequest) ======
class CustomerRequest(models.Model):
    """
    คำขอพิเศษจากลูกค้าที่ไม่ได้เป็นโครงการใหม่ เช่น ขอเอกสาร ขอข้อมูลเพิ่มเติม
    มีระบบสถานะตั้งแต่ RECEIVED จนถึง COMPLETED และบันทึกประวัติสถานะ
    """
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
    remarks = models.TextField(blank=True, verbose_name="หมายเหตุ")
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

    # แสดงหัวข้อคำขอและชื่อลูกค้า
    def __str__(self):
        return f"{self.title} - {self.customer.name}"

    # บันทึกข้อมูลคำขอ พร้อมเก็บประวัติการเปลี่ยนสถานะ
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_status = None
        if not is_new:
            try:
                old_status = CustomerRequest.objects.get(pk=self.pk).status
            except:
                pass
        
        super().save(*args, **kwargs)
        
        # บันทึก log เมื่อมีการเปลี่ยนสถานะ
        if is_new or (old_status != self.status):
            user = getattr(self, '_changed_by_user', None)
            RequestStatusLog.objects.create(
                request=self,
                old_status=old_status or 'NEW',
                new_status=self.status,
                changed_by=user
            )


# กำหนดเส้นทางการเก็บไฟล์แนบแยกตามประเภท (Project, Requirement, Request)
def project_file_upload_path(instance, filename):
    """ที่เก็บไฟล์: pms/files/<project_id หรือ req_id หรือ cust_req_id>/filename"""
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

    # แสดงชื่อไฟล์เดิม
    def __str__(self):
        return self.original_name

    # ตรวจสอบว่าเป็นไฟล์รูปภาพหรือไม่
    @property
    def is_image(self):
        ext = self.original_name.lower().rsplit('.', 1)[-1] if '.' in self.original_name else ''
        return ext in ('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'heic', 'heif')

    # คืนค่าส่วนขยายของไฟล์ (Extension)
    @property
    def file_extension(self):
        return self.original_name.lower().rsplit('.', 1)[-1] if '.' in self.original_name else ''

    # คำนวณและแสดงขนาดไฟล์ในรูปแบบที่อ่านง่าย (B, KB, MB)
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


# ===== Project Status Log =====
class ProjectStatusLog(models.Model):
    project = models.ForeignKey('Project', on_delete=models.CASCADE, related_name='status_logs', verbose_name="โครงการ")
    old_status = models.CharField(max_length=20, verbose_name="สถานะเดิม")
    new_status = models.CharField(max_length=20, verbose_name="สถานะใหม่")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="ผู้ทำการเปลี่ยน")
    changed_at = models.DateTimeField(auto_now_add=True, verbose_name="เวลาที่เปลี่ยน")

    class Meta:
        verbose_name = "ประวัติการเปลี่ยนสถานะโครงการ"
        verbose_name_plural = "ประวัติการเปลี่ยนสถานะโครงการ"
        ordering = ['-changed_at']

    # แสดงประวัติการเปลี่ยนสถานะ
    def __str__(self):
        return f"{self.project.name}: {self.old_status} -> {self.new_status}"
        
    @property
    def get_old_status_display(self):
        try:
            from .models import JobStatus
            dynamic_status = JobStatus.objects.filter(
                job_type=self.project.job_type, 
                status_key=self.old_status,
                is_active=True
            ).first()
            if dynamic_status:
                return dynamic_status.label
        except Exception:
            pass
        return dict(Project.Status.choices).get(self.old_status, self.old_status)
        
    @property
    def get_new_status_display(self):
        try:
            from .models import JobStatus
            dynamic_status = JobStatus.objects.filter(
                job_type=self.project.job_type, 
                status_key=self.new_status,
                is_active=True
            ).first()
            if dynamic_status:
                return dynamic_status.label
        except Exception:
            pass
        return dict(Project.Status.choices).get(self.new_status, self.new_status)


# ===== Request Status Log =====
class RequestStatusLog(models.Model):
    request = models.ForeignKey('CustomerRequest', on_delete=models.CASCADE, related_name='status_logs', verbose_name="คำขอ")
    old_status = models.CharField(max_length=20, verbose_name="สถานะเดิม")
    new_status = models.CharField(max_length=20, verbose_name="สถานะใหม่")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="ผู้ทำการเปลี่ยน")
    changed_at = models.DateTimeField(auto_now_add=True, verbose_name="เวลาที่เปลี่ยน")

    class Meta:
        verbose_name = "ประวัติคำขอ"
        verbose_name_plural = "ประวัติคำขอ"
        ordering = ['-changed_at']

    def __str__(self):
        return f"Req {self.request.id}: {self.old_status} -> {self.new_status}"
    
    @property
    def get_old_status_display(self):
        if self.old_status == 'NEW': return 'สร้างใหม่'
        return dict(CustomerRequest.Status.choices).get(self.old_status, self.old_status)

    @property
    def get_new_status_display(self):
        return dict(CustomerRequest.Status.choices).get(self.new_status, self.new_status)


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

    google_chat_webhook = models.URLField(blank=True, verbose_name="Google Chat Webhook", help_text="URL สำหรับส่งแจ้งเตือนเข้าช่อง Google Chat")
    line_token = models.CharField(max_length=255, blank=True, verbose_name="LINE Token", help_text="LINE Notify Token สำหรับส่งแจ้งเตือน")

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
        CANCELLED = 'CANCELLED', 'ยกเลิก'

    title = models.CharField(max_length=255, verbose_name="หัวข้องาน")
    description = models.TextField(blank=True, verbose_name="รายละเอียด")
    remarks = models.TextField(blank=True, verbose_name="หมายเหตุ")
    task_type = models.CharField(max_length=20, choices=TaskType.choices, default=TaskType.OTHER, verbose_name="ประเภทงาน")
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL, verbose_name="ความเร่งด่วน")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, verbose_name="สถานะ")

    # Links
    project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True, blank=True, related_name='service_tasks', verbose_name="โครงการ")
    repair_job = models.ForeignKey('repairs.RepairJob', on_delete=models.SET_NULL, null=True, blank=True, related_name='service_tasks', verbose_name="งานซ่อม")

    # Schedule
    assigned_teams = models.ManyToManyField(ServiceTeam, blank=True, related_name='tasks', verbose_name="ทีมรับผิดชอบ")
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
        old_status = None
        if self.pk:
            try:
                old_status = ServiceQueueItem.objects.get(pk=self.pk).status
            except ServiceQueueItem.DoesNotExist:
                pass

        if self.status == self.Status.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()
        elif self.status != self.Status.COMPLETED:
            self.completed_at = None

        super().save(*args, **kwargs)

        if self.project and self.status in [self.Status.COMPLETED, self.Status.CANCELLED] and old_status != self.status:
            proj = self.project
            # Only advance if we are currently in the Queue status
            can_advance = False
            next_status = None

            if proj.job_type == Project.JobType.PROJECT and proj.status == Project.Status.INSTALLATION:
                can_advance = True
                next_status = Project.Status.WAITING_FOR_SALE_KEY
            elif proj.job_type == Project.JobType.SERVICE and proj.status == Project.Status.DELIVERY:
                can_advance = True
                next_status = Project.Status.WAITING_FOR_SALE_KEY
            elif proj.job_type == Project.JobType.REPAIR and proj.status == Project.Status.DELIVERY:
                can_advance = True
                next_status = Project.Status.WAITING_FOR_SALE_KEY

            if can_advance and next_status:
                proj.status = next_status
                proj._changed_by_ai = True # Mark to bypass lock if needed
                proj.save()

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

class UserNotification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pms_notifications', verbose_name="ผู้รับ")
    project = models.ForeignKey('Project', on_delete=models.CASCADE, related_name='notifications', verbose_name="งานที่เกี่ยวข้อง")
    subject = models.CharField(max_length=255, verbose_name="หัวข้อ")
    content = models.TextField(verbose_name="เนื้อหา")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "แจ้งเตือนรายบุคคล"
        verbose_name_plural = "แจ้งเตือนรายบุคคล"
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.user.username}] {self.subject}"


# ====== GPS Tracking สำหรับช่างภาคสนาม (Technician GPS Log) ======
class TechnicianGPSLog(models.Model):
    """
    บันทึกพิกัด GPS ของช่างเทคนิคที่ออกปฏิบัติงานนอกสถานที่
    ข้อมูลนี้ใช้สร้างรายงานเส้นทางการทำงานประจำวัน
    """
    class CheckType(models.TextChoices):
        GO_WORK     = 'GO_WORK',     'ออกทำงาน (Go Work)'
        ON_SITE     = 'ON_SITE',     'เริ่มงาน (On-site)'
        CHECK_OUT   = 'CHECK_OUT',   'เสร็จงาน (Check-out)'
        BACK_OFFICE = 'BACK_OFFICE', 'กลับที่ทำงาน (Back to Office)'
        TRAVEL      = 'TRAVEL',      'กำลังเดินทาง (Auto-Track)'
        CHECK_IN    = 'CHECK_IN',    'เริ่มงาน (Check-in)'  # legacy

    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                    related_name='gps_logs', verbose_name="ช่าง")
    queue_item  = models.ForeignKey('ServiceQueueItem', on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='gps_logs',
                                    verbose_name="งานที่เกี่ยวข้อง")
    check_type  = models.CharField(max_length=20, choices=CheckType.choices,
                                   default=CheckType.ON_SITE, verbose_name="ประเภทการเช็คอิน")
    latitude    = models.DecimalField(max_digits=12, decimal_places=9, verbose_name="ละติจูด")
    longitude   = models.DecimalField(max_digits=12, decimal_places=9, verbose_name="ลองจิจูด")
    location_name = models.CharField(max_length=255, blank=True, verbose_name="ชื่อสถานที่")
    notes       = models.TextField(blank=True, verbose_name="หมายเหตุ")
    timestamp   = models.DateTimeField(auto_now_add=True, verbose_name="เวลาเช็คอิน")

    class Meta:
        verbose_name = "GPS Log ช่าง"
        verbose_name_plural = "GPS Logs ช่าง"
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.user.username} | {self.get_check_type_display()} | {self.timestamp.strftime('%d/%m/%Y %H:%M')}"


class CustomerSatisfaction(models.Model):
    """
    ผลประเมินความพอใจของลูกค้าหลังช่างเช็คเอาท์ (Check-out)
    บันทึกผ่านหน้าจอที่แสดงให้ลูกค้ากดประเมินก่อนช่างออกจากไซต์
    """
    class Rating(models.TextChoices):
        VERY_SATISFIED = 'VERY_SATISFIED', 'พอใจมาก'
        SATISFIED      = 'SATISFIED',      'พอใจ'
        NOT_SATISFIED  = 'NOT_SATISFIED',  'ไม่พอใจ'

    gps_log        = models.OneToOneField(
        TechnicianGPSLog, on_delete=models.CASCADE,
        related_name='satisfaction', verbose_name="GPS Log (Check-out)"
    )
    rating         = models.CharField(
        max_length=20, choices=Rating.choices, verbose_name="ความพอใจ"
    )
    customer_name  = models.CharField(max_length=100, blank=True, verbose_name="ชื่อลูกค้า")
    customer_phone = models.CharField(max_length=20,  blank=True, verbose_name="เบอร์โทร")
    created_at     = models.DateTimeField(auto_now_add=True, verbose_name="เวลาประเมิน")

    class Meta:
        verbose_name = "ประเมินความพอใจลูกค้า"
        verbose_name_plural = "ประเมินความพอใจลูกค้า"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.gps_log.user.username} | {self.get_rating_display()} | {self.created_at.strftime('%d/%m/%Y %H:%M')}"


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


