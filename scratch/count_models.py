import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.apps import apps

stocks_app = apps.get_app_config('stocks')
for model_name, model in stocks_app.models.items():
    count = model.objects.count()
    print(f"Model: {model_name}, Count: {count}")
