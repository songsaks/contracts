from django import forms
from decimal import Decimal
from .models import AssetCategory, MarketType


class AddPortfolioForm(forms.Form):
    symbol = forms.CharField(max_length=20, required=True, strip=True)
    name = forms.CharField(max_length=100, required=False, strip=True)
    quantity = forms.DecimalField(max_digits=15, decimal_places=7)
    entry_price = forms.DecimalField(max_digits=15, decimal_places=7)
    category = forms.ChoiceField(choices=AssetCategory.choices)
    market = forms.ChoiceField(choices=MarketType.choices)
    strategy = forms.CharField(max_length=50, required=False, strip=True)
    trail_multiplier = forms.FloatField(required=False, initial=2.5)

    def clean_symbol(self):
        symbol = self.cleaned_data['symbol'].strip().upper()
        if not symbol:
            raise forms.ValidationError("กรุณากรอก Symbol")
        return symbol

    def clean_quantity(self):
        qty = self.cleaned_data.get('quantity')
        if qty is None:
            raise forms.ValidationError("กรุณากรอกจำนวน")
        if qty <= Decimal('0'):
            raise forms.ValidationError("จำนวนต้องมากกว่า 0")
        return qty

    def clean_entry_price(self):
        price = self.cleaned_data.get('entry_price')
        if price is None:
            raise forms.ValidationError("กรุณากรอกราคาทุน")
        if price < Decimal('0'):
            raise forms.ValidationError("ราคาทุนต้องไม่ติดลบ")
        return price


class SellStockForm(forms.Form):
    quantity = forms.DecimalField(max_digits=15, decimal_places=7)
    sell_price = forms.DecimalField(max_digits=15, decimal_places=7)

    def clean_quantity(self):
        qty = self.cleaned_data.get('quantity')
        if qty is None:
            raise forms.ValidationError("กรุณากรอกจำนวน")
        if qty <= Decimal('0'):
            raise forms.ValidationError("จำนวนต้องมากกว่า 0")
        return qty

    def clean_sell_price(self):
        price = self.cleaned_data.get('sell_price')
        if price is None:
            raise forms.ValidationError("กรุณากรอกราคาขาย")
        if price <= Decimal('0'):
            raise forms.ValidationError("ราคาขายต้องมากกว่า 0")
        return price


class AddWatchlistForm(forms.Form):
    symbol = forms.CharField(max_length=20, required=True, strip=True)
    name = forms.CharField(max_length=100, required=False, strip=True)
    category = forms.ChoiceField(choices=AssetCategory.choices)
    market = forms.ChoiceField(choices=MarketType.choices)

    def clean_symbol(self):
        symbol = self.cleaned_data['symbol'].strip().upper()
        if not symbol:
            raise forms.ValidationError("กรุณากรอก Symbol")
        return symbol
