import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from stocks.models import Portfolio, MorningBriefing

User = get_user_model()
print("--- ALL USERS ---")
for u in User.objects.all():
    print(f"ID: {u.id}, Username: {u.username}, Email: {u.email}")

print("\n--- ALL PORTFOLIOS ---")
for p in Portfolio.objects.all():
    print(f"User: {p.user.username if p.user else 'None'}, Symbol: {p.symbol}, Qty: {p.quantity}, Entry: {p.entry_price}")
