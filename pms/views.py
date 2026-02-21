from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.http import FileResponse
from decimal import Decimal
import datetime
from .models import Project, ProductItem, Customer, Supplier, ProjectOwner, CustomerRequirement, ProjectFile, CustomerRequest
from .forms import ProjectForm, ProductItemForm, CustomerForm, SupplierForm, ProjectOwnerForm, CustomerRequirementForm, SalesServiceJobForm, CustomerRequestForm
from repairs.models import RepairItem


def _create_project_value_item(project, project_value):
    """Auto-create a ProductItem from the project_value field.
    The item name is derived from the project name (truncated to key text).
    """
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


@login_required
def dispatch(request):
    return render(request, 'pms/dispatch.html')

@login_required
def service_create(request):
    if request.method == 'POST':
        form = SalesServiceJobForm(request.POST, job_type=Project.JobType.SERVICE)
        if form.is_valid():
            project = form.save(commit=False)
            project.job_type = Project.JobType.SERVICE
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

@login_required
def repair_create(request):
    if request.method == 'POST':
        form = SalesServiceJobForm(request.POST, job_type=Project.JobType.REPAIR)
        if form.is_valid():
            project = form.save(commit=False)
            project.job_type = Project.JobType.REPAIR
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

# ... queue_management ...

# ... project_list ...

# ... project_detail ...

# ... project_create ...

