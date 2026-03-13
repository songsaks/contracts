# ====== views.py - View Functions ของระบบสัญญาเช่า ======
# ไฟล์นี้มี view functions ทั้งหมดสำหรับจัดการ:
#   - Dashboard      : แสดงภาพรวมสัญญาที่กำลังดำเนินอยู่
#   - Asset          : จัดการทรัพย์สิน (รายการ, เพิ่ม, แก้ไข, นำเข้า Excel)
#   - Tenant         : ลงทะเบียนผู้เช่า
#   - Contract       : สร้าง, ยกเลิก, ปิดสัญญา
#   - Payment        : บันทึกการชำระเงิน
#   - Reports        : รายงานสัญญาทั้งหมด
# ทุก view ต้องล็อกอินก่อน (@login_required)

from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.db.models import Sum, F
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Asset, Contract, Tenant
from decimal import Decimal
from datetime import datetime

# ====== Dashboard - หน้าหลักภาพรวมสัญญา ======
@login_required
def dashboard(request):
    """
    แสดงหน้า Dashboard หลัก:
    - สรุปยอดรายรับรวม (Total Revenue) และยอดค้างชำระรวม (Total Receivable)
    - รายการสัญญาที่กำลัง ACTIVE อยู่ พร้อมกรองตาม tenant ได้
    """
    active_contracts = Contract.objects.filter(status='ACTIVE')
    tenants = Tenant.objects.all()

    # กรองสัญญาตาม tenant ที่เลือก (ถ้ามีการส่ง tenant_id มาใน query string)
    tenant_id = request.GET.get('tenant')
    if tenant_id:
        active_contracts = active_contracts.filter(tenant_id=tenant_id)

    # Financial Stats (should likely reflect filtered view or global? Usually dashboard stats are global, but context implies tailored view. I'll keep stats global for now unless requested, but filtering the list.)
    # Actually, usually if I filter the dashboard, I expect stats to update too.
    # Let's update stats to reflect the filtered contracts?
    # "Financial Stats"
    # คำนวณรายรับรวมจากทุกสัญญา (ยอดที่ชำระแล้วทั้งหมด ไม่กรองตาม tenant)
    total_revenue = Contract.objects.aggregate(Sum('paid_amount'))['paid_amount__sum'] or 0
    # Total Receivable usually is for ALL active debt.
    # But if I filter by agency, maybe I want to see THEIR debt?
    # I will calculate stats based on the potentially filtered list for 'total_receivable' context but total_revenue might be historical.
    # To be safe and simple, I will keep stats Global for now as they are labelled "Total Revenue".
    # But wait, user might want to see specific agency debt.
    # Let's just filter the list first as requested.

    # คำนวณยอดค้างชำระรวมของสัญญา ACTIVE ทุกสัญญา (total_amount - paid_amount)
    total_receivable = Contract.objects.filter(status='ACTIVE').aggregate(
        debt=Sum(F('total_amount') - F('paid_amount'))
    )['debt'] or 0

    return render(request, 'rentals/dashboard.html', {
        'contracts': active_contracts,       # สัญญา ACTIVE (อาจถูกกรองตาม tenant)
        'total_revenue': total_revenue,      # รายรับรวมทั้งหมด
        'total_receivable': total_receivable, # ยอดค้างชำระรวม
        'tenants': tenants,                  # รายชื่อผู้เช่าทั้งหมด สำหรับ dropdown filter
        'selected_tenant': int(tenant_id) if tenant_id else None  # tenant ที่เลือกอยู่
    })

# ====== Asset Views - จัดการทรัพย์สิน ======

@login_required
def asset_list(request):
    """แสดงรายการทรัพย์สินทั้งหมดในระบบ พร้อมสถานะและค่าเช่าต่อเดือน"""
    assets = Asset.objects.all()
    return render(request, 'rentals/asset_list.html', {'assets': assets})

@login_required
def asset_create(request):
    """เพิ่มทรัพย์สินใหม่เข้าระบบ รับข้อมูลจาก form และบันทึกลงฐานข้อมูล"""
    if request.method == 'POST':
        name = request.POST.get('name')
        serial_number = request.POST.get('serial_number')
        description = request.POST.get('description')
        monthly_rate = request.POST.get('monthly_rate')
        Asset.objects.create(name=name, serial_number=serial_number, description=description, monthly_rate=monthly_rate)
        messages.success(request, 'Asset created successfully.')
        return redirect('rentals:asset_list')
    return render(request, 'rentals/asset_form.html')

