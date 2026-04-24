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
    path('dept/update/<int:dept_id>/', views.dept_update, name='dept_update'),
    path('dept/delete/<int:dept_id>/', views.dept_delete, name='dept_delete'),
    path('dept/members-update/<int:dept_id>/', views.bulk_update_members, name='members_update'),
    path('employee/create/', views.employee_create, name='employee_create'),
    path('weekly-report/', views.weekly_report, name='weekly_report'),
    path('ai-analysis/', views.ai_analysis, name='ai_analysis'),
    path('scheduler/', views.scheduler_view, name='scheduler'),
    path('scheduler/data/', views.scheduler_data, name='scheduler_data'),
    path('kanban/', views.kanban_view, name='kanban'),
    path('goal/update-status/', views.update_goal_status, name='update_goal_status'),

    # --- Meeting & Idea Management ---
    path('meetings/', views.meeting_list, name='meeting_list'),
    path('meetings/create/', views.meeting_create, name='meeting_create'),
    path('meetings/<int:meeting_id>/', views.meeting_detail, name='meeting_detail'),
    path('meetings/<int:meeting_id>/record/', views.meeting_record, name='meeting_record'),
    path('meetings/<int:meeting_id>/idea/add/', views.idea_add, name='idea_add'),
    path('ideas/', views.idea_list, name='idea_list'),
    path('ideas/<int:idea_id>/score/', views.idea_score, name='idea_score'),
    path('ideas/<int:idea_id>/approve/', views.idea_approve, name='idea_approve'),
    path('tasks/', views.task_list, name='task_list'),
    path('tasks/gantt/', views.task_gantt, name='task_gantt'),
    path('tasks/kanban/', views.task_kanban, name='task_kanban'),
]
