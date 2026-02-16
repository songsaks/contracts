from .models import CustomerRequirement

def pms_context(request):
    """Add PMS related global context variables."""
    if request.user.is_authenticated:
        unconverted_leads_count = CustomerRequirement.objects.filter(is_converted=False).count()
        return {
            'unconverted_leads_count': unconverted_leads_count
        }
    return {}