@login_required
def project_update(request, pk):
    project = get_object_or_404(Project, pk=pk)
    
    # Determine Form Class, Title, and Theme based on Job Type
    theme_color = 'primary'
    form_kwargs = {'instance': project}

    # --- AI QUEUE LOCK LOGIC ---
    # บล็อกการแก้ไขถ้างานอยู่ในคิว (PENDING, SCHEDULED, IN_PROGRESS)
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
    # ---------------------------

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
    else:
        FormClass = ProjectForm
        template = 'pms/project_form.html'
        title = 'แก้ไขโครงการ'


    if request.method == 'POST':
        form = FormClass(request.POST, **form_kwargs)
        if form.is_valid():
            form.save()
            messages.success(request, f'อัปเดต{title.replace("แก้ไข", "")}สำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = FormClass(**form_kwargs)
        
    return render(request, template, {'form': form, 'title': title, 'theme_color': theme_color})

@login_required
def queue_management(request):
    # Sales/Project Queue: Projects in DELIVERY status
    delivery_queue = Project.objects.filter(
        status=Project.Status.DELIVERY, 
        job_type__in=[Project.JobType.PROJECT, Project.JobType.SERVICE]
    ).order_by('deadline', 'created_at')
    
    # Repair Queue: Repair Jobs (Onsite) that are active
    # Active statuses logic: Not Closed, Billing, Accepted, Cancelled
    # Or maybe user wants specific "Queue" like waiting for technician?
    # Let's show SOURCING (Diagnosing), ORDERING (Waiting Parts), DELIVERY (Fixing/Onsite)
    repair_queue = Project.objects.filter(
        job_type=Project.JobType.REPAIR,
        status__in=[
            Project.Status.SOURCING, 
            Project.Status.QUOTED, 
            Project.Status.ORDERING, 
            Project.Status.RECEIVED_QC,
            Project.Status.DELIVERY
        ]
    ).order_by('created_at')
    
    return render(request, 'pms/queue_dashboard.html', {
        'delivery_queue': delivery_queue,
        'repair_queue': repair_queue,
    })

@login_required
def project_list(request):
    projects = Project.objects.all().order_by('-created_at')

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

    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from and date_to:
        projects = projects.filter(created_at__date__range=[date_from, date_to])

    context = {
        'projects': projects,
        'status_choices': Project.Status.choices,
        'project_owners': ProjectOwner.objects.all(),
    }
    return render(request, 'pms/project_list.html', context)

@login_required
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk)
    
    # Theme Color
    theme_color = 'primary'
    if project.job_type == Project.JobType.SERVICE:
        theme_color = 'success'
    elif project.job_type == Project.JobType.REPAIR:
        theme_color = 'warning'

    # Workflow steps based on job type
    raw_steps = []
    
    if project.job_type == Project.JobType.SERVICE:
        # Sales Service Workflow (Simplified)
        raw_steps = [
            (Project.Status.SOURCING, 'จัดหา'),
            (Project.Status.QUOTED, 'เสนอราคา'),
            (Project.Status.ORDERING, 'สั่งซื้อ'),
            (Project.Status.RECEIVED_QC, 'รับของ/QC'),
            (Project.Status.DELIVERY, 'ส่งมอบ'),
            (Project.Status.ACCEPTED, 'ตรวจรับ'),
            (Project.Status.CLOSED, 'ปิดจบ'),
        ]
    elif project.job_type == Project.JobType.REPAIR:
        # Repair Workflow (Custom Labels from User Request)
        raw_steps = [
            (Project.Status.SOURCING, 'รับแจ้งซ่อม'),
            (Project.Status.ORDERING, 'จัดคิวซ่อม'),
            (Project.Status.DELIVERY, 'ซ่อม'),
            (Project.Status.ACCEPTED, 'รอ'),
            (Project.Status.CLOSED, 'ปิดงานซ่อม'),
        ]
    else:
        # Full Project Workflow (Default Labels)
        raw_steps = [
            (Project.Status.DRAFT, 'รวบรวม'),
            (Project.Status.SOURCING, 'จัดหา'),
            (Project.Status.SUPPLIER_CHECK, 'เช็คราคา'),
            (Project.Status.QUOTED, 'เสนอราคา'),
            (Project.Status.CONTRACTED, 'ทำสัญญา'),
            (Project.Status.ORDERING, 'สั่งซื้อ'),
            (Project.Status.RECEIVED_QC, 'รับของ/QC'),
            (Project.Status.INSTALLATION, 'ติดตั้ง'),
            (Project.Status.DELIVERY, 'ส่งมอบ'),

            (Project.Status.ACCEPTED, 'ตรวจรับ'),
            (Project.Status.BILLING, 'วางบิล'),
            (Project.Status.CLOSED, 'ปิดจบ'),
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
        status__in=['PENDING', 'SCHEDULED', 'IN_PROGRESS']
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
    return render(request, 'pms/project_detail.html', context)


@login_required
def project_create(request):
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save()
            # Auto-create value item
            pv = form.cleaned_data.get('project_value')
            _create_project_value_item(project, pv)
            messages.success(request, 'สร้างโครงการสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, 'pms/project_form.html', {'form': form, 'title': 'สร้างโครงการใหม่'})

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
    else:
        FormClass = ProjectForm
        template = 'pms/project_form.html'
        title = 'แก้ไขโครงการ'

    # --- CLOSED LOCK LOGIC ---
    # อนุญาตให้เข้าถึงได้ถ้ามีรหัสปลดล็อก '9com' ผ่านทาง URL
    unlock_code = request.GET.get('unlock')
    if project.status == Project.Status.CLOSED and unlock_code != '9com':
        messages.warning(request, f'⚠️ ไม่สามารถแก้ไขงานที่ "ปิดจบ" แล้วได้')
        return redirect('pms:project_detail', pk=project.pk)
    # -------------------------


    if request.method == 'POST':

        form = FormClass(request.POST, **form_kwargs)
        if form.is_valid():
            form.save()
            messages.success(request, f'อัปเดต{title.replace("แก้ไข", "")}สำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = FormClass(**form_kwargs)
        
    return render(request, template, {'form': form, 'title': title, 'theme_color': theme_color})

@login_required
def item_add(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
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

@login_required
def item_update(request, item_id):
    item = get_object_or_404(ProductItem, pk=item_id)
    project = item.project
    if request.method == 'POST':
        form = ProductItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, 'แก้ไขรายการสำเร็จ')
            return redirect('pms:project_detail', pk=project.pk)
    else:
        form = ProductItemForm(instance=item)
    return render(request, 'pms/item_form.html', {'form': form, 'project': project, 'title': f'แก้ไขรายการ {item.name}'})

@login_required
def item_delete(request, item_id):
    item = get_object_or_404(ProductItem, pk=item_id)
    project_pk = item.project.pk
    item.delete()
    messages.success(request, 'ลบรายการสำเร็จ')
    return redirect('pms:project_detail', pk=project_pk)

# Customer Views
@login_required
def customer_list(request):
    customers = Customer.objects.all().order_by('-created_at')
    return render(request, 'pms/customer_list.html', {'customers': customers})

@login_required
def customer_create(request):
    if request.method == 'POST':
        # Reuse ProjectForm style but for Customer?
        # We need a CustomerForm. Let's create one inline in forms.py later or just use modelform_factory if lazy, 
        # but user likely wants a proper form. I'll need to define it in forms.py.
        # Check forms.py first. It does not have CustomerForm.
        # I will assume I will add CustomerForm in step 2.

        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'เพิ่มลูกค้าสำเร็จ')
            return redirect('pms:customer_list')
    else:

        form = CustomerForm()
    return render(request, 'pms/customer_form.html', {'form': form, 'title': 'เพิ่มลูกค้าใหม่'})

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

    return render(request, 'pms/customer_form.html', {'form': form, 'title': 'แก้ไขข้อมูลลูกค้า'})

# Supplier Views
@login_required
def supplier_list(request):
    suppliers = Supplier.objects.all().order_by('-created_at')
    return render(request, 'pms/supplier_list.html', {'suppliers': suppliers})

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
@login_required
def project_owner_list(request):
    owners = ProjectOwner.objects.all().order_by('name')
    return render(request, 'pms/project_owner_list.html', {'owners': owners})

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

    # Summary Cards
    total_projects = projects_in_period.count()
    active_projects = projects_in_period.exclude(status__in=[Project.Status.CLOSED, Project.Status.CANCELLED]).count()
    
    # ยอดรวมของงาน (Total Job Value) - based on creation date
    total_job_value = projects_in_period.aggregate(
        total=Sum(F('items__quantity') * F('items__unit_price'))
    )['total'] or 0
    
    # ยอดขาย (Actual Sales) - based on closed date
    # 1. Projects closed in period
    closed_projects_value = Project.objects.filter(
        status=Project.Status.CLOSED,
        closed_at__range=[start_of_period, end_of_period]
    ).aggregate(
        total=Sum(F('items__quantity') * F('items__unit_price'))
    )['total'] or 0
    
    # 2. RepairItems closed in period (Repairs App)
    from repairs.models import RepairItem
    closed_repairs_value = RepairItem.objects.filter(
        status__in=['FINISHED', 'COMPLETED'],
        closed_at__range=[start_of_period, end_of_period]
    ).aggregate(
        total=Sum('price')
    )['total'] or 0
    
    actual_sales = closed_projects_value + closed_repairs_value

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

    # Query for 'TOTAL' (Created): Repairs App
    from repairs.models import RepairItem
    total_repairs_qs = RepairItem.objects.filter(created_at__range=[start_of_year, end_of_year])\
        .annotate(month=TruncMonth('created_at'))\
        .values('month')\
        .annotate(
            count=Count('id'),
            value=Sum('price')
        )
    for entry in total_repairs_qs:
        m_index = entry['month'].month - 1
        # count is excluded from charts per previous setup, but value is included
        completion_total_value[m_index] += float(entry['value'] or 0)

    # Query for 'CLOSED' (Finished): PMS Projects (Using closed_at)
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

    # Query for 'CLOSED' (Finished): Repairs App (Using closed_at)
    closed_repairs_qs = RepairItem.objects.filter(
        status__in=['FINISHED', 'COMPLETED'],
        closed_at__range=[start_of_year, end_of_year]
    ).annotate(month=TruncMonth('closed_at'))\
     .values('month')\
     .annotate(
         count=Count('id'),
         value=Sum('price')
     )
    for entry in closed_repairs_qs:
        m_index = entry['month'].month - 1
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
                When(projects__created_at__range=[start_of_year, end_of_year], 
                     then=F('projects__items__quantity') * F('projects__items__unit_price')),
                default=0,
                output_field=models.DecimalField(max_digits=15, decimal_places=2)
            )
        ),
        job_count=Count(
            'projects',
            filter=Q(projects__created_at__range=[start_of_year, end_of_year]),
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
                output_field=models.DecimalField(max_digits=15, decimal_places=2)
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
@login_required
def requirement_list(request):
    requirements = CustomerRequirement.objects.all().order_by('-created_at')
    return render(request, 'pms/requirement_list.html', {'requirements': requirements})

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
        status='PENDING'
    ).select_related('assigned_team', 'project').order_by('deadline', 'created_at')

    # Block 2+: Scheduled/In-progress tasks grouped by date
    scheduled_tasks = ServiceQueueItem.objects.filter(
        status__in=['SCHEDULED', 'IN_PROGRESS']
    ).select_related('assigned_team', 'project').order_by('scheduled_date', 'scheduled_time')

    # Group by date
    date_groups = OrderedDict()
    for task in scheduled_tasks:
        d = task.scheduled_date or today
        if d not in date_groups:
            date_groups[d] = []
        date_groups[d].append(task)

    # Incomplete (carry-over)
    incomplete_tasks = ServiceQueueItem.objects.filter(
        status='INCOMPLETE'
    ).select_related('assigned_team', 'project').order_by('created_at')

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


