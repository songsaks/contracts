from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from .models import ScannableSymbol
import threading
from .utils import refresh_all_thai_symbols

@receiver(user_logged_in)
def on_user_login(sender, request, user, **kwargs):
    """
    Update the scannable symbols list when a user logs in.
    Runs in a background thread to avoid blocking login.
    """
    # Simply trigger the refresh logic (expanded SET+MAI universe)
    threading.Thread(target=refresh_all_thai_symbols).start()
