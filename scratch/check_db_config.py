import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection
print("DATABASE ENGINE:", connection.settings_dict.get('ENGINE'))
print("DATABASE NAME:", connection.settings_dict.get('NAME'))
print("DATABASE HOST:", connection.settings_dict.get('HOST'))
print("DATABASE PORT:", connection.settings_dict.get('PORT'))
print("DATABASE USER:", connection.settings_dict.get('USER'))
