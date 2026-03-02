from django import forms
from .models import WorkReport, EmployeeSalaryConfig, PayrollStatus

class WorkReportForm(forms.ModelForm):
    class Meta:
        model = WorkReport
        exclude = ['user', 'status', 'admin_remarks', 'created_at', 'updated_at']
        widgets = {
            'month': forms.Select(attrs={'class': 'form-select'}),
            'year': forms.NumberInput(attrs={'class': 'form-control'}),
            'working_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'ot_hours': forms.NumberInput(attrs={'class': 'form-control'}),
            'team_mgmt_fee': forms.NumberInput(attrs={'class': 'form-control'}),
            'professional_fee': forms.NumberInput(attrs={'class': 'form-control'}),
            'commissions': forms.NumberInput(attrs={'class': 'form-control'}),
            'incentives': forms.NumberInput(attrs={'class': 'form-control'}),
            'pb_liva_score': forms.NumberInput(attrs={'class': 'form-control'}),
            'absent_days': forms.NumberInput(attrs={'class': 'form-control'}),
            'absent_deduction_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'advance_pay': forms.NumberInput(attrs={'class': 'form-control'}),
            'savings': forms.NumberInput(attrs={'class': 'form-control'}),
            'lost_equipment_fee': forms.NumberInput(attrs={'class': 'form-control'}),
            'other_deductions': forms.NumberInput(attrs={'class': 'form-control'}),
            'remarks': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class AdminWorkReportForm(forms.ModelForm):
    """HR form: only change status and add remarks. All work data is read-only."""
    class Meta:
        model = WorkReport
        fields = ['status', 'admin_remarks']
        widgets = {
            'status': forms.Select(
                attrs={'class': 'form-select'},
                choices=[
                    (PayrollStatus.APPROVED, '✅ อนุมัติ (Approved)'),
                    (PayrollStatus.REJECTED, '❌ ส่งกลับแก้ไข (Rejected)'),
                ]
            ),
            'admin_remarks': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'หมายเหตุถึงพนักงาน (ถ้ามี)...'
            }),
        }

class EmployeeSalaryConfigForm(forms.ModelForm):
    class Meta:
        model = EmployeeSalaryConfig
        exclude = ['user']
        widgets = {
            'base_salary': forms.NumberInput(attrs={'class': 'form-control'}),
            'ot_rate_per_hour': forms.NumberInput(attrs={'class': 'form-control'}),
            'social_security_rate': forms.NumberInput(attrs={'class': 'form-control'}),
            'social_security_cap': forms.NumberInput(attrs={'class': 'form-control'}),
            'tax_withholding': forms.NumberInput(attrs={'class': 'form-control'}),
            'bank_account_number': forms.TextInput(attrs={'class': 'form-control'}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control'}),
        }
