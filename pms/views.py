from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Sum, Count, Q, F, Case, When, Value, DecimalField, IntegerField
from django.db.models.functions import TruncMonth
from django.http import FileResponse, JsonResponse
from decimal import Decimal
from datetime import datetime, date, time
import calendar
import requests
import json
from django.views.decorators.csrf import csrf_exempt
from .models import (
    Project, ProductItem, Customer, Supplier, ProjectOwner, 
    CustomerRequirement, ProjectFile, CustomerRequest, 
    ServiceQueueItem, SLAPlan, JobStatus, ProjectStatusAssignment,
    UserNotification
)
from .forms import (
    ProjectForm, ProductItemForm, CustomerForm, SupplierForm, 
    ProjectOwnerForm, CustomerRequirementForm, SalesServiceJobForm, 
    CustomerRequestForm, SLAPlanForm, JobStatusForm
)
import io
import pandas as pd
from accounts.models import user_can_view_all


# สร้างรายการสินค้าอัตโนมัติจากมูลค่าโครงการที่กรอกในฟอร์ม
# ใช้เมื่อผู้ใช้ระบุ "มูลค่าโครงการ" แทนการเพิ่มรายการสินค้าทีละชิ้น
def _create_project_value_item(project, project_value):
    """สร้าง ProductItem อัตโนมัติจากฟิลด์ project_value ในฟอร์ม"""
    if not project_value or project_value <= 0:
        return None
    # Truncate project name to ~80 chars for item name
    proj_name = project.name.strip()
    if len(proj_name) > 80:
        proj_name = proj_name[:77] + '...'
    item_name = f"{proj_name}"
    return ProductItem.objects.create(
        project=project,
        item_type=ProductItem.ItemType.SERVICE,
        name=item_name,
        description=f"มูลค่าโครงการ: {project.name}",
        quantity=1,
        unit_cost=Decimal('0'),
        unit_price=project_value,
    )


# หน้าจอเลือกเมนูหลัก (Dispatch) สำหรับเลือกสร้างงานประเภทใหม่ๆ
# เช่น การสร้างงานบริการขาย การแจ้งซ่อมระบบ หรือการทำสัญญาเช่าอุปกรณ์
@login_required
def dispatch(request):
    """ทำหน้าที่เป็นจุดเริ่มต้นสำหรับการสร้างงานใหม่ที่แยกตามประเภท"""
    return render(request, 'pms/dispatch.html')

