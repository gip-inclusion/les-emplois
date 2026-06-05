from itou.otp.models import ItouStaticDevice, ItouStaticToken, ItouTOTPDevice


STATIC_DEVICE_BACKUP_CODE_NAME = "backup-code"


def get_user_devices(user):
    return sorted(
        ItouTOTPDevice.objects.filter(user=user, disabled_at=None),
        key=lambda device: device.name,
    )


def create_otp_backup_code(user) -> str:
    device, _ = ItouStaticDevice.objects.get_or_create(
        user=user,
        defaults={"name": STATIC_DEVICE_BACKUP_CODE_NAME},
    )
    clear_code, _ = ItouStaticToken.objects.create(device)
    return clear_code
