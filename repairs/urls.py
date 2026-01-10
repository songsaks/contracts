from django.urls import path
from . import views

app_name = 'repairs'

urlpatterns = [
    path('', views.repair_list, name='repair_list'),
    path('create/', views.repair_create, name='repair_create'),
    path('job/<int:pk>/', views.repair_detail, name='repair_detail'),
    path('item/<int:item_id>/update-status/', views.repair_update_status, name='repair_update_status'),
    
    # Customer
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/create/', views.customer_create, name='customer_create'),
    
    # Device
    path('devices/', views.device_list, name='device_list'),
    path('devices/create/', views.device_create, name='device_create'),
    
    # Technician
    path('technicians/', views.technician_list, name='technician_list'),
    path('technicians/create/', views.technician_create, name='technician_create'),
    
    # DeviceType
    path('device-types/', views.device_type_list, name='device_type_list'),
    path('device-types/create/', views.device_type_create, name='device_type_create'),
]
