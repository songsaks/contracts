import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'contracts.settings')
django.setup()

from pms.forms import SalesServiceJobForm
from pms.models import Project, Customer

cust = Customer.objects.first()
form = SalesServiceJobForm({
    'name': 'Test Survey',
    'customer': cust.id if cust else '',
    'start_date': '2026-04-03',
}, job_type=Project.JobType.SURVEY)

print("IS VALID:", form.is_valid())
if not form.is_valid():
    print("ERRORS:", form.errors)