# ฟังก์ชันสำหรับสร้างใบงานบริการ/งานขาย (Sales Service)
# ระบบจะระบุประเภทงานเป็น 'SERVICE' อัตโนมัติ และสร้างรายการสินค้าเริ่มต้นจากมูลค่าโครงการที่ระบุ
@login_required
def service_create(request):
    if request.method == 'POST':
        form = SalesServiceJobForm(request.POST, job_type=Project.JobType.SERVICE)
        if form.is_valid():
            project = form.save(commit=False)
            project.job_type = Project.JobType.SERVICE
            project.status = Project.Status.SOURCING
            project._changed_by_user = request.user
            project.save()
            # Auto-create value item
            pv = form.cleaned_data.get('project_value')
            _create_project_value_item(project, pv)
            messages.success(request, 'สร้างงานบริการขายสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = SalesServiceJobForm(initial={'status': Project.Status.SOURCING}, job_type=Project.JobType.SERVICE)
    return render(request, 'pms/service_form.html', {
        'form': form, 'title': 'สร้างงานบริการขายใหม่', 'theme_color': 'success',
    })

# ฟังก์ชันสำหรับสร้างใบแจ้งซ่อมระบบ (On-site Repair)
# ใช้สำหรับการบันทึกงานซ่อมถึงสถานที่ลูกค้า โดยระบบจะระบุประเภทงานเป็น 'REPAIR'
@login_required
def repair_create(request):
    if request.method == 'POST':
        form = SalesServiceJobForm(request.POST, job_type=Project.JobType.REPAIR)
        if form.is_valid():
            project = form.save(commit=False)
            project.job_type = Project.JobType.REPAIR
            project.status = Project.Status.SOURCING
            project._changed_by_user = request.user
            project.save()
            # Auto-create value item
            pv = form.cleaned_data.get('project_value')
            _create_project_value_item(project, pv)
            messages.success(request, 'สร้างใบแจ้งซ่อมสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = SalesServiceJobForm(initial={'status': Project.Status.SOURCING, 'name': 'แจ้งซ่อม - '}, job_type=Project.JobType.REPAIR)
    return render(request, 'pms/service_form.html', {
        'form': form, 'title': 'สร้างใบแจ้งซ่อม (On-site Repair)', 'theme_color': 'warning',
    })

# ฟังก์ชันสำหรับสร้างใบงานเช่าอุปกรณ์ (Rental Service)
# ใช้สำหรับการทำเรื่องเช่าสินค้า โดยระบบจะระบุประเภทงานเป็น 'RENTAL' ให้ทันที
@login_required
def rental_create(request):
    if request.method == 'POST':
        form = SalesServiceJobForm(request.POST, job_type=Project.JobType.RENTAL)
        if form.is_valid():
            project = form.save(commit=False)
            project.job_type = Project.JobType.RENTAL
            project.status = Project.Status.SOURCING
            project._changed_by_user = request.user
            project.save()
            # Auto-create value item
            pv = form.cleaned_data.get('project_value')
            _create_project_value_item(project, pv)
            messages.success(request, 'สร้างงานเช่าสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = SalesServiceJobForm(initial={'status': Project.Status.SOURCING}, job_type=Project.JobType.RENTAL)
    return render(request, 'pms/service_form.html', {
        'form': form, 'title': 'สร้างงานเช่าใหม่', 'theme_color': 'pms-rental',
    })


# ฟังก์ชันสำหรับส่งช่างไปดูหน้างาน (Site Survey)
# ระบบจะระบุประเภทงานเป็น 'SURVEY' และสถานะเริ่มต้นที่เริ่มคิวทันที (QUEUE_SURVEY)
@login_required
def survey_create(request):
    if request.method == 'POST':
        form = SalesServiceJobForm(request.POST, job_type=Project.JobType.SURVEY)
        if form.is_valid():
            project = form.save(commit=False)
            project.job_type = Project.JobType.SURVEY
            project.status = 'QUEUE_SURVEY'
            project._changed_by_user = request.user
            project.save()
            # Auto-create value item (if any)
            pv = form.cleaned_data.get('project_value')
            _create_project_value_item(project, pv)
            messages.success(request, 'สร้างงานสำรวจหน้างานในคิวเรียบร้อย')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = SalesServiceJobForm(initial={'status': 'QUEUE_SURVEY', 'name': 'ดูหน้างาน - '}, job_type=Project.JobType.SURVEY)
    return render(request, 'pms/service_form.html', {
        'form': form, 'title': 'สร้างงานดูหน้างาน (Site Survey)', 'theme_color': 'info',
    })

# ฟังก์ชันสำหรับเปลี่ยนประเภทงานจาก 'SURVEY' เป็น 'PROJECT'
# ใช้เมื่อลูกค้าตกลงหลังการดูหน้างาน โดยจะเปลี่ยนสถานะเป็น 'QUOTED' (เสนอราคา) ทันที
@login_required
def survey_convert_to_project(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if project.job_type != Project.JobType.SURVEY:
        messages.warning(request, "งานนี้ไม่ใช่ประเภทงานดูหน้างาน ไม่สามารถแปลงได้")
        return redirect('pms:project_detail', pk=pk)
    
    project.job_type = Project.JobType.PROJECT
    project.status = Project.Status.QUOTED  # เปลี่ยนเป็นเสนอราคา
    project._changed_by_user = request.user
    project.save()
    
    messages.success(request, f'แปลงงาน "{project.name}" เป็นโครงการติดตั้งเรียบร้อยแล้ว ในขั้นตอนเสนอราคา')
    return redirect('pms:project_detail', pk=pk)

# ... queue_management ...

# ... project_list ...

# ... project_detail ...

# ... project_create ...



# แดชบอร์ด SLA Tracking — แสดงงานที่ใกล้เกิน/เกินกำหนดตามข้อตกลง SLA
# แบ่งเป็น 2 ส่วน: เส้นตายการตอบกลับ (Response) และเส้นตายการแก้ไข (Resolution)
@login_required
def sla_tracking_dashboard(request):
    """แดชบอร์ดตรวจสอบ SLA — แสดง alert สำหรับงานที่ยังไม่ตอบกลับหรือยังไม่แก้ไข"""
    from pms.models import Project as ProjectModel
    
    # SLA Alerts
    sla_response_alerts = ProjectModel.objects.filter(
        customer__sla_plan__isnull=False,
        responded_at__isnull=True
    ).select_related('customer').order_by('sla_response_deadline')[:10]

    sla_resolution_alerts = ProjectModel.objects.filter(
        customer__sla_plan__isnull=False
    ).exclude(
        status__in=['CLOSED', 'CANCELLED']
    ).select_related('customer').order_by('sla_resolution_deadline')[:10]
    
    return render(request, 'pms/tracking_dashboard.html', {
        'sla_response_alerts': sla_response_alerts,
        'sla_resolution_alerts': sla_resolution_alerts,
    })

# ตรวจสอบว่าโครงการถูกล็อก (ปิดจบ/ยกเลิก) และต้องใช้รหัสปลดล็อกหรือไม่
# คืนค่า True = ล็อกอยู่ (ห้ามแก้ไข), False = ยังแก้ไขได้
def _check_project_lock(project, request):
    """ตรวจสอบสถานะล็อก: ถ้าปิดจบ/ยกเลิกและไม่มีรหัส DELETE_PASSWORD คืนค่า True"""
    if project.status in [Project.Status.CLOSED, Project.Status.CANCELLED]:
        from django.conf import settings
        unlock_code = request.GET.get('unlock') or request.POST.get('unlock')
        if unlock_code != settings.DELETE_PASSWORD:
            return True
    return False

# รายการงานทั้งหมดที่ยังอยู่ในสถานะที่เจ้าหน้าที่ต้องดำเนินการ (Active)
# โดยระบบจะกรองเฉพาะงานที่ยังไม่ถูก 'ปิดจบ' หรือ 'ยกเลิก' ออกมาแสดงผล
@login_required
def project_list(request):
    # Default: Show active projects (Exclude CLOSED and CANCELLED)
    projects = Project.objects.exclude(
        status__in=[Project.Status.CLOSED, Project.Status.CANCELLED]
    ).order_by('-created_at')

    # Filter
    status_filter = request.GET.get('status')
    if status_filter:
        projects = projects.filter(status=status_filter)
    
    job_type_filter = request.GET.get('job_type')
    if job_type_filter:
        projects = projects.filter(job_type=job_type_filter)
        
    owner_filter = request.GET.get('owner')
    if owner_filter:
        projects = projects.filter(owner_id=owner_filter)

    customer_filter = request.GET.get('customer')
    if customer_filter:
        projects = projects.filter(customer_id=customer_filter)

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from and date_to:
        projects = projects.filter(created_at__date__range=[date_from, date_to])

    # Build status choices dynamically from JobStatus table so admin-added steps appear automatically.
    # For each status_key, prefer the PROJECT job_type entry's label and sort_order,
    # then SERVICE, REPAIR, RENTAL. Exclude CLOSED/CANCELLED (handled in history).
    _js_rows = (
        JobStatus.objects
        .filter(is_active=True)
        .exclude(status_key__in=['CLOSED', 'CANCELLED'])
        .order_by(
            'status_key',
            Case(
                When(job_type='PROJECT', then=Value(1)),
                When(job_type='SERVICE', then=Value(2)),
                When(job_type='REPAIR',  then=Value(3)),
                default=Value(4),
                output_field=IntegerField(),
            ),
            'sort_order',
        )
        .values('status_key', 'label', 'sort_order')
    )
    _seen_statuses = {}
    for _row in _js_rows:
        if _row['status_key'] not in _seen_statuses:
            _seen_statuses[_row['status_key']] = (_row['label'], _row['sort_order'])

    status_choices = [
        (k, v[0])
        for k, v in sorted(_seen_statuses.items(), key=lambda x: (x[1][1], x[0]))
    ]

    context = {
        'projects': projects,
        'status_choices': status_choices,
        'project_owners': ProjectOwner.objects.all(),
        'customers': Customer.objects.all().only('id', 'name'),
        'title': 'รายการงานที่กำลังดำเนินการ'
    }
    return render(request, 'pms/project_list.html', context)

# ประวัติงานที่ปิดจบหรือยกเลิกแล้ว — เรียงจากล่าสุดขึ้นก่อน รองรับค้นหาและกรองประเภทงาน
@login_required
def history_list(request):
    """แสดงงานที่มีสถานะ CLOSED/CANCELLED เรียงตาม closed_at ล่าสุด"""
    projects = Project.objects.filter(
        status__in=[Project.Status.CLOSED, Project.Status.CANCELLED]
    ).order_by('-closed_at')
    
    search_q = request.GET.get('q')
    if search_q:
        projects = projects.filter(
            Q(name__icontains=search_q) |
            Q(customer__name__icontains=search_q) |
            Q(owner__name__icontains=search_q)
        )
        
    jt_filter = request.GET.get('job_type')
    if jt_filter:
        projects = projects.filter(job_type=jt_filter)

    context = {
        'projects': projects,
        'title': 'ประวัติงานทั้งหมด (ปิดงาน/ยกเลิก)',
        'job_types': Project.JobType.choices,
        'search_q': search_q,
    }
    return render(request, 'pms/history_list.html', context)

# แสดงรายละเอียดทั้งหมดของโครงการ รายการค่าใช้จ่าย ประวัติการทำงาน และไฟล์แนบ
# รวมถึงหน้าจอสำหรับอัปเดตสถานะโครงการในรูปแบบขั้นตอนแบบ Step-by-Step
@login_required
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk)
    
    # Theme Color
    if project.job_type == Project.JobType.SERVICE:
        theme_color = 'success'
    elif project.job_type == Project.JobType.REPAIR:
        theme_color = 'warning'
    elif project.job_type == Project.JobType.RENTAL:
        theme_color = 'pms-rental'
    elif project.job_type == Project.JobType.SURVEY:
        theme_color = 'info'
    else:  # PROJECT
        theme_color = 'primary'

    # Workflow steps based on job type (Dynamic from JobStatus)
    from .models import JobStatus
    db_choices = JobStatus.get_choices(project.job_type)
    if db_choices:
        raw_steps = db_choices
    else:
        # Fallback Hardcoded Workflow (Synced with User Request March 3rd)
        if project.job_type == Project.JobType.SERVICE:
            raw_steps = [
                (Project.Status.DRAFT, 'รวบรวม'),
                (Project.Status.QUOTED, 'เสนอราคา'),
                (Project.Status.ORDERING, 'สั่งซื้อ'),
                (Project.Status.RECEIVED_QC, 'รับของ/QC'),
                (Project.Status.DELIVERY, 'คิว'),
                (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย'),
                (Project.Status.CLOSED, 'ปิดจบ'),
                (Project.Status.CANCELLED, 'ยกเลิก'),
            ]
        elif project.job_type == Project.JobType.REPAIR:
            raw_steps = [
                (Project.Status.DRAFT, 'รวบรวม'),
                (Project.Status.QUOTED, 'เสนอราคา'),
                (Project.Status.ORDERING, 'สั่งซื้อ'),
                (Project.Status.RECEIVED_QC, 'รับของ/QC'),
                (Project.Status.REPAIRING, 'ซ่อม'),
                (Project.Status.DELIVERY, 'คิว'),
                (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย'),
                (Project.Status.CLOSED, 'ปิดจบ'),
                (Project.Status.CANCELLED, 'ยกเลิก'),
            ]
        elif project.job_type == Project.JobType.RENTAL:
            raw_steps = [
                (Project.Status.DRAFT, 'รวบรวม'),
                (Project.Status.CONTRACTED, 'ทำสัญญา'),
                (Project.Status.RENTING, 'เช่า'),
                (Project.Status.CLOSED, 'ปิดจบ'),
            ]
        else: # PROJECT
            raw_steps = [
                (Project.Status.DRAFT, 'รวบรวม'),
                (Project.Status.QUOTED, 'เสนอราคา'),
                (Project.Status.CONTRACTED, 'ทำสัญญา'),
                (Project.Status.ORDERING, 'สั่งซื้อ'),
                (Project.Status.RECEIVED_QC, 'รับของ/QC'),
                (Project.Status.REQUESTING_ACTION, 'ขอดำเนินการ'),
                (Project.Status.INSTALLATION, 'คิว'),
                (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย'),
                (Project.Status.CLOSED, 'ปิดจบ'),
                (Project.Status.CANCELLED, 'ยกเลิก'),
            ]

    # Wrapper class to make template logic work: {% if step == project.status %} and {{ step.label }}
    class StepWrapper:
        def __init__(self, value, label):
            self.value = value
            self.label = label
        def __eq__(self, other):
            return str(self.value) == str(other)
        def __str__(self):
            return str(self.value)

    workflow_steps = [StepWrapper(val, lbl) for val, lbl in raw_steps]

    # Get current status label
    current_status_label = project.get_status_display()
    for step in workflow_steps:
        if step == project.status:
            current_status_label = step.label
            break

    # --- AI QUEUE LOCK STATUS ---
    active_queue_item = project.service_tasks.filter(
        status__in=['PENDING', 'SCHEDULED', 'IN_PROGRESS', 'INCOMPLETE']
    ).first()

    context = {
        'project': project,
        'items': project.items.all(),
        'project_files': project.files.all(),
        'workflow_steps': workflow_steps,
        'theme_color': theme_color,
        'current_status_label': current_status_label,
        'active_queue_item': active_queue_item,
    }

    if request.method == 'POST':
        # Quick Update Logic
        new_status = request.POST.get('status')
        new_description = request.POST.get('description')
        new_remarks = request.POST.get('remarks')

        if new_status:
            project.status = new_status
        if new_description is not None:
            project.description = new_description
        if new_remarks is not None:
            project.remarks = new_remarks
        
        project._changed_by_user = request.user
        project.save()
        messages.success(request, 'บันทึกการแก้ไขเรียบร้อยแล้ว')
        return redirect('pms:project_detail', pk=pk)

    return render(request, 'pms/project_detail.html', context)


# สร้างโครงการใหม่ (Project Type)
@login_required
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project._changed_by_user = request.user
            project.save()
            # Auto-create value item
            pv = form.cleaned_data.get('project_value')
            _create_project_value_item(project, pv)
            messages.success(request, 'สร้างโครงการสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, 'pms/project_form.html', {'form': form, 'title': 'สร้างโครงการใหม่'})

# แก้ไขข้อมูลโครงการและจัดการผลุกมูลค่าโครงการ (Project Update)
@login_required
def project_update(request, pk):
    project = get_object_or_404(Project, pk=pk)
    
    # Determine Form Class, Title, and Theme based on Job Type
    theme_color = 'primary'
    form_kwargs = {'instance': project}

    if project.job_type == Project.JobType.SERVICE:
        FormClass = SalesServiceJobForm
        template = 'pms/service_form.html'
        title = 'แก้ไขงานขาย'
        theme_color = 'success'
        form_kwargs['job_type'] = Project.JobType.SERVICE
    elif project.job_type == Project.JobType.REPAIR:
        FormClass = SalesServiceJobForm
        template = 'pms/service_form.html'
        title = 'แก้ไขงานซ่อม'
        theme_color = 'warning'
        form_kwargs['job_type'] = Project.JobType.REPAIR
    elif project.job_type == Project.JobType.RENTAL:
        FormClass = SalesServiceJobForm
        template = 'pms/service_form.html'
        title = 'แก้ไขงานเช่า'
        theme_color = 'pms-rental'
        form_kwargs['job_type'] = Project.JobType.RENTAL
    elif project.job_type == Project.JobType.SURVEY:
        FormClass = SalesServiceJobForm
        template = 'pms/service_form.html'
        title = 'แก้ไขงานดูหน้างาน'
        theme_color = 'info'
        form_kwargs['job_type'] = Project.JobType.SURVEY
    else:
        FormClass = ProjectForm
        template = 'pms/project_form.html'
        title = 'แก้ไขโครงการ'

    # --- LOCK LOGIC ---
    # 1. Closed/Cancelled Lock
    if _check_project_lock(project, request):
        messages.warning(request, f'⚠️ ไม่สามารถแก้ไขงานที่ "{project.get_job_status_display()}" แล้วได้ (ต้องมีรหัสปลดล็อก)')
        return redirect('pms:project_detail', pk=project.pk)

    # 2. AI Queue Lock
    active_queue_item = project.service_tasks.filter(
        status__in=['PENDING', 'SCHEDULED', 'IN_PROGRESS']
    ).first()

    if active_queue_item:
        messages.warning(
            request, 
            f'⚠️ ไม่สามารถแก้ไขงานนี้ได้เนื่องจากอยู่ในคิวบริการ ({active_queue_item.get_status_display()}) '
            'กรุณาจัดการในหน้า AI Queue ให้เสร็จสิ้นหรือยกเลิกก่อน'
        )
        return redirect('pms:project_detail', pk=project.pk)
    # ------------------


    if request.method == 'POST':
        # เก็บสถานะเดิมไว้ตรวจสอบการข้ามขั้นตอน
        old_status = project.status
        form = FormClass(request.POST, **form_kwargs)
        if form.is_valid():
            project = form.save(commit=False)
            new_status = project.status

            # ตรวจสอบการข้ามขั้นตอน (Jump Status Warning)
            if old_status != new_status:
                is_jumped = _check_skipped_steps(project.job_type, old_status, new_status)
                if is_jumped:
                    messages.info(request, "⚠️ คุณได้ทำระบบเปลี่ยนสถานะแบบข้ามขั้นตอนการทำงาน (Jump Status) เรียบร้อย")
            
            project._changed_by_user = request.user
            project.save()
            form.save_m2m()
            messages.success(request, f'อัปเดต{title.replace("แก้ไข", "")}สำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
        else:
            # แจ้ง Error ให้ชัดเจนหาก validation ไม่ผ่าน
            for error in form.non_field_errors():
                messages.error(request, error)
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = FormClass(**form_kwargs)

    return render(request, template, {'form': form, 'title': title, 'theme_color': theme_color})


def _check_skipped_steps(job_type, old_status_key, new_status_key):
    """
    ตรวจสอบว่าผู้ใช้เปลี่ยนสถานะข้ามขั้นตอนไปมากกว่า 1 ขั้นไปข้างหน้า (Forward Jump) หรือไม่
    """
    from .models import JobStatus
    steps = list(JobStatus.objects.filter(job_type=job_type, is_active=True).order_by('sort_order').values_list('status_key', flat=True))

    if not steps:
        return False

    try:
        old_idx = steps.index(old_status_key)
        new_idx = steps.index(new_status_key)
        return new_idx > old_idx + 1
    except ValueError:
        return False

# เพิ่มรายการสินค้า/บริการเข้าโครงการ — ป้องกันการเพิ่มเมื่อโครงการถูกล็อก
@login_required
def item_add(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if _check_project_lock(project, request):
        messages.error(request, 'ไม่สามารถเพิ่มรายการในงานที่ปิดจบหรือยกเลิกแล้วได้')
        return redirect('pms:project_detail', pk=project.pk)
    if request.method == 'POST':
        form = ProductItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.project = project
            item.save()
            messages.success(request, 'เพิ่มรายการสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = ProductItemForm()
    return render(request, 'pms/item_form.html', {'form': form, 'project': project, 'title': f'เพิ่มรายการใน {project.name}'})

# แก้ไขรายการสินค้า/บริการที่อยู่ในโครงการ — ป้องกันการแก้ไขเมื่อโครงการถูกล็อก
@login_required
def item_update(request, item_id):
    item = get_object_or_404(ProductItem, pk=item_id)
    project = item.project
    if _check_project_lock(project, request):
        messages.error(request, 'ไม่สามารถแก้ไขรายการในงานที่ปิดจบหรือยกเลิกแล้วได้')
        return redirect('pms:project_detail', pk=project.pk)
    if request.method == 'POST':
        form = ProductItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'แก้ไขรายการสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = ProductItemForm(instance=item)
    return render(request, 'pms/item_form.html', {'form': form, 'project': project, 'title': f'แก้ไขรายการ {item.name}'})

# ลบรายการสินค้าออกจากโครงการ
@login_required
def item_delete(request, item_id):
    item = get_object_or_404(ProductItem, pk=item_id)
    project_pk = item.project.pk
    item.delete()
    messages.success(request, 'ลบรายการสำเร็จ')
    return redirect('pms:project_detail', pk=project_pk)

# นำเข้ารายการสินค้าจากไฟล์ Excel พร้อมประมวลผลยอดรวมอัตโนมัติ
@login_required
def item_import_excel(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if _check_project_lock(project, request):
        messages.error(request, 'ไม่สามารถแก้ไขรายการในงานที่ปิดจบหรือยกเลิกแล้วได้')
        return redirect('pms:project_detail', pk=project.pk)
        
    if request.method == 'POST':
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            messages.error(request, 'กรุณาอัปโหลดไฟล์ Excel')
            return redirect('pms:item_import_excel', project_id=project.pk)
            
        try:
            import pandas as pd
            if excel_file.name.endswith('.csv'):
                df = pd.read_csv(excel_file)
            else:
                df = pd.read_excel(excel_file)
                
            # Expected columns: ชื่อรายการ, ประเภท (optional)
            df.columns = df.columns.astype(str).str.strip()
            
            success_count = 0
            for index, row in df.iterrows():
                name = str(row.get('ชื่อรายการ', '')).strip()
                if not name or name.lower() == 'nan':
                    continue
                    
                # Default values
                item_type = ProductItem.ItemType.PRODUCT
                type_val = str(row.get('ประเภท', '')).strip()
                if type_val and 'บริการ' in type_val:
                    item_type = ProductItem.ItemType.SERVICE
                
                try:
                    qty = int(row.get('จำนวน', 1) or 1)
                except:
                    qty = 1
                    
                try:
                    cost = Decimal(str(row.get('ต้นทุน', 0) or 0))
                except:
                    cost = Decimal('0')
                    
                try:
                    price = Decimal(str(row.get('ราคาขาย', 0) or 0))
                except:
                    price = Decimal('0')
                
                ProductItem.objects.create(
                    project=project,
                    item_type=item_type,
                    name=name[:255],
                    description=str(row.get('รายละเอียด', '')).strip() if 'รายละเอียด' in df.columns else '',
                    quantity=qty,
                    unit_cost=cost,
                    unit_price=price
                )
                success_count += 1
                
            messages.success(request, f'นำเข้าข้อมูลสินค้า/บริการสำเร็จ {success_count} รายการ')
            return redirect('pms:project_detail', pk=project.pk)
            
        except Exception as e:
            messages.error(request, f'เกิดข้อผิดพลาดในการอ่านไฟล์: อาจไม่ใช่รูปแบบที่ถูกต้อง ({str(e)})')
            return redirect('pms:item_import_excel', project_id=project.pk)
            
    return render(request, 'pms/item_import.html', {
        'project': project,
        'title': f'นำเข้าข้อมูลจาก Excel'
    })

# ดาวน์โหลดไฟล์เทมเพลต Excel สำหรับใช้ในการนำเข้าข้อมูลรายการสินค้า
@login_required
def download_item_template(request):
    import pandas as pd
    import io
    from django.http import HttpResponse
    
    df = pd.DataFrame({
        'ชื่อรายการ': ['กล้องวงจรปิด', 'ค่าแรงติดตั้ง', 'สาย LAN CAT6', 'บริการเซ็ตระบบเครือข่าย'],
        'ประเภท': ['สินค้า', 'บริการ', 'สินค้า', 'บริการ'],
        'จำนวน': [5, 1, 100, 1],
        'ราคาขาย': [2500, 5000, 15, 2000],
        'รายละเอียด': ['2MP Full Color', 'หน้างานลูกค้า', ' เมตร', 'Setup Router'],
    })
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Template')
        
    output.seek(0)
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="import_items_template.xlsx"'
    return response

# Customer Views
# รายการลูกค้าทั้งหมดในระบบ (Customer List)
@login_required
def customer_list(request):
    customers = Customer.objects.all().select_related('sla_plan').order_by('name')
    return render(request, 'pms/customer_list.html', {'customers': customers})

# เพิ่มข้อมูลลูกค้าใหม่ (Create Customer)
@login_required
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'เพิ่มข้อมูลลูกค้าสำเร็จ')
            return redirect('pms:customer_list')
    else:
        form = CustomerForm()
    return render(request, 'pms/customer_form.html', {'form': form, 'title': 'เพิ่มลูกค้าใหม่'})

# แก้ไขข้อมูลลูกค้า (Update Customer)
@login_required
def customer_update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, 'อัปเดตข้อมูลลูกค้าสำเร็จ')
            return redirect('pms:customer_list')
    else:
        form = CustomerForm(instance=customer)
    return render(request, 'pms/customer_form.html', {'form': form, 'title': f'แก้ไขข้อมูล: {customer.name}'})

# ลบข้อมูลลูกค้าออกจากระบบ (Delete Customer)
@login_required
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    
    # Check if customer has any related data
    has_projects = customer.projects.exists()
    has_requests = customer.requests.exists()
    
    if has_projects or has_requests:
        problems = []
        if has_projects: problems.append(f"โครงการ ({customer.projects.count()} รายการ)")
        if has_requests: problems.append(f"คำขอ/Request ({customer.requests.count()} รายการ)")
        
        related_str = " และ ".join(problems)
        messages.error(request, f"❌ ไม่สามารถลบลูกค้า '{customer.name}' ได้ เนื่องจากมีการใช้งานอยู่ในข้อมูล: {related_str}")
        return redirect('pms:customer_list')

    if request.method == 'POST':
        customer_name = customer.name
        customer.delete()
        messages.success(request, f"ลบข้อมูลลูกค้า '{customer_name}' สำเร็จ")
        return redirect('pms:customer_list')
    
    return render(request, 'pms/formatted_confirm_delete.html', {
        'object': customer, 
        'type': 'Customer', 
        'cancel_url': 'pms:customer_list'
    })

# SLA Plan Views
# รายการแผนบริการ SLA ทั้งหมด (SLA Plan List)
@login_required
def sla_plan_list(request):
    plans = SLAPlan.objects.all().order_by('name')
    return render(request, 'pms/sla_plan_list.html', {'plans': plans})

# สร้างแผนบริการ SLA ใหม่ (Create SLA Plan)
@login_required
def sla_plan_create(request):
    if request.method == 'POST':
        form = SLAPlanForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'สร้างแผน SLA สำเร็จ')
            return redirect('pms:sla_plan_list')
    else:
        form = SLAPlanForm()
    return render(request, 'pms/sla_plan_form.html', {'form': form, 'title': 'สร้างแผน SLA ใหม่'})

# แก้ไขข้อมูลแผนบริการ SLA (Update SLA Plan)
@login_required
def sla_plan_update(request, pk):
    plan = get_object_or_404(SLAPlan, pk=pk)
    if request.method == 'POST':
        form = SLAPlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, 'อัปเดตแผน SLA สำเร็จ')
            return redirect('pms:sla_plan_list')
    else:
        form = SLAPlanForm(instance=plan)
    return render(request, 'pms/sla_plan_form.html', {'form': form, 'title': f'แก้ไขแผน SLA: {plan.name}'})

# Supplier Views
# รายการซัพพลายเออร์ทั้งหมด (Supplier List)
@login_required
def supplier_list(request):
    suppliers = Supplier.objects.all().order_by('-created_at')
    return render(request, 'pms/supplier_list.html', {'suppliers': suppliers})

# เพิ่มข้อมูลซัพพลายเออร์ใหม่ (Create Supplier)
@login_required
def supplier_create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'เพิ่มซัพพลายเออร์สำเร็จ')
            return redirect('pms:supplier_list')
    else:
        form = SupplierForm()
    return render(request, 'pms/supplier_form.html', {'form': form, 'title': 'เพิ่มซัพพลายเออร์ใหม่'})

# แก้ไขข้อมูลซัพพลายเออร์ (Update Supplier)
@login_required
def supplier_update(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, 'อัปเดตข้อมูลซัพพลายเออร์สำเร็จ')
            return redirect('pms:supplier_list')
    else:
        form = SupplierForm(instance=supplier)
    return render(request, 'pms/supplier_form.html', {'form': form, 'title': 'แก้ไขข้อมูลซัพพลายเออร์'})

# Project Owner Views
# รายการเจ้าของโครงการ/ผู้ติดต่อหลัก (Project Owner List)
@login_required
def project_owner_list(request):
    owners = ProjectOwner.objects.all().order_by('name')
    return render(request, 'pms/project_owner_list.html', {'owners': owners})

# เพิ่มผู้ติดต่อหลัก/เจ้าของโครงการใหม่ (Create Project Owner)
@login_required
def project_owner_create(request):
    if request.method == 'POST':
        form = ProjectOwnerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'เพิ่มเจ้าของโครงการสำเร็จ')
            return redirect('pms:project_owner_list')
    else:
        form = ProjectOwnerForm()
    return render(request, 'pms/project_owner_form.html', {'form': form, 'title': 'เพิ่มเจ้าของโครงการ'})

# แก้ไขข้อมูลผู้ติดต่อหลัก/เจ้าของโครงการ (Update Project Owner)
@login_required
def project_owner_update(request, pk):
    owner = get_object_or_404(ProjectOwner, pk=pk)
    if request.method == 'POST':
        form = ProjectOwnerForm(request.POST, instance=owner)
        if form.is_valid():
            form.save()
            messages.success(request, 'อัปเดตข้อมูลเจ้าของโครงการสำเร็จ')
            return redirect('pms:project_owner_list')
    else:
        form = ProjectOwnerForm(instance=owner)
    return render(request, 'pms/project_owner_form.html', {'form': form, 'title': 'แก้ไขข้อมูลเจ้าของโครงการ'})

# Report View
# แสดงหน้าใบเสนอราคา (Quotation View) สำหรับพิมพ์หรือแสดงให้ลูกค้า
@login_required
def project_quotation(request, pk):
    project = get_object_or_404(Project, pk=pk)
    # Calculate totals
    subtotal = project.total_value
    # Assuming 7% VAT for now as common practice in Thailand, or just show total if no VAT logic yet
    # Since model doesn't have vat logic yet, we'll keep it simple or calculate on fly
    vat = subtotal * Decimal('0.07')
    grand_total = subtotal + vat
    
    context = {
        'project': project,
        'items': project.items.all(),
        'subtotal': subtotal,
        'vat': vat,
        'grand_total': grand_total,
        'today': timezone.now()
    }
    return render(request, 'pms/project_quotation.html', context)

# Dashboard
# หน้าแดชบอร์ดหลักของระบบ PMS แสดงสรุปสถิติ มูลค่าโครงการ และงานที่เกินกำหนด (SLA Alerts)
@login_required
def dashboard(request):
    from django.db import models
    from django.db.models import Sum, Count, F, Q, Case, When, Value
    from django.db.models.functions import TruncMonth
    import json
    from datetime import datetime, timedelta
    from django.utils import timezone

    # 1. Get Filter Params
    now = timezone.now()
    mode = request.GET.get('mode', 'monthly') # daily, monthly, yearly
    
    month_param = request.GET.get('month')
    year_param = request.GET.get('year')
    date_param = request.GET.get('date')
    
    # Parse params with defaults
    month_filter = int(month_param) if month_param and month_param.isdigit() else now.month
    year_filter = int(year_param) if year_param and year_param.isdigit() else now.year
    
    date_obj = now.date()
    if date_param:
        try:
            date_obj = datetime.strptime(date_param, '%Y-%m-%d').date()
        except ValueError:
            pass
            
    import calendar
    
    # Determine Period Range
    # Determine Period Range
    if mode == 'daily':
        # Custom Date Range
        start_date_param = request.GET.get('start_date')
        end_date_param = request.GET.get('end_date')
        
        if start_date_param and end_date_param:
            try:
                s_date = datetime.strptime(start_date_param, '%Y-%m-%d').date()
                e_date = datetime.strptime(end_date_param, '%Y-%m-%d').date()
                # Ensure start <= end
                if s_date > e_date:
                    s_date, e_date = e_date, s_date
                
                start_of_period = timezone.make_aware(datetime.combine(s_date, datetime.min.time()))
                end_of_period = timezone.make_aware(datetime.combine(e_date, datetime.max.time()))
                year_filter = s_date.year # Base year for chart context
                
                # Context helpers
                date_filter_start = s_date
                date_filter_end = e_date
            except ValueError:
                # Fallback to single date if parse fails
                start_of_period = timezone.make_aware(datetime.combine(date_obj, datetime.min.time()))
                end_of_period = timezone.make_aware(datetime.combine(date_obj, datetime.max.time()))
                year_filter = date_obj.year
                date_filter_start = date_obj
                date_filter_end = date_obj
        else:
            # Single Date (Fallback to 'date' param or today)
            start_of_period = timezone.make_aware(datetime.combine(date_obj, datetime.min.time()))
            end_of_period = timezone.make_aware(datetime.combine(date_obj, datetime.max.time()))
            year_filter = date_obj.year
            date_filter_start = date_obj
            date_filter_end = date_obj
        
    elif mode == 'yearly':
        # Yearly: Jan 1 to Dec 31 of selected year
        start_of_period = timezone.make_aware(datetime(year_filter, 1, 1))
        end_of_period = timezone.make_aware(datetime(year_filter, 12, 31, 23, 59, 59))
        
    else: # monthly (default)
        # Monthly: 1st to Last day of selected month
        _, last_day = calendar.monthrange(year_filter, month_filter)
        start_of_period = timezone.make_aware(datetime(year_filter, month_filter, 1))
        end_of_period = timezone.make_aware(datetime(year_filter, month_filter, last_day, 23, 59, 59))

    projects_in_period = Project.objects.filter(created_at__range=[start_of_period, end_of_period])

    # 1. Total Accumulated Backlog (งานสะสม)
    # As requested: "งานสะสม คืองานที่มีสถานะทุกสถานะ ยกเว้น สถานะปิดจบ และยกเลิก"
    all_projects = Project.objects.all()
    
    total_projects = all_projects.exclude(status__in=[Project.Status.CLOSED, Project.Status.CANCELLED]).count()
    
    # 2. Active Projects (งานที่ดำเนินการ)
    # As requested: "งานที่กำลังดำเนินการ คือ งานที่อยู่ในหน้า รายการงานทั้งหมด และ ที่อยู่ใน AI Queue 
    # แต่ไม่รวมถึงงานที่มีสถานะ: จัดหาในงานขายและเช่า, รับแจ้งซ่อมในงานซ่อม, รวบรวมในงานโครงการ"
    from django.db.models import Q
    
    # Exclusion for PMS Projects only
    p_exclude = Q(status__in=[Project.Status.CLOSED, Project.Status.CANCELLED])
    p_exclude |= Q(job_type=Project.JobType.PROJECT, status=Project.Status.DRAFT)      # รวบรวมในงานโครงการ
    p_exclude |= Q(job_type=Project.JobType.SERVICE, status=Project.Status.SOURCING)   # จัดหาในงานขาย
    p_exclude |= Q(job_type=Project.JobType.RENTAL, status=Project.Status.SOURCING)    # จัดหาในงานเช่า
    p_exclude |= Q(job_type=Project.JobType.REPAIR, status=Project.Status.SOURCING)    # รับแจ้งซ่อมในงานซ่อม (Mapped Status)
    
    active_projects = all_projects.exclude(p_exclude).count()
    
    # ยอดรวมของงาน (Total Job Value) - PMS Projects only in period
    total_job_value = projects_in_period.aggregate(
        total=Sum(F('items__quantity') * F('items__unit_price'))
    )['total'] or 0
    
    # ยอดขาย (Actual Sales) - PMS Projects closed in period only
    actual_sales = Project.objects.filter(
        status=Project.Status.CLOSED,
        closed_at__range=[start_of_period, end_of_period]
    ).aggregate(
        total=Sum(F('items__quantity') * F('items__unit_price'))
    )['total'] or 0
 
    # Cancelled PMS Projects in period
    cancelled_count = all_projects.filter(
        status=Project.Status.CANCELLED,
        closed_at__range=[start_of_period, end_of_period]
    ).count()
    
    cancelled_value = all_projects.filter(
        status=Project.Status.CANCELLED,
        closed_at__range=[start_of_period, end_of_period]
    ).aggregate(total=Sum(F('items__quantity') * F('items__unit_price')))['total'] or 0

    # 2. Sales by Month (Full Year: Jan to Dec of selected year)
    start_of_year = timezone.make_aware(datetime(year_filter, 1, 1))
    end_of_year = timezone.make_aware(datetime(year_filter, 12, 31, 23, 59, 59))
    
    monthly_sales_qs = Project.objects.filter(created_at__range=[start_of_year, end_of_year])\
        .annotate(month=TruncMonth('created_at'))\
        .values('month', 'job_type', 'owner__name')\
        .annotate(revenue=Sum(F('items__quantity') * F('items__unit_price')))\
        .order_by('month')

    # Prepare data for Line Chart (Full 12 Months)
    months_labels = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
    project_series = [0] * 12
    service_series = [0] * 12
    repair_series = [0] * 12
    
    # 2.1 Sales Trends by Owner
    owner_trends = {} # { 'Owner Name': [0]*12 }
    
    # --- 2.2 Completion and Value Analysis ---
    completion_closed_series = [0] * 12
    completion_total_series = [0] * 12
    completion_closed_value = [0] * 12
    completion_total_value = [0] * 12

    # Query for 'TOTAL' (Created): PMS Projects
    total_projects_qs = Project.objects.filter(created_at__range=[start_of_year, end_of_year])\
        .annotate(month=TruncMonth('created_at'))\
        .values('month')\
        .annotate(
            count=Count('id'),
            value=Sum(F('items__quantity') * F('items__unit_price'))
        )
    for entry in total_projects_qs:
        m_index = entry['month'].month - 1
        completion_total_series[m_index] += entry['count']
        completion_total_value[m_index] += float(entry['value'] or 0)

    # Query for 'CLOSED' (Finished): PMS Projects only (Using closed_at)
    closed_projects_qs = Project.objects.filter(
        status=Project.Status.CLOSED,
        closed_at__range=[start_of_year, end_of_year]
    ).annotate(month=TruncMonth('closed_at'))\
     .values('month')\
     .annotate(
         count=Count('id'),
         value=Sum(F('items__quantity') * F('items__unit_price'))
     )
    for entry in closed_projects_qs:
        m_index = entry['month'].month - 1
        completion_closed_series[m_index] += entry['count']
        completion_closed_value[m_index] += float(entry['value'] or 0)

    for entry in monthly_sales_qs:
        m_index = entry['month'].month - 1
        jt = entry['job_type']
        owner_name = entry['owner__name'] or 'ไม่ระบุ'
        rev = float(entry['revenue'] or 0)
        
        # Trend by Type
        if jt == 'PROJECT':
            project_series[m_index] += rev
        elif jt == 'SERVICE':
            service_series[m_index] += rev
        elif jt == 'REPAIR':
            repair_series[m_index] += rev
            
        # Trend by Owner
        if owner_name not in owner_trends:
            owner_trends[owner_name] = [0] * 12
        owner_trends[owner_name][m_index] += rev

    # Convert owner trends to Chart.js dataset format
    owner_trend_datasets = []
    # Use a set of colors for owners
    colors = ['#4f46e5', '#10b981', '#f59e0b', '#7c3aed', '#ec4899', '#06b6d4', '#8b5cf6', '#f97316']
    for i, (name, data) in enumerate(owner_trends.items()):
        if sum(data) > 0: # Only include owners with sales
            owner_trend_datasets.append({
                'label': name,
                'data': data,
                'borderColor': colors[i % len(colors)],
                'backgroundColor': colors[i % len(colors)],
                'tension': 0.4,
                'fill': False,
                'pointRadius': 4,
                'borderWidth': 3
            })

    # 3. Sales by Person (Project Owner) - Yearly
    sales_by_owner = ProjectOwner.objects.annotate(
        total_sales=Sum(
            Case(
                When(
                    projects__status=Project.Status.CLOSED,
                    projects__closed_at__range=[start_of_year, end_of_year], 
                    then=F('projects__items__quantity') * F('projects__items__unit_price')
                ),
                default=0,
                output_field=DecimalField(max_digits=15, decimal_places=2)
            )
        ),
        job_count=Count(
            'projects',
            filter=Q(
                projects__status=Project.Status.CLOSED,
                projects__closed_at__range=[start_of_year, end_of_year]
            ),
            distinct=True
        )
    ).order_by('-total_sales')

    owner_names = [o.name for o in sales_by_owner if o.total_sales and o.total_sales > 0]
    owner_sales = [float(o.total_sales or 0) for o in sales_by_owner if o.total_sales and o.total_sales > 0]

    # 4. Job Type Distribution (Pie Chart) - Filtered by period (Keep current period/mode for specific insights)
    # Actually, Pie chart usually reflects the current view. Let's keep it as 'projects_in_period' (Monthly/Daily as selected)
    type_map = {
        'PROJECT': {'label': 'โครงการ', 'value': 0},
        'SERVICE': {'label': 'งานบริการขาย', 'value': 0},
        'REPAIR': {'label': 'งานแจ้งซ่อม', 'value': 0},
    }
    
    type_dist_qs = projects_in_period.values('job_type').annotate(
        value=Sum(F('items__quantity') * F('items__unit_price'))
    )
    
    for d in type_dist_qs:
        jt = d['job_type']
        if jt in type_map:
            type_map[jt]['value'] = float(d['value'] or 0)

    type_labels = [type_map['PROJECT']['label'], type_map['SERVICE']['label'], type_map['REPAIR']['label']]
    type_values = [type_map['PROJECT']['value'], type_map['SERVICE']['value'], type_map['REPAIR']['value']]

    # 5. Top 10 Customers - From "All Projects List" (PMS Only) with status CLOSED
    # User: "10 อันดับลูกค้า คือ รายชื่อลูกค้าในรายการงานทั้งหมด ที่มีสถานะปิดจบ หรือปิดงานซ่อม ในช่วงเวลานั้นๆ"
    # Note: "ปิดงานซ่อม" = PMS Project with job_type=REPAIR and status=CLOSED (same CLOSED status)
    # So we only query PMS Customer model, filtering by status=CLOSED within the selected period.
    
    top_customers = Customer.objects.annotate(
        closed_revenue=Sum(
            Case(
                When(projects__status=Project.Status.CLOSED,
                     projects__closed_at__range=[start_of_period, end_of_period],
                     then=F('projects__items__quantity') * F('projects__items__unit_price')),
                default=Value(0),
                output_field=DecimalField(max_digits=15, decimal_places=2)
            )
        )
    ).filter(closed_revenue__gt=0).order_by('-closed_revenue')[:10]

    customer_labels = [c.name for c in top_customers]
    customer_closed_sales = [float(c.closed_revenue or 0) for c in top_customers]
    customer_active_sales = [0] * len(top_customers)  # Only showing closed revenue per user request
    
    # For compatibility with template which expects active vs closed
    # We will just show Closed bar (Green) and 0 for Active.

    # Calculate percentages for progress bars
    max_sales = max(owner_sales) if owner_sales else 0
    for owner in sales_by_owner:
        if max_sales > 0:
            owner.performance_pct = (float(owner.total_sales or 0) / max_sales) * 100
        else:
            owner.performance_pct = 0

    # Choices for filter
    month_choices = [
        (1, 'มกราคม'), (2, 'กุมภาพันธ์'), (3, 'มีนาคม'), (4, 'เมษายน'),
        (5, 'พฤษภาคม'), (6, 'มิถุนายน'), (7, 'กรกฎาคม'), (8, 'สิงหาคม'),
        (9, 'กันยายน'), (10, 'ตุลาคม'), (11, 'พฤศจิกายน'), (12, 'ธันวาคม')
    ]
    year_choices = range(now.year - 2, now.year + 2)


    context = {
        'mode': mode,
        'date_filter': date_obj.strftime('%Y-%m-%d'), 
        'date_start': date_filter_start.strftime('%Y-%m-%d') if 'date_filter_start' in locals() else date_obj.strftime('%Y-%m-%d'),
        'date_end': date_filter_end.strftime('%Y-%m-%d') if 'date_filter_end' in locals() else date_obj.strftime('%Y-%m-%d'),
        
        'total_projects': total_projects,
        'active_projects': active_projects,
        'total_job_value': total_job_value,
        'actual_sales': actual_sales,
        'cancelled_count': cancelled_count,
        'cancelled_value': cancelled_value,
        'month_filter': month_filter,
        'year_filter': year_filter,
        'month_choices': month_choices,
        'year_choices': year_choices,
        
        # Chart Data
        'chart_months': json.dumps(months_labels),
        'chart_project_series': json.dumps(project_series),
        'chart_service_series': json.dumps(service_series),
        'chart_repair_series': json.dumps(repair_series),
        'chart_owner_trends': json.dumps(owner_trend_datasets),
        'chart_completion_total': json.dumps(completion_total_series),
        'chart_completion_closed': json.dumps(completion_closed_series),
        'chart_completion_total_value': json.dumps(completion_total_value),
        'chart_completion_closed_value': json.dumps(completion_closed_value),
        
        'chart_owners': json.dumps(owner_names),
        'chart_owner_sales': json.dumps(owner_sales),
        
        'chart_type_labels': json.dumps(type_labels),
        'chart_type_values': json.dumps(type_values),
        
        'chart_customers': json.dumps(customer_labels),
        'chart_customer_active': json.dumps(customer_active_sales),
        'chart_customer_closed': json.dumps(customer_closed_sales),
        
        'sales_by_owner': sales_by_owner,
    }
    return render(request, 'pms/dashboard.html', context)

# Customer Requirement Views
# รายการความต้องการของลูกค้า (Customer Requirements/Leads)
@login_required
def requirement_list(request):
    requirements = CustomerRequirement.objects.all().order_by('-created_at')
    return render(request, 'pms/requirement_list.html', {'requirements': requirements})

# บันทึกความต้องการใหม่ของลูกค้า (Create Lead)
@login_required
def requirement_create(request):
    if request.method == 'POST':
        form = CustomerRequirementForm(request.POST)
        if form.is_valid():
            requirement = form.save()
            # Handle file uploads
            files = request.FILES.getlist('attachments')
            for f in files:
                ProjectFile.objects.create(
                    requirement=requirement,
                    file=f,
                    original_name=f.name,
                )
            file_count = len(files)
            msg = 'บันทึกความต้องการสำเร็จ'
            if file_count > 0:
                msg += f' (แนบไฟล์ {file_count} รายการ)'
            messages.success(request, msg)
            return redirect('pms:requirement_list')
    else:
        form = CustomerRequirementForm()
    return render(request, 'pms/requirement_form.html', {'form': form, 'title': 'บันทึกความต้องการเบื้องต้น'})

@login_required
def requirement_update(request, pk):
    requirement = get_object_or_404(CustomerRequirement, pk=pk)
    if request.method == 'POST':
        form = CustomerRequirementForm(request.POST, instance=requirement)
        if form.is_valid():
            form.save()
            # Handle file uploads
            files = request.FILES.getlist('attachments')
            for f in files:
                ProjectFile.objects.create(
                    requirement=requirement,
                    file=f,
                    original_name=f.name,
                )
            messages.success(request, 'แก้ไขความต้องการสำเร็จ')
            return redirect('pms:requirement_list')
    else:
        form = CustomerRequirementForm(instance=requirement)
    existing_files = requirement.files.all()
    return render(request, 'pms/requirement_form.html', {
        'form': form, 'title': 'แก้ไขความต้องการ',
        'requirement': requirement, 'existing_files': existing_files,
    })

@login_required
def requirement_delete(request, pk):
    requirement = get_object_or_404(CustomerRequirement, pk=pk)
    requirement.delete()
    messages.success(request, 'ลบรายการความต้องการสำเร็จ')
    return redirect('pms:requirement_list')

# แปลงความต้องการลูกค้า (Lead) ให้กลายเป็นโครงการจริง (Convert to Project)
@login_required
def create_project_from_requirement(request, pk):
    requirement = get_object_or_404(CustomerRequirement, pk=pk)
    
    # Check query param for job type
    job_type = request.GET.get('type', 'PROJECT') # Default to PROJECT if not specified
    
    # Special handling for REQUEST type (CustomerRequest)
    if job_type == 'REQUEST':
        if requirement.is_converted:
            # Maybe it was already converted to something else? 
            # Or previously converted to request? 
            # For now, let's treat it similarly: if converted, redirect.
            # But the 'project' field on requirement is a OneToOne to Project.
            # We don't have a direct link in requirement model to CustomerRequest yet (unless we added one).
            # The user didn't ask to link them strictly in DB, but logically convert it.
            # Let's perform conversion and mark is_converted = True.
            pass

        if request.method == 'POST':
            form = CustomerRequestForm(request.POST)
            if form.is_valid():
                req_obj = form.save(commit=False)
                # If we want to link requirement to this request, we might need a field.
                # Since we don't have one in CustomerRequirement model pointing to CustomerRequest,
                # we just mark requirement as converted.
                # However, files need to be moved.
                req_obj._changed_by_user = request.user
                req_obj.save()

                # Mark requirement as converted
                # Note: requirement.project will be null, but is_converted=True acts as flag.
                requirement.is_converted = True
                requirement.save()
                
                # Transfer files: update related_name / foreign key
                # ProjectFile has 'customer_request' field now.
                files = requirement.files.all()
                for f in files:
                    f.customer_request = req_obj
                    f.save()

                messages.success(request, "สร้างคำขอจากความต้องการสำเร็จ")
                return redirect('pms:request_detail', pk=req_obj.pk)
        else:
            initial_data = {
                'description': requirement.content,
                'title': f"คำขอจาก Leads ({requirement.created_at.strftime('%d/%m/%Y')})",
                'status': 'RECEIVED',
            }
            # Try to pre-fill owner
            try:
                owner = ProjectOwner.objects.filter(email=request.user.email).first()
                if owner:
                    initial_data['owner'] = owner
            except:
                pass
            form = CustomerRequestForm(initial=initial_data)
            
        return render(request, 'pms/request_form.html', {
            'form': form, 
            'title': 'สร้างคำขอจากความต้องการ',
        })


    if requirement.is_converted:
        messages.warning(request, 'รายการนี้ถูกสร้างเป็นงานแล้ว')
        if requirement.project:
            return redirect('pms:project_detail', pk=requirement.project.pk)
        return redirect('pms:requirement_list')

    if request.method == 'POST':
        if job_type in ['SERVICE', 'REPAIR']:
             form = SalesServiceJobForm(request.POST, job_type=job_type)
        else:
             form = ProjectForm(request.POST)

        if form.is_valid():
            project = form.save(commit=False)
            project.job_type = job_type
            project._changed_by_user = request.user
            project.save()
            # Auto-create value item
            pv = form.cleaned_data.get('project_value')
            _create_project_value_item(project, pv)
            
            # Link Requirement
            requirement.is_converted = True
            requirement.project = project
            requirement.save()

            # Transfer files from requirement to project
            requirement.files.update(project=project)
            
            job_label = 'โครงการ'
            if job_type == 'SERVICE': job_label = 'งานบริการขาย'
            elif job_type == 'REPAIR': job_label = 'ใบแจ้งซ่อม'

            messages.success(request, f"สร้าง{job_label}จากความต้องการสำเร็จ")
            return redirect('pms:project_detail', pk=project.pk)
    else:
        # Pre-fill description
        job_label = 'โครงการ'
        status = Project.Status.DRAFT
        theme_color = 'primary'
        
        if job_type == 'SERVICE': 
            job_label = 'งานขาย'
            status = Project.Status.SOURCING
            theme_color = 'success'
        elif job_type == 'REPAIR':
            job_label = 'แจ้งซ่อม'
            status = Project.Status.SOURCING
            theme_color = 'warning'

        initial_data = {
            'description': requirement.content,
            'name': f"{job_label}ใหม่ ({requirement.created_at.strftime('%d/%m/%Y')})",
            'status': status,
        }
        
        if job_type in ['SERVICE', 'REPAIR']:
            form = SalesServiceJobForm(initial=initial_data, job_type=job_type)
            template = 'pms/service_form.html'
            title = f'สร้าง{job_label}จากความต้องการ'
        else:
            form = ProjectForm(initial=initial_data)
            template = 'pms/project_form.html'
            title = 'สร้างโครงการจากความต้องการ'

    return render(request, template, {
        'form': form, 
        'title': title,
        'theme_color': theme_color if 'theme_color' in locals() else 'primary',
    })


# ===== AI Service Queue Views =====

# หน้าจอแดชบอร์ดสำหรับบริหารจัดการคิวงานบริการแบบอัจฉริยะ (AI Service Queue Dashboard)
# ระบบจะแบ่งงานออกเป็น 3 ส่วนหลัก: 
#   1. งานที่รอจัดคิว (Pending) สำหรับ Admin ระบุทีมและวันที่
#   2. งานที่จัดคิวแล้ว (Scheduled) โดยแสดงแยกตามวันที่
#   3. สรุปผลงานที่เสร็จสิ้น (Completed)
@login_required
def service_queue_dashboard(request):
    """
    AI Queue Dashboard:
    Block 1: Pending tasks (synced from Projects) — admin sets team + date
    Block 2+: Scheduled tasks grouped by date
    """
    from .models import ServiceQueueItem, ServiceTeam, TeamMessage
    from collections import OrderedDict

    today = timezone.now().date()

    # Sync new tasks from Projects
    try:
        from utils.ai_service_manager import sync_projects_to_queue
        synced = sync_projects_to_queue()
        if synced > 0:
            messages.info(request, f"🔄 ดึงงานใหม่จากระบบ {synced} รายการ")
    except Exception as e:
        messages.warning(request, f"⚠️ ไม่สามารถดึงงานใหม่: {str(e)}")

    # Block 1: Pending tasks (not yet scheduled)
    pending_tasks = ServiceQueueItem.objects.filter(
        status__in=['PENDING', 'INCOMPLETE']
    ).select_related('project').prefetch_related('assigned_teams').order_by('deadline', 'created_at')

    # Block 2+: Scheduled/In-progress tasks grouped by date
    scheduled_tasks = ServiceQueueItem.objects.filter(
        status__in=['SCHEDULED', 'IN_PROGRESS']
    ).select_related('project').prefetch_related('assigned_teams').order_by('scheduled_date', 'scheduled_time')

    # Group by date
    date_groups = OrderedDict()
    for task in scheduled_tasks:
        d = task.scheduled_date or today
        if d not in date_groups:
            date_groups[d] = []
        date_groups[d].append(task)

    # Incomplete (carry-over)
    incomplete_tasks = ServiceQueueItem.objects.none()

    # Teams for dropdown
    teams = ServiceTeam.objects.filter(is_active=True)

    # Stats
    completed_count = ServiceQueueItem.objects.filter(status='COMPLETED').count()

    context = {
        'pending_tasks': pending_tasks,
        'date_groups': date_groups,
        'incomplete_tasks': incomplete_tasks,
        'teams': teams,
        'today': today,
        'pending_count': pending_tasks.count(),
        'scheduled_count': scheduled_tasks.count(),
        'incomplete_count': incomplete_tasks.count(),
        'completed_count': completed_count,
    }
    return render(request, 'pms/service_queue_dashboard.html', context)


# ตั้งค่าทีมและวันที่สำหรับงานที่ยังรอจัดคิว (PENDING → เตรียม SCHEDULED)
@login_required
def update_pending_task(request, task_id):
    """Admin กำหนด assigned_teams (หลายทีม) และ scheduled_date ให้งานก่อนจัดคิวอัตโนมัติ"""
    from .models import ServiceQueueItem, ServiceTeam

    task = get_object_or_404(ServiceQueueItem, pk=task_id)
    if request.method == 'POST':
        team_ids = request.POST.getlist('team')
        date_str = request.POST.get('scheduled_date')

        # อัปเดต M2M teams (set() จะลบทีมเดิมและใส่ทีมใหม่ทั้งหมด)
        teams = ServiceTeam.objects.filter(pk__in=team_ids) if team_ids else ServiceTeam.objects.none()
        task.assigned_teams.set(teams)

        if date_str:
            try:
                task.scheduled_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        elif not date_str and 'scheduled_date' in request.POST:
            task.scheduled_date = None

        task.remarks = request.POST.get('remarks', task.remarks)
        task.save()
        messages.success(request, f"✅ อัปเดต: {task.title}")

    return redirect('pms:service_queue_dashboard')


# ระบบการวางแผนจัดคิวงานแบบอัตโนมัติ (AI Auto-Scheduling)
# เมื่อเรียกใช้ระบบจะทำการย้ายงานที่มีการระบุทีมและวันที่แล้วจาก 'Pending' ไปเป็น 'Scheduled'
# พร้อมทั้งส่งข้อความแจ้งเตือนอัตโนมัติไปยังกลุ่มแชทของทีมงานที่เกี่ยวข้อง
@login_required
def auto_schedule_tasks(request):
    """AI schedule: move pending tasks (with date+team set) to SCHEDULED status."""
    if request.method == 'POST':
        try:
            from utils.ai_service_manager import schedule_queue_items
            count = schedule_queue_items()
            if count > 0:
                messages.success(request, f"🤖 AI จัดคิวเรียบร้อย: {count} งาน พร้อมส่งข้อความไปทีม")
            else:
                messages.warning(request, "⚠️ ไม่มีงานที่พร้อมจัดคิว (ต้องใส่ทีม + วันที่ก่อน)")
        except Exception as e:
            messages.error(request, f"❌ เกิดข้อผิดพลาด: {str(e)}")

    return redirect('pms:service_queue_dashboard')


# ซิงค์ข้อมูลงานในมือถือ/หน้างาน เข้าสู่ระบบคิว AI
@login_required
def force_sync_queue(request):
    """Manually trigger sync from Projects to Queue."""
    try:
        from utils.ai_service_manager import sync_projects_to_queue
        count = sync_projects_to_queue()
        messages.success(request, f"🔄 กวาดตรวจข้อมูลเสร็จสิ้น: พบงานใหม่ {count} รายการ")
    except Exception as e:
        messages.error(request, f"❌ เกิดข้อผิดพลาดในการกวาดข้อมูล: {str(e)}")
    return redirect('pms:service_queue_dashboard')


# อัปเดตสถานะงานในคิว + บันทึกโน้ตผลงาน — ใช้จากปุ่มในหน้า AI Queue Dashboard
# ถ้า IN_PROGRESS: บันทึก responded_at บน Project, ถ้า INCOMPLETE: reset วันที่/ทีม
@login_required
def update_task_status(request, task_id):
    """อัปเดตสถานะ ServiceQueueItem พร้อม timestamp บันทึกโน้ตสะสม"""
    from .models import ServiceQueueItem

    task = get_object_or_404(ServiceQueueItem, pk=task_id)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        note = request.POST.get('note', '')

        if new_status:
            task.status = new_status
            
            # Record response time on project when task starts
            if new_status == 'IN_PROGRESS' and task.project and not task.project.responded_at:
                task.project.responded_at = timezone.now()
                task.project.save()

            if new_status in ['COMPLETED', 'CANCELLED']:
                if new_status == 'COMPLETED':
                    task.completed_at = timezone.now()
                if task.project:
                    task.project._changed_by_user = request.user
            elif new_status == 'INCOMPLETE':
                task.scheduled_date = None
                task.scheduled_time = None
                task.assigned_teams.clear()

        task.remarks = request.POST.get('remarks', task.remarks)
        
        if note:

            timestamp = timezone.now().strftime('%d/%m %H:%M')
            prev = task.completion_note
            task.completion_note = f"{prev}\n[{timestamp}] {note}".strip()

        task.save()
        messages.success(request, f"✅ อัปเดต: {task.title} → {task.get_status_display()}")

    return redirect('pms:service_queue_dashboard')


@login_required
def send_queue_notifications(request):
    """Manually send notifications to teams for a specific date."""
    if request.method == 'POST':
        date_str = request.POST.get('date')
        if not date_str:
            messages.error(request, "❌ ไม่ระบุวันที่")
            return redirect('pms:service_queue_dashboard')

        try:
            from datetime import datetime
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            from .models import ServiceQueueItem
            from utils.ai_service_manager import _send_schedule_messages
            from chat.models import ChatRoom, ChatMessage
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            from django.utils import timezone

            # Get scheduled items for this date
            items = ServiceQueueItem.objects.filter(
                scheduled_date=target_date,
                status__in=['SCHEDULED', 'IN_PROGRESS']
            ).prefetch_related('assigned_teams').order_by('scheduled_time')

            if items.exists():
                _send_schedule_messages(items)

                # ส่งแจ้งเตือนคิวงานรวมเข้าสู่ "ศูนย์แชทกลาง (Chat Room)" ห้อง PMS โดยตรง
                pms_room = ChatRoom.objects.filter(app_category='pms', project__isnull=True, is_active=True).first()
                if pms_room:
                    from utils.ai_service_manager import _clean_description, _get_customer_name
                    import html as _html

                    # สีประจำทีม — วนซ้ำถ้ามีมากกว่า 6 ทีม
                    _TEAM_COLORS = [
                        {'bg': '#dbeafe', 'text': '#1e40af', 'border': '#93c5fd'},  # blue
                        {'bg': '#dcfce7', 'text': '#166534', 'border': '#86efac'},  # green
                        {'bg': '#ede9fe', 'text': '#5b21b6', 'border': '#c4b5fd'},  # purple
                        {'bg': '#ffedd5', 'text': '#9a3412', 'border': '#fdba74'},  # orange
                        {'bg': '#fce7f3', 'text': '#9d174d', 'border': '#f9a8d4'},  # pink
                        {'bg': '#ccfbf1', 'text': '#115e59', 'border': '#5eead4'},  # teal
                    ]
                    _PRIO_BADGE = {
                        'CRITICAL': '<span style="background:#fee2e2;color:#b91c1c;padding:1px 6px;border-radius:4px;font-size:0.72rem;font-weight:700;margin-left:6px;">เร่งด่วนมาก</span>',
                        'HIGH':     '<span style="background:#ffedd5;color:#c2410c;padding:1px 6px;border-radius:4px;font-size:0.72rem;font-weight:700;margin-left:6px;">เร่งด่วน</span>',
                        'NORMAL': '', 'LOW': '',
                    }

                    total_tasks = items.count()
                    thai_date   = target_date.strftime('%d/%m/') + str(target_date.year + 543)

                    # จัดกลุ่มงานตามทีม
                    team_buckets: dict = {}
                    for item in items.prefetch_related('assigned_teams', 'project__customer'):
                        all_teams = list(item.assigned_teams.all())
                        if all_teams:
                            for t in all_teams:
                                team_buckets.setdefault(t.name, []).append((item, all_teams))
                        else:
                            team_buckets.setdefault('ยังไม่ระบุทีม', []).append((item, []))

                    # ── สร้าง HTML table ──────────────────────────────────
                    parts = [
                        '<div style="font-family:inherit;font-size:0.83rem;min-width:300px;max-width:460px;border-radius:10px;overflow:hidden;border:1px solid #e2e8f0;box-shadow:0 2px 8px rgba(0,0,0,0.08);">',
                        '<div style="background:#1e293b;color:#f8fafc;padding:9px 14px;display:flex;justify-content:space-between;align-items:center;">',
                        f'<span style="font-weight:700;font-size:0.88rem;">คิวงานประจำวัน {thai_date}</span>',
                        f'<span style="background:#334155;padding:2px 10px;border-radius:20px;font-size:0.75rem;">{total_tasks} งาน</span>',
                        '</div>',
                    ]

                    for t_idx, (t_name, task_pairs) in enumerate(team_buckets.items()):
                        clr = _TEAM_COLORS[t_idx % len(_TEAM_COLORS)]
                        parts += [
                            f'<div style="background:{clr["bg"]};color:{clr["text"]};padding:6px 14px;font-weight:700;font-size:0.8rem;border-top:2px solid {clr["border"]};display:flex;justify-content:space-between;">',
                            f'<span>{_html.escape(t_name)}</span>',
                            f'<span style="font-weight:400;opacity:0.75;">{len(task_pairs)} งาน</span>',
                            '</div>',
                            '<table style="width:100%;border-collapse:collapse;background:#ffffff;">',
                            '<tr style="background:#f8fafc;font-size:0.75rem;color:#94a3b8;font-weight:600;">',
                            '<td style="padding:4px 8px 4px 14px;width:28px;">#</td>',
                            '<td style="padding:4px 8px;width:50px;">เวลา</td>',
                            '<td style="padding:4px 14px 4px 8px;">งาน / ลูกค้า</td>',
                            '</tr>',
                        ]

                        for idx, (task, all_teams) in enumerate(task_pairs, 1):
                            time_str  = task.scheduled_time.strftime('%H:%M') if task.scheduled_time else '—:—'
                            prio_html = _PRIO_BADGE.get(getattr(task, 'priority', 'NORMAL'), '')
                            cust_name = _get_customer_name(task)
                            other     = [t.name for t in all_teams if t.name != t_name]
                            cross_str = f'  —  ร่วมกับ {", ".join(other)}' if other else ''
                            type_str  = task.get_task_type_display()
                            if task.deadline:
                                type_str += f'  ·  ครบ {task.deadline.strftime("%d/%m")}'
                            desc = _clean_description(task.title, task.description, max_len=70)

                            row_bg = '#ffffff' if idx % 2 == 1 else '#f8fafc'
                            border = 'border-top:1px solid #e2e8f0;' if idx > 1 else ''
                            parts += [
                                f'<tr style="background:{row_bg};{border}vertical-align:top;">',
                                f'<td style="padding:7px 8px 7px 14px;color:{clr["text"]};font-weight:700;">{idx}</td>',
                                f'<td style="padding:7px 8px;font-weight:700;color:#374151;white-space:nowrap;">{_html.escape(time_str)}</td>',
                                '<td style="padding:7px 14px 7px 8px;">',
                                f'<div style="font-weight:700;color:#111827;">{_html.escape(task.title)}{prio_html}</div>',
                                f'<div style="color:#6b7280;font-size:0.78rem;margin-top:2px;">{_html.escape(cust_name)}  ·  {_html.escape(type_str)}{_html.escape(cross_str)}</div>',
                            ]
                            if desc:
                                parts.append(f'<div style="color:#94a3b8;font-size:0.75rem;margin-top:2px;font-style:italic;">{_html.escape(desc)}</div>')
                            parts += ['</td>', '</tr>']

                        parts.append('</table>')

                    now_str = timezone.localtime(timezone.now()).strftime('%H:%M')
                    parts += [
                        f'<div style="background:#f8fafc;color:#94a3b8;padding:5px 14px;font-size:0.72rem;text-align:right;border-top:1px solid #e2e8f0;">ส่งอัตโนมัติ  {now_str}</div>',
                        '</div>',
                    ]
                    full_content = ''.join(parts)

                    chat_msg = ChatMessage.objects.create(
                        room=pms_room,
                        user=request.user,
                        content=full_content,
                        is_html=True,
                    )

                    # เปล่งสัญญาณออกไปยังระบบ WebSocket ของแชทให้ข้อความเด้งขึ้นมาแบบ Real-time
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f'chat_{pms_room.id}',
                        {
                            'type': 'chat_message',
                            'message': full_content,
                            'username': request.user.username,
                            'user_id': request.user.id,
                            'is_stt': False,
                            'is_html': True,
                            'image_url': None,
                            'file_url': None,
                            'latitude': None,
                            'longitude': None,
                            'location_name': '',
                            'timestamp': timezone.localtime(chat_msg.timestamp).strftime('%H:%M')
                        }
                    )

                messages.success(request, f"🚀 ส่งข้อความแจ้งเตือน และแบนเนอร์คิวงาน {target_date.strftime('%d/%m/%Y')} เข้าแชทเรียบร้อย")
            else:
                messages.warning(request, "⚠️ ไม่มีงานที่จัดคิวในวันนี้")
        except Exception as e:
            messages.error(request, f"❌ เกิดข้อผิดพลาด: {str(e)}")

    return redirect('pms:service_queue_dashboard')


# หน้าจอแชทสื่อสารภายในทีม (Team Messaging)
@login_required
def team_messages(request, team_id=None):
    """View messages for a specific team or all teams."""
    from .models import ServiceTeam, TeamMessage

    teams = ServiceTeam.objects.filter(is_active=True)

    if team_id:
        team = get_object_or_404(ServiceTeam, pk=team_id)
        team_msgs = TeamMessage.objects.filter(team=team).order_by('-created_at')[:20]
        team_msgs.filter(is_read=False).update(is_read=True)
    else:
        team = None
        team_msgs = TeamMessage.objects.all().order_by('-created_at')[:30]

    return render(request, 'pms/team_messages.html', {
        'teams': teams,
        'selected_team': team,
        'messages_list': team_msgs,
    })


# ===== Team Management Views — จัดการทีมบริการ =====

# ===== Skill CRUD Views =====

@login_required
def skill_list(request):
    from .models import Skill, ServiceTeam
    skills = Skill.objects.prefetch_related('teams').order_by('skill_type', 'name')
    return render(request, 'pms/skill_list.html', {
        'skills': skills,
        'active_count':   skills.filter(is_active=True).count(),
        'inactive_count': skills.filter(is_active=False).count(),
    })


@login_required
def skill_create(request):
    from .forms import SkillForm
    if request.method == 'POST':
        form = SkillForm(request.POST)
        if form.is_valid():
            skill = form.save()
            messages.success(request, f"✅ เพิ่มทักษะ '{skill.name}' เรียบร้อย")
            return redirect('pms:skill_list')
    else:
        form = SkillForm()
    return render(request, 'pms/skill_form.html', {'form': form, 'title': 'เพิ่มทักษะใหม่'})


@login_required
def skill_update(request, pk):
    from .models import Skill
    from .forms import SkillForm
    skill = get_object_or_404(Skill, pk=pk)
    if request.method == 'POST':
        form = SkillForm(request.POST, instance=skill)
        if form.is_valid():
            form.save()
            messages.success(request, f"✅ อัปเดตทักษะ '{skill.name}' เรียบร้อย")
            return redirect('pms:skill_list')
    else:
        form = SkillForm(instance=skill)
    return render(request, 'pms/skill_form.html', {
        'form': form, 'skill': skill,
        'title': f'แก้ไขทักษะ — {skill.name}',
    })


@login_required
def skill_delete(request, pk):
    from .models import Skill
    skill = get_object_or_404(Skill, pk=pk)
    if request.method == 'POST':
        name = skill.name
        skill.delete()
        messages.success(request, f"🗑️ ลบทักษะ '{name}' เรียบร้อย")
        return redirect('pms:skill_list')
    return render(request, 'pms/skill_confirm_delete.html', {
        'skill': skill,
        'team_count': skill.teams.count(),
    })


# รายการทีมบริการทั้งหมดในระบบ (Service Team List)
@login_required
@login_required
def team_list(request):
    """แสดงรายการทีมบริการทุกทีมเรียงตามชื่อ"""
    from .models import ServiceTeam
    teams = ServiceTeam.objects.prefetch_related('members').order_by('name')
    active_count   = teams.filter(is_active=True).count()
    inactive_count = teams.filter(is_active=False).count()
    return render(request, 'pms/team_list.html', {
        'teams':          teams,
        'active_count':   active_count,
        'inactive_count': inactive_count,
    })


# สร้างทีมบริการใหม่ พร้อมตั้งค่าสมาชิก, ทักษะ, งานสูงสุด/วัน และ webhook แจ้งเตือน
@login_required
def team_create(request):
    """สร้างทีมบริการใหม่ — รับค่า name, skills, members, webhook, lat/lng จากฟอร์ม"""
    from .models import ServiceTeam, Skill
    from django.contrib.auth.models import User

    if request.method == 'POST':
        name       = request.POST.get('name', '').strip()
        max_tasks  = int(request.POST.get('max_tasks_per_day', 5) or 5)
        is_active  = 'is_active' in request.POST
        member_ids = request.POST.getlist('members')
        skill_ids  = request.POST.getlist('team_skills')
        lat_raw    = request.POST.get('latitude', '').strip()
        lng_raw    = request.POST.get('longitude', '').strip()

        team = ServiceTeam.objects.create(
            name=name,
            max_tasks_per_day=max_tasks,
            is_active=is_active,
            base_address=request.POST.get('base_address', '').strip(),
            latitude=lat_raw or None,
            longitude=lng_raw or None,
            google_chat_webhook=request.POST.get('google_chat_webhook', '').strip(),
            line_token=request.POST.get('line_token', '').strip(),
        )
        team.members.set(member_ids)
        team.team_skills.set(skill_ids)
        messages.success(request, f"✅ สร้างทีม '{name}' เรียบร้อย")
        return redirect('pms:team_list')

    users  = User.objects.filter(is_active=True).order_by('first_name', 'username')
    skills = Skill.objects.filter(is_active=True).order_by('skill_type', 'name')
    return render(request, 'pms/team_form.html', {
        'users': users, 'skills': skills, 'title': 'สร้างทีมใหม่',
    })


# แก้ไขข้อมูลทีมบริการ — อัปเดตชื่อ, สมาชิก, ทักษะ และ webhook
@login_required
def team_update(request, pk):
    """แก้ไขข้อมูลทีมบริการที่มีอยู่"""
    from .models import ServiceTeam, Skill
    from django.contrib.auth.models import User

    team = get_object_or_404(ServiceTeam, pk=pk)

    if request.method == 'POST':
        lat_raw = request.POST.get('latitude', '').strip()
        lng_raw = request.POST.get('longitude', '').strip()
        team.name              = request.POST.get('name', team.name).strip()
        team.max_tasks_per_day = int(request.POST.get('max_tasks_per_day', team.max_tasks_per_day) or 5)
        team.is_active         = 'is_active' in request.POST
        team.base_address      = request.POST.get('base_address', '').strip()
        team.latitude          = lat_raw or None
        team.longitude         = lng_raw or None
        team.google_chat_webhook = request.POST.get('google_chat_webhook', '').strip()
        team.line_token          = request.POST.get('line_token', '').strip()
        team.save()
        team.members.set(request.POST.getlist('members'))
        team.team_skills.set(request.POST.getlist('team_skills'))
        messages.success(request, f"✅ อัปเดตทีม '{team.name}' เรียบร้อย")
        return redirect('pms:team_list')

    users  = User.objects.filter(is_active=True).order_by('first_name', 'username')
    skills = Skill.objects.filter(is_active=True).order_by('skill_type', 'name')
    current_skill_ids = list(team.team_skills.values_list('pk', flat=True))
    return render(request, 'pms/team_form.html', {
        'team': team, 'users': users, 'skills': skills,
        'current_skill_ids': current_skill_ids,
        'title': f'แก้ไขทีม — {team.name}',
    })


# ลบทีมบริการออกจากระบบ — ต้องผ่านหน้า confirm ก่อนลบจริง
@login_required
def team_delete(request, pk):
    """ลบทีมบริการ — ต้องยืนยันด้วยการ POST"""
    from .models import ServiceTeam, ServiceQueueItem
    team = get_object_or_404(ServiceTeam, pk=pk)
    if request.method == 'POST':
        name = team.name
        team.delete()
        messages.success(request, f"🗑️ ลบทีม '{name}' เรียบร้อย")
        return redirect('pms:team_list')
    active_tasks = ServiceQueueItem.objects.filter(
        assigned_teams=team,
        status__in=['PENDING', 'SCHEDULED', 'IN_PROGRESS'],
    ).count()
    return render(request, 'pms/team_confirm_delete.html', {
        'team': team,
        'active_tasks': active_tasks,
        'member_count': team.members.count(),
    })


# ===== File Management Views — จัดการไฟล์แนบโครงการ =====

# อัปโหลดไฟล์แนบเข้าโครงการ (รองรับหลายไฟล์พร้อมกัน)
@login_required
def project_file_upload(request, pk):
    """อัปโหลดไฟล์แนบเข้าโครงการ — บันทึกไฟล์จริงและ ProjectFile record"""
    project = get_object_or_404(Project, pk=pk)
    if request.method == 'POST':
        files = request.FILES.getlist('files')
        for f in files:
            ProjectFile.objects.create(
                project=project,
                file=f,
                original_name=f.name,
            )
        if files:
            messages.success(request, f'อัปโหลดไฟล์ {len(files)} รายการสำเร็จ')
    return redirect('pms:project_detail', pk=pk)


# ลบไฟล์แนบจากโครงการหรือ Requirement — ลบไฟล์จริงบน disk และ record ในฐานข้อมูล
@login_required
def project_file_delete(request, file_id):
    """ลบ ProjectFile — ลบไฟล์จริงด้วย .file.delete() และลบ record"""
    pf = get_object_or_404(ProjectFile, pk=file_id)
    project_pk = pf.project.pk if pf.project else None
    req_pk = pf.requirement.pk if pf.requirement else None
    pf.file.delete(save=False)  # Delete the actual file
    pf.delete()
    messages.success(request, 'ลบไฟล์สำเร็จ')
    if project_pk:
        return redirect('pms:project_detail', pk=project_pk)
    elif req_pk:
        return redirect('pms:requirement_update', pk=req_pk)
    return redirect('pms:requirement_list')


# ลบไฟล์แนบจาก Requirement — แยกออกจาก project_file_delete เพื่อ redirect กลับหน้า requirement
@login_required
def requirement_file_delete(request, file_id):
    """ลบไฟล์แนบของ Requirement — redirect กลับหน้าแก้ไข requirement"""
    pf = get_object_or_404(ProjectFile, pk=file_id)
    req_pk = pf.requirement.pk if pf.requirement else None
    pf.file.delete(save=False)
    pf.delete()
    messages.success(request, 'ลบไฟล์สำเร็จ')
    if req_pk:
        return redirect('pms:requirement_update', pk=req_pk)
    return redirect('pms:requirement_list')


# ยกเลิกโครงการ — เปลี่ยนสถานะเป็น CANCELLED และล็อกการแก้ไข
@login_required
def project_cancel(request, pk):
    """ยกเลิกโครงการ: ตั้งสถานะเป็น CANCELLED, บันทึก user ที่ทำการ, redirect กลับ detail"""
    project = get_object_or_404(Project, pk=pk)
    
    # Security: If already CLOSED or CANCELLED, it's already locked.
    # But usually this button will only be visible/active if not locked.
    if project.status in [Project.Status.CLOSED, Project.Status.CANCELLED]:
        messages.error(request, "โครงการนี้อยู่ในสถานะที่ไม่สามารถยกเลิกซ้ำได้")
        return redirect('pms:project_detail', pk=pk)

    project.status = Project.Status.CANCELLED
    project._changed_by_user = request.user
    project.save()
    
    messages.warning(request, f"🚫 ยกเลิกโครงการ '{project.name}' เรียบร้อยแล้ว (สถานะถูกล็อก)")
    return redirect('pms:project_detail', pk=pk)

# การเปลี่ยนสถานะโครงการเป็นขั้นตอนถัดไปแบบอัตโนมัติ (One-Click Advance)
# เลื่อนสถานะโครงการไปขั้นตอนถัดไปในระบบ Workflow แบบ One-Click
# บันทึก description และ remarks ก่อน แล้วเปลี่ยนสถานะอัตโนมัติ
@login_required
def project_advance(request, pk):
    """เลื่อนสถานะ (Advance): หาขั้นถัดไปจาก get_next_status() แล้วบันทึก"""
    project = get_object_or_404(Project, pk=pk)
    
    if request.method == 'POST':
        # 1. Save mid-workflow notes
        project.description = request.POST.get('description', project.description)
        project.remarks = request.POST.get('remarks', project.remarks)
        
        # 2. Try to advance status
        next_js = project.get_next_status()
        if next_js:
            old_label = project.get_job_status_display
            project.status = next_js.status_key
            project._changed_by_user = request.user
            
            from django.core.exceptions import ValidationError
            try:
                project.save()
                messages.success(request, f"🚀 เสร็จสิ้นขั้นตอน '{old_label}' และส่งต่อไปยัง '{next_js.label}' เรียบร้อยแล้ว")
            except ValidationError as e:
                # Get the error message from ValidationError
                msg = str(e)
                if hasattr(e, 'message_dict'):
                    msg = "; ".join([f"{k}: {', '.join(v)}" for k, v in e.message_dict.items()])
                elif hasattr(e, 'messages'):
                    msg = "; ".join(e.messages)
                messages.error(request, msg)
        else:
            # Just save if no next status
            project._changed_by_user = request.user
            project.save()
            messages.success(request, 'บันทึกข้อมูลเรียบร้อยแล้ว')
            
    return redirect('pms:project_detail', pk=pk)

# ลบโครงการออกจากระบบ — ต้องปิดจบ/ยกเลิกแล้ว และต้องใส่รหัส DELETE_PASSWORD
@login_required
def project_delete(request, pk):
    """ลบโครงการถาวร — ใช้ได้เฉพาะ CLOSED/CANCELLED และต้องใส่รหัสปลดล็อกถูกต้อง"""
    from django.conf import settings
    project = get_object_or_404(Project, pk=pk)
    
    if request.method == 'POST':
        password = request.POST.get('password')
        if password == settings.DELETE_PASSWORD:
            if project.status in [Project.Status.CLOSED, Project.Status.CANCELLED]:
                name = project.name
                project.delete()
                messages.success(request, f"🗑️ ลบโครงการ '{name}' เรียบร้อย")
                return redirect('pms:project_list')
            else:
                messages.error(request, "ไม่สามารถลบโครงการที่ยังไม่ปิดงานหรือยกเลิกได้")
                return redirect('pms:project_detail', pk=pk)
        else:
            messages.error(request, "รหัสผ่านไม่ถูกต้อง")
            return redirect('pms:project_detail', pk=pk)
    
    return redirect('pms:project_detail', pk=pk)

# ===== Customer Request Views =====

# รายการคำขอทั่วไปจากลูกค้า (Customer Requests)
@login_required
def request_list(request):
    """List all customer requests."""
    requests = CustomerRequest.objects.all()
    
    # Filter by status
    status = request.GET.get('status')
    if status:
        requests = requests.filter(status=status)
        
    return render(request, 'pms/request_list.html', {
        'requests': requests,
        'status_choices': CustomerRequest.Status.choices
    })

# สร้างคำขอใหม่ (Customer Request) — รองรับการ pre-fill ลูกค้าและ owner จาก GET params
@login_required
def request_create(request):
    if request.method == 'POST':
        form = CustomerRequestForm(request.POST)
        if form.is_valid():
            req = form.save(commit=False)
            req._changed_by_user = request.user
            req.save()
            messages.success(request, 'สร้างคำขอใหม่เรียบร้อย')
            return redirect('pms:request_detail', pk=req.pk)
    else:
        form = CustomerRequestForm()
        # Pre-select customer if provided in GET
        cust_id = request.GET.get('customer')
        if cust_id:
            form.initial['customer'] = cust_id
            
        # Try to pre-fill owner
        try:
            owner = ProjectOwner.objects.filter(email=request.user.email).first()
            if owner:
                form.initial['owner'] = owner
        except:
            pass
            
            
    return render(request, 'pms/request_form.html', {'form': form, 'title': 'สร้างคำขอใหม่'})

# แสดงรายละเอียดคำขอ พร้อมรองรับ Quick Update สถานะ/คำอธิบาย/หมายเหตุผ่าน POST
@login_required
def request_detail(request, pk):
    req = get_object_or_404(CustomerRequest, pk=pk)
    files = req.files.all()
    
    if request.method == 'POST':
        # Quick Update Logic
        new_status = request.POST.get('status')
        new_description = request.POST.get('description')
        new_remarks = request.POST.get('remarks')

        if new_status:
            req.status = new_status
        if new_description is not None:
            req.description = new_description
        if new_remarks is not None:
            req.remarks = new_remarks
            
        req._changed_by_user = request.user
        req.save()
        messages.success(request, 'บันทึกการแก้ไขคำขอเรียบร้อยแล้ว')
        return redirect('pms:request_detail', pk=pk)
            
    return render(request, 'pms/request_detail.html', {
        'req': req,
        'files': files,
        'status_choices': CustomerRequest.Status.choices
    })

# แก้ไขข้อมูลคำขอผ่านฟอร์มเต็ม (ต่างจาก Quick Update ใน request_detail)
@login_required
def request_update(request, pk):
    req = get_object_or_404(CustomerRequest, pk=pk)
    if request.method == 'POST':
        form = CustomerRequestForm(request.POST, instance=req)
        if form.is_valid():
            req = form.save(commit=False)
            req._changed_by_user = request.user
            req.save()
            messages.success(request, 'บันทึกการแก้ไขเรียบร้อย')
            return redirect('pms:request_detail', pk=pk)
    else:
        form = CustomerRequestForm(instance=req)
        
    return render(request, 'pms/request_form.html', {'form': form, 'title': 'แก้ไขคำขอ'})

# ลบคำขอและไฟล์แนบทั้งหมด — อนุญาตเฉพาะ COMPLETED/CANCELLED เท่านั้น
@login_required
def request_delete(request, pk):
    req = get_object_or_404(CustomerRequest, pk=pk)

    if request.method == 'POST':
        # ตรวจสอบสถานะ: ลบได้เฉพาะที่เสร็จสิ้นหรือยกเลิกแล้ว
        if req.status not in [CustomerRequest.Status.COMPLETED, CustomerRequest.Status.CANCELLED]:
            messages.error(request, 'สามารถลบได้เฉพาะคำขอที่เสร็จสิ้นหรือยกเลิกแล้วเท่านั้น')
            return redirect('pms:request_detail', pk=pk)

        # Delete all attached files physically first
        for pf in req.files.all():
            pf.file.delete(save=False) # Delete physical file
            pf.delete() # Delete record

        req.delete()
        messages.success(request, 'ลบคำขอและไฟล์แนบออกจากระบบเรียบร้อย')
        return redirect('pms:request_list')
    return redirect('pms:request_detail', pk=pk)

# อัปโหลดไฟล์แนบเข้าคำขอ (Customer Request)
@login_required
def request_file_upload(request, pk):
    req = get_object_or_404(CustomerRequest, pk=pk)
    if request.method == 'POST':
        files = request.FILES.getlist('files')
        for f in files:
            ProjectFile.objects.create(
                customer_request=req,
                file=f,
                original_name=f.name
            )
        messages.success(request, f'อัปโหลด {len(files)} ไฟล์เรียบร้อย')
    return redirect('pms:request_detail', pk=pk)

# ลบไฟล์แนบของคำขอ — ตรวจสอบความเป็นเจ้าของก่อนลบ
@login_required
def request_file_delete(request, file_id):
    pf = get_object_or_404(ProjectFile, pk=file_id)
    req_pk = pf.customer_request.pk if pf.customer_request else None

    # ตรวจสอบความปลอดภัย: ต้องเป็นไฟล์ที่ผูกกับ CustomerRequest เท่านั้น
    if not req_pk:
        return redirect('pms:dashboard')
        
    pf.file.delete(save=False)
    pf.delete()
    messages.success(request, 'ลบไฟล์สำเร็จ')
    return redirect('pms:request_detail', pk=req_pk)

# ฟังก์ชันเชื่อมต่อกับ AI (Gemini) เพื่อวิเคราะห์สรุปผลข้อมูลในแดชบอร์ดออกมาเป็นมุมมองเชิงกลยุทธ์
# ระบบจะรวบรวมยอดรวม มูลค่าโครงการ และสถิติงานที่ปิดจบ/ยกเลิก มาสรุปเป็นบทวิเคราะห์ภาษาไทย
@login_required
def ai_dashboard_analysis(request):
    from .ai_utils import get_gemini_analysis
    from django.http import JsonResponse
    from django.conf import settings
    from django.db.models import Sum, Count, F, Q, Case, When, Value, DecimalField
    from django.utils import timezone
    from datetime import datetime
    import calendar

    # 1. Get current month/year from request (same as dashboard)
    now = timezone.now()
    month_param = request.GET.get('month')
    year_param = request.GET.get('year')
    
    month_filter = int(month_param) if month_param and month_param.isdigit() else now.month
    year_filter = int(year_param) if year_param and year_param.isdigit() else now.year

    # 2. Gather data for AI
    _, last_day = calendar.monthrange(year_filter, month_filter)
    start_of_period = timezone.make_aware(datetime(year_filter, month_filter, 1))
    end_of_period = timezone.make_aware(datetime(year_filter, month_filter, last_day, 23, 59, 59))

    projects_in_period = Project.objects.filter(created_at__range=[start_of_period, end_of_period])
    total_revenue = projects_in_period.aggregate(total=Sum(F('items__quantity') * F('items__unit_price')))['total'] or 0
    total_count = projects_in_period.count()
    
    # Sales by Type
    type_stats = projects_in_period.values('job_type').annotate(revenue=Sum(F('items__quantity') * F('items__unit_price')))
    type_summary = ", ".join([f"{t['job_type']}: ฿{t['revenue'] or 0:,.2f}" for t in type_stats])

    # Sales by Owner
    owner_stats = ProjectOwner.objects.annotate(
        total_sales=Sum(Case(When(projects__created_at__range=[start_of_period, end_of_period], then=F('projects__items__quantity') * F('projects__items__unit_price')), default=0, output_field=DecimalField(max_digits=15, decimal_places=2)))
    ).filter(total_sales__gt=0).order_by('-total_sales')
    owner_summary = ", ".join([f"{o.name}: ฿{o.total_sales:,.2f}" for o in owner_stats])

    # Calculate actual sales (closed jobs) for AI context - PMS Projects only
    actual_sales = Project.objects.filter(status=Project.Status.CLOSED, closed_at__range=[start_of_period, end_of_period]).aggregate(total=Sum(F('items__quantity') * F('items__unit_price')))['total'] or 0

    # Cancelled Stats for AI
    cancelled_projects = Project.objects.filter(status=Project.Status.CANCELLED, closed_at__range=[start_of_period, end_of_period])
    cancelled_count = cancelled_projects.count()
    cancelled_value = cancelled_projects.aggregate(total=Sum(F('items__quantity') * F('items__unit_price')))['total'] or 0

    data_summary = f"""
    - ช่วงเวลา: {calendar.month_name[month_filter]} {year_filter}
    - ยอดรวมของงาน (รับเข้าในช่วงนี้): ฿{total_revenue:,.2f}
    - ยอดขายที่ปิดจบจริง (Actual Sales): ฿{actual_sales:,.2f}
    - งานที่ยกเลิก: {cancelled_count} รายการ (มูลค่า ฿{cancelled_value:,.2f})
    - จำนวนงานทั้งหมด: {total_count} งาน
    - สรุปแยกตามประเภทงาน: {type_summary}
    - สรุปยอดขายตามพนักงาน: {owner_summary}
    """

    try:
        analysis_result = get_gemini_analysis(data_summary)
        
        return JsonResponse({
            'status': 'success',
            'analysis': analysis_result,
            'debug_info': {
                'month': month_filter,
                'year': year_filter,
                'has_key': bool(getattr(settings, 'GEMINI_API_KEY', None))
            }
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

# บันทึกเวลาตอบกลับ SLA ด้วยตนเอง — ใช้เมื่อมีการตอบกลับนอกระบบ เช่น โทรออก
@login_required
def mark_as_responded(request, pk):
    """ตั้งค่า responded_at เป็นเวลาปัจจุบัน สำหรับติดตาม SLA Response Time"""
    project = get_object_or_404(Project, pk=pk)
    if not project.responded_at:
        project.responded_at = timezone.now()
        project.save()
        messages.success(request, f"✅ บันทึกเวลาตอบกลับสำหรับ {project.name} เรียบร้อย")
    return redirect('pms:project_detail', pk=pk)

# รายการแจ้งเตือนของผู้ใช้ (User Notifications)
@login_required
def notification_list(request):
    notifications = request.user.pms_notifications.all()
    return render(request, 'pms/notification_list.html', {
        'notifications': notifications
    })

# ทำเครื่องหมายการแจ้งเตือนว่าอ่านแล้ว และ redirect ไปยังหน้าโครงการที่เกี่ยวข้อง
@login_required
def notification_read(request, pk):
    from .models import UserNotification
    notif = get_object_or_404(UserNotification, pk=pk, user=request.user)
    notif.is_read = True
    notif.save()
    return redirect('pms:project_detail', pk=notif.project.pk)
# หน้าจอแสดงตารางบริหารจัดการผู้รับผิดชอบงานร่วมกัน (Mutual Responsibility Matrix)
# ช่วยให้เจ้าหน้าที่หลายคนสามารถดูแลโครงการเดียวกันได้ในขั้นตอนต่างๆ ของ Workflow
@login_required
def project_assignment_matrix(request):
    """ตารางแมตทริกซ์ที่แสดงขั้นตอนงาน (Row) แยกตามประเภทงานหลัก 4 ประเภท"""
    User = get_user_model()
    users = User.objects.filter(is_active=True).order_by('username')
    
    # Define Job Types
    job_types = [
        (Project.JobType.PROJECT, '📂 งานโครงการ (Project)'),
        (Project.JobType.SERVICE, '🛠️ งานบริการ/งานขาย (Service)'),
        (Project.JobType.REPAIR, '🔧 งานซ่อม (Repair)'),
        (Project.JobType.RENTAL, '🏢 งานเช่า (Rental)'),
        (Project.JobType.SURVEY, '🔍 ดูหน้างาน (Survey)'),
    ]
    
    matrix_data = []
    
    for jt_code, jt_label in job_types:
        # Get JobStatus for this type
        statuses = JobStatus.objects.filter(job_type=jt_code, is_active=True).order_by('sort_order')
        
        status_list = []
        for js in statuses:
            from .models import JobStatusAssignment
            try:
                assignment = js.assignment
                user_ids = list(assignment.responsible_users.values_list('id', flat=True))
            except JobStatusAssignment.DoesNotExist:
                user_ids = []
                
            status_list.append({
                'id': js.id,
                'key': js.status_key,
                'label': js.label,
                'user_ids': user_ids
            })
            
        matrix_data.append({
            'type_code': jt_code,
            'type_label': jt_label,
            'statuses': status_list
        })
        
    return render(request, 'pms/assignment_matrix.html', {
        'matrix_data': matrix_data,
        'users': users,
    })

# บันทึกการมอบหมายผู้รับผิดชอบงาน (ร่วม) ผ่าน AJAX
@login_required
def set_project_assignment(request):
    if request.method == 'POST':
        status_id = request.POST.get('status_id')
        user_ids = request.POST.getlist('user_ids[]') or request.POST.getlist('user_ids')
        
        from .models import JobStatus, JobStatusAssignment
        job_status = get_object_or_404(JobStatus, pk=status_id)
        
        assignment, created = JobStatusAssignment.objects.get_or_create(job_status=job_status)
        
        if not user_ids or (len(user_ids) == 1 and not user_ids[0]):
            assignment.responsible_users.clear()
            res = {'status': 'success', 'msg': 'Cleared'}
        else:
            User = get_user_model()
            users = User.objects.filter(id__in=user_ids)
            assignment.responsible_users.set(users)
            res = {'status': 'success', 'users': [u.username for u in users]}
            
        return JsonResponse(res)
    return JsonResponse({'status': 'error'}, status=400)

# ปั๊ม (Seed) ขั้นตอนงานมาตรฐานเข้าฐานข้อมูล — ใช้รันครั้งแรกหรือเมื่อ reset ระบบ
# รองรับ query param ?force=1 เพื่อบังคับรันซ้ำแม้ข้อมูลมีอยู่แล้ว
@login_required
def seed_pms_statuses(request):
    """Seed JobStatus สำหรับทุกประเภทงาน (PROJECT/SERVICE/REPAIR/RENTAL/SURVEY)
       โดยจะเพิ่มเฉพาะที่ยังไม่มีในระบบ เพื่อไม่ให้ทับข้อมูลที่ user ปรับแก้เอง
    """
    from .models import JobStatus, Project

    # Status configurations
    defaults = {
        Project.JobType.SERVICE: [
            (Project.Status.SOURCING, 'จัดหา', 10),
            (Project.Status.QUOTED, 'เสนอราคา', 20),
            (Project.Status.ORDERING, 'สั่งซื้อ', 30),
            (Project.Status.RECEIVED_QC, 'รับของ/QC', 40),
            (Project.Status.DELIVERY, 'ส่งมอบ', 50),
            (Project.Status.ACCEPTED, 'ตรวจรับ', 60),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 65),
            (Project.Status.CLOSED, 'ปิดจบ', 70),
            (Project.Status.CANCELLED, 'ยกเลิก', 80),
        ],
        Project.JobType.REPAIR: [
            (Project.Status.SOURCING, 'รับแจ้งซ่อม', 10),
            (Project.Status.SUPPLIER_CHECK, 'เช็คราคา', 20),
            (Project.Status.ORDERING, 'จัดคิวซ่อม', 30),
            (Project.Status.DELIVERY, 'ซ่อม', 40),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 45),
            (Project.Status.CLOSED, 'ปิดงานซ่อม', 50),
            (Project.Status.CANCELLED, 'ยกเลิก', 60),
        ],
        Project.JobType.SURVEY: [
            ('QUEUE_SURVEY', 'ดูหน้างาน', 10),
            (Project.Status.CLOSED, 'ปิดจบ', 20),
            (Project.Status.CANCELLED, 'ยกเลิก', 30),
        ],
        Project.JobType.RENTAL: [
            (Project.Status.SOURCING, 'จัดหา', 10),
            (Project.Status.CONTRACTED, 'ทำสัญญา', 20),
            (Project.Status.RENTING, 'เช่า', 30),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 35),
            (Project.Status.CLOSED, 'ปิดจบ', 40),
            (Project.Status.CANCELLED, 'ยกเลิก', 50),
        ],
        Project.JobType.PROJECT: [
            (Project.Status.DRAFT, 'รวบรวม', 10),
            (Project.Status.SOURCING, 'จัดหา', 20),
            (Project.Status.QUOTED, 'เสนอราคา', 30),
            (Project.Status.CONTRACTED, 'ทำสัญญา', 40),
            (Project.Status.ORDERING, 'สั่งซื้อ', 50),
            (Project.Status.RECEIVED_QC, 'รับของ/QC', 60),
            (Project.Status.INSTALLATION, 'ติดตั้ง', 70),
            (Project.Status.ACCEPTED, 'ตรวจรับ', 80),
            (Project.Status.BILLING, 'วางบิล', 90),
            (Project.Status.WAITING_FOR_SALE_KEY, 'รอคีย์ขาย', 100),
            (Project.Status.CLOSED, 'ปิดจบ', 110),
            (Project.Status.CANCELLED, 'ยกเลิก', 120),
        ]
    }

    count = 0
    for jt, steps in defaults.items():
        for key, label, sort in steps:
            # ใช้ get_or_create เพื่อเพิ่มเฉพาะ "รหัส (Key)" ที่ยังไม่มีในประเภทงานนั้นๆ
            # หากมีอยู่แล้ว จะไม่ไปทับข้อมูลป้ายชื่อ (Label) หรือลำดับ (Sort) ที่คุณเคยแก้ค้างไว้
            obj, created = JobStatus.objects.get_or_create(
                job_type=jt,
                status_key=key,
                defaults={'label': label, 'sort_order': sort}
            )
            if created:
                count += 1
    
    messages.success(request, f"สร้างขั้นตอนงานมาตรฐาน {count} รายการเรียบร้อยแล้ว")
    return redirect('pms:job_status_list')
# รายการสถานะงานแบบ Dynamic (Job Status Management)
@login_required
def job_status_list(request):
    """List and manage dynamic statuses."""
    statuses = JobStatus.objects.all().order_by('job_type', 'sort_order')
    return render(request, 'pms/job_status_list.html', {
        'statuses': statuses,
        'job_types': Project.JobType.choices,
        'title': 'จัดการขั้นตอนงาน (Workflow)'
    })

# เพิ่มขั้นตอนงานใหม่ (Dynamic Status) ด้วยการกรอกฟอร์ม
@login_required
def job_status_create(request):
    if request.method == 'POST':
        form = JobStatusForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'เพิ่มขั้นตอนงานสำเร็จ')
            return redirect('pms:job_status_list')
    else:
        form = JobStatusForm()
    return render(request, 'pms/job_status_form.html', {'form': form, 'title': 'เพิ่มขั้นตอนงานใหม่'})

# แก้ไขขั้นตอนงาน Dynamic (เช่น เปลี่ยนชื่อ, ลำดับ, สถานะ active)
@login_required
def job_status_update(request, pk):
    status = get_object_or_404(JobStatus, pk=pk)
    if request.method == 'POST':
        # Capture old values before the form overwrites them
        old_key      = status.status_key
        old_job_type = status.job_type

        form = JobStatusForm(request.POST, instance=status)
        if form.is_valid():
            form.save()  # model.save() cascades project statuses automatically

            new_key      = status.status_key
            new_job_type = status.job_type
            if old_key != new_key or old_job_type != new_job_type:
                affected = Project.objects.filter(job_type=new_job_type, status=new_key).count()
                if affected:
                    messages.info(request,
                                  f'อัปเดตสถานะโครงการ {affected} รายการ '
                                  f'({old_key} → {new_key}) เรียบร้อยแล้ว')

            messages.success(request, 'แก้ไขขั้นตอนงานสำเร็จ')
            return redirect('pms:job_status_list')
    else:
        form = JobStatusForm(instance=status)
    return render(request, 'pms/job_status_form.html', {'form': form, 'title': 'แก้ไขขั้นตอนงาน'})

# ลบขั้นตอนงาน Dynamic — แสดงหน้า confirm ก่อนลบจริง
@login_required
def job_status_delete(request, pk):
    status = get_object_or_404(JobStatus, pk=pk)
    if request.method == 'POST':
        status.delete()
        messages.success(request, 'ลบขั้นตอนงานสำเร็จ')
        return redirect('pms:job_status_list')
    return render(request, 'pms/formatted_confirm_delete.html', {
        'object': status,
        'type': 'JobStatus',
        'cancel_url': 'pms:job_status_list'
    })


@csrf_exempt
# ระบบ Chatbot Proxy สำหรับสื่อสารกับ OpenClaw AI
@login_required
def openclaw_chatbot(request):
    """
    Proxy view for OpenClaw (Hostinger) chatbot service.
    Using Gemini 2.0 Flash via OpenAI-compatible endpoint.
    """
    if request.method == 'POST':
        try:
            # 1. รับข้อความจากหน้าเว็บ PMS
            data = json.loads(request.body)
            user_message = data.get('message', '')

            # 2. ปลายทาง OpenClaw (ดึงจาก settings.py / .env)
            openclaw_url = getattr(settings, 'OPENCLAW_GATEWAY_URL', 'http://72.60.197.71:18789/v1/chat/completions')
            token = getattr(settings, 'OPENCLAW_GATEWAY_TOKEN', None)
            
            if not token:
                return JsonResponse({'status': 'error', 'message': 'ไม่พบ OPENCLAW_GATEWAY_TOKEN ในการตั้งค่า (.env)'}, status=500)
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            }
            
            # 4. รูปแบบ Payload ตามมาตรฐาน OpenAI
            payload = {
                "model": "google/gemini-3-flash-preview",
                "messages": [{"role": "user", "content": user_message}],
                "temperature": 0.7
            }

            # 5. ยิงคำถามไปหาเซิร์ฟเวอร์ AI
            response = requests.post(openclaw_url, headers=headers, json=payload, timeout=90)
            
            # 6. ประมวลผลคำตอบ
            if response.status_code == 200:
                try:
                    ai_data = response.json()
                    ai_reply = ai_data['choices'][0]['message']['content']
                    return JsonResponse({'status': 'success', 'reply': ai_reply})
                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    return JsonResponse({
                        'status': 'error', 
                        'message': f'Invalid JSON format: {str(e)}',
                        'debug': response.text[:500]
                    }, status=500)
            elif response.status_code == 404:
                return JsonResponse({
                    'status': 'error', 
                    'message': 'AI Gateway Endpoint ไม่ถูกเปิดใช้งาน (404 Not Found)',
                    'suggestion': 'รบกวนคุณ Song เข้าไปที่ VPS แล้วรันคำสั่ง "openclaw gateway config set openai.enabled true" และรีสตาร์ทครับ',
                    'debug': response.text[:200]
                }, status=500)
            else:
                return JsonResponse({
                    'status': 'error', 
                    'message': f'AI Server Error ({response.status_code})',
                    'debug': response.text[:200]
                }, status=500)

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Exception: {str(e)}'}, status=500)

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=400)

