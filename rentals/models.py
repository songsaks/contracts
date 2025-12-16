from django.db import models
from django.utils import timezone
from decimal import Decimal

class Asset(models.Model):
    STATUS_CHOICES = [
        ('AVAILABLE', 'Available'),
        ('MAINTENANCE', 'Maintenance'),
        ('RENTED', 'Rented'),
    ]
    
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AVAILABLE')
    monthly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

class Tenant(models.Model):
    agency_name = models.CharField(max_length=100, help_text="Company or Agency Name")
    contact_person = models.CharField(max_length=100, help_text="Name of the contact person")
    document_id = models.CharField(max_length=50, blank=True, help_text="ID Card or Passport Number")
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.agency_name} ({self.contact_person})"

class Contract(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]
    PAYMENT_FREQUENCY_CHOICES = [
        ('MONTHLY', 'Every Month'),
        ('QUARTERLY', 'Every 3 Months'),
        ('SEMI_ANNUAL', 'Every 6 Months'),
        ('ANNUAL', 'Every Year'),
        ('ONE_TIME', 'One Time Payment'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='contracts')
    assets = models.ManyToManyField(Asset, related_name='contracts')
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField()
    
    # Financials
    payment_frequency = models.CharField(max_length=20, choices=PAYMENT_FREQUENCY_CHOICES, default='MONTHLY')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Total calculated rent")
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), help_text="Amount paid so far")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def remaining_amount(self):
        return self.total_amount - self.paid_amount

    @property
    def contract_number(self):
        return f"{self.created_at.strftime('%Y%m%d')}-{self.id:04d}"

    def __str__(self):
        return f"Contract {self.contract_number} - {self.tenant}"
