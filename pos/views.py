# ====== นำเข้า Library และ Module ที่จำเป็น ======
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Sum, F
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
import json
from django.contrib.auth.decorators import login_required
from .models import Product, Order, OrderItem, Category
from .forms import ProductForm, CategoryForm


# ====== หน้าหลัก POS (Single Page Application) ======

@login_required
@ensure_csrf_cookie
def pos_view(request):
    """
    View หลักของระบบ POS แบบ Single Page Application
    โหลดข้อมูลสินค้าและหมวดหมู่ทั้งหมดครั้งแรก แล้ว render template หน้า POS
    ต้องล็อกอินก่อนใช้งาน และมีการฝัง CSRF cookie เพื่อใช้กับ AJAX
    """
    # ดึงสินค้าที่ active ทั้งหมด พร้อม join ข้อมูลหมวดหมู่ เรียงตามหมวดหมู่แล้วชื่อสินค้า
    products = Product.objects.filter(is_active=True).select_related('category').order_by('category__name', 'name')
    # ดึงหมวดหมู่ทั้งหมด
    categories = Category.objects.all()
    context = {
        'products': products,
        'categories': categories,
        'user': request.user,  # ส่งข้อมูล user ไปแสดงชื่อผู้ใช้ในหน้า POS
    }
    return render(request, 'pos/index.html', context)


# ====== API Endpoints สำหรับ SPA (ใช้ AJAX) ======

@login_required
def api_product_list(request):
    """
    JSON API: ดึงข้อมูลสินค้าที่ active ทั้งหมด
    ใช้สำหรับ refresh ข้อมูลสินค้าในหน้า POS โดยไม่ต้อง reload หน้า
    คืนค่าเป็น JSON array ของสินค้า
    """
    products = Product.objects.filter(is_active=True).values(
        'id', 'name', 'price', 'stock', 'code', 'category_id', 'image'
    )
    return JsonResponse({'status': 'success', 'products': list(products)})


@login_required
@require_POST
def api_product_create(request):
    """
    JSON API: สร้างสินค้าใหม่
    รับข้อมูลผ่าน POST (รวมถึงไฟล์รูปภาพ) และบันทึกลงฐานข้อมูล
    คืนค่าข้อมูลสินค้าที่สร้างใหม่เป็น JSON เมื่อสำเร็จ
    """
    form = ProductForm(request.POST, request.FILES)
    if form.is_valid():
        product = form.save()
        # คืนค่าข้อมูลสินค้าที่สร้างเพื่ออัปเดต UI ฝั่ง client
        return JsonResponse({
            'status': 'success',
            'product': {
                'id': product.id,
                'name': product.name,
                'price': float(product.price),
                'stock': product.stock,
                'category_id': product.category.id if product.category else None,
                'image_url': product.image.url if product.image else None
            }
        })
    # คืนค่า error พร้อม HTTP 400 เมื่อข้อมูลไม่ถูกต้อง
    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)


@login_required
@require_POST
def api_product_update(request, pk):
    """
    JSON API: แก้ไขข้อมูลสินค้าที่มีอยู่แล้ว
    ค้นหาสินค้าด้วย pk แล้วอัปเดตด้วยข้อมูลใหม่จาก POST
    คืนค่าข้อมูลสินค้าที่อัปเดตแล้วเป็น JSON
    """
    product = get_object_or_404(Product, pk=pk)  # ถ้าไม่พบสินค้าจะคืนค่า 404
    form = ProductForm(request.POST, request.FILES, instance=product)
    if form.is_valid():
        product = form.save()
        return JsonResponse({
            'status': 'success',
             'product': {
                'id': product.id,
                'name': product.name,
                'price': float(product.price),
                'stock': product.stock,
                'category_id': product.category.id if product.category else None,
                'image_url': product.image.url if product.image else None
            }
        })
    return JsonResponse({'status': 'error', 'errors': form.errors}, status=400)


# ====== กระบวนการชำระเงิน (Checkout) ======

