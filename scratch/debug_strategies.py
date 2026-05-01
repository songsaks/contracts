import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from stocks.models import Portfolio
items = Portfolio.objects.all()
print("-" * 30)
for p in items:
    print(f"Symbol: {p.symbol} | Strategy: '{p.strategy}'")
print("-" * 30)
