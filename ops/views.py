from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from .models import WeeklyGoal, DailyProgress, Department, Employee
from django.utils import timezone
from django.db.models import Sum

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
    # Find users who don't have an employee profile yet
    existing_employee_users = Employee.objects.values_list('user_id', flat=True)
    users = User.objects.exclude(id__in=existing_employee_users)
    
    return render(request, 'ops/management.html', {
        'depts': depts,
        'employees': employees,
        'users': users
    })

@login_required
def dept_create(request):
    if request.method == 'POST' and request.user.is_superuser:
        name = request.POST.get('name')
        if name:
            Department.objects.create(name=name)
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
    from google import genai
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