@login_required
def asset_edit(request, pk):
    """
    แก้ไขข้อมูลทรัพย์สิน
    - ถ้าสถานะเป็น RENTED จะไม่อนุญาตให้เปลี่ยนสถานะด้วยตนเอง
      (สถานะถูกจัดการโดยระบบสัญญาโดยอัตโนมัติ)
    """
    asset = get_object_or_404(Asset, pk=pk)
    if request.method == 'POST':
        asset.name = request.POST.get('name')
        asset.serial_number = request.POST.get('serial_number')
        asset.description = request.POST.get('description')
        asset.monthly_rate = request.POST.get('monthly_rate')

        # Only allow status change if not RENTED, or ensure we don't accidentally force it if hidden
        # อนุญาตให้เปลี่ยนสถานะได้เฉพาะเมื่อทรัพย์สินไม่ได้ถูกเช่าอยู่
        new_status = request.POST.get('status')
        if asset.status != 'RENTED' and new_status in ['AVAILABLE', 'MAINTENANCE']:
            asset.status = new_status

        asset.save()
        messages.success(request, 'Asset updated successfully.')
        return redirect('rentals:asset_list')
    return render(request, 'rentals/asset_edit.html', {'asset': asset})

@login_required
def asset_import(request):
    """
    นำเข้าทรัพย์สินจากไฟล์ Excel (.xlsx)
    - ใช้ pandas อ่านไฟล์ Excel
    - ถ้ามี Serial Number จะใช้ update_or_create เพื่อป้องกันข้อมูลซ้ำ
    - ถ้าไม่มี Serial Number จะสร้างรายการใหม่เสมอ
    - คอลัมน์ที่รองรับ: Name, Serial Number, Monthly Rate, Status, Description
    """
    if request.method == 'POST' and request.FILES.get('excel_file'):
        import pandas as pd
        excel_file = request.FILES['excel_file']
        try:
            df = pd.read_excel(excel_file)
            count = 0
            for index, row in df.iterrows():
                # Basic validation
                # ตรวจสอบว่า Name ไม่ว่างเปล่า (จำเป็นต้องมี)
                name = row.get('Name')
                if not name or pd.isna(name):
                    continue

                # แปลงค่า serial ที่เป็น NaN เป็น None
                serial = row.get('Serial Number')
                if pd.isna(serial):
                    serial = None

                # แปลงค่า monthly_rate ที่เป็น NaN เป็น 0
                monthly_rate = row.get('Monthly Rate', 0)
                if pd.isna(monthly_rate):
                    monthly_rate = 0

                # แปลงค่า description ที่เป็น NaN เป็น string ว่าง
                description = row.get('Description', '')
                if pd.isna(description):
                    description = ''

                # ตรวจสอบว่า Status อยู่ในค่าที่ถูกต้อง ถ้าไม่ใช่ให้ใช้ AVAILABLE
                status = row.get('Status', 'AVAILABLE').upper()
                if status not in ['AVAILABLE', 'MAINTENANCE', 'RENTED']:
                    status = 'AVAILABLE'

                # Use update_or_create to avoid duplicates if serial is present
                # ถ้ามี Serial Number ใช้ update_or_create เพื่อป้องกันข้อมูลซ้ำ
                if serial:
                    Asset.objects.update_or_create(
                        serial_number=serial,
                        defaults={
                            'name': name,
                            'monthly_rate': monthly_rate,
                            'description': description,
                            'status': status
                        }
                    )
                    count += 1
                else:
                    # If no serial, just create (allow duplicates? probably yes if no identifier)
                    # ไม่มี Serial Number - สร้างรายการใหม่โดยไม่ตรวจสอบซ้ำ
                    Asset.objects.create(
                        name=name,
                        monthly_rate=monthly_rate,
                        description=description,
                        status=status,
                        serial_number=None
                    )
                    count += 1

            messages.success(request, f'Successfully imported {count} assets.')
            return redirect('rentals:asset_list')
        except Exception as e:
            messages.error(request, f'Error importing file: {e}')
            return redirect('rentals:asset_import')

    return render(request, 'rentals/asset_import.html')

# ====== Tenant View - ลงทะเบียนผู้เช่า ======

