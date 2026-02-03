from django.contrib import admin
from .models import Project, ProductItem, Customer, Supplier

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