@login_required
@require_POST
def api_process_order(request):
    """
    JSON API: ประมวลผลการชำระเงินและสร้างคำสั่งซื้อ
    ขั้นตอน:
    1. รับข้อมูลสินค้า จำนวน วิธีชำระเงิน และส่วนลดจาก request body (JSON)
    2. ใช้ transaction.atomic() เพื่อให้การบันทึกทั้งหมดสำเร็จหรือล้มเหลวพร้อมกัน
    3. สร้าง Order และ OrderItem แต่ละรายการ
    4. ตัดสต็อกสินค้าตามจำนวนที่ขาย
    5. คำนวณยอดรวมสุทธิหลังหักส่วนลด
    """
    try:
        # แปลง JSON body เป็น Python dict
        data = json.loads(request.body)
        items = data.get('items', [])            # รายการสินค้าในตะกร้า
        payment_method = data.get('payment_method', 'CASH')  # วิธีชำระเงิน
        discount = float(data.get('discount', 0))  # ส่วนลด (บาท)

        # ตรวจสอบว่ามีสินค้าในตะกร้าอย่างน้อย 1 รายการ
        if not items:
            return JsonResponse({'status': 'error', 'message': 'No items in order'}, status=400)

        # ใช้ atomic transaction เพื่อป้องกันข้อมูลไม่สมบูรณ์หากเกิดข้อผิดพลาดระหว่างทาง
        with transaction.atomic():
            # สร้างคำสั่งซื้อใหม่ (สถานะ COMPLETED ทันที เนื่องจาก POS ชำระเงินสด)
            order = Order.objects.create(
                payment_method=payment_method,
                status='COMPLETED',
                discount_amount=discount
            )

            total = 0
            for item in items:
                try:
                    product = Product.objects.get(id=item['id'])
                except Product.DoesNotExist:
                    # ข้ามสินค้าที่ไม่พบในระบบ
                    continue

                quantity = int(item['quantity'])
                if quantity <= 0: continue  # ข้ามรายการที่มีจำนวนเป็น 0 หรือติดลบ

                price = product.price  # ใช้ราคาปัจจุบันของสินค้า ณ เวลาขาย
                subtotal = price * quantity

                # สร้างรายการสินค้าในคำสั่งซื้อ (OrderItem)
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    price=price,
                    subtotal=subtotal
                )

                # ====== การจัดการสต็อก: ตัดสต็อกตามจำนวนที่ขาย ======
                product.stock -= quantity
                product.save()

                total += subtotal

            # คำนวณยอดรวมสุทธิ: ไม่ให้ติดลบ (min = 0)
            # Apply Discount to Total
            final_total = max(0, float(total) - discount)
            order.total_amount = final_total
            order.save()

        # คืนค่าสำเร็จพร้อม order_id และยอดรวม
        return JsonResponse({
            'status': 'success',
            'order_id': order.id,
            'total': float(total)
        })
    except Exception as e:
        # จัดการ error ทั่วไป คืนค่าข้อความ error
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


# ====== การจัดการหมวดหมู่สินค้า ======

@login_required
@require_POST
def api_category_create(request):
    """
    JSON API: สร้างหมวดหมู่สินค้าใหม่
    รับชื่อหมวดหมู่ผ่าน POST แล้วบันทึกลงฐานข้อมูล
    """
    name = request.POST.get('name')
    if name:
        category = Category.objects.create(name=name)
        return JsonResponse({
            'status': 'success',
            'category': {'id': category.id, 'name': category.name}
        })
    # กรณีไม่ส่งชื่อมา
    return JsonResponse({'status': 'error', 'message': 'Name is required'}, status=400)


@login_required
@require_POST
def api_category_update(request, pk):
    """
    JSON API: แก้ไขชื่อหมวดหมู่สินค้า
    ค้นหาหมวดหมู่ด้วย pk แล้วอัปเดตชื่อใหม่
    """
    category = get_object_or_404(Category, pk=pk)  # ถ้าไม่พบจะคืนค่า 404
    name = request.POST.get('name')
    if name:
        category.name = name
        category.save()
        return JsonResponse({
            'status': 'success',
            'category': {'id': category.id, 'name': category.name}
        })
    return JsonResponse({'status': 'error', 'message': 'Name is required'}, status=400)


