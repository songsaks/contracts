import datetime
from decimal import Decimal
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Count, Sum, Q
from django.utils import timezone
from .models import RepairItem, Technician, RepairType, RepairJob

def parse_date_safely(date_val, default_date):
    if not date_val:
        return default_date
    if isinstance(date_val, datetime.date):
        return date_val
    if isinstance(date_val, datetime.datetime):
        return date_val.date()
    
    formats = ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d', '%d-%m-%Y']
    for fmt in formats:
        try:
            return datetime.datetime.strptime(str(date_val).strip(), fmt).date()
        except ValueError:
            continue
    return default_date


def send_repair_summary_email(recipient_email, start_date=None, end_date=None, report_type='dashboard', filter_user_id=None):
    """
    สร้างและส่งอีเมลสรุปรายงานการทำงานของระบบแจ้งซ่อมไปยัง recipient_email
    """
    today = timezone.now().date()
    start_date = parse_date_safely(start_date, today.replace(day=1))
    end_date = parse_date_safely(end_date, today)

    range_filter = [
        timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min)),
        timezone.make_aware(datetime.datetime.combine(end_date, datetime.time.max))
    ]


    # ดึงข้อมูล RepairItem ประจำช่วงเวลา
    items_qs = RepairItem.objects.filter(created_at__range=range_filter)
    if filter_user_id:
        items_qs = items_qs.filter(technicians__id=filter_user_id)

    total_items = items_qs.count()
    completed_items = items_qs.filter(status='COMPLETED')
    completed_count = completed_items.count()
    fixing_count = items_qs.filter(status='FIXING').count()
    waiting_count = items_qs.filter(status__in=['WAITING_APPROVAL', 'WAITING']).count()
    outsource_count = items_qs.filter(status='OUTSOURCE').count()
    finished_count = items_qs.filter(status='FINISHED').count()
    cancelled_count = items_qs.filter(status='CANCELLED').count()

    total_income = completed_items.aggregate(total=Sum('final_cost'))['total'] or Decimal('0.00')

    # สรุปตามประเภทงาน
    type_summary = []
    for rt in RepairType.objects.all():
        rt_items = completed_items.filter(job__repair_type=rt)
        c = rt_items.count()
        val = rt_items.aggregate(total=Sum('final_cost'))['total'] or Decimal('0.00')
        if c > 0 or val > 0:
            type_summary.append({
                'name': rt.name,
                'count': c,
                'amount': val,
            })

    # สรุปตามช่างผู้รับผิดชอบ
    tech_summary = []
    technicians = Technician.objects.all()
    if filter_user_id:
        technicians = technicians.filter(id=filter_user_id)

    for tech in technicians:
        tech_completed = tech.repairitem_set.filter(status='COMPLETED', updated_at__range=range_filter)
        t_count = tech_completed.count()
        t_income = tech_completed.aggregate(total=Sum('final_cost'))['total'] or Decimal('0.00')
        t_active = tech.repairitem_set.exclude(status__in=['FINISHED', 'CANCELLED', 'COMPLETED']).count()
        if t_count > 0 or t_active > 0 or t_income > 0:
            tech_summary.append({
                'name': tech.name,
                'active': t_active,
                'completed': t_count,
                'income': t_income,
            })

    # ดึงรายการล่าสุด 30 รายการ
    recent_items = items_qs.select_related('job', 'job__customer', 'device', 'device__brand').prefetch_related('technicians').order_by('-created_at')[:30]

    # สร้าง HTML Email
    subject = f"📊 สรุปรายงานระบบงานซ่อม [{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}]"
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f4f6f9; color: #333; margin: 0; padding: 20px; }}
            .container {{ max-width: 680px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.08); }}
            .header {{ background: linear-gradient(135deg, #4f46e5, #6366f1); color: #ffffff; padding: 25px 30px; text-align: left; }}
            .header h1 {{ margin: 0 0 5px 0; font-size: 22px; font-weight: 700; }}
            .header p {{ margin: 0; font-size: 14px; opacity: 0.9; }}
            .content {{ padding: 25px 30px; }}
            .grid {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 25px; }}
            .card {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 15px; text-align: center; flex: 1; min-width: 120px; }}
            .card-val {{ font-size: 20px; font-weight: 700; color: #1e293b; margin-top: 5px; }}
            .card-val.green {{ color: #10b981; }}
            .card-val.blue {{ color: #3b82f6; }}
            .card-val.orange {{ color: #f97316; }}
            .card-label {{ font-size: 12px; color: #64748b; font-weight: 600; text-transform: uppercase; }}
            .section-title {{ font-size: 16px; font-weight: 700; color: #1e293b; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-top: 25px; margin-bottom: 15px; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 13px; }}
            th {{ background: #f1f5f9; color: #475569; font-weight: 600; text-align: left; padding: 10px; border-bottom: 1px solid #cbd5e1; }}
            td {{ padding: 10px; border-bottom: 1px solid #e2e8f0; color: #334155; }}
            .badge {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
            .badge-success {{ background: #dcfce7; color: #15803d; }}
            .badge-warning {{ background: #fef9c3; color: #a16207; }}
            .badge-info {{ background: #e0f2fe; color: #0369a1; }}
            .footer {{ background: #f8fafc; border-top: 1px solid #e2e8f0; text-align: center; padding: 15px; font-size: 12px; color: #94a3b8; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🛠️ สรุปรายงานผลการทำงานระบบแจ้งซ่อม</h1>
                <p>ประจำวันที่ {start_date.strftime('%d/%m/%Y')} ถึง {end_date.strftime('%d/%m/%Y')}</p>
            </div>
            <div class="content">
                <!-- Summary Cards -->
                <div style="display: table; width: 100%; margin-bottom: 20px;">
                    <div style="display: table-cell; width: 25%; padding: 5px;">
                        <div class="card">
                            <div class="card-label">งานทั้งหมด</div>
                            <div class="card-val blue">{total_items:,}</div>
                        </div>
                    </div>
                    <div style="display: table-cell; width: 25%; padding: 5px;">
                        <div class="card">
                            <div class="card-label">ส่งมอบสำเร็จ</div>
                            <div class="card-val green">{completed_count:,}</div>
                        </div>
                    </div>
                    <div style="display: table-cell; width: 25%; padding: 5px;">
                        <div class="card">
                            <div class="card-label">กำลังซ่อม/รออะไหล่</div>
                            <div class="card-val orange">{fixing_count + waiting_count:,}</div>
                        </div>
                    </div>
                    <div style="display: table-cell; width: 25%; padding: 5px;">
                        <div class="card">
                            <div class="card-label">รายรับรวม (บาท)</div>
                            <div class="card-val green">฿{total_income:,.2f}</div>
                        </div>
                    </div>
                </div>

                <!-- Technician Performance -->
                <div class="section-title">👨‍🔧 ผลงานแยกตามช่างผู้รับผิดชอบ</div>
                <table>
                    <thead>
                        <tr>
                            <th>ชื่อช่าง / ผู้รับผิดชอบ</th>
                            <th style="text-align: center;">งานค้างซ่อม</th>
                            <th style="text-align: center;">ซ่อมเสร็จ/ส่งมอบ</th>
                            <th style="text-align: right;">รายรับสร้างได้</th>
                        </tr>
                    </thead>
                    <tbody>
    """

    for tech in tech_summary:
        html_content += f"""
                        <tr>
                            <td><strong>{tech['name']}</strong></td>
                            <td style="text-align: center;"><span class="badge badge-warning">{tech['active']}</span></td>
                            <td style="text-align: center;"><span class="badge badge-success">{tech['completed']}</span></td>
                            <td style="text-align: right; font-weight: 600; color: #10b981;">฿{tech['income']:,.2f}</td>
                        </tr>
        """

    if not tech_summary:
        html_content += """<tr><td colspan="4" style="text-align:center; color:#94a3b8;">ไม่มีข้อมูลช่างในช่วงเวลานี้</td></tr>"""

    html_content += f"""
                    </tbody>
                </table>

                <!-- Recent Items Table -->
                <div class="section-title">📋 รายการงานซ่อมล่าสุด ({min(len(recent_items), 30)} รายการ)</div>
                <table>
                    <thead>
                        <tr>
                            <th>Tracking ID / อุปกรณ์</th>
                            <th>ลูกค้า</th>
                            <th>ช่าง</th>
                            <th>สถานะ</th>
                            <th style="text-align: right;">ค่าบริการ</th>
                        </tr>
                    </thead>
                    <tbody>
    """

    status_display = dict(RepairItem.STATUS_CHOICES)

    for item in recent_items:
        st_text = status_display.get(item.status, item.status)
        st_class = "badge-info"
        if item.status == 'COMPLETED':
            st_class = "badge-success"
        elif item.status in ['FIXING', 'WAITING_APPROVAL', 'WAITING']:
            st_class = "badge-warning"

        cust_name = item.job.customer.name if (item.job and item.job.customer) else '-'
        tech_names = ", ".join([t.name for t in item.technicians.all()]) if item.technicians.exists() else '-'
        device_name = f"{item.device.brand.name} {item.device.model}" if (item.device and item.device.brand) else (str(item.device) if item.device else '-')
        tracking_id = item.job.tracking_id if (item.job and item.job.tracking_id) else device_name
        cost_str = f"฿{item.final_cost:,.2f}" if item.final_cost is not None else '-'
        issue = (item.issue_description or '')[:30]

        html_content += f"""
                        <tr>
                            <td>
                                <strong>{tracking_id}</strong><br>
                                <span style="font-size: 11px; color: #64748b;">{device_name} ({issue})</span>
                            </td>
                            <td>{cust_name}</td>
                            <td>{tech_names}</td>
                            <td><span class="badge {st_class}">{st_text}</span></td>
                            <td style="text-align: right;">{cost_str}</td>
                        </tr>
        """


    if not recent_items:
        html_content += """<tr><td colspan="5" style="text-align:center; color:#94a3b8;">ไม่มีรายการงานซ่อมในช่วงเวลานี้</td></tr>"""

    html_content += f"""
                    </tbody>
                </table>
            </div>
            <div class="footer">
                <p>รายงานนี้นำส่งอัตโนมัติจากระบบ <strong>Contracts / Repairs System</strong> (9COM Cloud)</p>
                <p>หากมีข้อสงสัยเพิ่มเติม โปรดติดต่อผู้ดูแลระบบ</p>
            </div>
        </div>
    </body>
    </html>
    """

    text_content = f"สรุปรายงานระบบงานซ่อม ประจำวันที่ {start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}\n" \
                   f"จำนวนงานทั้งหมด: {total_items}\n" \
                   f"ส่งมอบสำเร็จ: {completed_count}\n" \
                   f"รายรับรวม: {total_income:,.2f} บาท\n"

    import os
    from dotenv import load_dotenv
    load_dotenv(override=True)

    email_user = (os.getenv('EMAIL_HOST_USER') or getattr(settings, 'EMAIL_HOST_USER', '') or '').strip()
    email_pass = (os.getenv('EMAIL_HOST_PASSWORD') or getattr(settings, 'EMAIL_HOST_PASSWORD', '') or '').strip()
    from_email = (os.getenv('DEFAULT_FROM_EMAIL') or getattr(settings, 'DEFAULT_FROM_EMAIL', '') or email_user or 'noreply@9com.cloud').strip()

    if not email_user or not email_pass:
        return False, "ยังไม่ได้ตั้งค่าบัญชีอีเมลฝั่งส่งในไฟล์ .env (โปรดใส่ EMAIL_HOST_USER และ EMAIL_HOST_PASSWORD แล้ว Restart เซิร์ฟเวอร์)"


    # ส่งอีเมล
    msg = EmailMultiAlternatives(subject, text_content, from_email, [recipient_email])
    msg.attach_alternative(html_content, "text/html")
    
    try:
        msg.send(fail_silently=False)
        return True, f"ส่งอีเมลสรุปรายงานไปยัง {recipient_email} สำเร็จแล้ว!"
    except Exception as e:
        error_msg = str(e)
        if "AuthenticationRequired" in error_msg or "Please log in" in error_msg or "Username and Password not set" in error_msg or "535" in error_msg:
            return False, f"ไม่สามารถส่งผ่าน SMTP ได้เนื่องจาก App Password ไม่ถูกต้องหรือยังไม่ได้ตั้งค่า ({error_msg})"
        return False, f"เกิดข้อผิดพลาดในการส่งอีเมล: {error_msg}"

