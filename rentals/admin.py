from django.contrib import admin
from .models import Asset, Tenant, Contract

@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ('name', 'serial_number', 'monthly_rate', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'description', 'serial_number')

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('agency_name', 'contact_person', 'email', 'phone')
    search_fields = ('agency_name', 'contact_person', 'email', 'document_id')

@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ('id', 'tenant', 'start_date', 'end_date', 'total_amount', 'paid_amount', 'status')
    list_filter = ('status', 'start_date')
    search_fields = ('tenant__agency_name', 'tenant__contact_person', 'id')