# คืนค่าจำนวนการแจ้งเตือนต่างๆ ในรูปแบบ JSON สำหรับการทำ Polling
@login_required
def get_notification_counts(request):
    from .models import CustomerRequirement, CustomerRequest, UserNotification
    return JsonResponse({
        'unread_notifications_count': UserNotification.objects.filter(user=request.user, is_read=False).count(),
        'unconverted_leads_count': CustomerRequirement.objects.filter(is_converted=False).count(),
        'new_requests_count': CustomerRequest.objects.filter(status=CustomerRequest.Status.RECEIVED).count(),
    })


# รายงานติดตามพิกัดการทำงานของช่างเทคนิคภาคสนาม (Field Technician GPS Tracking)
# แสดงภาพรวมเส้นทางการทำงานจริงบนแผนที่ Leaflet ในแต่ละช่วงเวลา (Check-in/Out)
# เพื่อการตรวจสอบความโปร่งใสและประสิทธิภาพในการออกปฏิบัติงานนอกสถานที่
@login_required
def gps_tracking_report(request):
    """
    แสดงรายงาน GPS ของช่างเทคนิคประจำวัน
    - Admin/Superuser เห็นข้อมูลของทุกคน (สามารถกรองตาม user ได้)
    - User ทั่วไปเห็นเฉพาะข้อมูลของตัวเอง
    แสดงผลบนแผนที่ Leaflet พร้อมเส้นทาง (Polyline)
    """
    from .models import TechnicianGPSLog, ServiceQueueItem
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    import json as json_lib

    User = get_user_model()
    today = timezone.localdate()

    # รับค่าวันที่จาก query param (default = วันนี้)
    date_str = request.GET.get('date', today.isoformat())
    try:
        from datetime import date
        report_date = date.fromisoformat(date_str)
    except ValueError:
        report_date = today

    # รับค่า user filter (admin เท่านั้น)
    selected_user_id = request.GET.get('user_id')
    technicians = User.objects.filter(is_active=True).order_by('username')

    # กรองข้อมูล GPS ตามวันที่
    qs = TechnicianGPSLog.objects.filter(
        timestamp__date=report_date
    ).select_related('user', 'queue_item', 'queue_item__project')

    if user_can_view_all(request.user):
        if selected_user_id:
            qs = qs.filter(user_id=selected_user_id)
    else:
        qs = qs.filter(user=request.user)
        selected_user_id = str(request.user.id)

    logs = list(qs.order_by('user__username', 'timestamp'))

    # จัดกลุ่มตาม user สำหรับแสดง timeline
    from collections import defaultdict
    grouped = defaultdict(list)
    for log in logs:
        grouped[log.user.username].append(log)

    # สร้าง JSON สำหรับ Leaflet map
    map_data = {}
    for username, user_logs in grouped.items():
        map_data[username] = [
            {
                'lat': float(log.latitude),
                'lng': float(log.longitude),
                'check_type': log.get_check_type_display(),
                'check_type_key': log.check_type,
                'location_name': log.location_name or 'ไม่ระบุชื่อ',
                'notes': log.notes,
                'time': timezone.localtime(log.timestamp).strftime('%H:%M'),
                'job': log.queue_item.project.name if log.queue_item and log.queue_item.project else '-',
            }
            for log in user_logs
        ]

    return render(request, 'pms/gps_tracking_report.html', {
        'logs': logs,
        'grouped': dict(grouped),
        'map_data_json': json_lib.dumps(map_data, ensure_ascii=False),
        'report_date': report_date,
        'today': today,
        'technicians': technicians,
        'selected_user_id': selected_user_id,
    })


