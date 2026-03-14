from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.db import transaction
from django.contrib.auth.decorators import login_required
from .models import RepairJob, RepairItem, Customer, Device, Technician, DeviceType, Brand, RepairStatusHistory, OutsourceLog, RepairType, RepairStatus
from django.contrib.auth.models import User
from .forms import CustomerForm, DeviceForm, RepairJobForm, RepairItemForm, TechnicianForm, DeviceTypeForm, BrandForm, OutsourceLogForm, RepairTypeForm

import csv
import datetime
import json
from collections import defaultdict
from decimal import Decimal
from django.db.models import Q, Sum, Count
from django.utils import timezone

@login_required
def dashboard(request):
    # --- Date Filter Logic ---
    today = timezone.now().date()
    period = request.GET.get('period', 'this_month')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    if period == 'this_month':
        start_date = today.replace(day=1)
        end_date = today
    elif period == 'this_year':
        start_date = today.replace(month=1, day=1)
        end_date = today
    elif period == 'custom' and start_date_str and end_date_str:
        try:
            start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = today.replace(day=1)
            end_date = today
    elif period == 'all':
        start_date = datetime.date(2020, 1, 1) # Fallback start
        end_date = today
    else:
        # Default to this month
        start_date = today.replace(day=1)
        end_date = today
        period = 'this_month'

    # Ensure range for queries
    range_filter = [
        timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min)),
        timezone.make_aware(datetime.datetime.combine(end_date, datetime.time.max))
    ]

    # --- Data Queries ---
    
    # Base filter for items created/received in period
    period_items = RepairItem.objects.filter(created_at__range=range_filter)

    # 1. Overall Status Statistics (of items created in period)
    status_summary = period_items.values('status').annotate(count=Count('id'))
    ordered_statuses = [
        ('RECEIVED', '#ef4444'),
        ('FIXING', '#ff9100'),
        ('WAITING_APPROVAL', '#a855f7'),
        ('WAITING', '#eab308'),
        ('OUTSOURCE', '#6366f1'),
        ('RECEIVED_FROM_VENDOR', '#38bdf8'),
        ('FINISHED', '#10b981'),
        ('CANCELLED', '#6b7280'),
        ('COMPLETED', '#1f2937'),
    ]
    
    counts_map = {item['status']: item['count'] for item in status_summary}
    status_labels = []
    status_values = []
    status_colors = []
    status_display_map = dict(RepairItem.STATUS_CHOICES)
    for code, color in ordered_statuses:
        status_labels.append(status_display_map.get(code, code))
        status_values.append(counts_map.get(code, 0))
        status_colors.append(color)

    # 2. Technician Performance (Active is current, Completed is within period)
    tech_stats = []
    technicians = Technician.objects.all()
    for tech in technicians:
        active_count = tech.repairitem_set.exclude(status__in=['FINISHED', 'CANCELLED', 'COMPLETED']).count()
        completed_period_items = tech.repairitem_set.filter(
            status__in=['FINISHED', 'COMPLETED'],
            updated_at__range=range_filter
        )
        completed_period_count = completed_period_items.count()
        
        # Calculate income for items this technician was part of (within period)
        tech_income_period = completed_period_items.filter(status='COMPLETED').aggregate(total=Sum('final_cost'))['total'] or 0
        
        # Calculate lifetime income for this technician
        tech_income_lifetime = tech.repairitem_set.filter(status='COMPLETED').aggregate(total=Sum('final_cost'))['total'] or 0
        
        # Income breakdown by type
        type_incomes = []
        for rt in RepairType.objects.all():
            val = completed_period_items.filter(status='COMPLETED', job__repair_type=rt).aggregate(total=Sum('final_cost'))['total'] or 0
            if val > 0:
                type_incomes.append({
                    'name': rt.name, 
                    'amount': val, 
                    'color': rt.color,
                    'icon': rt.icon
                })
        type_incomes.sort(key=lambda x: x['amount'], reverse=True)

        tech_stats.append({
            'name': tech.name,
            'active': active_count,
            'completed': completed_period_count,
            'income': tech_income_period,
            'lifetime_income': tech_income_lifetime,
            'type_incomes': type_incomes,
            'total': active_count + completed_period_count
        })
    # Sort by income in period primarily, then active jobs
    tech_stats.sort(key=lambda x: (x['income'], x['active']), reverse=True)

    # 3. Income Summary (within period)
    income_items = RepairItem.objects.filter(
        status='COMPLETED', 
        updated_at__range=range_filter
    )
    period_income = income_items.aggregate(total=Sum('final_cost'))['total'] or 0
    total_lifetime_income = RepairItem.objects.filter(status='COMPLETED').aggregate(total=Sum('final_cost'))['total'] or 0
    
    # 4. Top Customers (within period)
    top_customers = Customer.objects.annotate(
        total_spent_period=Sum('jobs__items__final_cost', filter=Q(jobs__items__status='COMPLETED', jobs__items__updated_at__range=range_filter)),
        job_count_period=Count('jobs__items', filter=Q(jobs__items__status='COMPLETED', jobs__items__updated_at__range=range_filter), distinct=True)
    ).filter(total_spent_period__gt=0).order_by('-total_spent_period')[:5]

    # 5. Trend Graph (Last 30 days or based on range)
    # If range is small (<= 31 days), show daily. If larger, maybe monthly?
    days_diff = (end_date - start_date).days
    daily_labels = []
    daily_values = []
    
    if days_diff <= 31:
        # Show daily for the range
        current = start_date
        while current <= end_date:
            count = RepairItem.objects.filter(created_at__date=current).count()
            daily_labels.append(current.strftime('%d/%m'))
            daily_values.append(count)
            current += datetime.timedelta(days=1)
    else:
        # Show monthly summary if range is large
        # For simplicity, if > 31 days, just show last 7 days trend or some fixed sample
        # Let's just do last 10 points or something.
        # Better: just stick to daily for the selected range if it's reasonable.
        # Let's limit to 30 points.
        step = max(1, days_diff // 15)
        current = start_date
        while current <= end_date:
            count = RepairItem.objects.filter(created_at__date=current).count()
            daily_labels.append(current.strftime('%d/%m'))
            daily_values.append(count)
            current += datetime.timedelta(days=step)

    # 6. Repair Type Stats (within period)
    repair_types = RepairType.objects.all()
    type_stats = []
    for rt in repair_types:
        active = RepairItem.objects.filter(
            job__repair_type=rt
        ).exclude(status__in=['FINISHED', 'CANCELLED', 'COMPLETED']).count()
        
        completed_period = RepairItem.objects.filter(
            job__repair_type=rt,
            status__in=['FINISHED', 'COMPLETED'],
            updated_at__range=range_filter
        )
        
        income = completed_period.filter(status='COMPLETED').aggregate(total=Sum('final_cost'))['total'] or 0
        
        if active > 0 or completed_period.count() > 0:
            type_stats.append({
                'type': rt,
                'active': active,
                'completed': completed_period.count(),
                'income': income,
            })
    type_stats.sort(key=lambda x: x['income'], reverse=True)

    context = {
        'status_labels': json.dumps(status_labels),
        'status_values': json.dumps(status_values),
        'status_colors': json.dumps(status_colors),
        'tech_stats': tech_stats,
        'type_stats': type_stats,
        'period_income': period_income,
        'total_income': total_lifetime_income,
        'top_customers': top_customers,
        'daily_labels': json.dumps(daily_labels),
        'daily_values': json.dumps(daily_values),
        'active_repairs': RepairItem.objects.exclude(status__in=['FINISHED', 'CANCELLED', 'COMPLETED']).count(),
        'awaiting_approval': RepairItem.objects.filter(status='WAITING_APPROVAL', created_at__range=range_filter).count(),
        'total_jobs_in_period': period_items.count(),
        # For Form persistence
        'start_date': start_date,
        'end_date': end_date,
        'period': period,
    }
    return render(request, 'repairs/dashboard.html', context)

@login_required
def repair_list(request):
    # Exclude finished/cancelled items from main list
    items = RepairItem.objects.select_related('job', 'device', 'job__customer').prefetch_related('technicians').exclude(status__in=['FINISHED', 'COMPLETED', 'CANCELLED']).all()

    # Search
    q = request.GET.get('q')
    if q:
        items = items.filter(
            Q(job__job_code__icontains=q) |
            Q(job__customer__name__icontains=q) |
            Q(device__model__icontains=q) |
            Q(device__serial_number__icontains=q) |
            Q(issue_description__icontains=q) |
            Q(job__fix_id__icontains=q) |
            Q(created_by__username__icontains=q)
        ).distinct()

    # Filter by Status
    status = request.GET.get('status')
    if status:
        items = items.filter(status=status)

    # Filter by Creator (Receiver)
    created_by_param = request.GET.get('created_by')
    selected_created_by = ""
    
    if created_by_param:
        # Specific user selected
        selected_created_by = created_by_param
        items = items.filter(created_by__id=selected_created_by)
    else:
        # Default or "Everyone" selected (created_by="" or None)
        selected_created_by = ""

    # Sort
    sort = request.GET.get('sort', 'date_desc')
    if sort == 'date_desc':
        items = items.order_by('-created_at')
    elif sort == 'date_asc':
        items = items.order_by('created_at')
    elif sort == 'customer':
        items = items.order_by('job__customer__name')
    
    from django.contrib.auth.models import User
    users = User.objects.all().order_by('username')

    return render(request, 'repairs/repair_list.html', {
        'items': items, 
        'users': users, 
        'selected_created_by': selected_created_by,
        'status_choices': RepairItem.STATUS_CHOICES
    })

@login_required
def repair_completed_list(request):
    # Show items that are finished or cancelled (but not returned yet)
    items = RepairItem.objects.select_related('job', 'device', 'job__customer').prefetch_related('technicians').filter(status__in=['FINISHED', 'CANCELLED']).all()

    # Search (reuse same logic mostly)
    q = request.GET.get('q')
    if q:
        items = items.filter(
            Q(job__job_code__icontains=q) |
            Q(job__customer__name__icontains=q) |
            Q(device__model__icontains=q) |
            Q(device__serial_number__icontains=q) |
            Q(issue_description__icontains=q) |
            Q(job__fix_id__icontains=q) |
            Q(created_by__username__icontains=q)
        ).distinct()

    # Filter by Creator
    created_by_id = request.GET.get('created_by')
    if created_by_id:
        items = items.filter(created_by__id=created_by_id)

    # Filter by Status (specific within finished/cancelled)
    status_filter = request.GET.get('status')
    if status_filter:
        items = items.filter(status=status_filter)

    # Sort
    sort = request.GET.get('sort', 'date_desc')
    if sort == 'date_desc':
        items = items.order_by('-updated_at')
    elif sort == 'date_asc':
        items = items.order_by('created_at')
    elif sort == 'customer':
        items = items.order_by('job__customer__name')
    
    from django.contrib.auth.models import User
    users = User.objects.all().order_by('username')
    
    from django.conf import settings
    return render(request, 'repairs/repair_history.html', {
        'items': items, 
        'users': users,
        'delete_password': settings.DELETE_PASSWORD,
        'list_type': 'finished',
        'page_title': 'เสร็จแล้ว/ยกเลิก',
        'page_subtitle': 'งานที่ซ่อมเสร็จหรือยกเลิกแล้ว แต่ยังไม่ได้ส่งคืน',
        'status_choices': RepairItem.STATUS_CHOICES
    })

@login_required
def repair_returned_list(request):
    # Show items that are completed (returned)
    items = RepairItem.objects.select_related('job', 'device', 'job__customer').prefetch_related('technicians').filter(status='COMPLETED').all()

    # Search
    q = request.GET.get('q')
    if q:
        items = items.filter(
            Q(job__job_code__icontains=q) |
            Q(job__customer__name__icontains=q) |
            Q(device__model__icontains=q) |
            Q(device__serial_number__icontains=q) |
            Q(issue_description__icontains=q) |
            Q(job__fix_id__icontains=q) |
            Q(created_by__username__icontains=q)
        ).distinct()

    # Filter by Creator
    created_by_id = request.GET.get('created_by')
    if created_by_id:
        items = items.filter(created_by__id=created_by_id)

    # Sort
    sort = request.GET.get('sort', 'date_desc')
    if sort == 'date_desc':
        items = items.order_by('-updated_at')
    elif sort == 'date_asc':
        items = items.order_by('created_at')
    elif sort == 'customer':
        items = items.order_by('job__customer__name')
    
    from django.contrib.auth.models import User
    users = User.objects.all().order_by('username')
    
    from django.conf import settings
    return render(request, 'repairs/repair_history.html', {
        'items': items, 
        'users': users,
        'delete_password': settings.DELETE_PASSWORD,
        'list_type': 'returned',
        'page_title': 'ส่งคืนแล้ว',
        'page_subtitle': 'รายการที่ส่งคืนเครื่องให้ลูกค้าเรียบร้อยแล้ว',
        'status_choices': RepairItem.STATUS_CHOICES
    })

@login_required
def repair_create(request):
    # Determine customer instance if ID provided (GET or POST)
    customer_id = request.POST.get('customer_id') or request.GET.get('customer_id')
    customer_instance = None
    if customer_id and customer_id.isdigit():
        customer_instance = get_object_or_404(Customer, pk=customer_id)

    if request.method == 'POST':
        # Bind forms
        customer_form = CustomerForm(request.POST, instance=customer_instance, prefix='customer')
        job_form = RepairJobForm(request.POST, prefix='job')
        device_form = DeviceForm(request.POST, prefix='device')
        item_form = RepairItemForm(request.POST, prefix='item')

        if customer_form.is_valid() and job_form.is_valid() and device_form.is_valid() and item_form.is_valid():
            with transaction.atomic():
                # Save Customer (Update or Create)
                customer = customer_form.save()
                
                # Save Device linked to Customer
                device = device_form.save(commit=False)
                device.customer = customer
                device.save()
                
                # Save Job linked to Customer
                job = job_form.save(commit=False)
                job.customer = customer
                job.created_by = request.user
                job.save()
                
                # Save Item linked to Job and Device
                item = item_form.save(commit=False)
                item.job = job
                item.device = device
                item.created_by = request.user
                item.save()
                item_form.save_m2m() # Save technicians
                
                # Record Initial Status History
                RepairStatusHistory.objects.create(
                    repair_item=item,
                    status=item.status,
                    changed_by=request.user,
                    note="เริ่มต้นรับงาน"
                )
                
                return redirect('repairs:repair_detail', pk=job.pk)
        else:
            print("DEBUG: Validation Failed")
            print(f"Customer Errors: {customer_form.errors}")
            print(f"Job Errors: {job_form.errors}")
            print(f"Device Errors: {device_form.errors}")
            print(f"Item Errors: {item_form.errors}")
    else:
        # Initial forms
        customer_form = CustomerForm(instance=customer_instance, prefix='customer')
        job_form = RepairJobForm(prefix='job')
        device_form = DeviceForm(prefix='device')
        item_form = RepairItemForm(prefix='item')

    # Get all customers for dropdown
    all_customers = Customer.objects.all().order_by('name')

    context = {
        'customer_form': customer_form,
        'job_form': job_form,
        'device_form': device_form,
        'item_form': item_form,
        'all_customers': all_customers,
        'selected_customer_id': customer_id if customer_instance else '',
    }
    return render(request, 'repairs/repair_form.html', context)

@login_required
def repair_detail(request, pk):
    job = get_object_or_404(RepairJob, pk=pk)
    all_technicians = Technician.objects.all().order_by('name')
    all_repair_types = RepairType.objects.all().order_by('name')
    return render(request, 'repairs/repair_detail.html', {
        'job': job, 
        'all_technicians': all_technicians,
        'all_repair_types': all_repair_types
    })

@login_required
def repair_update_status(request, item_id):
    item = get_object_or_404(RepairItem, pk=item_id)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        note = request.POST.get('status_note')
        
        # Allow updating repair type for the entire job
        repair_type_id = request.POST.get('repair_type')
        if repair_type_id:
            try:
                item.job.repair_type_id = int(repair_type_id)
                item.job.save()
            except (ValueError, RepairType.DoesNotExist):
                pass
        elif 'repair_type' in request.POST: # If field exists but empty, set to None
            item.job.repair_type = None
            item.job.save()

        if new_status:
            item.status = new_status
            if note is not None:
                item.status_note = note
            
            # Handle additional updates
            issue_desc = request.POST.get('issue_description')
            accessories = request.POST.get('accessories')
            
            if issue_desc:
                item.issue_description = issue_desc
            if accessories is not None: # Can be empty string
                item.accessories = accessories

            # Handle Price and Final Cost
            price = request.POST.get('price')
            final_cost = request.POST.get('final_cost')
            
            if price:
                try:
                    item.price = float(price)
                except ValueError:
                    pass
            
            # Use 'final_cost' from POST. If empty string, set to None? Or 0?
            # User said "Free of charge due to warranty" -> likely explicitly 0.
            # If empty, maybe keep previous? Or set to None?
            # Let's save it if present.
            if final_cost is not None:
                if final_cost.strip() == '':
                     item.final_cost = None
                else:
                    try:
                        item.final_cost = float(final_cost)
                    except ValueError:
                        pass
            
            # Handle Technicians - Allow editing only at RECEIVED or when moving to FIXING
            # However, the user specifically asked for 'RECEIVED' status assignment.
            if item.status == 'RECEIVED' or new_status == 'FIXING':
                tech_ids = request.POST.getlist('technicians')
                if tech_ids:
                    item.technicians.set(tech_ids)

            item.save()

            # Record Status History
            RepairStatusHistory.objects.create(
                repair_item=item,
                status=item.status,
                changed_by=request.user,
                note=item.status_note
            )
    # Redirect back to the repair list
    return redirect('repairs:repair_list')

@login_required
def get_repair_item_note(request, item_id):
    item = get_object_or_404(RepairItem, pk=item_id)
    return JsonResponse({'note': item.status_note})

@login_required
def get_repair_job_notes(request, job_id):
    job = get_object_or_404(RepairJob, pk=job_id)
    items = job.items.all()
    data = []
    for item in items:
        data.append({
            'device': f"{item.device.brand} {item.device.model}",
            'status': item.get_status_display(),
            'note': item.status_note,
            'status_code': item.status 
        })
    return JsonResponse({'items': data})

@login_required
def repair_outsource_assign(request, item_id):
    item = get_object_or_404(RepairItem, pk=item_id)
    if request.method == 'POST':
        form = OutsourceLogForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                outsource_log = form.save(commit=False)
                outsource_log.repair_item = item
                outsource_log.save()
                
                # Update status
                item.status = 'OUTSOURCE'
                item.status_note = f"ส่งซ่อมศูนย์/ภายนอก: {outsource_log.vendor_name}"
                item.save()
                
                # Record History
                RepairStatusHistory.objects.create(
                    repair_item=item,
                    status='OUTSOURCE',
                    changed_by=request.user,
                    note=f"ส่งซ่อมศูนย์: {outsource_log.vendor_name} (Tracking: {outsource_log.tracking_no})"
                )
            return redirect('repairs:repair_detail', pk=item.job.pk)
    else:
        form = OutsourceLogForm()
    
    return render(request, 'repairs/outsource_assign_form.html', {'form': form, 'item': item})

@login_required
def repair_outsource_receive(request, item_id):
    item = get_object_or_404(RepairItem, pk=item_id)
    if request.method == 'POST':
        with transaction.atomic():
            # Update status to RECEIVED_FROM_VENDOR
            item.status = 'RECEIVED_FROM_VENDOR'
            item.status_note = "ได้รับเครื่องกลับจากศูนย์/ภายนอกแล้ว รอตรวจรับ"
            item.save()
            
            # Record History
            RepairStatusHistory.objects.create(
                repair_item=item,
                status='RECEIVED_FROM_VENDOR',
                changed_by=request.user,
                note="ได้รับเครื่องกลับจากศูนย์แล้ว"
            )
        return redirect('repairs:repair_detail', pk=item.job.pk)
    
    return render(request, 'repairs/outsource_receive_confirm.html', {'item': item})

# --- New Views ---

@login_required
def customer_list(request):
    customers = Customer.objects.all().order_by('-id')
    return render(request, 'repairs/customer_list.html', {'customers': customers})

@login_required
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('repairs:customer_list')
    else:
        form = CustomerForm()
    return render(request, 'repairs/customer_form.html', {'form': form})

@login_required
def customer_update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            return redirect('repairs:customer_list')
    else:
        form = CustomerForm(instance=customer)
    return render(request, 'repairs/customer_form.html', {'form': form})

@login_required
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    
    # Check if customer has any related data
    has_jobs = customer.jobs.exists()
    has_devices = customer.devices.exists()
    
    if has_jobs or has_devices:
        problems = []
        if has_jobs: problems.append(f"งานซ่อม ({customer.jobs.count()} รายการ)")
        if has_devices: problems.append(f"อุปกรณ์ ({customer.devices.count()} รายการ)")
        
        related_str = " และ ".join(problems)
        from django.contrib import messages
        messages.error(request, f"❌ ไม่สามารถลบลูกค้า '{customer.name}' ได้ เนื่องจากมีการใช้งานอยู่ในข้อมูล: {related_str}")
        return redirect('repairs:customer_list')

    if request.method == 'POST':
        customer_name = customer.name
        customer.delete()
        from django.contrib import messages
        messages.success(request, f"ลบข้อมูลลูกค้า '{customer_name}' สำเร็จ")
        return redirect('repairs:customer_list')
    
    return render(request, 'repairs/formatted_confirm_delete.html', {
        'object': customer, 
        'type': 'Customer', 
        'cancel_url': 'repairs:customer_list'
    })

@login_required
def device_list(request):
    devices = Device.objects.all().order_by('-id')
    return render(request, 'repairs/device_list.html', {'devices': devices})



@login_required
def technician_list(request):
    techs = Technician.objects.all()
    return render(request, 'repairs/technician_list.html', {'techs': techs})

@login_required
def technician_create(request):
    if request.method == 'POST':
        form = TechnicianForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('repairs:technician_list')
    else:
        form = TechnicianForm()
    return render(request, 'repairs/technician_form.html', {'form': form})

@login_required
def technician_update(request, pk):
    tech = get_object_or_404(Technician, pk=pk)
    if request.method == 'POST':
        form = TechnicianForm(request.POST, instance=tech)
        if form.is_valid():
            form.save()
            return redirect('repairs:technician_list')
    else:
        form = TechnicianForm(instance=tech)
    return render(request, 'repairs/technician_form.html', {'form': form})

@login_required
def technician_delete(request, pk):
    tech = get_object_or_404(Technician, pk=pk)
    if request.method == 'POST':
        tech.delete()
        return redirect('repairs:technician_list')
    return render(request, 'repairs/formatted_confirm_delete.html', {'object': tech, 'type': 'Technician', 'cancel_url': 'repairs:technician_list'})

@login_required
def device_type_list(request):
    device_types = DeviceType.objects.all()
    return render(request, 'repairs/device_type_list.html', {'device_types': device_types})

@login_required
def device_type_create(request):
    if request.method == 'POST':
        form = DeviceTypeForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('repairs:device_type_list')
    else:
        form = DeviceTypeForm()
    return render(request, 'repairs/device_type_form.html', {'form': form})

@login_required
def device_type_update(request, pk):
    dt = get_object_or_404(DeviceType, pk=pk)
    if request.method == 'POST':
        form = DeviceTypeForm(request.POST, instance=dt)
        if form.is_valid():
            form.save()
            return redirect('repairs:device_type_list')
    else:
        form = DeviceTypeForm(instance=dt)
    return render(request, 'repairs/device_type_form.html', {'form': form})

@login_required
def device_type_delete(request, pk):
    dt = get_object_or_404(DeviceType, pk=pk)
    if request.method == 'POST':
        dt.delete()
        return redirect('repairs:device_type_list')
    return render(request, 'repairs/formatted_confirm_delete.html', {'object': dt, 'type': 'Device Type', 'cancel_url': 'repairs:device_type_list'})

# --- RepairType Views ---

@login_required
def repair_type_list(request):
    repair_types = RepairType.objects.all()
    return render(request, 'repairs/repair_type_list.html', {'repair_types': repair_types})

@login_required
def repair_type_create(request):
    if request.method == 'POST':
        form = RepairTypeForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('repairs:repair_type_list')
    else:
        form = RepairTypeForm()
    return render(request, 'repairs/repair_type_form.html', {'form': form, 'title': 'เพิ่มประเภทงานซ่อม'})

@login_required
def repair_type_update(request, pk):
    rt = get_object_or_404(RepairType, pk=pk)
    if request.method == 'POST':
        form = RepairTypeForm(request.POST, instance=rt)
        if form.is_valid():
            form.save()
            return redirect('repairs:repair_type_list')
    else:
        form = RepairTypeForm(instance=rt)
    return render(request, 'repairs/repair_type_form.html', {'form': form, 'title': 'แก้ไขประเภทงานซ่อม'})

@login_required
def repair_type_delete(request, pk):
    rt = get_object_or_404(RepairType, pk=pk)
    if request.method == 'POST':
        rt.delete()
        return redirect('repairs:repair_type_list')
    return render(request, 'repairs/repair_type_confirm_delete.html', {'object': rt})
    
@login_required
def repair_print(request, pk):
    job = get_object_or_404(RepairJob, pk=pk)
    return render(request, 'repairs/repair_print.html', {
        'job': job,
        'now': timezone.now()
    })

# --- Brand Views ---

@login_required
def brand_list(request):
    brands = Brand.objects.all().order_by('name')
    return render(request, 'repairs/brand_list.html', {'brands': brands})

@login_required
def brand_create(request):
    if request.method == 'POST':
        form = BrandForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('repairs:brand_list')
    else:
        form = BrandForm()
    return render(request, 'repairs/brand_form.html', {'form': form, 'title': 'Create Brand'})

@login_required
def brand_update(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if request.method == 'POST':
        form = BrandForm(request.POST, instance=brand)
        if form.is_valid():
            form.save()
            return redirect('repairs:brand_list')
    else:
        form = BrandForm(instance=brand)
    return render(request, 'repairs/brand_form.html', {'form': form, 'title': 'Edit Brand'})

@login_required
def brand_delete(request, pk):
    brand = get_object_or_404(Brand, pk=pk)
    if request.method == 'POST':
        try:
            brand.delete()
        except Exception:
            pass
        return redirect('repairs:brand_list')
    return render(request, 'repairs/brand_confirm_delete.html', {'brand': brand})

@login_required
def repair_income_report(request):
    from django.contrib.auth.models import User
    from django.db.models import Sum, Count, Prefetch

    today = datetime.date.today()
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    if start_date_str:
        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
    else:
        start_date = today.replace(day=1) # First day of month

    if end_date_str:
         end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
         end_date = today 

    items = RepairItem.objects.filter(
        updated_at__date__range=[start_date, end_date],
        status='COMPLETED'
    ).select_related(
        'job', 'device', 'device__brand', 'job__customer', 'created_by'
    ).prefetch_related(
        Prefetch(
            'status_history',
            queryset=RepairStatusHistory.objects.filter(
                status='COMPLETED'
            ).select_related('changed_by').order_by('-changed_at'),
            to_attr='completed_history'
        )
    ).order_by('-updated_at')

    # Filter by user (created_by)
    filter_user_id = request.GET.get('user')
    if filter_user_id:
        items = items.filter(
            Q(created_by__id=filter_user_id) |
            Q(status_history__status='COMPLETED', status_history__changed_by__id=filter_user_id)
        ).distinct()

    # Build items list with completed_by info
    items_list = list(items)
    for item in items_list:
        # Find the user who marked it COMPLETED
        if hasattr(item, 'completed_history') and item.completed_history:
            item.completed_by_user = item.completed_history[0].changed_by
        else:
            item.completed_by_user = item.created_by

    total_income = sum(item.final_cost or 0 for item in items_list)
    total_count = len(items_list)

    # Per-user income summary
    user_income = {}
    for item in items_list:
        user = item.completed_by_user or item.created_by
        username = user.username if user else 'ไม่ระบุ'
        user_id = user.id if user else 0
        if user_id not in user_income:
            user_income[user_id] = {
                'username': username,
                'user_id': user_id,
                'total': 0,
                'count': 0,
            }
        user_income[user_id]['total'] += (item.final_cost or 0)
        user_income[user_id]['count'] += 1
    
    user_income_list = sorted(user_income.values(), key=lambda x: x['total'], reverse=True)

    # Get all users that have repair data for the dropdown
    users = User.objects.filter(
        Q(created_repair_items__status='COMPLETED') |
        Q(repairstatushistory__status='COMPLETED')
    ).distinct().order_by('username')
    
    if request.GET.get('export') == 'excel':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="income_report_{start_date}_{end_date}.csv"'
        response.write(u'\ufeff'.encode('utf8')) # BOM
        
        writer = csv.writer(response)
        writer.writerow(['วันที่', 'รหัสงาน', 'ลูกค้า', 'รายการ', 'ผู้รับงาน', 'ผู้ส่งคืน', 'ค่าใช้จ่ายจริง'])
        for item in items_list:
             completed_by = item.completed_by_user.username if item.completed_by_user else '-'
             created_by = item.created_by.username if item.created_by else '-'
             writer.writerow([
                 item.updated_at.strftime('%d/%m/%Y'),
                 item.job.job_code,
                 item.job.customer.name,
                 f"{item.device.brand} {item.device.model} - {item.issue_description}",
                 created_by,
                 completed_by,
                 item.final_cost or 0
             ])
        return response

    return render(request, 'repairs/reports/income_report.html', {
        'items': items_list,
        'total_income': total_income,
        'total_count': total_count,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'users': users,
        'filter_user_id': filter_user_id,
        'user_income_list': user_income_list,
        'daily_income_json': _build_daily_income_json(items_list, start_date, end_date),
    })


def _build_daily_income_json(items_list, start_date, end_date):
    """Build JSON data for daily income chart."""
    daily = defaultdict(lambda: {'income': Decimal('0'), 'count': 0})
    for item in items_list:
        day_key = item.updated_at.strftime('%Y-%m-%d')
        daily[day_key]['income'] += (item.final_cost or Decimal('0'))
        daily[day_key]['count'] += 1

    # Fill in all days in the range
    labels = []
    incomes = []
    counts = []
    current = start_date
    while current <= end_date:
        key = current.strftime('%Y-%m-%d')
        label = current.strftime('%d/%m')
        labels.append(label)
        incomes.append(float(daily[key]['income']))
        counts.append(daily[key]['count'])
        current += datetime.timedelta(days=1)

    return json.dumps({
        'labels': labels,
        'incomes': incomes,
        'counts': counts,
    }, ensure_ascii=False)

def repair_tracking(request, tracking_id):
    job = get_object_or_404(RepairJob, tracking_id=tracking_id)
    status_choices = RepairItem.STATUS_CHOICES
    all_technicians = Technician.objects.all().order_by('name')
    return render(request, 'repairs/repair_tracking.html', {
        'job': job, 
        'status_choices': status_choices,
        'all_technicians': all_technicians
    })



@login_required
def repair_item_delete(request, item_id):
    item = get_object_or_404(RepairItem, pk=item_id)
    
    if request.method == 'POST':
        password = request.POST.get('password')
        from django.conf import settings
        if password == settings.DELETE_PASSWORD:
            if item.status == 'COMPLETED':
                with transaction.atomic():
                    job = item.job
                    item.delete()
                    if not job.items.exists():
                        job.delete()
                
                return redirect('repairs:repair_returned_list')
            else:
                return redirect('repairs:repair_list')
        else:
            return redirect('repairs:repair_returned_list')
            
    return redirect('repairs:repair_returned_list')

def repair_status_search(request):
    if request.method == 'POST':
        job_code = request.POST.get('job_code')
        phone = request.POST.get('phone')
        
        if not job_code or not phone:
             return render(request, 'repairs/repair_status_search.html', {'error': 'กรุณากรอกข้อมูลให้ครบถ้วน'})

        job_code = job_code.strip()
        phone = phone.strip()
        
        try:
            job = RepairJob.objects.get(job_code__iexact=job_code)
            # Check phone last 4 digits
            cust_phone = job.customer.contact_number.replace('-', '').replace(' ', '')
            
            if cust_phone.endswith(phone):
                if not job.tracking_id:
                     import uuid
                     job.tracking_id = uuid.uuid4()
                     job.save()
                
                return redirect('repairs:repair_tracking', tracking_id=job.tracking_id)
            else:
                return render(request, 'repairs/repair_status_search.html', {'error': 'เบอร์โทรศัพท์ไม่ถูกต้อง (กรุณาระบุ 4 ตัวท้าย)'})
        except RepairJob.DoesNotExist:
            return render(request, 'repairs/repair_status_search.html', {'error': 'ไม่พบข้อมูลใบรับบริการนี้'})
            
    return render(request, 'repairs/repair_status_search.html')


# --- Notification API ---

@login_required
def repair_notifications_api(request):
    """AJAX endpoint: return recent new repair items for notification bell."""
    # Get last seen timestamp from session
    last_seen_str = request.session.get('notif_last_seen')
    if last_seen_str:
        try:
            last_seen = datetime.datetime.fromisoformat(last_seen_str)
        except (ValueError, TypeError):
            last_seen = timezone.now() - datetime.timedelta(hours=24)
    else:
        # Default to 8 hours instead of 24 for cleaner first-look
        last_seen = timezone.now() - datetime.timedelta(hours=8)

    # 1. Get new items since last seen
    # Exclude items created by current user
    new_items_query = RepairItem.objects.filter(
        created_at__gt=last_seen
    ).exclude(created_by=request.user)
    
    # If not superuser, maybe only show what they might care about (optional, keeping broad for now)
    new_items = new_items_query.select_related(
        'job', 'device', 'device__brand', 'job__customer', 'created_by'
    ).order_by('-created_at')[:20]

    # Build response
    notifications = []
    for item in new_items:
        notifications.append({
            'id': item.id,
            'job_code': item.job.job_code,
            'job_pk': item.job.pk,
            'customer': item.job.customer.name,
            'device': f"{item.device.brand} {item.device.model}",
            'issue': item.issue_description[:60],
            'created_by': item.created_by.username if item.created_by else '-',
            'created_at': item.created_at.strftime('%H:%M'),
            'created_date': item.created_at.strftime('%d/%m/%Y'),
        })

    # 2. Get status changes
    # Exclude changes made by current user
    status_changes_query = RepairStatusHistory.objects.filter(
        changed_at__gt=last_seen
    ).exclude(
        Q(status='RECEIVED') | Q(changed_by=request.user)
    )

    # Filter: Normal users only see what they are responsible for
    # Superusers see everything
    if not request.user.is_superuser:
        status_changes_query = status_changes_query.filter(
            status_obj__responsibles=request.user
        )

    status_changes = status_changes_query.select_related(
        'repair_item', 'repair_item__job', 'repair_item__device',
        'repair_item__device__brand', 'changed_by', 'status_obj'
    ).order_by('-changed_at')[:15]

    status_notifs = []
    for sh in status_changes:
        status_notifs.append({
            'id': sh.id,
            'job_code': sh.repair_item.job.job_code,
            'job_pk': sh.repair_item.job.pk,
            'device': f"{sh.repair_item.device.brand} {sh.repair_item.device.model}",
            'status': sh.get_status_display(),
            'status_code': sh.status,
            'status_color': sh.status_obj.color if sh.status_obj else None,
            'is_responsible': sh.status_obj.responsibles.filter(id=request.user.id).exists() if sh.status_obj else False,
            'changed_by': sh.changed_by.username if sh.changed_by else '-',
            'changed_at': sh.changed_at.strftime('%H:%M'),
        })

    return JsonResponse({
        'new_count': len(notifications),
        'status_count': len(status_notifs),
        'total_count': len(notifications) + len(status_notifs),
        'new_items': notifications,
        'status_changes': status_notifs,
    })


@login_required
def repair_notifications_mark_seen(request):
    """AJAX POST: mark all notifications as seen."""
    if request.method == 'POST':
        request.session['notif_last_seen'] = timezone.now().isoformat()
        return JsonResponse({'ok': True})
    return JsonResponse({'error': 'POST required'}, status=405)
# --- Technician Quick Status Update (Via QR Code Tracking Page) ---

def technician_status_login(request):
    """View to 'log in' a technician for quick status updates via session."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        
        from django.contrib.auth import authenticate, login
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if user.is_active:
                login(request, user) # Standard Django Login
                # We can also set a specific session flag if we want to know they logged in via track page
                request.session['tech_quick_auth'] = True
                return JsonResponse({'status': 'success', 'name': user.get_full_name() or user.username})
            else:
                return JsonResponse({'status': 'error', 'message': 'Account is disabled'}, status=401)
        else:
            return JsonResponse({'status': 'error', 'message': 'Username หรือ Password ไม่ถูกต้อง'}, status=401)
            
    return JsonResponse({'status': 'error', 'message': 'POST required'}, status=400)

def technician_status_logout(request):
    """Clear the technician session."""
    from django.contrib.auth import logout
    logout(request)
    
    # Redirect back to where they were if tracking ID is present
    tracking_id = request.GET.get('tracking_id')
    if tracking_id:
        return redirect('repairs:repair_tracking', tracking_id=tracking_id)
    return redirect('repairs:repair_status_search')

def technician_update_status_api(request):
    """AJAX endpoint for technicians to update status from tracking page."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=400)
    
    # Standard Django user authentication check
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'Session expired. Please login again.'}, status=401)
    
    item_id = request.POST.get('item_id')
    new_status = request.POST.get('status')
    note = request.POST.get('note', '')
    
    item = get_object_or_404(RepairItem, pk=item_id)
    
    with transaction.atomic():
        item.status = new_status
        item.status_note = note
        
        # Handle Technicians - ONLY if new status is FIXING
        if new_status == 'FIXING':
            tech_ids = request.POST.getlist('technicians')
            if tech_ids:
                item.technicians.set(tech_ids)
                
        item.save()
        
        # Record history - NOW correctly links to request.user
        RepairStatusHistory.objects.create(
            repair_item=item,
            status=new_status,
            changed_by=request.user,
            note=f"[Quick Update] {note}"
        )
        
    return JsonResponse({'status': 'success', 'new_status_display': item.get_status_display()})

