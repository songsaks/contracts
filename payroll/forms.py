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
    # Money fields that may have commas from JS formatting
    MONEY_FIELDS  = ['base_salary', 'ot_rate_per_hour', 'social_security_cap', 'tax_withholding']
    PERCENT_FIELDS = ['social_security_rate']

    class Meta:
        model = EmployeeSalaryConfig
        exclude = ['user', 'is_payroll_member']
        widgets = {
            'employee_code':        forms.TextInput(attrs={'class': 'form-control num-input', 'maxlength': 7, 'placeholder': 'เช่น 0000001'}),
            'national_id':          forms.TextInput(attrs={'class': 'form-control', 'maxlength': 13, 'placeholder': 'x-xxxx-xxxxx-xx-x'}),
            'base_salary':          forms.TextInput(attrs={'class': 'form-control money-input', 'data-decimals': '2'}),
            'ot_rate_per_hour':     forms.TextInput(attrs={'class': 'form-control money-input', 'data-decimals': '2'}),
            'use_sso_bracket':      forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'social_security_rate': forms.TextInput(attrs={'class': 'form-control percent-input', 'data-decimals': '2'}),
            'social_security_cap':  forms.TextInput(attrs={'class': 'form-control money-input', 'data-decimals': '2'}),
            'tax_withholding':      forms.TextInput(attrs={'class': 'form-control money-input', 'data-decimals': '2'}),
            'bank_account_number':  forms.TextInput(attrs={'class': 'form-control'}),
            'bank_name':            forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned = super().clean()
        # Strip commas from money/percent fields that JS may have formatted
        for field in self.MONEY_FIELDS + self.PERCENT_FIELDS:
            val = self.data.get(field, '')
            if val:
                self.data = self.data.copy()
                self.data[field] = val.replace(',', '').strip()
        return cleaned