@login_required
def gps_live_data(request):
    """
    JSON API สำหรับ AJAX polling — คืนค่า GPS log ของวันนี้ในรูปแบบ JSON
    ใช้กับปุ่ม Live บนหน้า GPS Tracking Report
    """
    from .models import TechnicianGPSLog
    from django.utils import timezone
    from collections import defaultdict

    today = timezone.localdate()
    selected_user_id = request.GET.get('user_id')

    qs = TechnicianGPSLog.objects.filter(
        timestamp__date=today
    ).select_related('user', 'queue_item', 'queue_item__project')

    if user_can_view_all(request.user):
        if selected_user_id:
            qs = qs.filter(user_id=selected_user_id)
    else:
        qs = qs.filter(user=request.user)

    logs = list(qs.order_by('user__username', 'timestamp'))
    grouped = defaultdict(list)
    for log in logs:
        grouped[log.user.username].append(log)

    map_data = {}
    for username, user_logs in grouped.items():
        map_data[username] = [
            {
                'lat': float(log.latitude),
                'lng': float(log.longitude),
                'check_type': log.get_check_type_display(),
                'check_type_key': log.check_type,
                'location_name': log.location_name or 'ไม่ระบุชื่อ',
                'notes': log.notes,
                'time': timezone.localtime(log.timestamp).strftime('%H:%M'),
                'job': log.queue_item.project.name if log.queue_item and log.queue_item.project else '-',
            }
            for log in user_logs
        ]

    return JsonResponse({'map_data': map_data, 'total': len(logs)})


