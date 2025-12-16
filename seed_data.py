import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from rentals.models import Tenant, Asset

def seed():
    # Create Tenants
    if not Tenant.objects.exists():
        Tenant.objects.create(
            agency_name='Acme Construction Co.',
            contact_person='John Doe',
            email='john@acme.com',
            phone='081-234-5678',
            document_id='TAX12345678',
            address='123 Industrial Estate, Bangkok'
        )
        Tenant.objects.create(
            agency_name='BuildIt Fast Ltd.',
            contact_person='Jane Smith',
            email='jane@buildit.com',
            phone='089-876-5432',
            document_id='TAX87654321',
            address='456 Rama 9 Road, Bangkok'
        )
        print("Created 2 tenants.")
    else:
        print("Tenants already exist.")

    # Create Assets
    if not Asset.objects.exists():
        Asset.objects.create(name='Heavy Excavator X200', description='20-ton excavator', monthly_rate=Decimal('15000.00'), status='AVAILABLE')
        Asset.objects.create(name='Bulldozer D5', description='Medium bulldozer', monthly_rate=Decimal('10500.00'), status='AVAILABLE')
        Asset.objects.create(name='Mobile Crane C1', description='50-ton mobile crane', monthly_rate=Decimal('24000.00'), status='AVAILABLE')
        Asset.objects.create(name='Scissor Lift S19', description='19ft electric scissor lift', monthly_rate=Decimal('3000.00'), status='MAINTENANCE')
        print("Created 4 assets.")
    else:
        print("Assets already exist.")

if __name__ == '__main__':
    seed()
