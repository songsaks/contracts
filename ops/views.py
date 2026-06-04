import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import (
    ActionTask,
    DailyProgress,
    Department,
    Employee,
    Meeting,
    MeetingIdea,
    MeetingParticipant,
    WeeklyGoal,
    AICoworkerLog,
)


@login_required
def dashboard(request):
    is_admin = request.user.is_superuser
    today = timezone.now().date()
    
    if is_admin:
        # Admin: See everything
        goals = WeeklyGoal.objects.filter(end_date__gte=today).order_by('department')
        depts = Department.objects.all()
        return render(request, 'ops/admin_dashboard.html', {
            'goals': goals,
            'depts': depts
        })
    else:
        # Employee: See own department goals
        employee = getattr(request.user, 'employee_profile', None)
        if not employee:
            return render(request, 'ops/no_profile.html')
            
        goals = WeeklyGoal.objects.filter(department=employee.department, end_date__gte=today)
        return render(request, 'ops/employee_dashboard.html', {
            'goals': goals,
            'employee': employee
        })

@login_required
def report_progress(request, goal_id):
    goal = get_object_or_404(WeeklyGoal, id=goal_id)
    if request.method == 'POST':
        actual = request.POST.get('actual_value')
        note = request.POST.get('note')
        image = request.FILES.get('image')
        
        DailyProgress.objects.create(
            goal=goal,
            employee=request.user,
            actual_value=actual,
            note=note,
            image=image,
            date=timezone.now().date()
        )
        return redirect('ops:dashboard')
    
    return render(request, 'ops/report_form.html', {'goal': goal})

@login_required
def weekly_report(request):
    # Summary logic for Friday/Saturday assessment
    today = timezone.now().date()
    # Find active goals for the current week
    goals = WeeklyGoal.objects.filter(end_date__gte=today)
    
    summary_data = []
    for goal in goals:
        summary_data.append({
            'goal': goal,
            'total_actual': goal.total_actual,
            'success_rate': goal.success_percentage,
            'obstacles': goal.daily_progresses.exclude(note='').values_list('note', flat=True)
        })
        
    return render(request, 'ops/weekly_report.html', {'summary': summary_data})

@login_required
def goal_create(request):
    if not request.user.is_superuser:
        return redirect('ops:dashboard')
        
    if request.method == 'POST':
        title = request.POST.get('title')
        dept_id = request.POST.get('department')
        unit = request.POST.get('unit')
        target = request.POST.get('target_value')
        start = request.POST.get('start_date')
        end = request.POST.get('end_date')
        desc = request.POST.get('description')
        
        if title and dept_id:
            dept = Department.objects.get(id=dept_id)
            WeeklyGoal.objects.create(
                title=title, 
                department=dept, 
                unit=unit, 
                target_value=target,
                start_date=start,
                end_date=end,
                description=desc
            )
            return redirect('ops:dashboard')
            
    depts = Department.objects.all()
    return render(request, 'ops/goal_form.html', {'depts': depts})

@login_required
def goal_delete(request, goal_id):
    if request.user.is_superuser:
        goal = get_object_or_404(WeeklyGoal, id=goal_id)
        goal.delete()
    return redirect('ops:dashboard')

@login_required
def management_view(request):
    if not request.user.is_superuser:
        return redirect('ops:dashboard')
    
    depts = Department.objects.all()
    employees = Employee.objects.all()
    existing_employee_users = Employee.objects.values_list('user_id', flat=True)
    users = User.objects.exclude(id__in=existing_employee_users)
    all_users = User.objects.all().order_by('username')
    
    return render(request, 'ops/management.html', {
        'depts': depts,
        'employees': employees,
        'users': users,
        'all_users': all_users
    })

@login_required
def dept_create(request):
    if request.method == 'POST' and request.user.is_superuser:
        name = request.POST.get('name')
        if name:
            Department.objects.create(name=name)
        messages.success(request, f"สร้างฝ่าย {name} สำเร็จแล้ว")
    return redirect('ops:management')

