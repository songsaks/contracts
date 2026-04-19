import os
import django
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

def check_columns():
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA table_info(ops_weeklygoal)")
        columns = [c[1] for c in cursor.fetchall()]
        print(f"Columns in ops_weeklygoal: {columns}")
        if 'status' in columns:
            print("SUCCESS: 'status' column exists.")
        else:
            print("ERROR: 'status' column is MISSING!")

if __name__ == "__main__":
    check_columns()
