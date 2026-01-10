from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.db import transaction
from django.contrib.auth.decorators import login_required
from .models import RepairJob, RepairItem, Customer, Device, Technician, DeviceType
from .forms import CustomerForm, DeviceForm, RepairJobForm, RepairItemForm, TechnicianForm, DeviceTypeForm

@login_required
def repair_list(request):
    jobs = RepairJob.objects.all().order_by('-created_at')
    return render(request, 'repairs/repair_list.html', {'jobs': jobs})

@login_required
def repair_create(request):
    customer_id = request.GET.get('customer_id')
    prefilled_customer = None
    if customer_id:
        prefilled_customer = get_object_or_404(Customer, pk=customer_id)

    if request.method == 'POST':
        if prefilled_customer:
             # Skip customer form validation if existing customer
             customer_form = None
             customer = prefilled_customer
        else:
            customer_form = CustomerForm(request.POST, prefix='customer')

        job_form = RepairJobForm(request.POST, prefix='job')
        
        # Simple implementation: 1 device per job creation for now, to keep it simple initially
        # Enhancing to support at least one device in the main flow
        device_form = DeviceForm(request.POST, prefix='device')
        item_form = RepairItemForm(request.POST, prefix='item')

        if (prefilled_customer or customer_form.is_valid()) and job_form.is_valid() and device_form.is_valid() and item_form.is_valid():
            with transaction.atomic():
                # Save Customer if new
                if not prefilled_customer:
                    customer = customer_form.save()
                
                # Save Device linked to Customer
                device = device_form.save(commit=False)
                device.customer = customer
                device.save()
                
                # Save Job linked to Customer
                job = job_form.save(commit=False)
                job.customer = customer
                job.save()
                
                # Save Item linked to Job and Device
                item = item_form.save(commit=False)
                item.job = job
                item.device = device
                item.save()
                item_form.save_m2m() # Save technicians
                
                return redirect('repairs:repair_detail', pk=job.pk)
    else:
        if prefilled_customer:
            customer_form = None
        else:
            customer_form = CustomerForm(prefix='customer')
        job_form = RepairJobForm(prefix='job')
        device_form = DeviceForm(prefix='device')
        item_form = RepairItemForm(prefix='item')

    context = {
        'customer_form': customer_form,
        'prefilled_customer': prefilled_customer,
        'job_form': job_form,
        'device_form': device_form,
        'item_form': item_form,
    }
    return render(request, 'repairs/repair_form.html', context)

@login_required
def repair_detail(request, pk):
    job = get_object_or_404(RepairJob, pk=pk)
    return render(request, 'repairs/repair_detail.html', {'job': job})

@login_required
def repair_update_status(request, item_id):
    item = get_object_or_404(RepairItem, pk=item_id)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status:
            item.status = new_status
            item.save()
    return redirect('repairs:repair_detail', pk=item.job.pk)

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
def device_list(request):
    devices = Device.objects.all().order_by('-id')
    return render(request, 'repairs/device_list.html', {'devices': devices})

@login_required
def device_create(request):
    if request.method == 'POST':
        form = DeviceForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('repairs:device_list')
    else:
        form = DeviceForm()
    return render(request, 'repairs/device_form.html', {'form': form})

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

