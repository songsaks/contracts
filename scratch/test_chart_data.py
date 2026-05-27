import os
import django

import sys
sys.path.append(os.path.abspath('.'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from stocks.views import stock_chart_data
import json

from django.contrib.auth.models import User
rf = RequestFactory()
request = rf.get('/stocks/chart/BTC-USD/data/', {'market': 'crypto', 'period': '1d'})
request.user = User.objects.first()
response = stock_chart_data(request, 'BTC-USD')
print("Status:", response.status_code)
data = json.loads(response.content)
print("Keys:", data.keys())
print("Is Intraday:", data.get('is_intraday'))
for k in ['candles', 'volume', 'rsi', 'dc20_upper', 'dc20_lower', 'dc55_upper', 'dc55_lower', 'ema20', 'ema50', 'ema200']:
    print(f"{k} length:", len(data.get(k, [])))

