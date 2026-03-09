import os
import sys
import django

# Setup Django Environment — module name must match manage.py
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Add project root to sys.path so Django can find config.settings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

django.setup()

from django.core.management import call_command

def update_workflow():
    print("🚀 Starting Server Workflow Update...")
    
    try:
        # 1. Run Migrations
        print("📦 Running migrations...")
        call_command('makemigrations', 'pms', '--no-input')
        call_command('migrate', '--no-input')
        
        # 2. Seed Statuses
        print("🌱 Seeding Dynamic Workflows...")
        call_command('seed_statuses')
        
        print("✅ Workflow Update Completed Successfully!")
        
    except Exception as e:
        print(f"❌ Error during update: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    update_workflow()