@login_required
def dept_update(request, dept_id):
    if request.method == 'POST' and request.user.is_superuser:
        dept = get_object_or_404(Department, id=dept_id)
        name = request.POST.get('name')
        if name:
            old_name = dept.name
            dept.name = name
            dept.save()
            messages.success(request, f"เปลี่ยนชื่อฝ่ายจาก {old_name} เป็น {name} สำเร็จ")
    return redirect('ops:management')

@login_required
def dept_delete(request, dept_id):
    if request.user.is_superuser:
        dept = get_object_or_404(Department, id=dept_id)
        emp_count = dept.employees.count()
        if emp_count > 0:
            messages.error(request, f"ไม่สามารถลบฝ่าย {dept.name} ได้เนื่องจากยังมีสมาชิก {emp_count} คน กรุณาย้ายสมาชิกออกก่อน")
        else:
            dept.delete()
            messages.success(request, f"ลบฝ่ายสำเร็จแล้ว")
    return redirect('ops:management')

@login_required
def bulk_update_members(request, dept_id):
    if request.method == 'POST' and request.user.is_superuser:
        dept = get_object_or_404(Department, id=dept_id)
        user_ids = request.POST.getlist('user_ids') # IDs of users selected for THIS department
        
        # 1. Any user who is currently in this department but NOT in the selected list
        # should have their department set to None.
        Employee.objects.filter(department=dept).exclude(user_id__in=user_ids).update(department=None)
        
        # 2. For all selected users, update or create their profile to be in THIS department
        selected_users = User.objects.filter(id__in=user_ids)
        for user in selected_users:
            Employee.objects.update_or_create(user=user, defaults={'department': dept})
            
        messages.success(request, f"จัดการสมาชิกฝ่าย {dept.name} เรียบร้อยแล้ว (มีสมาชิกทั้งหมด {selected_users.count()} คน)")
    return redirect('ops:management')

@login_required
def employee_create(request):
    if request.method == 'POST' and request.user.is_superuser:
        user_id = request.POST.get('user_id')
        dept_id = request.POST.get('dept_id')
        if user_id and dept_id:
            user = User.objects.get(id=user_id)
            dept = Department.objects.get(id=dept_id)
            Employee.objects.update_or_create(user=user, defaults={'department': dept})
    return redirect('ops:management')

@login_required
def ai_analysis(request):
    import google.genai as genai
    from django.conf import settings
    
    today = timezone.now().date()
    goals = WeeklyGoal.objects.filter(end_date__gte=today)
    
    # Bundle data for AI
    data_context = "สรุปอุปสรรคการทำงานรายฝ่ายสัปดาห์นี้:\n"
    for goal in goals:
        notes = goal.daily_progresses.exclude(note='').values_list('note', flat=True)
        if notes:
            data_context += f"- ฝ่าย {goal.department.name} (เป้าหมาย: {goal.title}):\n"
            data_context += "  อุปสรรคที่พบ: " + " | ".join(notes) + "\n"

    prompt = f"""
    คุณเป็น 'Senior Operations Manager' และ 'AI Business Analyst' 
    นี่คือข้อมูลอุปสรรคที่พนักงานคีย์เข้ามาในระบบ Tracking รายวัน:
    ---
    {data_context}
    ---
    ช่วยวิเคราะห์ปัญหาดังนี้:
    1. Root Cause: อะไรคือสาเหตุที่แท้จริงของความล่าช้าในแต่ละฝ่าย?
    2. Pattern Recognition: มีปัญหาไหนที่เป็นปัญหาซ้ำซ้อนหรือเกี่ยวเนื่องกันระหว่างฝ่ายไหม?
    3. Action Plan: ข้อเสนอแนะ 3 ข้อสั้นๆ สำหรับการประชุมเช้าวันจันทร์หน้าเพื่อแก้ปัญหาเหล่านี้
    ขอคำตอบที่กระชับ ตรงประเด็น และเป็นประโยชน์ต่อผู้บริหาร
    """

    api_key = getattr(settings, "GEMINI_API_KEY", None)
    if not api_key:
        return render(request, 'ops/ai_result.html', {'error': "กรุณาตั้งค่า GEMINI_API_KEY ในระบบ"})

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        analysis = response.text
    except Exception as e:
        analysis = f"เกิดข้อผิดพลาดในการติดต่อ AI: {str(e)}"

    return render(request, 'ops/ai_result.html', {
        'analysis': analysis,
        'data_context': data_context
    })

