from django.urls import path
from . import views

app_name = 'repairs'

urlpatterns = [
    path('', views.repair_list, name='repair_list'),
    path('completed/', views.repair_completed_list, name='repair_completed_list'),
    path('create/', views.repair_create, name='repair_create'),
    path('job/<int:pk>/', views.repair_detail, name='repair_detail'),
    path('job/<int:pk>/print/', views.repair_print, name='repair_print'),
    path('item/<int:item_id>/update-status/', views.repair_update_status, name='repair_update_status'),
    path('item/<int:item_id>/note/', views.get_repair_item_note, name='get_repair_item_note'),
    path('job/<int:job_id>/notes/', views.get_repair_job_notes, name='get_repair_job_notes'),
    path('item/<int:item_id>/outsource-assign/', views.repair_outsource_assign, name='repair_outsource_assign'),
    path('item/<int:item_id>/outsource-receive/', views.repair_outsource_receive, name='repair_outsource_receive'),
    path('reports/income/', views.repair_income_report, name='repair_income_report'),
    path('track/<uuid:tracking_id>/', views.repair_tracking, name='repair_tracking'),
    path('status/', views.repair_status_search, name='repair_status_search'),
    
    # Customer
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/create/', views.customer_create, name='customer_create'),
    path('customers/<int:pk>/update/', views.customer_update, name='customer_update'),
    path('customers/<int:pk>/delete/', views.customer_delete, name='customer_delete'),
    
    # Device
    path('devices/', views.device_list, name='device_list'),
    
    # Technician
    path('technicians/', views.technician_list, name='technician_list'),
    path('technicians/create/', views.technician_create, name='technician_create'),
    path('technicians/<int:pk>/update/', views.technician_update, name='technician_update'),
    path('technicians/<int:pk>/delete/', views.technician_delete, name='technician_delete'),
    
    # DeviceType
    path('device-types/', views.device_type_list, name='device_type_list'),
    path('device-types/create/', views.device_type_create, name='device_type_create'),
    path('device-types/<int:pk>/update/', views.device_type_update, name='device_type_update'),
    path('device-types/<int:pk>/delete/', views.device_type_delete, name='device_type_delete'),
    
    # Brands
    path('brands/', views.brand_list, name='brand_list'),
    path('brands/create/', views.brand_create, name='brand_create'),
    path('brands/<int:pk>/update/', views.brand_update, name='brand_update'),
    path('brands/<int:pk>/delete/', views.brand_delete, name='brand_delete'),
]
