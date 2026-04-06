from django.urls import path
from . import views

# ======================================================================
# pms/urls.py — URL Configuration สำหรับ Project Management System (PMS)
# ======================================================================
# แบ่งหมวดหมู่ URL ดังนี้:
#   - โครงการ (Projects)      : CRUD + Workflow + Quotation
#   - ลูกค้า (Customers)      : CRUD + SLA Plans
#   - ซัพพลายเออร์ (Suppliers): CRUD
#   - ความต้องการ/Leads       : CRUD + แปลงเป็น Project
#   - AI Service Queue        : Sync, Schedule, Notify, Task Update
#   - ทีม (Teams)             : CRUD
#   - ไฟล์แนบ (Files)         : Upload + Delete
#   - คำขอลูกค้า (Requests)   : CRUD + ไฟล์แนบ
#   - GPS Tracking            : Report + Live Data + Delete
#   - API / Chatbot / Notifications
# ======================================================================

app_name = 'pms'

urlpatterns = [
    # ===== หน้าแรก & โครงการ (Dashboard & Projects) =====
    path('', views.dashboard, name='dashboard'),                                          # แดชบอร์ดหลัก
    path('projects/', views.project_list, name='project_list'),                          # รายการงานที่ดำเนินการ
    path('history/', views.history_list, name='history_list'),                           # ประวัติงานที่ปิดจบ/ยกเลิก
    path('create/', views.project_create, name='project_create'),                        # สร้างโครงการใหม่
    path('<int:pk>/', views.project_detail, name='project_detail'),                      # รายละเอียดโครงการ
    path('<int:pk>/edit/', views.project_update, name='project_update'),                 # แก้ไขโครงการ
    path('<int:pk>/cancel/', views.project_cancel, name='project_cancel'),               # ยกเลิกโครงการ
    path('<int:pk>/advance/', views.project_advance, name='project_advance'),            # เลื่อนสถานะถัดไป
    path('<int:pk>/delete/', views.project_delete, name='project_delete'),               # ลบโครงการ (ต้องมีรหัส)
    path('<int:pk>/quotation/', views.project_quotation, name='project_quotation'),      # ใบเสนอราคา
    path('<int:pk>/respond/', views.mark_as_responded, name='mark_as_responded'),        # บันทึกการตอบกลับ SLA

    # ===== รายการสินค้า/บริการในโครงการ (Product Items) =====
    path('<int:project_id>/add-item/', views.item_add, name='item_add'),                                # เพิ่มรายการ
    path('<int:project_id>/import-items/', views.item_import_excel, name='item_import_excel'),          # นำเข้าจาก Excel
    path('import-items/template/', views.download_item_template, name='download_item_template'),        # ดาวน์โหลด Template
    path('item/<int:item_id>/edit/', views.item_update, name='item_update'),                            # แก้ไขรายการ
    path('item/<int:item_id>/delete/', views.item_delete, name='item_delete'),                          # ลบรายการ

    # ===== Dispatch & งานประเภทต่างๆ (Service / Repair / Rental) =====
    path('dispatch/', views.dispatch, name='dispatch'),                          # หน้าเลือกสร้างงาน
    path('service/create/', views.service_create, name='service_create'),        # สร้างงานบริการขาย
    path('repair/create/', views.repair_create, name='repair_create'),           # สร้างใบแจ้งซ่อม
    path('rental/create/', views.rental_create, name='rental_create'),           # สร้างงานเช่า
    path('survey/create/', views.survey_create, name='survey_create'),           # สร้างงานดูหน้างาน
    path('survey/<int:pk>/convert/', views.survey_convert_to_project, name='survey_convert_to_project'),  # แปลง SURVEY เป็น PROJECT
    path('tracking/', views.sla_tracking_dashboard, name='tracking'),            # แดชบอร์ด SLA Tracking

    # ===== ลูกค้า (Customers) =====
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/create/', views.customer_create, name='customer_create'),
    path('customers/<int:pk>/edit/', views.customer_update, name='customer_update'),
    path('customers/<int:pk>/delete/', views.customer_delete, name='customer_delete'),

    # ===== แผน SLA (SLA Plans) =====
    path('sla-plans/', views.sla_plan_list, name='sla_plan_list'),
    path('sla-plans/create/', views.sla_plan_create, name='sla_plan_create'),
    path('sla-plans/<int:pk>/edit/', views.sla_plan_update, name='sla_plan_update'),

    # ===== ซัพพลายเออร์ (Suppliers) =====
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:pk>/edit/', views.supplier_update, name='supplier_update'),

    # ===== เจ้าของโครงการ (Project Owners) =====
    path('owners/', views.project_owner_list, name='project_owner_list'),
    path('owners/create/', views.project_owner_create, name='project_owner_create'),
    path('owners/<int:pk>/edit/', views.project_owner_update, name='project_owner_update'),

    # ===== ความต้องการลูกค้า / Leads =====
    path('requirements/', views.requirement_list, name='requirement_list'),
    path('requirements/create/', views.requirement_create, name='requirement_create'),
    path('requirements/<int:pk>/edit/', views.requirement_update, name='requirement_update'),
    path('requirements/<int:pk>/delete/', views.requirement_delete, name='requirement_delete'),
    path('requirements/<int:pk>/create-project/', views.create_project_from_requirement, name='create_project_from_requirement'),  # แปลง Lead → Project

    # ===== AI Service Queue (คิวงานอัตโนมัติ) =====
    path('queue/ai/', views.service_queue_dashboard, name='service_queue_dashboard'),          # หน้าหลักคิว
    path('queue/ai/sync/', views.force_sync_queue, name='force_sync_queue'),                   # Sync งานจาก Project
    path('queue/ai/schedule/', views.auto_schedule_tasks, name='auto_schedule_tasks'),         # AI จัดคิวอัตโนมัติ
    path('queue/ai/notify/', views.send_queue_notifications, name='send_queue_notifications'), # ส่งแจ้งเตือนทีม
    path('queue/ai/<int:task_id>/update/', views.update_task_status, name='update_task_status'),  # อัปเดตสถานะงาน
    path('queue/ai/<int:task_id>/set/', views.update_pending_task, name='update_pending_task'),   # กำหนดทีม+วันที่
    path('queue/ai/messages/', views.team_messages, name='team_messages'),                          # ข้อความทีมทั้งหมด
    path('queue/ai/messages/<int:team_id>/', views.team_messages, name='team_messages_by_team'),   # ข้อความทีมเฉพาะ

    # ===== ทักษะ (Skills) =====
    path('skills/', views.skill_list, name='skill_list'),
    path('skills/create/', views.skill_create, name='skill_create'),
    path('skills/<int:pk>/edit/', views.skill_update, name='skill_update'),
    path('skills/<int:pk>/delete/', views.skill_delete, name='skill_delete'),

    # ===== ทีมบริการ (Service Teams) =====
    path('teams/', views.team_list, name='team_list'),
    path('teams/create/', views.team_create, name='team_create'),
    path('teams/<int:pk>/edit/', views.team_update, name='team_update'),
    path('teams/<int:pk>/delete/', views.team_delete, name='team_delete'),

    # ===== ไฟล์แนบ (File Management) =====
    path('<int:pk>/upload-files/', views.project_file_upload, name='project_file_upload'),
    path('file/<int:file_id>/delete/', views.project_file_delete, name='project_file_delete'),
    path('requirements/file/<int:file_id>/delete/', views.requirement_file_delete, name='requirement_file_delete'),

    # ===== คำขอลูกค้า (Customer Requests) =====
    path('requests/', views.request_list, name='request_list'),
    path('requests/create/', views.request_create, name='request_create'),
    path('requests/<int:pk>/', views.request_detail, name='request_detail'),
    path('requests/<int:pk>/edit/', views.request_update, name='request_update'),
    path('requests/<int:pk>/delete/', views.request_delete, name='request_delete'),
    path('requests/<int:pk>/upload/', views.request_file_upload, name='request_file_upload'),
    path('requests/file/<int:file_id>/delete/', views.request_file_delete, name='request_file_delete'),

    # ===== AI Analysis & การแจ้งเตือน (Notifications) =====
    path('dashboard/ai-analysis/', views.ai_dashboard_analysis, name='ai_dashboard_analysis'),   # Gemini วิเคราะห์ Dashboard
    path('notifications/', views.notification_list, name='notification_list'),                    # รายการแจ้งเตือน
    path('notifications/<int:pk>/read/', views.notification_read, name='notification_read'),      # ทำเครื่องหมายอ่านแล้ว

    # ===== ตารางมอบหมาย (Assignment Matrix) =====
    path('assignments/', views.project_assignment_matrix, name='project_assignment_matrix'),  # ตารางผู้รับผิดชอบ
    path('assignments/set/', views.set_project_assignment, name='set_project_assignment'),    # บันทึกการมอบหมาย (AJAX)
    path('assignments/seed/', views.seed_pms_statuses, name='seed_pms_statuses'),            # Seed ขั้นตอนมาตรฐาน

    # ===== ขั้นตอนงาน Dynamic (Job Status Workflow) =====
    path('job-statuses/', views.job_status_list, name='job_status_list'),
    path('job-statuses/create/', views.job_status_create, name='job_status_create'),
    path('job-statuses/<int:pk>/edit/', views.job_status_update, name='job_status_update'),
    path('job-statuses/<int:pk>/delete/', views.job_status_delete, name='job_status_delete'),

    # ===== API Endpoints =====
    path('api/chatbot/', views.openclaw_chatbot, name='api_chatbot'),                              # Chatbot Proxy (OpenClaw)
    path('api/notifications/counts/', views.get_notification_counts, name='get_notification_counts'),  # จำนวนแจ้งเตือน (Polling)

    # ===== GPS Tracking — ติดตามพิกัดช่าง =====
    path('gps-tracking/track-state/', views.gps_track_state, name='gps_track_state'),                              # API สถานะ force-track ของตัวเอง
    path('gps-tracking/track-state/<int:user_id>/toggle/', views.gps_track_state_toggle, name='gps_track_state_toggle'),  # Admin toggle force-track
    path('gps-tracking/', views.gps_tracking_report, name='gps_tracking_report'),             # รายงานเส้นทางประจำวัน
    path('gps-tracking/live/', views.gps_live_data, name='gps_live_data'),                    # JSON API สำหรับ Live mode
    path('gps-tracking/daily-summary/', views.gps_daily_summary, name='gps_daily_summary'),   # รายงานสรุปการทำงานรายวัน
    path('gps-tracking/daily-summary/send-to-chat/', views.gps_daily_summary_send_to_chat, name='gps_daily_summary_send_to_chat'),  # ส่งสรุปไปยังห้องแชท
    path('gps-tracking/warn-notify/', views.gps_track_warn_notify, name='gps_track_warn_notify'),  # แจ้งเตือนช่างที่ GPS หาย
    path('gps-tracking/warn-status/', views.gps_warn_status_api, name='gps_warn_status_api'),      # JSON API รายชื่อช่างที่ GPS หาย
    path('gps-tracking/summary/', views.gps_summary_report, name='gps_summary_report'),       # รายงานสรุปรายเดือน
    path('gps-tracking/summary/export/', views.gps_summary_export, name='gps_summary_export'),  # Export CSV
    path('gps-tracking/stats/', views.gps_technician_stats, name='gps_technician_stats'),        # กราฟสถิติรายบุคคล
    path('gps-tracking/<int:pk>/delete/', views.gps_log_delete, name='gps_log_delete'),       # ลบ GPS log entry
    path('gps-tracking/map-embed/<str:username>/<str:date_str>/', views.gps_map_embed, name='gps_map_embed'),  # Leaflet iframe embed
    path('gps-tracking/map-image/<str:username>/<str:date_str>/', views.gps_map_image, name='gps_map_image'),  # PNG map image

    # ── Work Summary Report + AI Analysis ─────────────────────────────────
    path('work-summary/', views.work_summary_report, name='work_summary_report'),              # รายงานสรุปการทำงาน
    path('work-summary/ai/', views.work_summary_ai_analysis, name='work_summary_ai_analysis'), # AI วิเคราะห์ประสิทธิภาพ
    path('installation-report/', views.installation_report, name='installation_report'),        # รายงานมูลค่าและเวลาติดตั้ง
    path('installation-report/send-to-chat/', views.installation_report_send_to_chat, name='installation_report_send_to_chat'),
]

