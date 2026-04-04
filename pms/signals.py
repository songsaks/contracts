from django.db.models.signals import post_save
from django.dispatch import receiver


def _set_force_track(user, force, toggled_by=None):
    """เปิด/ปิด force_track state สำหรับ user"""
    from django.utils import timezone
    from pms.models import TechnicianTrackingState
    state, _ = TechnicianTrackingState.objects.get_or_create(user=user)
    state.force_track = force
    state.forced_at   = timezone.now() if force else None
    state.toggled_by  = toggled_by
    state.save(update_fields=['force_track', 'forced_at', 'toggled_by'])


@receiver(post_save, sender='pms.TechnicianGPSLog')
def handle_gps_log(sender, instance, created, **kwargs):
    """เปิด force_track เมื่อ GO_WORK / ปิดเมื่อ BACK_OFFICE"""
    if not created:
        return
    if instance.check_type == 'GO_WORK':
        _set_force_track(instance.user, force=True)
    elif instance.check_type == 'BACK_OFFICE':
        _set_force_track(instance.user, force=False)


@receiver(post_save, sender='pms.TechnicianGPSLog')
def notify_go_work(sender, instance, created, **kwargs):
    """
    เมื่อมีการบันทึก GPS log ประเภท GO_WORK ใหม่ (ออกทำงาน)
    ส่ง Telegram แจ้งเตือนให้ผู้ใช้เปิด Auto-Track GPS
    """
    if not created:
        return
    if instance.check_type != 'GO_WORK':
        return

    from django.utils import timezone
    from stocks.telegram_utils import send_telegram_message

    user = instance.user
    time_str = timezone.localtime(instance.timestamp).strftime('%H:%M')
    full_name = user.get_full_name() or user.username

    message = (
        f"🚀 <b>{full_name}</b> ออกทำงานแล้ว ({time_str})\n\n"
        f"📍 <b>อย่าลืม!</b> เปิด <b>Auto-Track GPS</b> เพื่อบันทึกเส้นทางการทำงาน\n\n"
        f"วิธีเปิด: แอป → GPS Tracking → เปิด Auto-Track ✅"
    )

    # ส่งให้ตัวผู้ใช้เอง
    try:
        chat_id = user.telegram_profile.chat_id
        send_telegram_message(chat_id, message)
    except Exception:
        pass  # ไม่มี telegram_profile หรือส่งไม่ได้ — ไม่ crash

    # ส่งให้ admin/superuser ทุกคนที่มี telegram_profile
    from django.contrib.auth import get_user_model
    from stocks.models import UserTelegramProfile
    User = get_user_model()

    admin_message = (
        f"📋 <b>แจ้งเตือนผู้จัดการ</b>\n"
        f"👤 <b>{full_name}</b> (@{user.username}) ออกทำงานแล้ว เวลา {time_str}\n"
        f"📍 {instance.location_name or 'ไม่ระบุสถานที่'}"
    )

    admin_profiles = UserTelegramProfile.objects.filter(
        user__is_staff=True
    ).exclude(user=user).select_related('user')

    for profile in admin_profiles:
        try:
            send_telegram_message(profile.chat_id, admin_message)
        except Exception:
            pass
