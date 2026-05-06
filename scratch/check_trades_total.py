import os
import django
import sys

# Set up Django environment
sys.path.append('d:\\DjangoProjects\\contracts')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from stocks.models import TradeOrder

count = TradeOrder.objects.count()
print(f"Total Trades in DB: {count}")

if count > 0:
    trades = TradeOrder.objects.all().order_by('-id')[:10]
    for t in trades:
        print(f"ID: {t.id} | Symbol: {t.symbol} | Type: {t.order_type} | Date: {t.created_at}")
