import os
import sys
import django

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'contracts.settings')
django.setup()

from django.core.management import call_command

def update_workflow():
    print("🚀 Starting Server Workflow Update...")
    
    try:
        # 1. Run Migrations (for new Status choices if we were using a list, 
        # but here we use strings so it's mostly database seeding)
        print("📦 Running migrations...")
        call_command('makemigrations', 'pms')
        call_command('migrate')
        
        # 2. Seed Statuses
        print("🌱 Seeding Dynamic Workflows...")
        call_command('seed_statuses')
        
        print("✅ Workflow Update Completed Successfully!")
        
    except Exception as e:
        print(f"❌ Error during update: {e}")
        sys.exit(1)

if __name__ == "__main__":
    update_workflow()