@login_required
def repair_status_list(request):
    """จัดการรายการสถานะงานซ่อม และลำดับขั้นตอน"""
    if not request.user.is_superuser:
        return redirect('repairs:dashboard')
        
    statuses = RepairStatus.objects.all().prefetch_related('responsibles')
    
    # Initialize if empty
    if not statuses.exists():
        defaults = [
            ('RECEIVED', 'รับแจ้ง', 10, '#ef4444'),
            ('FIXING', 'กำลังซ่อม/ตรวจเช็ค', 20, '#f97316'),
            ('WAITING_APPROVAL', 'รออนุมัติงานซ่อม', 30, '#a855f7'),
            ('WAITING', 'รออะไหล่', 40, '#eab308'),
            ('OUTSOURCE', 'ส่งซ่อมศูนย์/ภายนอก', 50, '#6366f1'),
            ('RECEIVED_FROM_VENDOR', 'รอตรวจรับกลับ', 60, '#3b82f6'),
            ('FINISHED', 'ซ่อมเสร็จ', 70, '#22c55e'),
            ('CANCELLED', 'ยกเลิกการซ่อม', 80, '#6b7280'),
            ('COMPLETED', 'ส่งคืนให้ลูกค้าแล้ว', 90, '#1f2937'),
        ]
        for code, name, seq, color in defaults:
            RepairStatus.objects.get_or_create(code=code, defaults={'name': name, 'sequence': seq, 'color': color})
        statuses = RepairStatus.objects.all().prefetch_related('responsibles')

    users = User.objects.all().order_by('username')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'update_responsible':
            status_id = request.POST.get('status_id')
            user_ids = request.POST.getlist('responsibles')
            status = get_object_or_404(RepairStatus, id=status_id)
            status.responsibles.set(user_ids)
            return JsonResponse({'status': 'success'})
        elif action == 'update_basic':
            status_id = request.POST.get('status_id')
            status = get_object_or_404(RepairStatus, id=status_id)
            status.name = request.POST.get('name')
            status.sequence = request.POST.get('sequence')
            status.color = request.POST.get('color')
            status.save()
            return JsonResponse({'status': 'success'})
        elif action == 'create':
            name = request.POST.get('name')
            code = request.POST.get('code', name.upper().replace(' ', '_')) # Default code from name
            sequence = request.POST.get('sequence', 0)
            color = request.POST.get('color', '#6b7280')
            
            if RepairStatus.objects.filter(code=code).exists():
                return JsonResponse({'status': 'error', 'message': f'รหัสสถานะ {code} มีอยู่ในระบบแล้ว'}, status=400)
                
            RepairStatus.objects.create(name=name, code=code, sequence=sequence, color=color)
            return JsonResponse({'status': 'success'})
        elif action == 'delete':
            status_id = request.POST.get('status_id')
            status = get_object_or_404(RepairStatus, id=status_id)
            if status.items.exists():
                return JsonResponse({'status': 'error', 'message': 'ไม่สามารถลบได้เนื่องจากมีงานซ่อมใช้งานสถานะนี้อยู่'}, status=400)
            status.delete()
            return JsonResponse({'status': 'success'})

    return render(request, 'repairs/repair_status_list.html', {
        'statuses': statuses,
        'users': users
    })

