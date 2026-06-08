import os
import django
from django.test import Client

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

client = Client(HTTP_HOST='127.0.0.1')

from django.contrib.auth.models import User
user = User.objects.filter(is_superuser=True).first() or User.objects.first()
client.force_login(user)

print("--- Calling AI Analyze for EPG ---")
import json
payload = {
    'market': 'SET',
    'price': '5.60',
    'trend': 'Stage 2 (Broke)',
    'signals': [{'type': 'BUY_DC10'}],
    'force_refresh': True,
    'active_indicators_data': 'EMA(9, 20, 50, 200), MACD, RSI, ITL'
}

response = client.post('/stocks/chart/EPG/ai_analyze/', data=json.dumps(payload), content_type='application/json')
print('Status Code:', response.status_code)
res_data = response.json()
print("Result:\n", res_data.get('result', 'No result found'))