@login_required
def gps_log_delete(request, pk):
    """ลบ GPS log entry (เฉพาะ owner หรือ admin)"""
    from .models import TechnicianGPSLog
    log = get_object_or_404(TechnicianGPSLog, pk=pk)
    if request.user == log.user or user_can_view_all(request.user):
        log.delete()
        messages.success(request, "ลบ GPS log แล้ว")
    return redirect(request.META.get('HTTP_REFERER', 'pms:gps_tracking_report'))


@login_required
def gps_summary_report(request):
    """
    รายงานสรุป GPS รายเดือน แสดงเป็นตาราง (แถว = วัน, คอลัมน์ = ช่าง)
    - Admin/Staff เห็นข้อมูลทุกคน
    - User ทั่วไปเห็นเฉพาะข้อมูลตัวเอง
    - คลิกที่ช่องใดช่องหนึ่งเพื่อไปยังรายงานรายวันของวันและคนนั้น
    """
    from .models import TechnicianGPSLog
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from collections import defaultdict
    import calendar
    from datetime import date, timedelta

    User = get_user_model()
    today = timezone.localdate()
    mode = request.GET.get('mode', 'monthly')   # 'monthly' | 'daily'

    THAI_MONTHS = ['', 'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
                   'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม']
    DAY_SHORT = ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา']

    # ── DAILY MODE ─────────────────────────────────────────────────────
    if mode == 'daily':
        import json as json_lib
        from .models import CustomerSatisfaction as _CS

        try:
            report_date = date.fromisoformat(request.GET.get('date', today.isoformat()))
        except (ValueError, TypeError):
            report_date = today

        prev_date = report_date - timedelta(days=1)
        next_date = report_date + timedelta(days=1)
        day_short = DAY_SHORT[report_date.weekday()]

        qs_day = TechnicianGPSLog.objects.filter(
            timestamp__date=report_date
        ).select_related('user').order_by('timestamp')
        if not user_can_view_all(request.user):
            qs_day = qs_day.filter(user=request.user)

        # Build per-technician data
        daily_tech_raw = {}
        user_id_map_day = {}
        for log in qs_day:
            uname = log.user.username
            user_id_map_day[uname] = log.user_id
            if uname not in daily_tech_raw:
                daily_tech_raw[uname] = {
                    'logs': [], 'ci_count': 0, 'co_count': 0,
                    'go_work_count': 0, 'back_office_count': 0,
                    'first': None, 'last': None,
                }
            cell = daily_tech_raw[uname]
            lt = timezone.localtime(log.timestamp)
            t_str = lt.strftime('%H:%M')
            cell['logs'].append({
                'time':         t_str,
                'type':         log.check_type,
                'type_display': log.get_check_type_display(),
                'location':     log.location_name or '',
                'notes':        log.notes or '',
            })
            if log.check_type in ('ON_SITE', 'CHECK_IN'):
                cell['ci_count'] += 1
            elif log.check_type == 'CHECK_OUT':
                cell['co_count'] += 1
            elif log.check_type == 'GO_WORK':
                cell['go_work_count'] += 1
            elif log.check_type == 'BACK_OFFICE':
                cell['back_office_count'] += 1
            if cell['first'] is None:
                cell['first'] = t_str
            cell['last'] = t_str

        daily_tech_list = []
        for uname in sorted(daily_tech_raw.keys()):
            cell = daily_tech_raw[uname]
            go_ok   = cell['go_work_count'] == 1
            back_ok = cell['back_office_count'] == 1
            bal_ok  = cell['ci_count'] == cell['co_count']
            consistent = go_ok and back_ok and bal_ok
            daily_tech_list.append({
                'username':          uname,
                'user_id':           user_id_map_day[uname],
                'logs':              cell['logs'],
                'ci_count':          cell['ci_count'],
                'co_count':          cell['co_count'],
                'go_work_count':     cell['go_work_count'],
                'back_office_count': cell['back_office_count'],
                'go_work_ok':        go_ok,
                'back_office_ok':    back_ok,
                'onsite_balanced':   bal_ok,
                'consistent':        consistent,
                'first':             cell['first'] or '',
                'last':              cell['last'] or '',
                'total':             len(cell['logs']),
                'imbalanced':        not consistent,
            })
        imbalanced_daily_techs = [t for t in daily_tech_list if t['imbalanced']]

        # Satisfaction for the day
        sat_qs_day = _CS.objects.filter(
            gps_log__timestamp__date=report_date
        ).select_related('gps_log__user').order_by('created_at')
        if not user_can_view_all(request.user):
            sat_qs_day = sat_qs_day.filter(gps_log__user=request.user)

        _empty_sat = lambda: {'VERY_SATISFIED': 0, 'SATISFIED': 0, 'NOT_SATISFIED': 0, 'total': 0}
        sat_complete_by_user_d   = defaultdict(_empty_sat)
        sat_incomplete_by_user_d = defaultdict(int)
        sat_complete_records_d   = []
        sat_incomplete_records_d = []

        for s in sat_qs_day:
            uname = s.gps_log.user.username
            is_complete = bool(
                s.customer_name  and s.customer_name.strip() and
                s.customer_phone and s.customer_phone.strip()
            )
            rec = {
                'date':           timezone.localtime(s.gps_log.timestamp).strftime('%d/%m/%Y %H:%M'),
                'username':       uname,
                'customer_name':  s.customer_name  or '—',
                'customer_phone': s.customer_phone or '—',
                'rating':         s.rating,
                'rating_display': s.get_rating_display(),
            }
            if is_complete:
                sat_complete_records_d.append(rec)
                sat_complete_by_user_d[uname][s.rating] += 1
                sat_complete_by_user_d[uname]['total']   += 1
            else:
                sat_incomplete_records_d.append(rec)
                sat_incomplete_by_user_d[uname] += 1

        sat_complete_total_d = {'VERY_SATISFIED': 0, 'SATISFIED': 0, 'NOT_SATISFIED': 0, 'total': 0}
        for v in sat_complete_by_user_d.values():
            for k in ('VERY_SATISFIED', 'SATISFIED', 'NOT_SATISFIED'):
                sat_complete_total_d[k] += v[k]
        sat_complete_total_d['total'] = sum(
            sat_complete_total_d[k] for k in ('VERY_SATISFIED', 'SATISFIED', 'NOT_SATISFIED')
        )
        sat_incomplete_total_d = sum(sat_incomplete_by_user_d.values())

        # Chart JSON — complete (stacked bar per technician)
        complete_labels_d = sorted(sat_complete_by_user_d.keys())
        sat_complete_chart_json_d = {}
        if complete_labels_d:
            sat_complete_chart_json_d = {
                'labels':         complete_labels_d,
                'very_satisfied': [sat_complete_by_user_d[u]['VERY_SATISFIED'] for u in complete_labels_d],
                'satisfied':      [sat_complete_by_user_d[u]['SATISFIED']      for u in complete_labels_d],
                'not_satisfied':  [sat_complete_by_user_d[u]['NOT_SATISFIED']  for u in complete_labels_d],
            }

        # Chart JSON — incomplete (bar per technician)
        incomplete_labels_d = sorted(sat_incomplete_by_user_d.keys())
        sat_incomplete_chart_json_d = {}
        if incomplete_labels_d:
            sat_incomplete_chart_json_d = {
                'labels': incomplete_labels_d,
                'counts': [sat_incomplete_by_user_d[u] for u in incomplete_labels_d],
            }

        return render(request, 'pms/gps_summary_report.html', {
            'mode':           'daily',
            'report_date':    report_date,
            'day_short':      day_short,
            'prev_date':      prev_date,
            'next_date':      next_date,
            'today':          today,
            'daily_tech_list':        daily_tech_list,
            'imbalanced_daily_techs': imbalanced_daily_techs,
            'user_id_map_json': json_lib.dumps(user_id_map_day),
            'total_logs':     sum(t['total'] for t in daily_tech_list),
            'month_name':     THAI_MONTHS[report_date.month],
            'year':           report_date.year,
            'month':          report_date.month,
            # Satisfaction (same var names as monthly)
            'sat_grand_total':           sat_complete_total_d['total'] + sat_incomplete_total_d,
            'sat_complete_records':      sat_complete_records_d,
            'sat_incomplete_records':    sat_incomplete_records_d,
            'sat_complete_total':        sat_complete_total_d,
            'sat_incomplete_total':      sat_incomplete_total_d,
            'sat_complete_by_user':      dict(sat_complete_by_user_d),
            'sat_complete_chart_json':   json_lib.dumps(sat_complete_chart_json_d),
            'sat_incomplete_chart_json': json_lib.dumps(sat_incomplete_chart_json_d),
        })

    # ── MONTHLY MODE (continues below) ─────────────────────────────────
    # รับ month/year จาก query param
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        if not (1 <= month <= 12):
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month

    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date   = date(year, month, last_day)

    # Query GPS logs ในเดือนนั้น
    qs = TechnicianGPSLog.objects.filter(
        timestamp__date__gte=start_date,
        timestamp__date__lte=end_date,
    ).select_related('user').order_by('timestamp')

    if not (user_can_view_all(request.user)):
        qs = qs.filter(user=request.user)

    # จัดกลุ่ม: raw_data[date_obj][username] = {count, first_ts, last_ts, types, ci_count, co_count, go_work_count, back_office_count}
    raw_data = defaultdict(lambda: defaultdict(lambda: {
        'count': 0, 'first': None, 'last': None, 'types': set(),
        'ci_count': 0, 'co_count': 0,
        'go_work_count': 0, 'back_office_count': 0,
    }))
    users_ordered = {}  # ใช้ dict เพื่อรักษาลำดับ insertion (Python 3.7+)

    user_id_map = {}  # {username: user_id}
    for log in qs:
        d = timezone.localtime(log.timestamp).date()
        uname = log.user.username
        users_ordered[uname] = True
        user_id_map[uname] = log.user_id
        cell = raw_data[d][uname]
        cell['count'] += 1
        local_ts = timezone.localtime(log.timestamp)
        if cell['first'] is None or local_ts < cell['first']:
            cell['first'] = local_ts
        if cell['last'] is None or local_ts > cell['last']:
            cell['last'] = local_ts
        cell['types'].add(log.check_type)
        if log.check_type in ('ON_SITE', 'CHECK_IN'):
            cell['ci_count'] += 1
        elif log.check_type == 'CHECK_OUT':
            cell['co_count'] += 1
        elif log.check_type == 'GO_WORK':
            cell['go_work_count'] += 1
        elif log.check_type == 'BACK_OFFICE':
            cell['back_office_count'] += 1

    all_users = sorted(users_ordered.keys())

    # สรุปรายช่าง (คอลัมน์) และรายวัน (แถว)
    user_totals    = defaultdict(int)
    user_ci_totals = defaultdict(int)   # {username: total ON_SITE}
    user_co_totals = defaultdict(int)   # {username: total CHECK_OUT}
    date_totals    = defaultdict(int)
    for d, users_data in raw_data.items():
        for u, cell in users_data.items():
            user_totals[u]    += cell['count']
            user_ci_totals[u] += cell['ci_count']
            user_co_totals[u] += cell['co_count']
            date_totals[d]    += cell['count']

    # สร้าง table_rows
    table_rows = []
    for d in [date(year, month, day) for day in range(1, last_day + 1)]:
        cells = []
        for u in all_users:
            cell = raw_data[d].get(u)
            if cell:
                ci_c  = cell['ci_count']
                co_c  = cell['co_count']
                gw_c  = cell['go_work_count']
                bo_c  = cell['back_office_count']
                go_ok   = gw_c == 1
                back_ok = bo_c == 1
                bal_ok  = ci_c == co_c
                consistent = go_ok and back_ok and bal_ok
                cells.append({
                    'count':             cell['count'],
                    'first':             cell['first'].strftime('%H:%M') if cell['first'] else '',
                    'last':              cell['last'].strftime('%H:%M') if cell['last'] else '',
                    'has_ci':            'ON_SITE' in cell['types'] or 'CHECK_IN' in cell['types'],
                    'has_co':            'CHECK_OUT' in cell['types'],
                    'has_travel':        'TRAVEL' in cell['types'],
                    'ci_count':          ci_c,
                    'co_count':          co_c,
                    'go_work_count':     gw_c,
                    'back_office_count': bo_c,
                    'go_work_ok':        go_ok,
                    'back_office_ok':    back_ok,
                    'onsite_balanced':   bal_ok,
                    'consistent':        consistent,
                    'imbalanced':        not consistent,
                })
            else:
                cells.append(None)
        table_rows.append({
            'date':       d,
            'day_short':  DAY_SHORT[d.weekday()],
            'cells':      cells,
            'total':      date_totals.get(d, 0),
            'is_weekend': d.weekday() >= 5,
            'is_today':   d == today,
        })

    # วันที่ไม่สอดคล้อง (ต้องสร้างหลัง table_rows)
    imbalance_days = []
    for row in table_rows:
        day_issues = []
        for u, cell_data in zip(all_users, row['cells']):
            if cell_data and cell_data['imbalanced']:
                issues = []
                if not cell_data['go_work_ok']:
                    issues.append(f"ออกงาน={cell_data['go_work_count']}")
                if not cell_data['back_office_ok']:
                    issues.append(f"กลับ={cell_data['back_office_count']}")
                if not cell_data['onsite_balanced']:
                    issues.append(f"เริ่ม{cell_data['ci_count']}≠เสร็จ{cell_data['co_count']}")
                day_issues.append({
                    'username':    u,
                    'ci':          cell_data['ci_count'],
                    'co':          cell_data['co_count'],
                    'go_work':     cell_data['go_work_count'],
                    'back_office': cell_data['back_office_count'],
                    'issues':      issues,
                    'diff':        cell_data['ci_count'] - cell_data['co_count'],
                })
        if day_issues:
            imbalance_days.append({
                'date':      row['date'],
                'day_short': row['day_short'],
                'items':     day_issues,
            })

    # เดือนก่อน / เดือนหน้า สำหรับปุ่มนำทาง
    prev_month = month - 1 or 12
    prev_year  = year - (1 if month == 1 else 0)
    next_month = (month % 12) + 1
    next_year  = year + (1 if month == 12 else 0)

    # ─── Customer Satisfaction data ────────────────────────────────────
    from .models import CustomerSatisfaction
    sat_qs = CustomerSatisfaction.objects.filter(
        gps_log__timestamp__date__gte=start_date,
        gps_log__timestamp__date__lte=end_date,
    ).select_related('gps_log__user').order_by('-created_at')

    if not (user_can_view_all(request.user)):
        sat_qs = sat_qs.filter(gps_log__user=request.user)

    # แยก "สมบูรณ์" (มีชื่อ + เบอร์โทร) vs "ไม่สมบูรณ์"
    _empty_sat = lambda: {'VERY_SATISFIED': 0, 'SATISFIED': 0, 'NOT_SATISFIED': 0, 'total': 0}
    sat_complete_by_user   = defaultdict(_empty_sat)
    sat_incomplete_by_user = defaultdict(int)

    sat_complete_records   = []
    sat_incomplete_records = []

    for s in sat_qs:
        uname = s.gps_log.user.username
        is_complete = bool(
            s.customer_name  and s.customer_name.strip() and
            s.customer_phone and s.customer_phone.strip()
        )
        rec = {
            'date':           timezone.localtime(s.gps_log.timestamp).strftime('%d/%m/%Y %H:%M'),
            'username':       uname,
            'customer_name':  s.customer_name  or '—',
            'customer_phone': s.customer_phone or '—',
            'rating':         s.rating,
            'rating_display': s.get_rating_display(),
        }
        if is_complete:
            sat_complete_records.append(rec)
            sat_complete_by_user[uname][s.rating] += 1
            sat_complete_by_user[uname]['total']   += 1
        else:
            sat_incomplete_records.append(rec)
            sat_incomplete_by_user[uname] += 1

    # รวมทั้งหมด (ใช้แสดงยอดรวม)
    sat_complete_total = {'VERY_SATISFIED': 0, 'SATISFIED': 0, 'NOT_SATISFIED': 0, 'total': 0}
    for v in sat_complete_by_user.values():
        for k in ('VERY_SATISFIED', 'SATISFIED', 'NOT_SATISFIED'):
            sat_complete_total[k] += v[k]
    sat_complete_total['total'] = sum(
        sat_complete_total[k] for k in ('VERY_SATISFIED', 'SATISFIED', 'NOT_SATISFIED')
    )
    sat_incomplete_total = sum(sat_incomplete_by_user.values())
    sat_grand_total      = sat_complete_total['total'] + sat_incomplete_total

    # Chart JSON — สมบูรณ์ (stacked bar per technician)
    complete_labels = sorted(sat_complete_by_user.keys())
    sat_complete_chart_json = {}
    if complete_labels:
        sat_complete_chart_json = {
            'labels':        complete_labels,
            'very_satisfied': [sat_complete_by_user[u]['VERY_SATISFIED'] for u in complete_labels],
            'satisfied':      [sat_complete_by_user[u]['SATISFIED']      for u in complete_labels],
            'not_satisfied':  [sat_complete_by_user[u]['NOT_SATISFIED']  for u in complete_labels],
        }

    # Chart JSON — ไม่สมบูรณ์ (bar per technician, count only)
    incomplete_labels = sorted(sat_incomplete_by_user.keys())
    sat_incomplete_chart_json = {}
    if incomplete_labels:
        sat_incomplete_chart_json = {
            'labels': incomplete_labels,
            'counts': [sat_incomplete_by_user[u] for u in incomplete_labels],
        }

    import json as json_lib
    return render(request, 'pms/gps_summary_report.html', {
        'mode':           'monthly',
        'year':           year,
        'month':          month,
        'month_name':     THAI_MONTHS[month],
        'report_date':    today,
        'all_users':      all_users,
        'user_id_map_json': json_lib.dumps(user_id_map),
        'user_totals':    dict(user_totals),
        'user_ci_totals': dict(user_ci_totals),
        'user_co_totals': dict(user_co_totals),
        'table_rows':     table_rows,
        'imbalance_days': imbalance_days,
        'prev_year':      prev_year,
        'prev_month':     prev_month,
        'next_year':      next_year,
        'next_month':     next_month,
        'today':          today,
        'total_logs':     sum(user_totals.values()),
        # Satisfaction
        'sat_grand_total':           sat_grand_total,
        'sat_complete_records':      sat_complete_records,
        'sat_incomplete_records':    sat_incomplete_records,
        'sat_complete_total':        sat_complete_total,
        'sat_incomplete_total':      sat_incomplete_total,
        'sat_complete_by_user':      dict(sat_complete_by_user),
        'sat_complete_chart_json':   json_lib.dumps(sat_complete_chart_json),
        'sat_incomplete_chart_json': json_lib.dumps(sat_incomplete_chart_json),
    })


