from django.urls import path
from . import views

app_name = 'pms'

urlpatterns = [
    path('', views.dashboard, name='dashboard'), # Changed index to dashboard
    path('projects/', views.project_list, name='project_list'),
    path('history/', views.history_list, name='history_list'),
    path('create/', views.project_create, name='project_create'),
    path('<int:pk>/', views.project_detail, name='project_detail'),
    path('<int:pk>/edit/', views.project_update, name='project_update'),
    path('<int:pk>/cancel/', views.project_cancel, name='project_cancel'),
    path('<int:pk>/delete/', views.project_delete, name='project_delete'),
    path('<int:pk>/quotation/', views.project_quotation, name='project_quotation'),
    path('<int:pk>/respond/', views.mark_as_responded, name='mark_as_responded'),
    path('<int:project_id>/add-item/', views.item_add, name='item_add'),
    path('<int:project_id>/import-items/', views.item_import_excel, name='item_import_excel'),
    path('import-items/template/', views.download_item_template, name='download_item_template'),
    path('item/<int:item_id>/edit/', views.item_update, name='item_update'),
    path('item/<int:item_id>/delete/', views.item_delete, name='item_delete'),
    
    # Service & Dispatch
    path('dispatch/', views.dispatch, name='dispatch'),
    path('service/create/', views.service_create, name='service_create'),
    path('repair/create/', views.repair_create, name='repair_create'), # New Repair Job
    path('tracking/', views.sla_tracking_dashboard, name='tracking'),  

    # Customer URLs
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/create/', views.customer_create, name='customer_create'),
    path('customers/<int:pk>/edit/', views.customer_update, name='customer_update'),
    path('customers/<int:pk>/delete/', views.customer_delete, name='customer_delete'),

    # SLA Plan URLs
    path('sla-plans/', views.sla_plan_list, name='sla_plan_list'),
    path('sla-plans/create/', views.sla_plan_create, name='sla_plan_create'),
    path('sla-plans/<int:pk>/edit/', views.sla_plan_update, name='sla_plan_update'),

    # Supplier URLs
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:pk>/edit/', views.supplier_update, name='supplier_update'),
    # Manufacturer / Brand / Owner? -> Project Owner URLs
    path('owners/', views.project_owner_list, name='project_owner_list'),
    path('owners/create/', views.project_owner_create, name='project_owner_create'),
    path('owners/<int:pk>/edit/', views.project_owner_update, name='project_owner_update'),
    
    # Requirement / Leads
    path('requirements/', views.requirement_list, name='requirement_list'),
    path('requirements/create/', views.requirement_create, name='requirement_create'),
    path('requirements/<int:pk>/edit/', views.requirement_update, name='requirement_update'),
    path('requirements/<int:pk>/delete/', views.requirement_delete, name='requirement_delete'),
    path('requirements/<int:pk>/create-project/', views.create_project_from_requirement, name='create_project_from_requirement'),

    # AI Service Queue
    path('queue/ai/', views.service_queue_dashboard, name='service_queue_dashboard'),
    path('queue/ai/sync/', views.force_sync_queue, name='force_sync_queue'),
    path('queue/ai/schedule/', views.auto_schedule_tasks, name='auto_schedule_tasks'),

    path('queue/ai/<int:task_id>/update/', views.update_task_status, name='update_task_status'),
    path('queue/ai/<int:task_id>/set/', views.update_pending_task, name='update_pending_task'),
    path('queue/ai/messages/', views.team_messages, name='team_messages'),
    path('queue/ai/messages/<int:team_id>/', views.team_messages, name='team_messages_by_team'),

    # Team Management
    path('teams/', views.team_list, name='team_list'),
    path('teams/create/', views.team_create, name='team_create'),
    path('teams/<int:pk>/edit/', views.team_update, name='team_update'),
    path('teams/<int:pk>/delete/', views.team_delete, name='team_delete'),

    # File Management
    path('<int:pk>/upload-files/', views.project_file_upload, name='project_file_upload'),
    path('file/<int:file_id>/delete/', views.project_file_delete, name='project_file_delete'),
    path('requirements/file/<int:file_id>/delete/', views.requirement_file_delete, name='requirement_file_delete'),
    
    # Customer Requests
    path('requests/', views.request_list, name='request_list'),
    path('requests/create/', views.request_create, name='request_create'),
    path('requests/<int:pk>/', views.request_detail, name='request_detail'),
    path('requests/<int:pk>/edit/', views.request_update, name='request_update'),
    path('requests/<int:pk>/delete/', views.request_delete, name='request_delete'),
    path('requests/<int:pk>/upload/', views.request_file_upload, name='request_file_upload'),
    path('requests/file/<int:file_id>/delete/', views.request_file_delete, name='request_file_delete'),

    # AI Analysis
    path('dashboard/ai-analysis/', views.ai_dashboard_analysis, name='ai_dashboard_analysis'),
]

