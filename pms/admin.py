from django.contrib import admin
from .models import (
    Project, ProductItem, Customer, Supplier, ProjectOwner,
    CustomerRequirement, ServiceTeam, ServiceQueueItem, TeamMessage,
    SLAPlan, JobStatus, JobStatusAssignment, ProjectStatusAssignment, UserNotification,
    TechnicianGPSLog, CustomerSatisfaction,
)

# จัดการตารางสถานะงานแบบ Dynamic (สำหรับเลือกใช้ตาม Job Type)
@admin.register(JobStatus)
class JobStatusAdmin(admin.ModelAdmin):
    list_display = ('job_type', 'status_key', 'label', 'sort_order', 'is_active')
    list_filter = ('job_type', 'is_active')
    list_editable = ('sort_order', 'label', 'is_active')
    search_fields = ('status_key', 'label')

@admin.register(SLAPlan)
class SLAPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'response_time_hours', 'resolution_time_hours', 'is_active')

@admin.register(ProjectOwner)
class ProjectOwnerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'position')

@admin.register(CustomerRequirement)
class CustomerRequirementAdmin(admin.ModelAdmin):
    list_display = ('pk', 'created_at', 'is_converted')
    list_filter = ('is_converted',)

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'sla_plan')
    list_filter = ('sla_plan',)

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_name', 'email', 'phone')

class ProductItemInline(admin.TabularInline):
    model = ProductItem
    extra = 0

# จัดการข้อมูลโครงการหลัก พร้อมแสดงรายการสินค้าในรูปแบบ Inline
@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'customer', 'status', 'start_date', 'deadline', 'total_value')
    list_filter = ('status', 'customer')
    search_fields = ('name', 'customer__name')
    inlines = [ProductItemInline]

@admin.register(ProductItem)
class ProductItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'project', 'item_type', 'quantity', 'unit_price', 'total_price')
    list_filter = ('item_type', 'project')

@admin.register(ServiceTeam)
class ServiceTeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'skills', 'max_tasks_per_day', 'is_active')
    filter_horizontal = ('members',)

# จัดการคิวงานบริการ (AI Service Queue) สำหรับแสดงผลและมอบหมายทีมงาน
@admin.register(ServiceQueueItem)
class ServiceQueueItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'task_type', 'priority', 'status', 'get_teams', 'deadline', 'scheduled_date', 'scheduled_time')
    list_filter = ('status', 'priority', 'task_type', 'assigned_teams')

    def get_teams(self, obj):
        return ", ".join(t.name for t in obj.assigned_teams.all())
    get_teams.short_description = "ทีม"
    search_fields = ('title', 'description')

@admin.register(TeamMessage)
class TeamMessageAdmin(admin.ModelAdmin):
    list_display = ('subject', 'team', 'is_read', 'created_at')
    list_filter = ('team', 'is_read')


@admin.register(JobStatusAssignment)
class JobStatusAssignmentAdmin(admin.ModelAdmin):
    list_display = ('job_status',)
    filter_horizontal = ('responsible_users',)

@admin.register(ProjectStatusAssignment)
class ProjectStatusAssignmentAdmin(admin.ModelAdmin):
    list_display = ('project', 'status_key')
    list_filter = ('project',)
    filter_horizontal = ('responsible_users',)

# ประวัติการแจ้งเตือนผู้รับผิดชอบโครงการ
@admin.register(UserNotification)
class UserNotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'project', 'subject', 'is_read', 'created_at')
    list_filter = ('user', 'is_read')



@admin.register(TechnicianGPSLog)
class TechnicianGPSLogAdmin(admin.ModelAdmin):
    list_display  = ('user', 'check_type', 'location_name', 'timestamp')
    list_filter   = ('check_type', 'user')
    search_fields = ('user__username', 'location_name')
    date_hierarchy = 'timestamp'


@admin.register(CustomerSatisfaction)
class CustomerSatisfactionAdmin(admin.ModelAdmin):
    list_display  = ('get_technician', 'rating', 'customer_name', 'customer_phone', 'get_location', 'created_at')
    list_filter   = ('rating', 'gps_log__user')
    search_fields = ('customer_name', 'customer_phone', 'gps_log__user__username')
    date_hierarchy = 'created_at'
    readonly_fields = ('gps_log', 'created_at')

    @admin.display(description='ช่าง')
    def get_technician(self, obj):
        return obj.gps_log.user.username

    @admin.display(description='สถานที่')
    def get_location(self, obj):
        return obj.gps_log.location_name or '—'