@login_required
def gps_daily_summary(request):
    """
    รายงานสรุปการทำงานรายวัน — แสดงผลต่อวันต่อช่าง
    • ตรวจสอบความสอดคล้อง GPS (ออกงาน/กลับ/เริ่ม=เสร็จ)
    • เวลาทำงาน (GO_WORK → BACK_OFFICE)
    • สถานที่ที่ไปและจำนวนงาน
    • ผลประเมินความพอใจลูกค้า
    • งานในคิวที่เสร็จ/อยู่ระหว่างดำเนินการในวันนั้น
    """
    from .models import TechnicianGPSLog, CustomerSatisfaction, ServiceQueueItem
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from datetime import date, timedelta
    from collections import defaultdict
    import json as json_lib

    User = get_user_model()
    today = timezone.localdate()
    THAI_DAYS = ['จันทร์', 'อังคาร', 'พุธ', 'พฤหัสบดี', 'ศุกร์', 'เสาร์', 'อาทิตย์']
    THAI_MONTHS_SHORT = ['', 'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.',
                         'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']

    date_str = request.GET.get('date', today.isoformat())
    try:
        report_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        report_date = today

    prev_date = report_date - timedelta(days=1)
    next_date = report_date + timedelta(days=1)
    day_name  = THAI_DAYS[report_date.weekday()]
    month_short = THAI_MONTHS_SHORT[report_date.month]

    # ── Query GPS logs ──────────────────────────────────────────────────
    gps_qs = TechnicianGPSLog.objects.filter(
        timestamp__date=report_date
    ).select_related('user').order_by('timestamp')
    if not user_can_view_all(request.user):
        gps_qs = gps_qs.filter(user=request.user)

    # ── Build per-technician GPS summary ───────────────────────────────
    tech_raw = {}
    for log in gps_qs:
        uname = log.user.username
        uid   = log.user_id
        if uname not in tech_raw:
            tech_raw[uname] = {
                'user_id': uid,
                'logs': [],
                'go_work': None,       # first GO_WORK time
                'back_office': None,   # last BACK_OFFICE time
                'go_work_count': 0,
                'back_office_count': 0,
                'on_site_count': 0,
                'check_out_count': 0,
                'locations': [],       # unique location names
                'satisfaction': [],
                'sat_by_log': {},      # gps_log_id → satisfaction info
                'pending_checkins': [],  # unpaired ON_SITE logs (for pairing)
                'work_sessions': [],   # paired ON_SITE→CHECK_OUT sessions
            }
        c = tech_raw[uname]
        lt = timezone.localtime(log.timestamp)
        t_str = lt.strftime('%H:%M')
        c['logs'].append({
            'time': t_str,
            'type': log.check_type,
            'type_display': log.get_check_type_display(),
            'location': log.location_name or '',
            'notes': log.notes or '',
            'log_id': log.id,
            'lat': float(log.latitude),
            'lng': float(log.longitude),
        })
        ct = log.check_type
        if ct == 'GO_WORK':
            c['go_work_count'] += 1
            if c['go_work'] is None:
                c['go_work'] = t_str
        elif ct == 'BACK_OFFICE':
            c['back_office_count'] += 1
            c['back_office'] = t_str      # keep last one
        elif ct in ('ON_SITE', 'CHECK_IN'):
            c['on_site_count'] += 1
            if log.location_name and log.location_name not in c['locations']:
                c['locations'].append(log.location_name)
            c['pending_checkins'].append({
                'time': t_str, 'dt': lt,
                'location': log.location_name or '',
            })
        elif ct == 'CHECK_OUT':
            c['check_out_count'] += 1
            if c['pending_checkins']:
                ci = c['pending_checkins'].pop(0)
                delta_min = max(0, int((lt - ci['dt']).total_seconds() / 60))
                c['work_sessions'].append({
                    'on_site_time':     ci['time'],
                    'check_out_time':   t_str,
                    'duration_min':     delta_min,
                    'duration_str':     (f"{delta_min // 60}ชม. {delta_min % 60}น."
                                         if delta_min >= 60 else f"{delta_min}น."),
                    'location':         ci['location'],
                    'check_out_log_id': log.id,
                    'customer_name':    '',
                    'customer_phone':   '',
                    'rating':           '',
                    'rating_display':   '',
                })

    # ── Fetch satisfaction linked to today's CHECK_OUT logs ────────────
    sat_qs = CustomerSatisfaction.objects.filter(
        gps_log__timestamp__date=report_date
    ).select_related('gps_log__user')
    if not user_can_view_all(request.user):
        sat_qs = sat_qs.filter(gps_log__user=request.user)
    for s in sat_qs:
        uname = s.gps_log.user.username
        if uname in tech_raw:
            sat_info = {
                'rating':         s.rating,
                'rating_display': s.get_rating_display(),
                'customer_name':  s.customer_name or '',
                'customer_phone': s.customer_phone or '',
                'complete':       bool(s.customer_name and s.customer_phone),
            }
            tech_raw[uname]['satisfaction'].append(sat_info)
            tech_raw[uname]['sat_by_log'][s.gps_log_id] = sat_info

    # ── Link satisfaction info into work sessions ───────────────────────
    for c in tech_raw.values():
        for session in c['work_sessions']:
            sat = c['sat_by_log'].get(session['check_out_log_id'])
            if sat:
                session['customer_name']  = sat['customer_name']
                session['customer_phone'] = sat['customer_phone']
                session['rating']         = sat['rating']
                session['rating_display'] = sat['rating_display']

    # ── Fetch ServiceQueueItems scheduled or completed today ───────────
    queue_qs = ServiceQueueItem.objects.filter(
        scheduled_date=report_date
    ).select_related('project').prefetch_related('assigned_teams__members')
    if not user_can_view_all(request.user):
        queue_qs = queue_qs.filter(assigned_teams__members=request.user)
    queue_by_user = defaultdict(list)
    for qi in queue_qs.distinct():
        for team in qi.assigned_teams.all():
            for member in team.members.all():
                queue_by_user[member.username].append({
                    'id': qi.id,
                    'title': qi.title,
                    'status': qi.status,
                    'status_display': qi.get_status_display(),
                    'priority': qi.priority,
                    'task_type_display': qi.get_task_type_display(),
                    'project_name': qi.project.name if qi.project else '',
                    'completed': qi.status == 'COMPLETED',
                })

    # ── Build final technician list ────────────────────────────────────
    RATING_ORDER = {'VERY_SATISFIED': 0, 'SATISFIED': 1, 'NOT_SATISFIED': 2}
    tech_list = []
    for uname in sorted(tech_raw.keys()):
        c = tech_raw[uname]
        go_ok   = c['go_work_count'] == 1
        back_ok = c['back_office_count'] == 1
        bal_ok  = c['on_site_count'] == c['check_out_count']
        consistent = go_ok and back_ok and bal_ok

        # work duration
        work_duration = None
        if c['go_work'] and c['back_office']:
            try:
                from datetime import datetime
                fmt = '%H:%M'
                t1 = datetime.strptime(c['go_work'], fmt)
                t2 = datetime.strptime(c['back_office'], fmt)
                delta_min = int((t2 - t1).total_seconds() / 60)
                if delta_min > 0:
                    work_duration = f"{delta_min // 60}ชม. {delta_min % 60}น."
            except Exception:
                pass

        sat_list = c['satisfaction']
        sat_counts = {'VERY_SATISFIED': 0, 'SATISFIED': 0, 'NOT_SATISFIED': 0}
        sat_complete = sum(1 for s in sat_list if s['complete'])
        sat_incomplete = len(sat_list) - sat_complete
        for s in sat_list:
            if s['rating'] in sat_counts:
                sat_counts[s['rating']] += 1

        queue_items = queue_by_user.get(uname, [])
        jobs_done = sum(1 for q in queue_items if q['completed'])

        # total on-site working time (sum of all paired sessions)
        total_onsite_min = sum(s['duration_min'] for s in c['work_sessions'])
        if total_onsite_min > 0:
            total_onsite_duration = (f"{total_onsite_min // 60}ชม. {total_onsite_min % 60}น."
                                     if total_onsite_min >= 60 else f"{total_onsite_min}น.")
        else:
            total_onsite_duration = ''

        tech_list.append({
            'username':               uname,
            'user_id':                c['user_id'],
            'logs':                   c['logs'],
            'go_work_time':           c['go_work'] or '',
            'back_office_time':       c['back_office'] or '',
            'go_work_count':          c['go_work_count'],
            'back_office_count':      c['back_office_count'],
            'on_site_count':          c['on_site_count'],
            'check_out_count':        c['check_out_count'],
            'locations':              c['locations'],
            'work_duration':          work_duration,
            'consistent':             consistent,
            'go_work_ok':             go_ok,
            'back_office_ok':         back_ok,
            'onsite_balanced':        bal_ok,
            'satisfaction':           sat_list,
            'sat_counts':             sat_counts,
            'sat_complete':           sat_complete,
            'sat_incomplete':         sat_incomplete,
            'queue_items':            queue_items,
            'jobs_done':              jobs_done,
            'total_jobs':             len(queue_items),
            'total_logs':             len(c['logs']),
            'work_sessions':          c['work_sessions'],
            'total_onsite_duration':  total_onsite_duration,
            'total_onsite_min':       total_onsite_min,
        })

    # ── Summary stats ──────────────────────────────────────────────────
    total_techs           = len(tech_list)
    consistent_techs      = sum(1 for t in tech_list if t['consistent'])
    total_locations       = sum(t['on_site_count'] for t in tech_list)
    total_sat             = sum(len(t['satisfaction']) for t in tech_list)
    total_sat_vs          = sum(t['sat_counts']['VERY_SATISFIED'] for t in tech_list)
    total_sat_s           = sum(t['sat_counts']['SATISFIED'] for t in tech_list)
    total_sat_ns          = sum(t['sat_counts']['NOT_SATISFIED'] for t in tech_list)
    total_jobs_done       = sum(t['jobs_done'] for t in tech_list)
    total_onsite_min_all  = sum(t['total_onsite_min'] for t in tech_list)
    if total_onsite_min_all > 0:
        total_onsite_duration_all = (f"{total_onsite_min_all // 60}ชม. {total_onsite_min_all % 60}น."
                                     if total_onsite_min_all >= 60 else f"{total_onsite_min_all}น.")
    else:
        total_onsite_duration_all = ''

    return render(request, 'pms/gps_daily_summary.html', {
        'report_date':              report_date,
        'prev_date':                prev_date,
        'next_date':                next_date,
        'today':                    today,
        'day_name':                 day_name,
        'month_short':              month_short,
        'tech_list':                tech_list,
        'total_techs':              total_techs,
        'consistent_techs':         consistent_techs,
        'total_locations':          total_locations,
        'total_sat':                total_sat,
        'total_sat_vs':             total_sat_vs,
        'total_sat_s':              total_sat_s,
        'total_sat_ns':             total_sat_ns,
        'total_jobs_done':          total_jobs_done,
        'total_onsite_duration_all': total_onsite_duration_all,
    })