@login_required
def repair_next_step(request, item_id):
    """เลื่อนสถานะงานซ่อมไปยังขั้นตอนถัดไปอัตโนมัติ"""
    item = get_object_or_404(RepairItem, pk=item_id)
    
    # ดึงสถานะปัจจุบัน
    current = item.current_status
    if not current:
        # ถ้ายังไม่มีสถานะผูกกับโมเดลใหม่ ให้ลองหาจาก code เดิม
        current = RepairStatus.objects.filter(code=item.status).first()
    
    if not current:
        # ถ้าหาไม่ได้เลย ให้เริ่มที่ตัวแรก
        next_status = RepairStatus.objects.first()
    else:
        # หาตัวที่มี sequence มากกว่าตัวปัจจุบัน
        next_status = RepairStatus.objects.filter(sequence__gt=current.sequence).first()
    
    if next_status:
        with transaction.atomic():
            item.current_status = next_status
            item.status = next_status.code #Sync with old field for compatibility
            
            # Additional logic for COMPLETED
            if next_status.code == 'COMPLETED':
                item.closed_at = timezone.now()
            
            # Save technicians and status note if provided
            tech_ids = request.POST.getlist('technicians[]') or request.POST.getlist('technicians')
            if tech_ids:
                item.technicians.set(tech_ids)
            
            status_note = request.POST.get('status_note')
            if status_note:
                item.status_note = status_note
            
            item.save()
            
            note_text = f"เลื่อนสถานะเป็น {next_status.name} (อัตโนมัติ)"
            if status_note:
                note_text += f" - {status_note}"

            RepairStatusHistory.objects.create(
                repair_item=item,
                status=next_status.code,
                status_obj=next_status,
                changed_by=request.user,
                note=note_text
            )
            
        return JsonResponse({
            'status': 'success', 
            'new_status_name': next_status.name,
            'new_status_color': next_status.color
        })
    
    return JsonResponse({'status': 'error', 'message': 'ไม่มีขั้นตอนถัดไปแล้ว'})
