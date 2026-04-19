from django.contrib import admin
from .models import Department, Employee, WeeklyGoal, DailyProgress

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name',)

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('user', 'department')
    list_filter = ('department',)

@admin.register(WeeklyGoal)
class WeeklyGoalAdmin(admin.ModelAdmin):
    list_display = ('title', 'department', 'target_value', 'unit', 'start_date', 'end_date')
    list_filter = ('department', 'start_date')

@admin.register(DailyProgress)
class DailyProgressAdmin(admin.ModelAdmin):
    list_display = ('goal', 'employee', 'date', 'actual_value', 'created_at')
    list_filter = ('date', 'goal__department')