@login_required
def update_pending_task(request, task_id):
    """Admin updates team and date for a pending task."""
    from .models import ServiceQueueItem, ServiceTeam

    task = get_object_or_404(ServiceQueueItem, pk=task_id)
    if request.method == 'POST':
        team_id = request.POST.get('team')
        date_str = request.POST.get('scheduled_date')

        if team_id:
            try:
                task.assigned_team = ServiceTeam.objects.get(pk=team_id)
            except ServiceTeam.DoesNotExist:
                pass

        if date_str:
            try:
                task.scheduled_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        task.save()
        messages.success(request, f"✅ อัปเดต: {task.title}")

    return redirect('pms:service_queue_dashboard')


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


@login_required
def update_task_status(request, task_id):
    """Update task status and completion notes."""
    from .models import ServiceQueueItem

    task = get_object_or_404(ServiceQueueItem, pk=task_id)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        note = request.POST.get('note', '')

        if new_status:
            task.status = new_status
            if new_status == 'COMPLETED':
                task.completed_at = timezone.now()
                # Move linked project to next status
                if task.project:
                    proj = task.project
                    # Repair: จัดคิวซ่อม(ORDERING) -> ซ่อม(DELIVERY)
                    if proj.status == 'ORDERING':
                        proj.status = 'DELIVERY'
                    # Project: ติดตั้ง(INSTALLATION) -> ส่งมอบ(DELIVERY)
                    elif proj.status == 'INSTALLATION':
                        proj.status = 'DELIVERY'
                    # Sale/Project: ส่งมอบ(DELIVERY) -> ตรวจรับ(ACCEPTED)
                    elif proj.status == 'DELIVERY':
                        proj.status = 'ACCEPTED'
                    proj.save()
            elif new_status == 'INCOMPLETE':
                task.scheduled_date = None
                task.scheduled_time = None
                task.assigned_team = None

        if note:

            timestamp = timezone.now().strftime('%d/%m %H:%M')
            prev = task.completion_note
            task.completion_note = f"{prev}\n[{timestamp}] {note}".strip()

        task.save()
        messages.success(request, f"✅ อัปเดต: {task.title} → {task.get_status_display()}")

    return redirect('pms:service_queue_dashboard')


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