@login_required
def tenant_create(request):
    """
    ลงทะเบียนผู้เช่าใหม่เข้าระบบ
    หลังจากลงทะเบียนสำเร็จ จะ redirect ไปหน้าสร้างสัญญาเช่าทันที
    """
    if request.method == 'POST':
        Tenant.objects.create(
            agency_name=request.POST.get('agency_name'),
            contact_person=request.POST.get('contact_person'),
            email=request.POST.get('email'),
            phone=request.POST.get('phone'),
            document_id=request.POST.get('document_id'),
            address=request.POST.get('address')
        )
        messages.success(request, 'Tenant registered successfully.')
        return redirect('rentals:contract_create')  # ไปหน้าสร้างสัญญาต่อเลย
    return render(request, 'rentals/tenant_form.html')

# ====== Contract Views - จัดการสัญญาเช่า ======

@login_required
def contract_create(request):
    """
    สร้างสัญญาเช่าใหม่ โดยมีขั้นตอนดังนี้:
    1. ตรวจสอบว่าเลือกทรัพย์สินอย่างน้อย 1 รายการ
    2. ตรวจสอบว่าทรัพย์สินทุกชิ้นมีสถานะ AVAILABLE
    3. คำนวณค่าเช่ารวม = (ผลรวมค่าเช่ารายเดือน) x (จำนวนเดือน ปัดขึ้น)
    4. สร้าง Contract และเปลี่ยนสถานะ Asset เป็น RENTED
    ทุกขั้นตอนอยู่ใน transaction.atomic() เพื่อความปลอดภัยของข้อมูล
    """
    if request.method == 'POST':
        tenant_id = request.POST.get('tenant')
        asset_ids = request.POST.getlist('assets')  # รายการ ID ของทรัพย์สินที่เลือก
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        payment_frequency = request.POST.get('payment_frequency')

        # ต้องเลือกทรัพย์สินอย่างน้อย 1 รายการ
        if not asset_ids:
            messages.error(request, 'Please select at least one asset.')
            return redirect('rentals:contract_create')

        try:
            with transaction.atomic():
                # แปลงวันที่จาก string เป็น date object
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                days = (end_date - start_date).days

                # ตรวจสอบว่าวันสิ้นสุดต้องมาหลังวันเริ่มต้น
                if days <= 0:
                    raise ValueError("End date must be after start date.")

                assets_to_rent = Asset.objects.filter(id__in=asset_ids)

                # Check availability
                # ตรวจสอบสถานะทรัพย์สินทุกชิ้นว่ายังว่างอยู่
                for asset in assets_to_rent:
                    if asset.status != 'AVAILABLE':
                        raise ValueError(f"Asset {asset.name} is no longer available.")

                # Calculate Total Amount
                # คำนวณค่าเช่ารายเดือนรวมของทรัพย์สินที่เลือกทั้งหมด
                monthly_total = sum(a.monthly_rate for a in assets_to_rent)

                # Calculate duration in months (rounding up to nearest month)
                # คำนวณจำนวนเดือน โดยปัดขึ้นเสมอ (เช่น 45 วัน = 2 เดือน)
                import math
                num_months = math.ceil(days / 30)
                if num_months < 1:
                    num_months = 1

                # ค่าเช่ารวม = ค่าเช่ารายเดือนรวม x จำนวนเดือน
                total_amount = monthly_total * Decimal(num_months)
                total_amount = round(total_amount, 2)

                # สร้างสัญญาเช่าและผูกกับทรัพย์สิน
                tenant = Tenant.objects.get(id=tenant_id)
                contract = Contract.objects.create(
                    tenant=tenant,
                    start_date=start_date,
                    end_date=end_date,
                    payment_frequency=payment_frequency,
                    total_amount=total_amount,
                    status='ACTIVE'
                )
                contract.assets.set(assets_to_rent)

                # เปลี่ยนสถานะทรัพย์สินทั้งหมดเป็น RENTED
                assets_to_rent.update(status='RENTED')

                messages.success(request, f'Contract created. Total: \u0e3f{total_amount}')
                return redirect('rentals:dashboard')
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")

    # GET context
    # ดึงข้อมูลสำหรับแสดง form (ผู้เช่าทั้งหมด และทรัพย์สินที่ว่างอยู่)
    tenants = Tenant.objects.all()
    available_assets = Asset.objects.filter(status='AVAILABLE')
    return render(request, 'rentals/contract_form.html', {
        'tenants': tenants,
        'assets': available_assets
    })