@login_required
def gps_daily_summary_send_to_chat(request):
    """
    ส่งสรุปการทำงานประจำวัน (GPS Daily Summary) ไปยัง ChatRoom id=1
    — ส่งข้อความ HTML หนึ่งชุดสรุปทุกคน พร้อม broadcast ผ่าน WebSocket
    """
    if request.method != 'POST':
        from django.http import JsonResponse
        return JsonResponse({'ok': False, 'error': 'POST only'}, status=405)

    from django.http import JsonResponse
    from django.utils import timezone
    from datetime import date, timedelta
    from collections import defaultdict
    from .models import TechnicianGPSLog, CustomerSatisfaction, ServiceQueueItem
    from django.contrib.auth import get_user_model

    User = get_user_model()
    today = timezone.localdate()
    THAI_DAYS = ['จันทร์', 'อังคาร', 'พุธ', 'พฤหัสบดี', 'ศุกร์', 'เสาร์', 'อาทิตย์']
    THAI_MONTHS_SHORT = ['', 'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.',
                         'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']

    date_str = request.POST.get('date', today.isoformat())
    try:
        report_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        report_date = today

    day_name    = THAI_DAYS[report_date.weekday()]
    month_short = THAI_MONTHS_SHORT[report_date.month]
    date_label  = f"{day_name} {report_date.day} {month_short} {report_date.year + 543}"

    # ── Reuse the same query logic as gps_daily_summary ─────────────────
    gps_qs = TechnicianGPSLog.objects.filter(
        timestamp__date=report_date
    ).select_related('user').order_by('timestamp')

    tech_raw = {}
    for log in gps_qs:
        uname = log.user.username
        uid   = log.user_id
        if uname not in tech_raw:
            tech_raw[uname] = {
                'user_id': uid,
                'go_work': None, 'back_office': None,
                'go_work_count': 0, 'back_office_count': 0,
                'on_site_count': 0, 'check_out_count': 0,
                'locations': [],
                'satisfaction': [],
                'sat_by_log': {},
                'pending_checkins': [],
                'work_sessions': [],
                'gps_points': [],   # (lat, lng, check_type)
            }
        c = tech_raw[uname]
        lt    = timezone.localtime(log.timestamp)
        t_str = lt.strftime('%H:%M')
        ct = log.check_type
        lat = float(log.latitude)
        lng = float(log.longitude)
        if lat != 0 and lng != 0:
            c['gps_points'].append((lat, lng, ct))
        if ct == 'GO_WORK':
            c['go_work_count'] += 1
            if c['go_work'] is None:
                c['go_work'] = t_str
        elif ct == 'BACK_OFFICE':
            c['back_office_count'] += 1
            c['back_office'] = t_str
        elif ct in ('ON_SITE', 'CHECK_IN'):
            c['on_site_count'] += 1
            if log.location_name and log.location_name not in c['locations']:
                c['locations'].append(log.location_name)
            c['pending_checkins'].append({'time': t_str, 'dt': lt, 'location': log.location_name or ''})
        elif ct == 'CHECK_OUT':
            c['check_out_count'] += 1
            if c['pending_checkins']:
                ci = c['pending_checkins'].pop(0)
                delta_min = max(0, int((lt - ci['dt']).total_seconds() / 60))
                c['work_sessions'].append({
                    'on_site_time': ci['time'], 'check_out_time': t_str,
                    'duration_min': delta_min,
                    'duration_str': (f"{delta_min // 60}ชม. {delta_min % 60}น." if delta_min >= 60 else f"{delta_min}น."),
                    'location': ci['location'], 'check_out_log_id': log.id,
                    'customer_name': '', 'rating': '',
                })

    sat_qs = CustomerSatisfaction.objects.filter(
        gps_log__timestamp__date=report_date
    ).select_related('gps_log__user')
    for s in sat_qs:
        uname = s.gps_log.user.username
        if uname in tech_raw:
            si = {'rating': s.rating, 'rating_display': s.get_rating_display(),
                  'customer_name': s.customer_name or ''}
            tech_raw[uname]['satisfaction'].append(si)
            tech_raw[uname]['sat_by_log'][s.gps_log_id] = si

    for c in tech_raw.values():
        for session in c['work_sessions']:
            sat = c['sat_by_log'].get(session['check_out_log_id'])
            if sat:
                session['customer_name'] = sat['customer_name']
                session['rating']        = sat['rating']

    queue_qs = ServiceQueueItem.objects.filter(
        scheduled_date=report_date
    ).prefetch_related('assigned_teams__members')
    queue_by_user = defaultdict(list)
    for qi in queue_qs.distinct():
        for team in qi.assigned_teams.all():
            for member in team.members.all():
                queue_by_user[member.username].append({
                    'title': qi.title,
                    'completed': qi.status == 'COMPLETED',
                    'status_display': qi.get_status_display(),
                })

    # ── Build tech_list ──────────────────────────────────────────────
    tech_list = []
    for uname in sorted(tech_raw.keys()):
        c = tech_raw[uname]
        go_ok      = c['go_work_count'] == 1
        back_ok    = c['back_office_count'] == 1
        bal_ok     = c['on_site_count'] == c['check_out_count']
        consistent = go_ok and back_ok and bal_ok

        work_duration = ''
        if c['go_work'] and c['back_office']:
            try:
                from datetime import datetime as dt_cls
                t1 = dt_cls.strptime(c['go_work'], '%H:%M')
                t2 = dt_cls.strptime(c['back_office'], '%H:%M')
                dm = int((t2 - t1).total_seconds() / 60)
                if dm > 0:
                    work_duration = f"{dm // 60}ชม. {dm % 60}น."
            except Exception:
                pass

        sat_counts = {'VERY_SATISFIED': 0, 'SATISFIED': 0, 'NOT_SATISFIED': 0}
        for s in c['satisfaction']:
            if s['rating'] in sat_counts:
                sat_counts[s['rating']] += 1

        total_onsite_min = sum(s['duration_min'] for s in c['work_sessions'])
        total_onsite_dur = (f"{total_onsite_min // 60}ชม. {total_onsite_min % 60}น."
                            if total_onsite_min >= 60 else (f"{total_onsite_min}น." if total_onsite_min else ''))

        queue_items = queue_by_user.get(uname, [])
        jobs_done   = sum(1 for q in queue_items if q['completed'])

        gps_pts = c['gps_points']

        tech_list.append({
            'username':          uname,
            'consistent':        consistent,
            'go_work_time':      c['go_work'] or '',
            'back_office_time':  c['back_office'] or '',
            'work_duration':     work_duration,
            'on_site_count':     c['on_site_count'],
            'check_out_count':   c['check_out_count'],
            'locations':         c['locations'],
            'sat_counts':        sat_counts,
            'total_sat':         len(c['satisfaction']),
            'work_sessions':     c['work_sessions'],
            'total_onsite_dur':  total_onsite_dur,
            'queue_items':       queue_items,
            'jobs_done':         jobs_done,
            'total_jobs':        len(queue_items),
            'gps_count':         len(gps_pts),
        })

    if not tech_list:
        return JsonResponse({'ok': False, 'error': 'ไม่มีข้อมูล GPS สำหรับวันนี้'})

    # ── Build HTML message ────────────────────────────────────────────
    RATING_EMOJI   = {'VERY_SATISFIED': '😊', 'SATISFIED': '🙂', 'NOT_SATISFIED': '😞'}
    RATING_COLOR   = {'VERY_SATISFIED': '#15803d', 'SATISFIED': '#1d4ed8', 'NOT_SATISFIED': '#991b1b', '': '#64748b'}
    RATING_BG      = {'VERY_SATISFIED': '#dcfce7', 'SATISFIED': '#dbeafe', 'NOT_SATISFIED': '#fee2e2', '': '#f1f5f9'}
    RATING_LABEL   = {'VERY_SATISFIED': 'พอใจมาก', 'SATISFIED': 'พอใจ', 'NOT_SATISFIED': 'ไม่พอใจ', '': '—'}
    SEP = '<div style="border-top:1px solid #e2e8f0;margin:6px 0;"></div>'

    cards_html = []
    for t in tech_list:
        status_color = '#22c55e' if t['consistent'] else '#f97316'
        status_bg    = '#dcfce7' if t['consistent'] else '#fff7ed'
        status_text  = '✅ GPS สอดคล้อง' if t['consistent'] else '⚠️ GPS ไม่ครบ'

        # ── Time summary row ─────────────────────────────────────────
        time_parts = []
        if t['go_work_time']:
            time_parts.append(f"🚀 {t['go_work_time']}")
        if t['back_office_time']:
            time_parts.append(f"🏢 {t['back_office_time']}")
        time_row = ' → '.join(time_parts) if time_parts else 'ยังไม่ออกงาน'
        dur_badge = (f'<span style="background:#dbeafe;color:#1d4ed8;padding:2px 8px;border-radius:999px;'
                     f'font-size:0.8rem;font-weight:700;margin-left:6px;">⏱ {t["work_duration"]}</span>') if t['work_duration'] else ''

        # ── Stats pills ───────────────────────────────────────────────
        vs = t['sat_counts']['VERY_SATISFIED']
        s_ = t['sat_counts']['SATISFIED']
        ns = t['sat_counts']['NOT_SATISFIED']
        sat_html = ''
        if t['total_sat']:
            sat_html = (
                f'<span style="background:#dcfce7;color:#15803d;padding:1px 8px;border-radius:999px;font-size:0.78rem;">😊 {vs}</span> '
                f'<span style="background:#dbeafe;color:#1d4ed8;padding:1px 8px;border-radius:999px;font-size:0.78rem;">🙂 {s_}</span> '
                + (f'<span style="background:#fee2e2;color:#991b1b;padding:1px 8px;border-radius:999px;font-size:0.78rem;">😞 {ns}</span> ' if ns else '')
            )

        # ── Work sessions ─────────────────────────────────────────────
        sessions_html = ''
        if t['work_sessions']:
            rows = []
            for i, s in enumerate(t['work_sessions'], 1):
                r      = s.get('rating', '')
                r_emoji = RATING_EMOJI.get(r, '')
                r_label = RATING_LABEL.get(r, '')
                r_color = RATING_COLOR.get(r, '#64748b')
                r_bg    = RATING_BG.get(r, '#f1f5f9')
                cust    = s.get('customer_name', '')
                loc     = s.get('location', '')
                loc_span  = f'<span style="color:#2563eb;margin-left:4px;">📍{loc}</span>' if loc else ''
                cust_span = (f'<span style="background:{r_bg};color:{r_color};padding:0 6px;border-radius:4px;font-size:0.75rem;margin-left:4px;">'
                             f'{r_emoji} {cust} · {r_label}</span>') if cust else ''
                rows.append(
                    f'<div style="padding:3px 0 3px 8px;border-left:3px solid #e2e8f0;margin:3px 0;font-size:0.85rem;color:#334155;">'
                    f'<b>{i}.</b> <code style="background:#f1f5f9;padding:0 4px;border-radius:3px;">{s["on_site_time"]}→{s["check_out_time"]}</code> '
                    f'<span style="background:#eff6ff;color:#2563eb;padding:0 6px;border-radius:4px;font-size:0.78rem;">⏱{s["duration_str"]}</span>'
                    f'{loc_span}{cust_span}'
                    f'</div>'
                )
            total_badge = (f'<div style="margin-top:4px;font-size:0.82rem;color:#1d4ed8;font-weight:700;">'
                           f'รวมหน้างาน ⏱ {t["total_onsite_dur"]}</div>') if t['total_onsite_dur'] else ''
            sessions_html = (
                f'{SEP}'
                f'<div style="font-size:0.75rem;font-weight:700;color:#94a3b8;letter-spacing:.05em;margin-bottom:4px;">⏱ งานหน้างาน {len(t["work_sessions"])} งาน</div>'
                + ''.join(rows) + total_badge
            )

        # ── Queue items ───────────────────────────────────────────────
        queue_html = ''
        if t['queue_items']:
            rows = []
            for q in t['queue_items']:
                done  = q['completed']
                clr   = '#15803d' if done else '#334155'
                bg    = '#dcfce7' if done else '#f1f5f9'
                dot   = '✅' if done else '🔵'
                rows.append(
                    f'<div style="padding:2px 0;font-size:0.84rem;color:{clr};">'
                    f'{dot} {q["title"][:55]}'
                    f'<span style="background:{bg};color:{clr};padding:0 5px;border-radius:3px;font-size:0.72rem;margin-left:4px;">'
                    f'{q["status_display"]}</span></div>'
                )
            queue_html = (
                f'{SEP}'
                f'<div style="font-size:0.75rem;font-weight:700;color:#94a3b8;letter-spacing:.05em;margin-bottom:4px;">'
                f'📋 คิวงาน {t["jobs_done"]}/{t["total_jobs"]} เสร็จ</div>'
                + ''.join(rows)
            )

        # ── Leaflet iframe map ────────────────────────────────────────
        map_html = ''
        if t['gps_count'] > 0:
            map_url = f"/pms/gps-tracking/map-embed/{t['username']}/{report_date.isoformat()}/"
            uname_t = t['username']
            img_url = f'/pms/gps-tracking/map-image/{uname_t}/{report_date.isoformat()}/'
            map_html = (
                f'{SEP}'
                f'<div style="font-size:0.75rem;font-weight:700;color:#94a3b8;letter-spacing:.05em;margin-bottom:6px;">'
                f'🗺️ เส้นทางการเดินทาง ({t["gps_count"]} จุด)</div>'
                f'<img src="{img_url}" '
                f'style="width:100%;border-radius:10px;border:1px solid #e2e8f0;display:block;" '
                f'alt="แผนที่ {uname_t}" loading="lazy"/>'
            )

        cards_html.append(
            f'<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;'
            f'overflow:hidden;margin:8px 0;font-family:system-ui,sans-serif;box-shadow:0 1px 4px rgba(0,0,0,0.06);">'

            # ── Card header ───────────────────────────────────────────
            f'<div style="background:linear-gradient(135deg,#1e293b,#334155);padding:10px 14px;'
            f'display:flex;align-items:center;gap:8px;">'
            f'<div style="background:{status_color};width:10px;height:10px;border-radius:50%;flex-shrink:0;"></div>'
            f'<span style="font-weight:700;font-size:0.95rem;color:#fff;flex:1;">👷 {t["username"]}</span>'
            f'<span style="background:{status_bg};color:{status_color};padding:2px 9px;border-radius:999px;'
            f'font-size:0.72rem;font-weight:700;">{status_text}</span>'
            f'</div>'

            # ── Card body ─────────────────────────────────────────────
            f'<div style="padding:10px 14px;">'
            # time + duration
            f'<div style="font-size:0.88rem;color:#475569;margin-bottom:5px;">{time_row}{dur_badge}</div>'
            # stat pills row
            f'<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:2px;">'
            f'<span style="background:#f1f5f9;color:#475569;padding:1px 8px;border-radius:999px;font-size:0.78rem;">🏠 {t["on_site_count"]} จุด</span>'
            + (f'<span style="background:#f1f5f9;color:#475569;padding:1px 8px;border-radius:999px;font-size:0.78rem;">📊 {t["gps_count"]} GPS log</span>' if t['gps_count'] else '')
            + sat_html
            + f'</div>'
            + sessions_html + queue_html + map_html
            + f'</div></div>'
        )

    consistent_count = sum(1 for t in tech_list if t['consistent'])
    total_sites      = sum(t['on_site_count'] for t in tech_list)
    total_sat_all    = sum(t['total_sat'] for t in tech_list)

    header_html = f"""<div style="background:linear-gradient(135deg,#0f172a,#1e3a5f);color:white;border-radius:12px;padding:14px 18px;margin-bottom:10px;font-family:system-ui,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,0.18);">
  <div style="font-weight:800;font-size:1.1rem;margin-bottom:6px;">📋 สรุปการทำงานประจำวัน</div>
  <div style="opacity:0.85;font-size:0.88rem;margin-bottom:10px;">{date_label}</div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;">
    <span style="background:rgba(255,255,255,0.12);padding:3px 12px;border-radius:999px;font-size:0.82rem;">👷 {len(tech_list)} คน</span>
    <span style="background:rgba(34,197,94,0.25);color:#86efac;padding:3px 12px;border-radius:999px;font-size:0.82rem;">✅ GPS {consistent_count}/{len(tech_list)}</span>
    <span style="background:rgba(255,255,255,0.12);padding:3px 12px;border-radius:999px;font-size:0.82rem;">📍 {total_sites} จุด</span>
    <span style="background:rgba(255,255,255,0.12);padding:3px 12px;border-radius:999px;font-size:0.82rem;">😊 ประเมิน {total_sat_all} ครั้ง</span>
  </div>
</div>"""

    full_html = header_html + '\n'.join(cards_html)

    # ── Post to ChatRoom id=1 ─────────────────────────────────────────
    try:
        from chat.models import ChatRoom, ChatMessage
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        chat_room = ChatRoom.objects.filter(pk=1, is_active=True).first()
        if not chat_room:
            return JsonResponse({'ok': False, 'error': 'ไม่พบห้องแชท id=1'})

        msg = ChatMessage.objects.create(
            room=chat_room,
            user=request.user,
            content=full_html,
            is_html=True,
        )

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'chat_{chat_room.id}',
            {
                'type': 'chat_message',
                'message': full_html,
                'username': request.user.username,
                'user_id': request.user.id,
                'is_stt': False,
                'is_html': True,
                'image_url': None,
                'file_url': None,
                'latitude': None,
                'longitude': None,
                'location_name': '',
                'timestamp': timezone.localtime(msg.timestamp).strftime('%H:%M'),
            }
        )
        return JsonResponse({'ok': True, 'sent': len(tech_list)})

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f'gps_daily_summary_send_to_chat error: {e}')
        return JsonResponse({'ok': False, 'error': str(e)})