# ====== Scheduler Views ======

@login_required
def scheduler_view(request):
    """แสดงหน้าปฏิทินวางแผนงาน"""
    departments = Department.objects.all()
    return render(request, 'ops/scheduler.html', {
        'departments': departments,
    })

@login_required
def scheduler_data(request):
    """ส่งข้อมูลเป้าหมายรายสัปดาห์ในรูปแบบ JSON สำหรับ FullCalendar"""
    goals = WeeklyGoal.objects.all()
    events = []
    
    # กำหนดสีตามฝ่าย (เพื่อให้ดูง่ายในปฏิทิน)
    color_map = {
        'Sales': '#3b82f6',      # Blue
        'Technician': '#f59e0b', # Amber
        'Warehouse': '#10b981',  # Emerald
        'Social Media': '#ec4899' # Pink
    }
    
    for goal in goals:
        # คำนวณสี
        bg_color = color_map.get(goal.department.name, '#6366f1')
        
        events.append({
            'id': goal.id,
            'title': f"[{goal.department.name}] {goal.title}",
            'start': goal.start_date.isoformat(),
            'end': (goal.end_date + timezone.timedelta(days=1)).isoformat(), # FullCalendar end is exclusive
            'backgroundColor': bg_color,
            'borderColor': bg_color,
            'extendedProps': {
                'department': goal.department.name,
                'target': f"{goal.target_value} {goal.unit}",
                'progress': f"{goal.success_percentage}%"
            }
        })
    
    return JsonResponse(events, safe=False)

# ====== Kanban Views ======

@login_required
def kanban_view(request):
    """แสดงบอร์ดคุมสถานะงาน (Kanban)"""
    goals = WeeklyGoal.objects.all().order_by('status', '-created_at')
    
    # จัดกลุ่มเป้าหมายตามสถานะ
    todo = goals.filter(status='todo')
    doing = goals.filter(status='doing')
    done = goals.filter(status='done')
    blocked = goals.filter(status='blocked')
    
    return render(request, 'ops/kanban.html', {
        'todo': todo,
        'doing': doing,
        'done': done,
        'blocked': blocked,
    })

