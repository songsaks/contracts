from django.contrib import admin
from .models import Customer, Device, Technician, RepairJob, RepairItem, DeviceType

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['customer_code', 'name', 'contact_number', 'created_at']
    search_fields = ['name', 'customer_code', 'contact_number']
    readonly_fields = ['customer_code', 'created_at']
    list_filter = ['created_at']

@admin.register(DeviceType)
class DeviceTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['brand', 'model', 'serial_number', 'device_type', 'customer']
    search_fields = ['brand', 'model', 'serial_number']
    list_filter = ['device_type', 'brand']
    raw_id_fields = ['customer']

@admin.register(Technician)
class TechnicianAdmin(admin.ModelAdmin):
    list_display = ['name', 'expertise']
    search_fields = ['name', 'expertise']

@admin.register(RepairJob)
class RepairJobAdmin(admin.ModelAdmin):
    list_display = ['job_code', 'customer', 'fix_id', 'created_at']
    search_fields = ['job_code', 'fix_id', 'customer__name']
    readonly_fields = ['job_code', 'created_at']
    list_filter = ['created_at']
    raw_id_fields = ['customer']

@admin.register(RepairItem)
class RepairItemAdmin(admin.ModelAdmin):
    list_display = ['job', 'device', 'status', 'price', 'created_at']
    search_fields = ['job__job_code', 'device__brand', 'device__model', 'issue_description']
    list_filter = ['status', 'created_at']
    raw_id_fields = ['job', 'device']
    filter_horizontal = ['technicians']
    readonly_fields = ['created_at']
