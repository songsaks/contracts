from django.contrib import admin
from .models import Project, ProductItem, Customer, Supplier, ProjectOwner, CustomerRequirement, ServiceTeam, ServiceQueueItem, TeamMessage

@admin.register(ProjectOwner)
class ProjectOwnerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'position')

@admin.register(CustomerRequirement)
class CustomerRequirementAdmin(admin.ModelAdmin):
    list_display = ('pk', 'created_at', 'is_converted')
    list_filter = ('is_converted',)

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone')

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_name', 'email', 'phone')

class ProductItemInline(admin.TabularInline):
    model = ProductItem
    extra = 0

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

@admin.register(ServiceQueueItem)
class ServiceQueueItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'task_type', 'priority', 'status', 'assigned_team', 'deadline', 'scheduled_date', 'scheduled_time')
    list_filter = ('status', 'priority', 'task_type', 'assigned_team')
    search_fields = ('title', 'description')

@admin.register(TeamMessage)
class TeamMessageAdmin(admin.ModelAdmin):
    list_display = ('subject', 'team', 'is_read', 'created_at')
    list_filter = ('team', 'is_read')

