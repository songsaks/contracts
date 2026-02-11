from django.db import models
from django.utils import timezone
from django.conf import settings
import datetime
import uuid

class Customer(models.Model):
    name = models.CharField(max_length=255)
    customer_code = models.CharField(max_length=50, unique=True, editable=False)
    contact_number = models.CharField(max_length=50)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.customer_code:
            today = timezone.now()
            date_str = today.strftime("C%Y%m%d")
            # Get last code for today
            last_customer = Customer.objects.filter(customer_code__startswith=date_str).order_by('customer_code').last()
            if last_customer:
                last_seq = int(last_customer.customer_code[-3:])
                new_seq = last_seq + 1
            else:
                new_seq = 1
            self.customer_code = f"{date_str}{new_seq:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.customer_code})"

class DeviceType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

class Device(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='devices')
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name='devices')
    model = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=100, blank=True)
    device_type = models.ForeignKey('DeviceType', on_delete=models.PROTECT, related_name='devices')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.brand} {self.model} - {self.customer.name}"

class Technician(models.Model):
    name = models.CharField(max_length=255)
    expertise = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return self.name

class RepairJob(models.Model):
    job_code = models.CharField(max_length=50, unique=True, editable=False)
    tracking_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    fix_id = models.CharField(max_length=50, blank=True, null=True, help_text="Manual Fix ID if needed") 
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='jobs')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_repair_jobs')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.job_code:
            today = timezone.now()
            date_str = today.strftime("J%Y%m%d")
            last_job = RepairJob.objects.filter(job_code__startswith=date_str).order_by('job_code').last()
            if last_job:
                last_seq = int(last_job.job_code[-3:])
                new_seq = last_seq + 1
            else:
                new_seq = 1
            self.job_code = f"{date_str}{new_seq:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.job_code

    def get_overall_status_bg_light(self):
        # Determine overall status based on items
        # Priority: FIXING > WAITING > RECEIVED > FINISHED (if all finished)
        items = self.items.all()
        if not items:
            return 'bg-gray-100'
        
        statuses = [item.status for item in items]
        
        if 'FIXING' in statuses:
            return 'bg-orange-50'
        if 'WAITING' in statuses:
            return 'bg-yellow-50'
        
        # If all are finished
        if all(s == 'FINISHED' for s in statuses):
             return 'bg-green-50'
             
        return 'bg-red-50'

class RepairItem(models.Model):
    STATUS_CHOICES = [
        ('RECEIVED', 'รับแจ้ง'),
        ('FIXING', 'กำลังซ่อม'),
        ('WAITING', 'รออะไหล่'),
        ('OUTSOURCE', 'ส่งซ่อมศูนย์/ภายนอก'),
        ('RECEIVED_FROM_VENDOR', 'รอตรวจรับกลับ'),
        ('FINISHED', 'ซ่อมเสร็จ'),
        ('COMPLETED', 'ส่งคืนแล้ว'),
    ]

    job = models.ForeignKey(RepairJob, on_delete=models.CASCADE, related_name='items')
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    technicians = models.ManyToManyField(Technician, blank=True)
    issue_description = models.TextField()
    accessories = models.CharField(max_length=255, blank=True, verbose_name="อุปกรณ์ที่นำมาด้วย", help_text="เช่น สายชาร์จ, กระเป๋า, เมาส์")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RECEIVED')
    status_note = models.TextField(blank=True, help_text="Reason for waiting or other status details")
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="ราคาประเมิน")
    final_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="ค่าใช้จ่ายจริง")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_repair_items')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_status_color(self):
        colors = {
            'RECEIVED': 'bg-red-500 text-white',
            'FIXING': 'bg-orange-500 text-white',
            'WAITING': 'bg-yellow-400 text-black',
            'OUTSOURCE': 'bg-purple-500 text-white',
            'RECEIVED_FROM_VENDOR': 'bg-blue-400 text-white',
            'FINISHED': 'bg-green-500 text-white',
        }
        return colors.get(self.status, 'bg-gray-500 text-white')

    def get_status_bg_light(self):
        colors = {
            'RECEIVED': 'bg-red-50',
            'FIXING': 'bg-orange-50',
            'WAITING': 'bg-yellow-50',
            'OUTSOURCE': 'bg-purple-50',
            'RECEIVED_FROM_VENDOR': 'bg-blue-50',
            'FINISHED': 'bg-green-50',
        }
        return colors.get(self.status, 'bg-gray-50')

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.pk:
            old_instance = RepairItem.objects.get(pk=self.pk)
            # If currently OUTSOURCE, only allow status change to RECEIVED_FROM_VENDOR
            if old_instance.status == 'OUTSOURCE':
                if self.status != 'RECEIVED_FROM_VENDOR' and self.status != 'OUTSOURCE':
                    raise ValidationError("สินค้าอยู่ในระหว่างส่งซ่อมภายนอก ไม่สามารถเปลี่ยนสถานะเป็นอย่างอื่นได้นอกจาก 'รอตรวจรับกลับ'")
                
                # Check for other field changes
                if (old_instance.issue_description != self.issue_description or 
                    old_instance.accessories != self.accessories or
                    old_instance.device != self.device or 
                    old_instance.price != self.price):
                    raise ValidationError("ไม่สามารถแก้ไขรายละเอียดสินค้าได้ในระหว่างที่ส่งซ่อมภายนอก")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.device} - {self.get_status_display()}"

class OutsourceLog(models.Model):
    repair_item = models.OneToOneField(RepairItem, on_delete=models.CASCADE, related_name='outsource_details')
    vendor_name = models.CharField(max_length=255, verbose_name="ชื่อร้าน/ศูนย์ที่ส่งซ่อม")
    tracking_no = models.CharField(max_length=100, blank=True, verbose_name="เลข Tracking/เลขรับงานศูนย์")
    sent_date = models.DateField(default=timezone.now, verbose_name="วันที่ส่ง")
    expected_return = models.DateField(null=True, blank=True, verbose_name="วันที่คาดว่าจะได้รับ")
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="ค่าซ่อมจากศูนย์")
    note = models.TextField(blank=True, verbose_name="หมายเหตุ")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Outsource: {self.repair_item.job.job_code} to {self.vendor_name}"

class RepairStatusHistory(models.Model):
    repair_item = models.ForeignKey(RepairItem, on_delete=models.CASCADE, related_name='status_history')
    status = models.CharField(max_length=20, choices=RepairItem.STATUS_CHOICES)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    def __str__(self):
        return f"{self.repair_item.job.job_code} -> {self.status} at {self.changed_at}"

    class Meta:
        ordering = ['-changed_at']
        verbose_name_plural = "Repair Status Histories"
