from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

app_name = 'payroll'

urlpatterns = [
    # ── Auth ──────────────────────────────────────────────────────
    path('login/', auth_views.LoginView.as_view(
        template_name='payroll/login.html',
        redirect_authenticated_user=True,
        next_page='payroll:admin_dashboard',
    ), name='login'),
    path('logout/', views.payroll_logout, name='logout'),

    # ── Employee ────────────────────────────────────────────────────
    path('', views.report_list, name='report_list'),
    path('create/', views.report_create, name='report_create'),
    path('edit/<int:pk>/', views.report_edit, name='report_edit'),
    path('detail/<int:pk>/', views.report_detail, name='report_detail'),
    path('submit/<int:pk>/', views.report_submit, name='report_submit'),
    path('my-payslips/', views.my_payslips, name='my_payslips'),
    
    # HR/Admin only
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/approve/<int:pk>/', views.admin_approve, name='admin_approve'),
    path('admin/batch-approve/', views.batch_approve, name='batch_approve'),
    path('admin/batch-approve/create-report/', views.exec_create_report, name='exec_create_report'),
    path('admin/bank-export/', views.bank_export, name='bank_export'),
    path('admin/bank-export/excel/', views.bank_export_excel, name='bank_export_excel'),
    path('admin/config/', views.salary_config_list, name='salary_config_list'),
    path('admin/config/edit/<int:user_id>/', views.salary_config_edit, name='salary_config_edit'),
    path('admin/users/', views.user_management, name='user_management'),
    path('admin/sso/', views.sso_bracket_config, name='sso_bracket_config'),
    path('admin/users/toggle/<int:user_id>/', views.toggle_staff, name='toggle_staff'),
    path('admin/users/<int:user_id>/set-password/', views.set_user_password, name='set_user_password'),
    path('admin/bulk/', views.bulk_management, name='bulk_management'),
    path('admin/bulk/save-row/', views.bulk_save_row, name='bulk_save_row'),
    path('admin/import-excel/', views.import_excel, name='import_excel'),
    path('admin/download-template/', views.download_template, name='download_template'),

    # ── Employee Roster Management ──────────────────────────────────
    path('admin/employees/', views.employee_list, name='employee_list'),
    path('admin/employees/add/', views.create_payroll_employee, name='create_payroll_employee'),
    path('admin/employees/import/', views.import_employees, name='import_employees'),
    path('admin/employees/download-template/', views.download_employee_template, name='download_employee_template'),
    path('admin/employees/<int:user_id>/edit/', views.edit_payroll_employee, name='edit_payroll_employee'),
    path('admin/employees/<int:user_id>/remove/', views.remove_payroll_member, name='remove_payroll_member'),

    # Payslip
    path('payslip/<int:pk>/', views.payslip_view, name='payslip'),
    path('record/<int:pk>/', views.record_detail, name='record_detail'),
]