# ===== Team Management Views =====

@login_required
def team_list(request):
    """List all service teams."""
    from .models import ServiceTeam
    teams = ServiceTeam.objects.all().order_by('name')
    return render(request, 'pms/team_list.html', {'teams': teams})


@login_required
def team_create(request):
    """Create a new service team."""
    from .models import ServiceTeam
    from django.contrib.auth.models import User

    if request.method == 'POST':
        name = request.POST.get('name', '')
        skills = request.POST.get('skills', '')
        max_tasks = request.POST.get('max_tasks_per_day', 5)
        member_ids = request.POST.getlist('members')

        team = ServiceTeam.objects.create(
            name=name,
            skills=skills,
            max_tasks_per_day=int(max_tasks),
        )
        if member_ids:
            team.members.set(member_ids)
        messages.success(request, f"✅ สร้างทีม '{name}' เรียบร้อย")
        return redirect('pms:team_list')

    users = User.objects.filter(is_active=True).order_by('username')
    return render(request, 'pms/team_form.html', {'users': users, 'title': 'สร้างทีมบริการ'})


@login_required
def team_update(request, pk):
    """Update a service team."""
    from .models import ServiceTeam
    from django.contrib.auth.models import User

    team = get_object_or_404(ServiceTeam, pk=pk)

    if request.method == 'POST':
        team.name = request.POST.get('name', team.name)
        team.skills = request.POST.get('skills', team.skills)
        team.max_tasks_per_day = int(request.POST.get('max_tasks_per_day', team.max_tasks_per_day))
        team.is_active = 'is_active' in request.POST
        team.save()

        member_ids = request.POST.getlist('members')
        team.members.set(member_ids)

        messages.success(request, f"✅ อัปเดตทีม '{team.name}' เรียบร้อย")
        return redirect('pms:team_list')

    users = User.objects.filter(is_active=True).order_by('username')
    return render(request, 'pms/team_form.html', {'team': team, 'users': users, 'title': f'แก้ไขทีม: {team.name}'})


@login_required
def team_delete(request, pk):
    """Delete a service team."""
    from .models import ServiceTeam
    team = get_object_or_404(ServiceTeam, pk=pk)
    if request.method == 'POST':
        name = team.name
        team.delete()
        messages.success(request, f"🗑️ ลบทีม '{name}' เรียบร้อย")
        return redirect('pms:team_list')
    return render(request, 'pms/team_confirm_delete.html', {'team': team})


