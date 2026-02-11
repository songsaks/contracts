from django.contrib import admin
from .models import Customer, Device, Technician, RepairJob, RepairItem, DeviceType, Brand, OutsourceLog, RepairStatusHistory
from django.contrib import messages

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

@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at']
    search_fields = ['name']

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
    list_display = ['job_code', 'customer', 'fix_id', 'created_by', 'created_at']
    search_fields = ['job_code', 'fix_id', 'customer__name', 'created_by__username']
    readonly_fields = ['job_code', 'created_by', 'created_at']
    list_filter = ['created_at', 'created_by']
    raw_id_fields = ['customer']

@admin.register(OutsourceLog)
class OutsourceLogAdmin(admin.ModelAdmin):
    list_display = ['repair_item', 'vendor_name', 'tracking_no', 'sent_date', 'expected_return', 'cost']
    search_fields = ['repair_item__job__job_code', 'vendor_name', 'tracking_no']
    raw_id_fields = ['repair_item']

class OutsourceLogInline(admin.StackedInline):
    model = OutsourceLog
    extra = 0

@admin.register(RepairItem)
class RepairItemAdmin(admin.ModelAdmin):
    list_display = ['job', 'device', 'status', 'price', 'created_by', 'created_at']
    search_fields = ['job__job_code', 'device__brand', 'device__model', 'issue_description', 'created_by__username']
    list_filter = ['status', 'created_at', 'created_by']
    raw_id_fields = ['job', 'device']
    filter_horizontal = ['technicians']
    readonly_fields = ['created_by', 'created_at', 'updated_at']
    inlines = [OutsourceLogInline]
    actions = ['receive_from_vendor']

    def receive_from_vendor(self, request, queryset):
        count = 0
        for item in queryset:
            if item.status == 'OUTSOURCE':
                item.status = 'RECEIVED_FROM_VENDOR'
                item.status_note = "ได้รับเครื่องกลับจากศูนย์/ภายนอกแล้ว (Admin Action)"
                item.save()
                
                # Record History
                RepairStatusHistory.objects.create(
                    repair_item=item,
                    status='RECEIVED_FROM_VENDOR',
                    changed_by=request.user,
                    note="ได้รับเครื่องกลับจากศูนย์แล้ว (ผ่านระบบจัดการหลังบ้าน)"
                )
                count += 1
        self.message_user(request, f"ดำเนินการยืนยันรับเครื่องคืนแล้ว {count} รายการ", messages.SUCCESS)
    
    receive_from_vendor.short_description = "ยืนยันรับเครื่องคืนจากศูนย์ (RECEIVED_FROM_VENDOR)"