@login_required
def update_goal_status(request):
    """API สำหรับอัปเดตสถานะเป้าหมายเมื่อลากการ์ดมาวาง (AJAX)"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            goal_id = data.get('goal_id')
            new_status = data.get('status')
            
            goal = WeeklyGoal.objects.get(id=goal_id)
            goal.status = new_status
            goal.save()
            
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)

# --- Meeting & Idea Management Views ---

@login_required
def meeting_list(request):
    meetings = Meeting.objects.all().order_by('-date', '-start_time')
    return render(request, 'ops/meeting_list.html', {'meetings': meetings})

@login_required
def meeting_create(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        agenda = request.POST.get('agenda')
        date = request.POST.get('date')
        start_time = request.POST.get('start_time')
        location = request.POST.get('location')
        participant_ids = request.POST.getlist('participants')
        
        meeting = Meeting.objects.create(
            title=title,
            agenda=agenda,
            date=date,
            start_time=start_time,
            location=location,
            organizer=request.user
        )
        
        for p_id in participant_ids:
            user = User.objects.get(id=p_id)
            MeetingParticipant.objects.create(meeting=meeting, user=user)
            
        messages.success(request, f"นัดหมายการประชุม {title} สำเร็จ")
        return redirect('ops:meeting_list')
        
    users = User.objects.all().order_by('username')
    return render(request, 'ops/meeting_form.html', {'users': users})

@login_required
def meeting_detail(request, meeting_id):
    meeting = get_object_or_404(Meeting, id=meeting_id)
    ideas = meeting.ideas.all().order_by('-total_score')
    return render(request, 'ops/meeting_detail.html', {
        'meeting': meeting,
        'ideas': ideas
    })

@login_required
def meeting_record(request, meeting_id):
    """บันทึกมติที่ประชุมแบบ Real-time (AJAX/POST)"""
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if request.method == 'POST':
        minutes = request.POST.get('minutes')
        status = request.POST.get('status')
        if minutes is not None:
            meeting.minutes = minutes
        if status:
            meeting.status = status
        meeting.save()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)

@login_required
def idea_add(request, meeting_id):
    """พนักงานเสนอไอเดียในที่ประชุม"""
    meeting = get_object_or_404(Meeting, id=meeting_id)
    if request.method == 'POST':
        title = request.POST.get('title')
        desc = request.POST.get('description')
        MeetingIdea.objects.create(
            meeting=meeting,
            proposer=request.user,
            title=title,
            description=desc
        )
        messages.success(request, "เสนอไอเดียเรียบร้อยแล้ว")
        return redirect('ops:meeting_detail', meeting_id=meeting_id)
    return render(request, 'ops/idea_form.html', {'meeting': meeting})

@login_required
def idea_list(request):
    ideas = MeetingIdea.objects.all().order_by('-created_at')
    return render(request, 'ops/idea_list.html', {'ideas': ideas})

@login_required
def idea_score(request, idea_id):
    """ระบบ Scoring ไอเดีย"""
    idea = get_object_or_404(MeetingIdea, id=idea_id)
    if request.method == 'POST':
        idea.impact_score = int(request.POST.get('impact_score', 0))
        idea.feasibility_score = int(request.POST.get('feasibility_score', 0))
        idea.status = 'under_review'
        idea.save()
        messages.success(request, f"บันทึกคะแนนไอเดีย {idea.title} เรียบร้อย")
        return redirect('ops:meeting_detail', meeting_id=idea.meeting.id)
    return render(request, 'ops/idea_score_form.html', {'idea': idea})

@login_required
def idea_approve(request, idea_id):
    """อนุมัติไอเดียและสร้าง ActionTask อัตโนมัติ"""
    idea = get_object_or_404(MeetingIdea, id=idea_id)
    if not request.user.is_superuser:
        return redirect('ops:dashboard')
        
    if request.method == 'POST':
        idea.status = 'approved'
        idea.approved_by = request.user
        idea.save()
        
        # สร้าง ActionTask อัตโนมัติ
        ActionTask.objects.get_or_create(
            idea=idea,
            defaults={
                'title': f"[Project] {idea.title}",
                'assigned_to': idea.proposer,
                'start_date': timezone.now().date(),
                'due_date': timezone.now().date() + timezone.timedelta(days=30),
                'status': 'todo'
            }
        )
        messages.success(request, f"อนุมัติไอเดียและสร้างโครงการเรียบร้อยแล้ว")
        return redirect('ops:task_list')
    return render(request, 'ops/idea_approve_confirm.html', {'idea': idea})

@login_required
def task_list(request):
    tasks = ActionTask.objects.all().order_by('-created_at')
    return render(request, 'ops/task_list.html', {'tasks': tasks})

@login_required
def task_gantt(request):
    """Gantt Chart สำหรับติดตามงาน"""
    tasks = ActionTask.objects.all()
    return render(request, 'ops/task_gantt.html', {'tasks': tasks})

@login_required
def task_kanban(request):
    """Kanban Board สำหรับจัดการงานจากไอเดีย"""
    tasks = ActionTask.objects.all()
    todo = tasks.filter(status='todo')
    doing = tasks.filter(status='doing')
    done = tasks.filter(status='done')
    blocked = tasks.filter(status='blocked')
    return render(request, 'ops/task_kanban.html', {
        'todo': todo,
        'doing': doing,
        'done': done,
        'blocked': blocked
    })


# ====== AI Co-workers Views ======

@login_required
def coworker_hub(request):
    """ศูนย์ปฏิบัติการเพื่อนร่วมงาน AI"""
    logs = AICoworkerLog.objects.filter(user=request.user).order_by('-created_at')[:15]
    all_logs = AICoworkerLog.objects.all().order_by('-created_at')[:30] # สำหรับประวัติทั้งหมด
    
    # สถิติง่ายๆ แสดงในแดชบอร์ด
    goals_count = WeeklyGoal.objects.count()
    tasks_count = ActionTask.objects.count()
    
    return render(request, 'ops/coworker_hub.html', {
        'logs': logs,
        'all_logs': all_logs,
        'goals_count': goals_count,
        'tasks_count': tasks_count,
    })


@login_required
def coworker_history_detail(request, log_id):
    """ดึงข้อมูลรายละเอียดและผลลัพธ์ประวัติการรันในอดีต (AJAX)"""
    log = get_object_or_404(AICoworkerLog, id=log_id)
    return JsonResponse({
        'id': log.id,
        'agent_type': log.agent_type,
        'agent_display': log.get_agent_type_display(),
        'input_data': log.input_data,
        'output_data': log.output_data,
        'created_at': log.created_at.strftime('%d/%m/%Y %H:%M'),
        'user': log.user.username
    })


@login_required
def execute_coworker(request):
    """ส่งคำสั่งให้เอเจนต์ AI เพื่อนร่วมงานประมวลผลงานแบบหลายขั้นตอน (AJAX)"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Method not allowed'}, status=405)
        
    try:
        import os
        import google.genai as genai
        from google.genai import types
        from django.conf import settings
        
        # ดึง API Key
        api_key = getattr(settings, "GEMINI_API_KEY", os.environ.get('GEMINI_API_KEY', None))
        if not api_key:
            return JsonResponse({
                'status': 'error', 
                'message': 'กรุณาตั้งค่า GEMINI_API_KEY ในระบบก่อนใช้งาน'
            }, status=400)
            
        data = json.loads(request.body)
        agent_type = data.get('agent_type')
        input_text = data.get('input_text', '').strip()
        
        if agent_type not in ['marketing', 'sales', 'executive']:
            return JsonResponse({'status': 'error', 'message': 'ระบุประเภทเอเจนต์ไม่ถูกต้อง'}, status=400)
            
        if agent_type != 'executive' and not input_text:
            return JsonResponse({'status': 'error', 'message': 'กรุณากรอกข้อมูลนำเข้าสำหรับเอเจนต์'}, status=400)
            
        client = genai.Client(api_key=api_key)
        
        # 1. จัดเตรียม System Instruction และ Prompt ตามเอเจนต์
        if agent_type == 'marketing':
            system_instruction = (
                "คุณคือ 'Marketing Automation Agent' เพื่อนร่วมงาน AI ผู้เชี่ยวชาญด้านการวางแผนการตลาดดิจิทัลและสร้างสรรค์คอนเทนต์.\n"
                "คุณมีหน้าที่ทำงาน 3 ขั้นตอนดังนี้:\n"
                "1. วางแผน Content Plan สำหรับ 1 เดือน (4 สัปดาห์ สัปดาห์ละ 2 โพสต์ รวม 8 โพสต์) สำหรับหัวข้อหรือแคมเปญที่ได้รับ โดยแสดงรายละเอียดในแต่ละโพสต์\n"
                "2. วิเคราะห์ช่องทางการโปรโมทและกลยุทธ์เพื่อให้แคมเปญนี้มีประสิทธิภาพสูงสุด (Performance Analysis)\n"
                "3. ร่างรายงานสรุปแคมเปญและตารางเวลาสำหรับส่งต่อให้ผู้จัดการฝ่ายการตลาด (Manager Report)\n\n"
                "โปรดตอบกลับเป็นข้อมูลรูปแบบ JSON เท่านั้น ห้ามใส่ข้อความนอก JSON ห้ามมี markdown wrap เช่น ```json ... ``` โดยตรงในผลลัพธ์ (หรือถ้ามี ต้องเป็น JSON ที่สมบูรณ์แบบ)\n"
                "โครงสร้าง JSON ต้องประกอบด้วย key ดังนี้:\n"
                "- 'content_plan': โครงสร้างเนื้อหาแผนงานรายสัปดาห์ (สัปดาห์ที่ 1-4, หัวข้อโพสต์, แคปชั่น/คำบรรยาย, แฮชแท็ก, ไอเดียภาพประกอบ) ในรูปแบบ Markdown หรือ HTML\n"
                "- 'performance_analysis': สรุปกลยุทธ์การวิเคราะห์ช่องทางการตลาดที่คุ้มค่าและแนะนำการวัดผลการเข้าถึง\n"
                "- 'manager_report': ร่างจดหมายหรือบันทึกข้อความเพื่อขออนุมัติแคมเปญการตลาดนี้ต่อผู้จัดการ\n\n"
                "ตอบเป็นภาษาไทยทั้งหมด"
            )
            prompt = f"หัวข้อแคมเปญการตลาด: {input_text}"
            
        elif agent_type == 'sales':
            system_instruction = (
                "คุณคือ 'Sales Intelligence Agent' เพื่อนร่วมงาน AI ด้านการขายและจัดการข้อมูลลูกค้า.\n"
                "คุณมีหน้าที่ทำงาน 3 ขั้นตอนดังนี้:\n"
                "1. อ่านสกัดข้อมูลและประเมิน Lead (ชื่อลูกค้า, ข้อมูลติดต่อ, สินค้าที่สนใจ, ระดับความเร่งด่วน [High/Medium/Low], งบประมาณโดยประมาณ) จากข้อความดิบที่ได้รับ\n"
                "2. แปลงข้อมูลลงตารางวิเคราะห์เพื่อเข้าแดชบอร์ด\n"
                "3. ร่างข้อความตอบกลับเพื่อส่งให้ลูกค้า (Professional Draft Reply) ทั้งในภาษาไทยและภาษาอังกฤษ\n\n"
                "โปรดตอบกลับเป็นข้อมูลรูปแบบ JSON เท่านั้น\n"
                "โครงสร้าง JSON ต้องประกอบด้วย key ดังนี้:\n"
                "- 'lead_summary': สรุปข้อมูลที่ได้ในรูปแบบตารางสวยงาม (HTML หรือ Markdown)\n"
                "- 'dashboard_data': ออบเจกต์ JSON ย่อยที่มีฟิลด์ (customer_name, contact, interest, urgency, estimated_value)\n"
                "- 'draft_reply': ข้อความคำตอบของแอดมินหรือเซลส์ที่สุภาพ เป็นมืออาชีพ พร้อมส่ง\n\n"
                "ตอบเป็นภาษาไทยในส่วนสรุปและวิเคราะห์ และแสดงร่างอีเมลอย่างเป็นทางการ"
            )
            prompt = f"ข้อความแชตหรืออีเมลดิบของลูกค้า:\n{input_text}"
            
        elif agent_type == 'executive':
            # ดึงข้อมูลจากฐานข้อมูลของสัปดาห์นี้
            today = timezone.now().date()
            start_of_week = today - timezone.timedelta(days=today.weekday())
            
            goals = WeeklyGoal.objects.filter(end_date__gte=start_of_week)
            tasks = ActionTask.objects.filter(due_date__gte=start_of_week)
            progress_entries = DailyProgress.objects.filter(date__gte=start_of_week)
            
            # รวมบริบทข้อมูล
            context_data = "ข้อมูลปฏิบัติงานจริงสัปดาห์นี้:\n"
            context_data += "--- เป้าหมายประจำสัปดาห์ (Weekly Goals) ---\n"
            for g in goals:
                context_data += f"- [{g.department.name}] {g.title} | สถานะ: {g.get_status_display()} | เป้าหมาย: {g.target_value} {g.unit} | ทำได้จริง: {g.total_actual} {g.unit} (สำเร็จ {g.success_percentage:.1f}%)\n"
                
            context_data += "\n--- ปัญหาอุปสรรครายวัน (Obstacles) ---\n"
            obstacles = progress_entries.exclude(note='').values_list('goal__department__name', 'goal__title', 'employee__username', 'note')
            for dept, goal_title, emp, note in obstacles:
                context_data += f"- ฝ่าย: {dept} | งาน: {goal_title} | บันทึกโดย {emp}: {note}\n"
                
            context_data += "\n--- งานโครงการย่อย (Action Tasks) ---\n"
            for t in tasks:
                context_data += f"- [{t.department.name if t.department else 'ไม่มีฝ่าย'}] {t.title} | ผู้รับผิดชอบ: {t.assigned_to.username if t.assigned_to else 'ยังไม่มอบหมาย'} | สถานะ: {t.get_status_display()} | คืบหน้า: {t.progress_pct}%\n"

            system_instruction = (
                "คุณคือ 'Executive Reporting Agent' เพื่อนร่วมงาน AI ฝ่ายบริหารจัดการรายงานระดับสูง.\n"
                "คุณมีหน้าที่ทำงาน 3 ขั้นตอนดังนี้:\n"
                "1. วิเคราะห์ข้อมูลผลสัมฤทธิ์ สถิติตัวเลข ปัญหาอุปสรรครายวัน และสถานะโครงการทั้งหมดจากบริบทที่ได้รับในสัปดาห์นี้\n"
                "2. จัดทำรายงานสรุปประจำสัปดาห์ของบริษัท (Executive Weekly Report) โดยวิเคราะห์เปรียบเทียบจุดเด่น คอขวด และข้อเสนอแนะในการปรับปรุง\n"
                "3. ร่างข้อความสั้นกระชับพร้อม Emoji สำหรับแชร์ใน Slack ทีมบริหาร และร่างอีเมลสรุปแบบเป็นทางการส่งคณะกรรมการบริหาร\n\n"
                "โปรดตอบกลับเป็นข้อมูลรูปแบบ JSON เท่านั้น\n"
                "โครงสร้าง JSON ต้องประกอบด้วย key ดังนี้:\n"
                "- 'executive_summary': บทวิเคราะห์สรุปผลงานระดับผู้บริหารในรูปแบบ Markdown\n"
                "- 'stats_grid': ข้อมูลสถิติเชิงปริมาณ (เป้าหมายทั้งหมด, เป้าหมายที่เสร็จสิ้น, เป้าหมายที่ติดขัด/Blocked, อัตราความสำเร็จเฉลี่ยในสัปดาห์นี้)\n"
                "- 'slack_draft': ร่างข้อความสั้นพร้อม Emoji สำหรับแชร์แจ้งข่าวในช่อง Slack ของบริษัท\n"
                "- 'email_draft': ร่างอีเมลสรุปสัปดาห์อย่างเป็นทางการ\n\n"
                "ตอบเป็นภาษาไทยทั้งหมด"
            )
            prompt = f"ข้อมูลดิบปฏิบัติงานจริงของสัปดาห์นี้:\n{context_data}"

        # เรียกใช้โมเดล Gemini API
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                system_instruction=system_instruction,
                temperature=0.2
            )
        )
        
        # แกะแปลงข้อมูล JSON
        text_cleaned = response.text.strip()
        if text_cleaned.startswith("```json"):
            text_cleaned = text_cleaned.replace("```json", "", 1)
        if text_cleaned.endswith("```"):
            text_cleaned = text_cleaned[:-3].strip()
        text_cleaned = text_cleaned.strip()
            
        result_json = json.loads(text_cleaned)
            
        # บันทึกข้อมูลลงฐานข้อมูล
        log = AICoworkerLog.objects.create(
            agent_type=agent_type,
            user=request.user,
            input_data=input_text if agent_type != 'executive' else "ออโต้สรุปข้อมูลระบบปฏิบัติการประจำสัปดาห์",
            output_data=result_json
        )
        
        return JsonResponse({
            'status': 'success',
            'log_id': log.id,
            'result': result_json
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'status': 'error', 
            'message': f"เกิดข้อผิดพลาดในการประมวลผล: {str(e)}"
        }, status=500)

