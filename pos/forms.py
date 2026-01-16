from django import forms
from .models import Product

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'code', 'category', 'price', 'stock', 'image', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'shadow-sm focus:ring-primary focus:border-primary block w-full sm:text-sm border-slate-300 rounded-md p-2'}),
            'code': forms.TextInput(attrs={'class': 'shadow-sm focus:ring-primary focus:border-primary block w-full sm:text-sm border-slate-300 rounded-md p-2'}),
            'category': forms.Select(attrs={'class': 'shadow-sm focus:ring-primary focus:border-primary block w-full sm:text-sm border-slate-300 rounded-md p-2'}),
            'price': forms.NumberInput(attrs={'class': 'shadow-sm focus:ring-primary focus:border-primary block w-full sm:text-sm border-slate-300 rounded-md p-2', 'step': '0.01'}),
            'stock': forms.NumberInput(attrs={'class': 'shadow-sm focus:ring-primary focus:border-primary block w-full sm:text-sm border-slate-300 rounded-md p-2'}),
            'image': forms.FileInput(attrs={'class': 'block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-primary hover:file:bg-blue-100'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'focus:ring-primary h-4 w-4 text-primary border-slate-300 rounded'}),
        }
