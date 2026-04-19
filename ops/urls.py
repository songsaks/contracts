from django.urls import path
from . import views

app_name = 'ops'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('report/<int:goal_id>/', views.report_progress, name='report_progress'),
    path('goal/create/', views.goal_create, name='goal_create'),
    path('goal/delete/<int:goal_id>/', views.goal_delete, name='goal_delete'),
    path('management/', views.management_view, name='management'),
    path('dept/create/', views.dept_create, name='dept_create'),
    path('employee/create/', views.employee_create, name='employee_create'),
    path('weekly-report/', views.weekly_report, name='weekly_report'),
    path('ai-analysis/', views.ai_analysis, name='ai_analysis'),
]