# ===== File Management Views =====

@login_required
def project_file_upload(request, pk):
    """Upload files to a project."""
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


@login_required
def project_file_delete(request, file_id):
    """Delete a file from project or requirement."""
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


@login_required
def requirement_file_delete(request, file_id):
    """Delete a file from requirement (used in requirement form)."""
    pf = get_object_or_404(ProjectFile, pk=file_id)
    req_pk = pf.requirement.pk if pf.requirement else None
    pf.file.delete(save=False)
    pf.delete()
    messages.success(request, 'ลบไฟล์สำเร็จ')
    if req_pk:
        return redirect('pms:requirement_update', pk=req_pk)
    return redirect('pms:requirement_list')


@login_required
def project_delete(request, pk):
    """Delete a project if it's CLOSED and password is correct."""
    from django.conf import settings
    project = get_object_or_404(Project, pk=pk)
    
    if request.method == 'POST':
        password = request.POST.get('password')
        if password == settings.DELETE_PASSWORD:
            if project.status == Project.Status.CLOSED:
                name = project.name
                project.delete()
                messages.success(request, f"🗑️ ลบโครงการ '{name}' เรียบร้อย")
                return redirect('pms:project_list')
            else:
                messages.error(request, "ไม่สามารถลบโครงการที่ยังไม่ปิดงานได้")
                return redirect('pms:project_detail', pk=pk)
        else:
            messages.error(request, "รหัสผ่านไม่ถูกต้อง")
            return redirect('pms:project_detail', pk=pk)
    
    return redirect('pms:project_detail', pk=pk)

# ===== Customer Request Views =====

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

@login_required
def request_create(request):
    if request.method == 'POST':
        form = CustomerRequestForm(request.POST)
        if form.is_valid():
            req = form.save()
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

@login_required
def request_detail(request, pk):
    req = get_object_or_404(CustomerRequest, pk=pk)
    files = req.files.all()
    
    if request.method == 'POST':
        # Quick status update from detail view
        new_status = request.POST.get('status')
        if new_status:
            req.status = new_status
            req.save()
            messages.success(request, f'อัปเดตสถานะเป็น {req.get_status_display()} แล้ว')
            return redirect('pms:request_detail', pk=pk)
            
    return render(request, 'pms/request_detail.html', {
        'req': req,
        'files': files,
        'status_choices': CustomerRequest.Status.choices
    })

@login_required
def request_update(request, pk):
    req = get_object_or_404(CustomerRequest, pk=pk)
    if request.method == 'POST':
        form = CustomerRequestForm(request.POST, instance=req)
        if form.is_valid():
            form.save()
            messages.success(request, 'บันทึกการแก้ไขเรียบร้อย')
            return redirect('pms:request_detail', pk=pk)
    else:
        form = CustomerRequestForm(instance=req)
        
    return render(request, 'pms/request_form.html', {'form': form, 'title': 'แก้ไขคำขอ'})

@login_required
def request_delete(request, pk):
    req = get_object_or_404(CustomerRequest, pk=pk)
    
    if request.method == 'POST':
        # Check if status allows deletion
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

@login_required
def request_file_delete(request, file_id):
    pf = get_object_or_404(ProjectFile, pk=file_id)
    req_pk = pf.customer_request.pk if pf.customer_request else None
    
    # Security check: ensure it's a request file
    if not req_pk:
        return redirect('pms:dashboard')
        
    pf.file.delete(save=False)
    pf.delete()
    messages.success(request, 'ลบไฟล์สำเร็จ')
    return redirect('pms:request_detail', pk=req_pk)

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

    # Calculate actual sales (closed jobs) for AI context
    closed_projects_value = Project.objects.filter(status=Project.Status.CLOSED, closed_at__range=[start_of_period, end_of_period]).aggregate(total=Sum(F('items__quantity') * F('items__unit_price')))['total'] or 0
    from repairs.models import RepairItem
    closed_repairs_value = RepairItem.objects.filter(status__in=['FINISHED', 'COMPLETED'], closed_at__range=[start_of_period, end_of_period]).aggregate(total=Sum('price'))['total'] or 0
    actual_sales = closed_projects_value + closed_repairs_value

    data_summary = f"""
    - ช่วงเวลา: {calendar.month_name[month_filter]} {year_filter}
    - ยอดรวมของงาน (สะสมในช่วงนี้): ฿{total_revenue:,.2f}
    - ยอดขายที่ปิดจบจริง (Actual Sales): ฿{actual_sales:,.2f}
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