@login_required
def gps_map_embed(request, username, date_str):
    """
    Standalone Leaflet map page สำหรับ embed ใน iframe ในห้องแชท
    แสดงเส้นทาง GPS ของช่างคนหนึ่งในวันที่กำหนด
    """
    from django.http import HttpResponse
    from .models import TechnicianGPSLog
    from django.utils import timezone
    from datetime import date
    import json as json_lib

    try:
        report_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        report_date = timezone.localdate()

    logs = TechnicianGPSLog.objects.filter(
        user__username=username,
        timestamp__date=report_date,
    ).order_by('timestamp')

    TYPE_COLOR = {
        'GO_WORK':     '#2563eb',
        'ON_SITE':     '#16a34a',
        'CHECK_IN':    '#16a34a',
        'CHECK_OUT':   '#dc2626',
        'BACK_OFFICE': '#7c3aed',
        'TRAVEL':      '#64748b',
    }
    TYPE_ICON = {
        'GO_WORK': '🚀', 'ON_SITE': '↑', 'CHECK_IN': '↑',
        'CHECK_OUT': '↓', 'BACK_OFFICE': '🏢', 'TRAVEL': '•',
    }
    TYPE_LABEL = {
        'GO_WORK': 'ออกทำงาน', 'ON_SITE': 'เริ่มงาน', 'CHECK_IN': 'เช็คอิน',
        'CHECK_OUT': 'เสร็จงาน', 'BACK_OFFICE': 'กลับออฟฟิศ', 'TRAVEL': 'เดินทาง',
    }

    points = []
    for i, log in enumerate(logs, 1):
        lat = float(log.latitude)
        lng = float(log.longitude)
        if lat == 0 and lng == 0:
            continue
        lt = timezone.localtime(log.timestamp)
        points.append({
            'i': i, 'lat': lat, 'lng': lng,
            'type': log.check_type,
            'color': TYPE_COLOR.get(log.check_type, '#64748b'),
            'icon': TYPE_ICON.get(log.check_type, '•'),
            'label': TYPE_LABEL.get(log.check_type, log.check_type),
            'time': lt.strftime('%H:%M'),
            'location': log.location_name or '',
            'notes': log.notes or '',
        })

    points_json = json_lib.dumps(points, ensure_ascii=False)
    date_th = report_date.strftime('%d/%m/') + str(report_date.year + 543)

    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<style>
  * {{ margin:0;padding:0;box-sizing:border-box; }}
  body {{ font-family:system-ui,sans-serif;background:#0f172a; }}
  #header {{ background:linear-gradient(135deg,#1e293b,#334155);color:white;padding:8px 12px;font-size:0.82rem;display:flex;align-items:center;gap:8px; }}
  #header strong {{ font-size:0.9rem; }}
  #map {{ width:100%;height:calc(100vh - 40px); }}
  .legend {{ background:white;padding:6px 10px;border-radius:8px;font-size:0.72rem;line-height:1.7; }}
</style>
</head>
<body>
<div id="header">
  <span>👷</span>
  <strong>{username}</strong>
  <span style="opacity:0.7;">· {date_th} · {len(points)} จุด</span>
</div>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const PTS = {points_json};
if (PTS.length === 0) {{
  document.getElementById('map').innerHTML = '<div style="color:#94a3b8;text-align:center;padding:40px;font-size:0.9rem;">ไม่มีข้อมูล GPS</div>';
}} else {{
  const map = L.map('map');
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{
    attribution:'© OpenStreetMap', maxZoom:18
  }}).addTo(map);

  const lls = [];
  PTS.forEach(function(p, idx) {{
    const icon = L.divIcon({{
      html: '<div style="background:' + p.color + ';color:white;width:26px;height:26px;border-radius:50%;' +
            'display:flex;align-items:center;justify-content:center;font-size:0.72rem;font-weight:700;' +
            'border:2px solid white;box-shadow:0 2px 5px rgba(0,0,0,0.35);">' + p.i + '</div>',
      className:'', iconSize:[26,26], iconAnchor:[13,13]
    }});
    const ll = [p.lat, p.lng];
    lls.push(ll);
    const popup = '<div style="font-size:0.8rem;min-width:150px;">' +
      '<div style="font-weight:700;color:' + p.color + '">' + p.icon + ' ' + p.label + '</div>' +
      '<div>' + p.time + '</div>' +
      (p.location ? '<div style="color:#2563eb">📍 ' + p.location + '</div>' : '') +
      (p.notes ? '<div style="color:#64748b;font-size:0.72rem">' + p.notes + '</div>' : '') +
      '</div>';
    L.marker(ll, {{icon}}).addTo(map).bindPopup(popup);
  }});

  if (lls.length > 1) {{
    L.polyline(lls, {{color:'#3b82f6',weight:3,opacity:0.75}}).addTo(map);

    // ── Directional arrows on each segment ────────────────────────────
    function _addArrow(map, p1, p2) {{
      var dy = p2[0] - p1[0];
      var dx = p2[1] - p1[1];
      var dist = Math.sqrt(dx*dx + dy*dy);
      if (dist < 0.00015) return;  // too short
      var mx = p1[0] + dy * 0.55;
      var my = p1[1] + dx * 0.55;
      // angle in degrees for CSS rotate (Leaflet lat/lng: north=up)
      var angleDeg = Math.atan2(dx, dy) * 180 / Math.PI;
      var arrowIcon = L.divIcon({{
        html: '<div style="transform:rotate(' + angleDeg + 'deg);' +
              'font-size:16px;line-height:1;color:#2563eb;' +
              'text-shadow:0 0 3px white,0 0 3px white;' +
              'display:flex;align-items:center;justify-content:center;' +
              'width:18px;height:18px;margin:-9px 0 0 -9px;">▶</div>',
        className: '',
        iconSize: [18, 18],
        iconAnchor: [9, 9],
      }});
      L.marker([mx, my], {{icon: arrowIcon, interactive: false}}).addTo(map);
    }}

    for (var i = 0; i < lls.length - 1; i++) {{
      _addArrow(map, lls[i], lls[i+1]);
    }}
  }}

  // Legend
  const legend = L.control({{position:'bottomright'}});
  legend.onAdd = function() {{
    const div = L.DomUtil.create('div','legend');
    div.innerHTML = '<b style="display:block;margin-bottom:2px;">สัญลักษณ์</b>' +
      '<span style="color:#2563eb">🚀 ออกทำงาน</span><br>' +
      '<span style="color:#16a34a">↑ เริ่มงาน</span><br>' +
      '<span style="color:#dc2626">↓ เสร็จงาน</span><br>' +
      '<span style="color:#7c3aed">🏢 กลับออฟฟิศ</span><br>' +
      '<span style="color:#64748b">• เดินทาง</span>';
    return div;
  }};
  legend.addTo(map);

  map.fitBounds(L.latLngBounds(lls), {{padding:[20,20]}});
}}
</script>
</body>
</html>"""
    return HttpResponse(html, content_type='text/html; charset=utf-8')


@login_required
def gps_map_image(request, username, date_str):
    """
    Generate PNG map image of a technician's GPS route using OSM tiles + Pillow.
    Returns image/png response — ใช้ใน <img src="..."> ในห้องแชทได้เลย
    """
    import math, io, requests as req_lib
    from PIL import Image, ImageDraw, ImageFont
    from django.http import HttpResponse, Http404
    from .models import TechnicianGPSLog
    from django.utils import timezone
    from datetime import date

    try:
        report_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        raise Http404

    logs = TechnicianGPSLog.objects.filter(
        user__username=username,
        timestamp__date=report_date,
    ).order_by('timestamp')

    points = []
    for log in logs:
        lat = float(log.latitude)
        lng = float(log.longitude)
        if lat != 0 or lng != 0:
            points.append((lat, lng, log.check_type))

    if not points:
        # Return simple placeholder image
        img = Image.new('RGB', (560, 200), color='#f1f5f9')
        draw = ImageDraw.Draw(img)
        draw.text((200, 90), 'ไม่มีข้อมูล GPS', fill='#94a3b8')
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # ── Map parameters ───────────────────────────────────────────────────────
    IMG_W, IMG_H = 560, 240
    TILE_SIZE    = 256

    def deg2num(lat, lng, zoom):
        lat_r = math.radians(lat)
        n = 2 ** zoom
        x = (lng + 180) / 360 * n
        y = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n
        return x, y

    def num2deg(xtile, ytile, zoom):
        n = 2 ** zoom
        lng = xtile / n * 360 - 180
        lat_r = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
        return math.degrees(lat_r), lng

    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    lat_min, lat_max = min(lats), max(lats)
    lng_min, lng_max = min(lngs), max(lngs)

    # Auto zoom
    def _zoom_for_extent(lat_min, lat_max, lng_min, lng_max, w, h):
        for zoom in range(16, 9, -1):
            x0, y0 = deg2num(lat_max, lng_min, zoom)
            x1, y1 = deg2num(lat_min, lng_max, zoom)
            px_w = (x1 - x0) * TILE_SIZE
            px_h = (y1 - y0) * TILE_SIZE
            if px_w <= w * 0.75 and px_h <= h * 0.75:
                return zoom
        return 12

    if lat_min == lat_max and lng_min == lng_max:
        zoom = 14
    else:
        zoom = _zoom_for_extent(lat_min, lat_max, lng_min, lng_max, IMG_W, IMG_H)

    center_lat = (lat_min + lat_max) / 2
    center_lng = (lng_min + lng_max) / 2
    cx, cy = deg2num(center_lat, center_lng, zoom)

    # Tile range to cover IMG_W x IMG_H
    tiles_x = math.ceil(IMG_W / TILE_SIZE) + 2
    tiles_y = math.ceil(IMG_H / TILE_SIZE) + 2

    tile_x0 = int(cx) - tiles_x // 2
    tile_y0 = int(cy) - tiles_y // 2

    canvas_w = (tiles_x + 1) * TILE_SIZE
    canvas_h = (tiles_y + 1) * TILE_SIZE
    canvas = Image.new('RGB', (canvas_w, canvas_h), '#e2e8f0')

    headers = {'User-Agent': 'PMS-GPS-Report/1.0 (internal app)'}
    for tx in range(tile_x0, tile_x0 + tiles_x + 1):
        for ty in range(tile_y0, tile_y0 + tiles_y + 1):
            tile_url = f'https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png'
            try:
                r = req_lib.get(tile_url, headers=headers, timeout=4)
                if r.status_code == 200:
                    tile_img = Image.open(io.BytesIO(r.content)).convert('RGB')
                    px = (tx - tile_x0) * TILE_SIZE
                    py = (ty - tile_y0) * TILE_SIZE
                    canvas.paste(tile_img, (px, py))
            except Exception:
                pass

    # Offset so center of canvas = center of map
    offset_x = canvas_w // 2 - int((cx - int(cx)) * TILE_SIZE) - (int(cx) - tile_x0) * TILE_SIZE
    offset_y = canvas_h // 2 - int((cy - int(cy)) * TILE_SIZE) - (int(cy) - tile_y0) * TILE_SIZE

    def latlon_to_px(lat, lng):
        tx, ty = deg2num(lat, lng, zoom)
        px = int((tx - tile_x0) * TILE_SIZE) + offset_x + (IMG_W // 2 - canvas_w // 2)
        py = int((ty - tile_y0) * TILE_SIZE) + offset_y + (IMG_H // 2 - canvas_h // 2)
        return px, py

    # Crop to IMG_W x IMG_H centered
    left  = canvas_w // 2 - IMG_W // 2 - offset_x
    top   = canvas_h // 2 - IMG_H // 2 - offset_y
    map_img = canvas.crop((left, top, left + IMG_W, top + IMG_H))

    def _latlon_to_crop(lat, lng):
        tx, ty = deg2num(lat, lng, zoom)
        px = int((tx - tile_x0) * TILE_SIZE) - left
        py = int((ty - tile_y0) * TILE_SIZE) - top
        return px, py

    draw = ImageDraw.Draw(map_img)

    # ── Helper: draw directional arrow at midpoint of segment ────────────
    def _draw_arrow(d, p1, p2, color, size=9):
        x1, y1 = p1
        x2, y2 = p2
        seg_len = math.hypot(x2 - x1, y2 - y1)
        if seg_len < 20:   # too short — skip
            return
        angle = math.atan2(y2 - y1, x2 - x1)
        # Place arrow at 55% along the segment
        mx = x1 + (x2 - x1) * 0.55
        my = y1 + (y2 - y1) * 0.55
        # Tip and base of arrowhead
        tip   = (mx + math.cos(angle) * size,       my + math.sin(angle) * size)
        perp  = angle + math.pi / 2
        left  = (mx - math.cos(angle) * size * 0.6 + math.cos(perp) * size * 0.55,
                 my - math.sin(angle) * size * 0.6 + math.sin(perp) * size * 0.55)
        right = (mx - math.cos(angle) * size * 0.6 - math.cos(perp) * size * 0.55,
                 my - math.sin(angle) * size * 0.6 - math.sin(perp) * size * 0.55)
        d.polygon([tip, left, right], fill=color, outline='white')

    # Draw polyline segments + directional arrows
    px_pts = [_latlon_to_crop(p[0], p[1]) for p in points]
    LINE_COLOR = (59, 130, 246)   # #3b82f6
    if len(px_pts) > 1:
        draw.line(px_pts, fill=LINE_COLOR, width=3)
        for i in range(len(px_pts) - 1):
            _draw_arrow(draw, px_pts[i], px_pts[i + 1], LINE_COLOR)

    # Marker colors
    TYPE_COLOR = {
        'GO_WORK':     (37, 99, 235),
        'ON_SITE':     (22, 163, 74),
        'CHECK_IN':    (22, 163, 74),
        'CHECK_OUT':   (220, 38, 38),
        'BACK_OFFICE': (124, 58, 237),
        'TRAVEL':      (100, 116, 139),
    }

    R = 8
    for i, (lat, lng, ct) in enumerate(points, 1):
        px, py = _latlon_to_crop(lat, lng)
        color = TYPE_COLOR.get(ct, (100, 116, 139))
        draw.ellipse([px - R, py - R, px + R, py + R], fill=color, outline='white', width=2)
        try:
            draw.text((px - 4, py - 6), str(i), fill='white')
        except Exception:
            pass

    # Header bar
    bar = Image.new('RGB', (IMG_W, 28), (30, 41, 59))
    bar_draw = ImageDraw.Draw(bar)
    bar_draw.text((10, 6), f'{username}  |  {report_date.strftime("%d/%m/")+str(report_date.year+543)}  |  {len(points)} จุด', fill='white')
    final = Image.new('RGB', (IMG_W, IMG_H + 28))
    final.paste(bar, (0, 0))
    final.paste(map_img, (0, 28))

    buf = io.BytesIO()
    final.save(buf, 'PNG', optimize=True)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
def gps_summary_export(request):
    """
    Export รายงานสรุป GPS รายเดือน เป็น CSV
    """
    import csv
    from .models import TechnicianGPSLog
    from django.utils import timezone
    from collections import defaultdict
    import calendar
    from datetime import date
    from django.http import HttpResponse

    User = get_user_model()
    today = timezone.localdate()

    THAI_MONTHS = ['', 'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
                   'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม']

    try:
        year  = int(request.GET.get('year',  today.year))
        month = int(request.GET.get('month', today.month))
        if not (1 <= month <= 12):
            raise ValueError
    except (ValueError, TypeError):
        year, month = today.year, today.month

    _, last_day = calendar.monthrange(year, month)
    start_date  = date(year, month, 1)
    end_date    = date(year, month, last_day)

    qs = TechnicianGPSLog.objects.filter(
        timestamp__date__gte=start_date,
        timestamp__date__lte=end_date,
    ).select_related('user').order_by('timestamp')

    if not (user_can_view_all(request.user)):
        qs = qs.filter(user=request.user)

    raw_data = defaultdict(lambda: defaultdict(lambda: {
        'count': 0, 'first': None, 'last': None, 'types': set()
    }))
    users_ordered = {}
    for log in qs:
        d     = timezone.localtime(log.timestamp).date()
        uname = log.user.username
        users_ordered[uname] = True
        cell  = raw_data[d][uname]
        cell['count'] += 1
        local_ts = timezone.localtime(log.timestamp)
        if cell['first'] is None or local_ts < cell['first']:
            cell['first'] = local_ts
        if cell['last'] is None or local_ts > cell['last']:
            cell['last'] = local_ts
        cell['types'].add(log.check_type)

    all_users   = sorted(users_ordered.keys())
    user_totals = defaultdict(int)
    date_totals = defaultdict(int)
    for d, users_data in raw_data.items():
        for u, cell in users_data.items():
            user_totals[u] += cell['count']
            date_totals[d] += cell['count']

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    filename = f"gps_summary_{year}_{month:02d}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)

    # Header row: วัน, user1, user2, ..., รวม/วัน
    header = ['วัน', 'วันที่'] + all_users + ['รวม/วัน']
    writer.writerow(header)

    DAY_TH = ['จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส', 'อา']
    for d in [date(year, month, day) for day in range(1, last_day + 1)]:
        row = [DAY_TH[d.weekday()], d.strftime('%d/%m/%Y')]
        for u in all_users:
            cell = raw_data[d].get(u)
            if cell:
                val = str(cell['count'])
                if cell['first']:
                    val += f" ({cell['first'].strftime('%H:%M')}"
                    if cell['last'] and cell['last'] != cell['first']:
                        val += f"-{cell['last'].strftime('%H:%M')}"
                    val += ')'
                row.append(val)
            else:
                row.append('')
        row.append(date_totals.get(d, 0))
        writer.writerow(row)

    # Footer: รวม/คน
    footer = ['รวม/คน', ''] + [user_totals.get(u, 0) for u in all_users] + [sum(user_totals.values())]
    writer.writerow(footer)

    return response


@login_required
def gps_technician_stats(request):
    """
    กราฟสถิติช่างเทคนิครายบุคคล — งานที่ได้รับมอบหมาย + GPS check-in/out ย้อนหลัง 12 เดือน
    """
    from .models import TechnicianGPSLog, ServiceQueueItem
    from django.utils import timezone
    from django.db.models import Count
    from django.db.models.functions import ExtractYear, ExtractMonth
    from collections import defaultdict
    from datetime import date
    import json as json_lib

    User = get_user_model()
    today = timezone.localdate()

    THAI_MONTHS_SHORT = ['', 'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.',
                         'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']

    # 12 เดือนย้อนหลัง (รวมเดือนปัจจุบัน)
    months = []
    for i in range(11, -1, -1):
        m = today.month - i
        y = today.year
        if m <= 0:
            m += 12
            y -= 1
        months.append(date(y, m, 1))

    start_date  = months[0]
    month_keys  = [(d.year, d.month) for d in months]
    month_labels = [f"{THAI_MONTHS_SHORT[d.month]} {d.year}" for d in months]

    # หา users ที่มี GPS log หรือ job ในช่วง 12 เดือน
    gps_user_ids = set(
        TechnicianGPSLog.objects.filter(timestamp__date__gte=start_date)
        .values_list('user_id', flat=True).distinct()
    )
    job_user_ids = set(filter(None, (
        ServiceQueueItem.objects.filter(
            scheduled_date__gte=start_date,
            scheduled_date__isnull=False,
        ).values_list('assigned_teams__members', flat=True).distinct()
    )))
    all_user_ids = gps_user_ids | job_user_ids

    if not (user_can_view_all(request.user)):
        all_user_ids = {request.user.pk}

    users = User.objects.filter(pk__in=all_user_ids).order_by('username')

    # GPS logs — grouping ด้วย Python เพื่อรองรับ timezone ที่ถูกต้อง
    gps_logs = TechnicianGPSLog.objects.filter(
        timestamp__date__gte=start_date,
        user__in=users,
    ).only('user_id', 'check_type', 'timestamp')

    # gps_data[user_id][(year, month)][check_type] = count
    gps_data = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for log in gps_logs:
        local_ts = timezone.localtime(log.timestamp)
        key = (local_ts.year, local_ts.month)
        gps_data[log.user_id][key][log.check_type] += 1

    # Jobs per user per month ผ่าน assigned_teams → members
    job_rows = (
        ServiceQueueItem.objects
        .filter(
            scheduled_date__gte=start_date,
            scheduled_date__isnull=False,
            assigned_teams__members__in=users,
        )
        .annotate(yr=ExtractYear('scheduled_date'), mn=ExtractMonth('scheduled_date'))
        .values('assigned_teams__members', 'yr', 'mn')
        .annotate(count=Count('id', distinct=True))
    )
    # job_data[user_id][(year, month)] = count
    job_data = defaultdict(lambda: defaultdict(int))
    for row in job_rows:
        uid = row['assigned_teams__members']
        job_data[uid][(row['yr'], row['mn'])] = row['count']

    COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444',
              '#8b5cf6', '#06b6d4', '#f97316', '#ec4899']

    chart_users = []
    for idx, user in enumerate(users):
        uid   = user.pk
        color = COLORS[idx % len(COLORS)]
        jobs_list = [job_data[uid].get(k, 0) for k in month_keys]
        ci_list   = [gps_data[uid].get(k, {}).get('CHECK_IN', 0) for k in month_keys]
        co_list   = [gps_data[uid].get(k, {}).get('CHECK_OUT', 0) for k in month_keys]
        chart_users.append({
            'name':       user.username,
            'display':    user.get_full_name() or user.username,
            'color':      color,
            'jobs':       jobs_list,
            'check_in':   ci_list,
            'check_out':  co_list,
            'total_jobs': sum(jobs_list),
            'total_ci':   sum(ci_list),
            'total_co':   sum(co_list),
        })

    return render(request, 'pms/technician_stats.html', {
        'month_labels':      json_lib.dumps(month_labels),
        'chart_users_json':  json_lib.dumps(chart_users),
        'chart_users':       chart_users,
        'months':            months,
        'today':             today,
    })


# ======================================================================
# WORK SUMMARY REPORT
# ======================================================================

@login_required
def work_summary_report(request):
    from .models import TechnicianGPSLog, CustomerSatisfaction, ServiceQueueItem, ServiceTeam
    from datetime import timedelta
    from collections import defaultdict
    import json as json_lib

    today = timezone.localdate()
    date_from_str = request.GET.get("date_from", (today - timedelta(days=6)).isoformat())
    date_to_str   = request.GET.get("date_to",   today.isoformat())
    try:
        date_from = date.fromisoformat(date_from_str)
    except Exception:
        date_from = today - timedelta(days=6)
    try:
        date_to = date.fromisoformat(date_to_str)
    except Exception:
        date_to = today

    uid_filter       = request.GET.get("user_id", "")
    task_type_filter = request.GET.get("task_type", "")
    team_id_filter   = request.GET.get("team_id", "")

    gps_qs = (
        TechnicianGPSLog.objects
        .filter(timestamp__date__gte=date_from, timestamp__date__lte=date_to)
        .select_related("user", "queue_item", "queue_item__project", "queue_item__project__customer")
        .prefetch_related("queue_item__assigned_teams")
        .order_by("user_id", "timestamp")
    )
    if not user_can_view_all(request.user):
        gps_qs = gps_qs.filter(user=request.user)
    elif uid_filter:
        gps_qs = gps_qs.filter(user_id=uid_filter)

    sat_qs = CustomerSatisfaction.objects.filter(
        gps_log__timestamp__date__gte=date_from,
        gps_log__timestamp__date__lte=date_to,
    ).select_related("gps_log")
    if not user_can_view_all(request.user):
        sat_qs = sat_qs.filter(gps_log__user=request.user)
    sat_map = {s.gps_log_id: s for s in sat_qs}

    by_user_date = defaultdict(list)
    for log in gps_qs:
        key = (log.user_id, timezone.localtime(log.timestamp).date())
        by_user_date[key].append(log)

    all_sessions = []
    for (_uid, day), logs in sorted(by_user_date.items()):
        pending = []
        for log in logs:
            lt = timezone.localtime(log.timestamp)
            ct = log.check_type
            if ct in ("ON_SITE", "CHECK_IN"):
                pending.append({"log": log, "dt": lt})
            elif ct == "CHECK_OUT" and pending:
                ci      = pending.pop(0)
                ci_log  = ci["log"]
                delta_m = max(0, int((lt - ci["dt"]).total_seconds() / 60))
                qi = log.queue_item or ci_log.queue_item
                task_title = ci_log.location_name or log.location_name or "ไม่ระบุ"
                task_type = ""
                task_type_display = "ไม่ระบุ"
                teams = []
                project_name = "ไม่ระบุ"
                customer_name = "ไม่ระบุ"
                estimated_hours = None
                if qi:
                    task_title        = qi.title or task_title
                    task_type         = qi.task_type or ""
                    task_type_display = qi.get_task_type_display() or "ไม่ระบุ"
                    teams             = list(qi.assigned_teams.values_list("name", flat=True))
                    estimated_hours   = float(qi.estimated_hours) if qi.estimated_hours else None
                    if qi.project:
                        project_name = qi.project.name or "ไม่ระบุ"
                        if qi.project.customer:
                            customer_name = qi.project.customer.name or "ไม่ระบุ"
                actual_hours = round(delta_m / 60, 2)
                efficiency   = round(actual_hours / estimated_hours * 100) if estimated_hours else None
                sat = sat_map.get(log.id)
                all_sessions.append({
                    "date": day, "date_str": day.strftime("%d/%m/%Y"),
                    "technician": log.user.get_full_name() or log.user.username,
                    "username": log.user.username, "user_id": log.user_id,
                    "teams": teams, "teams_str": ", ".join(teams) if teams else "ไม่ระบุทีม",
                    "task_title": task_title, "task_type": task_type,
                    "task_type_display": task_type_display,
                    "project_name": project_name, "customer_name": customer_name,
                    "location": ci_log.location_name or log.location_name or "ไม่ระบุ",
                    "check_in_time": ci["dt"].strftime("%H:%M"),
                    "check_out_time": lt.strftime("%H:%M"),
                    "duration_min": delta_m,
                    "duration_str": (f"{delta_m//60}ชม. {delta_m%60}น." if delta_m >= 60 else f"{delta_m}น."),
                    "actual_hours": actual_hours, "estimated_hours": estimated_hours,
                    "efficiency": efficiency,
                    "satisfaction_rating": sat.rating if sat else "",
                    "satisfaction_display": sat.get_rating_display() if sat else "ไม่มีข้อมูล",
                })

    if task_type_filter:
        all_sessions = [s for s in all_sessions if s["task_type"] == task_type_filter]
    if team_id_filter:
        try:
            tname = ServiceTeam.objects.get(pk=int(team_id_filter)).name
            all_sessions = [s for s in all_sessions if tname in s["teams"]]
        except Exception:
            pass

    all_sessions.sort(key=lambda s: (s["date"], s["technician"]), reverse=True)
    total_minutes = sum(s["duration_min"] for s in all_sessions)

    by_tech = defaultdict(lambda: {"sessions": 0, "minutes": 0, "locs": set(), "sat": []})
    by_type = defaultdict(lambda: {"count": 0, "minutes": 0})
    by_team = defaultdict(lambda: {"count": 0, "minutes": 0})

    for s in all_sessions:
        bt = by_tech[s["technician"]]
        bt["sessions"] += 1
        bt["minutes"]  += s["duration_min"]
        bt["locs"].add(s["location"])
        if s["satisfaction_rating"]:
            bt["sat"].append(s["satisfaction_rating"])
        by_type[s["task_type_display"]]["count"]  += 1
        by_type[s["task_type_display"]]["minutes"] += s["duration_min"]
        for team in s["teams"]:
            by_team[team]["count"]  += 1
            by_team[team]["minutes"] += s["duration_min"]

    tech_stats = sorted([
        {"name": n, "sessions": d["sessions"], "hours": round(d["minutes"]/60,1),
         "locs": len(d["locs"]),
         "sat_pos": sum(1 for r in d["sat"] if r in ("VERY_SATISFIED","SATISFIED")),
         "sat_total": len(d["sat"])}
        for n, d in by_tech.items()
    ], key=lambda x: x["hours"], reverse=True)
    type_stats = [{"type": k, "count": v["count"], "hours": round(v["minutes"]/60,1)} for k,v in by_type.items()]
    team_stats = [{"team": k, "count": v["count"], "hours": round(v["minutes"]/60,1)} for k,v in by_team.items()]

    ai_summary = {
        "period": f"{date_from_str} ถึง {date_to_str}",
        "total_sessions": len(all_sessions),
        "total_hours": round(total_minutes/60,1),
        "technicians": tech_stats, "by_task_type": type_stats, "by_team": team_stats,
        "sessions_sample": [
            {"date": s["date_str"], "tech": s["technician"], "team": s["teams_str"],
             "task": s["task_title"], "type": s["task_type_display"], "location": s["location"],
             "duration": s["duration_str"],
             "estimated": (str(s["estimated_hours"]) + "ชม.") if s["estimated_hours"] else "ไม่ระบุ",
             "efficiency": (str(s["efficiency"]) + "%") if s["efficiency"] else "ไม่ระบุ",
             "satisfaction": s["satisfaction_display"]}
            for s in all_sessions[:50]
        ],
    }

    User = get_user_model()
    users_list = (User.objects.filter(is_active=True).order_by("username")
                  if user_can_view_all(request.user) else [])
    teams_all  = ServiceTeam.objects.filter(is_active=True).order_by("name")
    task_type_choices = [("REPAIR","ซ่อม"),("INSTALLATION","ติดตั้ง"),
                         ("DELIVERY","ส่งสินค้า"),("OTHER","อื่นๆ")]

    return render(request, "pms/work_summary_report.html", {
        "sessions": all_sessions, "total_sessions": len(all_sessions),
        "total_hours": round(total_minutes/60,1),
        "tech_stats": tech_stats, "type_stats": type_stats, "team_stats": team_stats,
        "date_from_str": date_from_str, "date_to_str": date_to_str,
        "selected_user_id": uid_filter, "selected_task_type": task_type_filter,
        "selected_team_id": team_id_filter,
        "users_list": users_list, "teams_all": teams_all,
        "task_type_choices": task_type_choices,
        "can_view_all": user_can_view_all(request.user),
        "ai_summary_json": json_lib.dumps(ai_summary, ensure_ascii=False, default=str),
    })


@login_required
def work_summary_ai_analysis(request):
    from .ai_utils import get_gemini_work_analysis
    import json as json_lib
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        body    = json_lib.loads(request.body)
        summary = body.get("summary", "")
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    analysis = get_gemini_work_analysis(summary)
    return JsonResponse({"status": "success", "analysis": analysis})
