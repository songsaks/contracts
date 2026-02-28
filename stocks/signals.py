from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from .models import ScannableSymbol
import threading
from .utils import refresh_set100_symbols

@receiver(user_logged_in)
def on_user_login(sender, request, user, **kwargs):
    """
    Update the scannable symbols list when a user logs in.
    Runs in a background thread to avoid blocking login.
    """
    # Simply trigger the refresh logic
    threading.Thread(target=refresh_set100_symbols).start()
