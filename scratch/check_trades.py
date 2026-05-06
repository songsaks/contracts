import os
import django
import sys

# Set up Django environment
sys.path.append('d:\\DjangoProjects\\contracts')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from stocks.models import TradeOrder

# Get last 5 trades
trades = TradeOrder.objects.all().order_by('-created_at')[:5]

print("Last 5 Trades:")
for t in trades:
    print(f"ID: {t.id} | Symbol: {t.symbol} | Type: {t.order_type} | Vol: {t.volume} | Strategy: {t.strategy} | Date: {t.created_at}")
