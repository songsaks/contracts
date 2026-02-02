from django.db import models
from django.utils import timezone
import datetime

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
    fix_id = models.CharField(max_length=50, blank=True, null=True, help_text="Manual Fix ID if needed") 
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='jobs')
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
        ('RECEIVED', 'Received'),
        ('FIXING', 'Fixing'),
        ('WAITING', 'Waiting'),
        ('FINISHED', 'Finished'),
    ]

    job = models.ForeignKey(RepairJob, on_delete=models.CASCADE, related_name='items')
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    technicians = models.ManyToManyField(Technician, blank=True)
    issue_description = models.TextField()
    accessories = models.CharField(max_length=255, blank=True, verbose_name="อุปกรณ์ที่นำมาด้วย", help_text="เช่น สายชาร์จ, กระเป๋า, เมาส์")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='RECEIVED')
    status_note = models.TextField(blank=True, help_text="Reason for waiting or other status details")
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_status_color(self):
        colors = {
            'RECEIVED': 'bg-red-500 text-white',
            'FIXING': 'bg-orange-500 text-white',
            'WAITING': 'bg-yellow-400 text-black',
            'FINISHED': 'bg-green-500 text-white',
        }
        return colors.get(self.status, 'bg-gray-500 text-white')

    def get_status_bg_light(self):
        colors = {
            'RECEIVED': 'bg-red-50',
            'FIXING': 'bg-orange-50',
            'WAITING': 'bg-yellow-50',
            'FINISHED': 'bg-green-50',
        }
        return colors.get(self.status, 'bg-gray-50')

    def __str__(self):
        return f"{self.device} - {self.get_status_display()}"