@login_required
def contract_cancel(request, pk):
    """
    ยกเลิกสัญญาเช่า (ACTIVE -> CANCELLED)
    - เปลี่ยนสถานะสัญญาเป็น CANCELLED
    - คืนสถานะทรัพย์สินทุกชิ้นในสัญญาเป็น AVAILABLE
    """
    contract = get_object_or_404(Contract, pk=pk)
    if contract.status == 'ACTIVE':
        with transaction.atomic():
            contract.status = 'CANCELLED'
            contract.save()
            # คืนทรัพย์สินทั้งหมดในสัญญากลับสู่สถานะพร้อมให้เช่า
            contract.assets.update(status='AVAILABLE')
            messages.success(request, 'Contract cancelled.')
    return redirect('rentals:dashboard')

@login_required
def contract_complete(request, pk):
    """
    ปิดสัญญาเช่าที่ครบกำหนด (ACTIVE -> COMPLETED)
    - เปลี่ยนสถานะสัญญาเป็น COMPLETED
    - คืนสถานะทรัพย์สินทุกชิ้นในสัญญาเป็น AVAILABLE
    """
    contract = get_object_or_404(Contract, pk=pk)
    if contract.status == 'ACTIVE':
        with transaction.atomic():
            contract.status = 'COMPLETED'
            contract.save()
            # คืนทรัพย์สินทั้งหมดในสัญญากลับสู่สถานะพร้อมให้เช่า
            contract.assets.update(status='AVAILABLE')
            messages.success(request, 'Contract completed.')
    return redirect('rentals:dashboard')

@login_required
def contract_payment(request, pk):
    """
    บันทึกการชำระเงินของสัญญา
    - รับจำนวนเงินที่ชำระ และบวกเพิ่มเข้า paid_amount ของสัญญา
    - จำนวนเงินต้องมากกว่า 0
    """
    contract = get_object_or_404(Contract, pk=pk)
    if request.method == 'POST':
        amount = Decimal(request.POST.get('payment_amount', '0'))
        if amount > 0:
            with transaction.atomic():
                # บวกยอดชำระใหม่เข้าไปใน paid_amount ของสัญญา
                contract.paid_amount += amount
                contract.save()
                messages.success(request, f'Payment of \u0e3f{amount} recorded.')
        return redirect('rentals:dashboard')
    return render(request, 'rentals/contract_payment.html', {'contract': contract})

# ====== Reports View - รายงานสัญญา ======

@login_required
def reports(request):
    """
    หน้ารายงานสัญญาเช่าทั้งหมด
    - กรองได้ตาม tenant และ status
    - ส่งข้อมูล 2 ชุด:
        rentals    = ข้อมูลที่ผ่านการกรอง (แสดงบนหน้าจอ)
        all_rentals = ข้อมูลทั้งหมดไม่กรอง (ใช้สำหรับพิมพ์)
    """
    # Base query for both
    # query หลักดึงสัญญาทั้งหมดเรียงจากใหม่สุดไปเก่าสุด
    base_query = Contract.objects.all().order_by('-created_at')

    # Filtered rentals for screen view
    # สำเนา query สำหรับกรองแสดงบนหน้าจอ
    rentals = base_query

    tenants = Tenant.objects.all()  # รายชื่อผู้เช่าทั้งหมดสำหรับ dropdown

    # กรองตาม tenant (ถ้ามีการเลือก)
    tenant_id = request.GET.get('tenant')
    if tenant_id:
        rentals = rentals.filter(tenant_id=tenant_id)

    # กรองตามสถานะสัญญา (ถ้ามีการเลือก)
    status = request.GET.get('status')
    if status:
        rentals = rentals.filter(status=status)

    return render(request, 'rentals/reports.html', {
        'rentals': rentals,       # Filtered - ข้อมูลที่กรองแล้ว สำหรับแสดงบนหน้าจอ
        'all_rentals': base_query, # Unfiltered for print - ข้อมูลทั้งหมดสำหรับพิมพ์
        'tenants': tenants,
        'selected_tenant': int(tenant_id) if tenant_id else None,
        'status_choices': Contract.STATUS_CHOICES,  # ตัวเลือกสถานะสำหรับ dropdown
        'selected_status': status,
    })