@login_required
@require_POST
def api_category_delete(request, pk):
    """
    JSON API: ลบหมวดหมู่สินค้า
    เมื่อลบหมวดหมู่ สินค้าที่อยู่ในหมวดหมู่นี้จะถูกตั้งค่าเป็น category=NULL
    (ตาม on_delete=SET_NULL ใน Product model)
    """
    category = get_object_or_404(Category, pk=pk)
    category.delete()
    return JsonResponse({'status': 'success'})


# ====== รายงานยอดขายและสต็อก ======

@login_required
def api_sales_report(request):
    """
    JSON API: ดึงข้อมูลรายงานยอดขายและสต็อกสินค้า
    สามารถกรองตามช่วงวันที่ผ่าน query params: start_date และ end_date (รูปแบบ YYYY-MM-DD)
    ถ้าไม่ระบุวันที่จะใช้วันนี้เป็นค่า default
    ข้อมูลที่คืนค่า:
    - ยอดขายรวม, ยอดเงินสด, ยอด QR
    - ส่วนลดรวม
    - มูลค่าสินค้าคงเหลือ
    - รายการสินค้าสต็อกต่ำ (< 10 ชิ้น)
    - รายการคำสั่งซื้อล่าสุด
    - ประสิทธิภาพการขายแยกตามสินค้า (พร้อมคำนวณส่วนลดเฉลี่ย)
    """
    today = timezone.now().date()

    # รับช่วงวันที่จาก query parameters (ค่า default คือวันนี้)
    # Get date range from request (default to today)
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    try:
        if start_date:
            start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            start_date = today

        if end_date:
            end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            end_date = start_date
    except ValueError:
        # ถ้า format วันที่ผิดพลาด ใช้วันนี้แทน
        # Fallback to today if parsing fails
        start_date = today
        end_date = today

    # กรองเฉพาะคำสั่งซื้อที่สถานะ COMPLETED ในช่วงวันที่กำหนด
    # Filter completed orders within range
    # created_at is DateTime, so we filter by date range
    orders_qs = Order.objects.filter(
        status='COMPLETED',
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )

    # คำนวณยอดขายรวมสุทธิ
    total_sales = orders_qs.aggregate(sum=Sum('total_amount'))['sum'] or 0

    # แยกยอดขายตามวิธีชำระเงิน
    # Payment method breakdown
    cash_sales = orders_qs.filter(payment_method='CASH').aggregate(sum=Sum('total_amount'))['sum'] or 0
    qr_sales = orders_qs.filter(payment_method='QR').aggregate(sum=Sum('total_amount'))['sum'] or 0

    # มูลค่าสต็อกสินค้าปัจจุบัน (ราคา × จำนวน)
    # Stock info (Always current)
    stock_value = Product.objects.filter(is_active=True).aggregate(
        val=Sum(F('price') * F('stock'))
    )['val'] or 0

    # รายการสินค้าสต็อกต่ำ (น้อยกว่า 10 ชิ้น) เตือนให้เติมสินค้า
    # Low stock items (< 10)
    low_stock_qs = Product.objects.filter(is_active=True, stock__lt=10)
    low_stock = []
    for p in low_stock_qs:
        low_stock.append({
            'name': p.name,
            'stock': p.stock,
            'image': p.image.url if p.image else None,
            'price': float(p.price)
        })

    # รายการคำสั่งซื้อล่าสุด (สูงสุด 20 รายการ) เรียงจากใหม่ไปเก่า
    # Recent orders (last 5 within filter)
    recent_orders_qs = orders_qs.order_by('-created_at')[:20] # Show more orders if filtering
    recent_orders = []
    for o in recent_orders_qs:
        recent_orders.append({
            'id': o.id,
            'total_amount': float(o.total_amount),
            'payment_method': o.payment_method,
            'created_at': o.created_at
        })

    # ====== คำนวณประสิทธิภาพการขายแยกตามสินค้า ======
    # Product Performance (Detailed)
    # 1. ดึงสินค้า active ทั้งหมด พร้อมข้อมูลหมวดหมู่
    # 1. Get all active products
    all_products = Product.objects.filter(is_active=True).select_related('category')

    # 2. คำนวณสถิติการขาย โดยกระจายส่วนลดตามสัดส่วนยอดขายของแต่ละสินค้า (prorated discount)
    # 2. Calculate sales stats with prorated discount
    # We iterate over orders to distribute discount
    from collections import defaultdict
    product_stats = defaultdict(lambda: {'qty': 0, 'subtotal': 0, 'discount': 0})

    # prefetch_related เพื่อลดจำนวน query ในการดึง items ของแต่ละ order
    orders = orders_qs.prefetch_related('items', 'items__product')

    for order in orders:
        items = order.items.all()
        # คำนวณยอดรวมก่อนส่วนลดของ order นี้
        # Calculate order subtotal sum (pre-discount)
        order_subtotal_sum = sum(item.subtotal for item in items)

        # คำนวณอัตราส่วนของส่วนลดเทียบกับยอดรวม เพื่อกระจายส่วนลดตามสัดส่วน
        discount_ratio = 0
        if order_subtotal_sum > 0:
            discount_ratio = float(order.discount_amount) / float(order_subtotal_sum)

        for item in items:
            # ส่วนลดที่ควรได้รับของสินค้านี้ = subtotal × อัตราส่วนส่วนลด
            item_discount = float(item.subtotal) * discount_ratio
            product_stats[item.product_id]['qty'] += item.quantity
            product_stats[item.product_id]['subtotal'] += float(item.subtotal)
            product_stats[item.product_id]['discount'] += item_discount

    # สร้าง list ประสิทธิภาพการขายแต่ละสินค้า
    product_performance = []
    for p in all_products:
        stat = product_stats[p.id]
        revenue = stat['subtotal']      # ยอดขายรวม (ก่อนส่วนลด)
        discount = stat['discount']     # ส่วนลดที่ได้รับ
        net_sale = revenue - discount   # ยอดขายสุทธิ

        product_performance.append({
            'name': p.name,
            'code': p.code or '-',
            'category': p.category.name if p.category else 'Uncategorized',
            'price': float(p.price),
            'stock': p.stock,
            'sold_qty': stat['qty'],        # จำนวนที่ขายได้
            'gross_revenue': revenue,        # รายได้รวมก่อนส่วนลด
            'discount': discount,            # ส่วนลดที่ให้
            'net_sale': net_sale             # รายได้สุทธิหลังส่วนลด
        })

    # ยอดส่วนลดรวมทั้งหมดในช่วงวันที่กำหนด
    # Discount
    total_discount = orders_qs.aggregate(sum=Sum('discount_amount'))['sum'] or 0

    return JsonResponse({
        'status': 'success',
        'data': {
            'sales_amount': float(total_sales),          # ยอดขายสุทธิรวม
            'cash_sales': float(cash_sales),             # ยอดขายเงินสด
            'qr_sales': float(qr_sales),                 # ยอดขาย QR
            'total_discount': float(total_discount),     # ส่วนลดรวม
            'stock_value': float(stock_value),           # มูลค่าสต็อกปัจจุบัน
            'low_stock': low_stock,                      # สินค้าสต็อกต่ำ
            'recent_orders': recent_orders,              # คำสั่งซื้อล่าสุด
            'product_performance': product_performance,  # ประสิทธิภาพขายแยกสินค้า
            'period': {
                'start': start_date,  # วันเริ่มต้นที่กรอง
                'end': end_date       # วันสิ้นสุดที่กรอง
            }
        }
    })


