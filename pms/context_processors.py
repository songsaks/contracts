from .models import CustomerRequirement, CustomerRequest

def pms_context(request):
    """Add PMS related global context variables."""
    if request.user.is_authenticated:
        unconverted_leads_count = CustomerRequirement.objects.filter(is_converted=False).count()
        new_requests_count = CustomerRequest.objects.filter(status=CustomerRequest.Status.RECEIVED).count()
        return {
            'unconverted_leads_count': unconverted_leads_count,
            'new_requests_count': new_requests_count,
        }
    return {}