# ====== Export รายงานยอดขายเป็น CSV ======

@login_required
def export_sales_csv(request):
    """
    Export รายงานยอดขายเป็นไฟล์ CSV
    รองรับการกรองตามช่วงวันที่ผ่าน query params: start_date และ end_date
    ไฟล์ CSV มี BOM (Byte Order Mark) เพื่อให้ Excel เปิดภาษาไทยได้ถูกต้อง
    """
    import csv
    from django.http import HttpResponse

    today = timezone.now().date()
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # แปลงวันที่จาก string เป็น date object
    try:
        if start_date:
            start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            start_date = today
        if end_date:
            end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
        else:
            end_date = start_date
    except ValueError:
        start_date = today
        end_date = today

    # ตั้งค่า response เป็นไฟล์ CSV พร้อมชื่อไฟล์ที่มีช่วงวันที่
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="sales_report_{start_date}_{end_date}.csv"'

    # เพิ่ม BOM เพื่อให้ Excel เปิดไฟล์ UTF-8 ได้ถูกต้อง
    # BOM for Excel to open UTF-8 correctly
    response.write(u'\ufeff'.encode('utf8'))

    writer = csv.writer(response)
    # หัวรายงาน: แสดงช่วงวันที่
    writer.writerow(['Period', f'{start_date} to {end_date}'])
    writer.writerow([])

    # ====== ส่วนสรุปยอดขาย ======
    # Summary
    orders_qs = Order.objects.filter(
        status='COMPLETED',
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    total_sales = orders_qs.aggregate(sum=Sum('total_amount'))['sum'] or 0
    total_discount = orders_qs.aggregate(sum=Sum('discount_amount'))['sum'] or 0
    cash_sales = orders_qs.filter(payment_method='CASH').aggregate(sum=Sum('total_amount'))['sum'] or 0
    qr_sales = orders_qs.filter(payment_method='QR').aggregate(sum=Sum('total_amount'))['sum'] or 0

    # เขียนข้อมูลสรุปลง CSV
    writer.writerow(['Total Sales', total_sales])
    writer.writerow(['Total Discount', total_discount])
    writer.writerow(['Total Cash Get', cash_sales])
    writer.writerow(['QR Sales', qr_sales])
    writer.writerow([])

    # ====== ส่วนรายละเอียดสินค้าแยกตามชนิด ======
    # Product Details
    writer.writerow(['Product Name', 'Code', 'Category', 'Current Price', 'Current Stock', 'Sold Qty', 'Gross Revenue', 'Discount', 'Net Sale'])

    # กระจายส่วนลดตามสัดส่วน (Prorated Discount) เช่นเดียวกับ api_sales_report
    # Prorate discounts
    from collections import defaultdict
    product_stats = defaultdict(lambda: {'qty': 0, 'subtotal': 0, 'discount': 0})

    all_orders = Order.objects.filter(
        status='COMPLETED',
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    ).prefetch_related('items') # Note: items__product prefetched implicitly or can be added if needed, but here we just need item data

    for order in all_orders:
        items = order.items.all()
        # คำนวณยอดก่อนส่วนลดของ order นี้
        order_subtotal_sum = sum(item.subtotal for item in items)

        discount_ratio = 0
        if order_subtotal_sum > 0:
            discount_ratio = float(order.discount_amount) / float(order_subtotal_sum)

        for item in items:
            # คำนวณส่วนลดตามสัดส่วนของสินค้านี้
            item_discount = float(item.subtotal) * discount_ratio
            product_stats[item.product_id]['qty'] += item.quantity
            product_stats[item.product_id]['subtotal'] += float(item.subtotal)
            product_stats[item.product_id]['discount'] += item_discount

    # เขียนข้อมูลสินค้าแต่ละชนิดลง CSV เรียงตามชื่อสินค้า
    products = Product.objects.filter(is_active=True).select_related('category').order_by('name')

    for p in products:
        stat = product_stats[p.id]
        revenue = stat['subtotal']       # ยอดขายรวมก่อนส่วนลด
        discount = stat['discount']      # ส่วนลดที่กระจายมา
        net_sale = revenue - discount    # ยอดขายสุทธิ

        writer.writerow([
            p.name,
            p.code or '-',
            p.category.name if p.category else 'Uncategorized',
            p.price,
            p.stock,
            stat['qty'],
            f"{revenue:.2f}",
            f"{discount:.2f}",
            f"{net_sale:.2f}"
        ])

    return response
