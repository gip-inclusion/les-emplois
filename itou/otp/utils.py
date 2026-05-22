import django_otp


def get_user_devices(user):
    return sorted(
        django_otp.devices_for_user(user),
        key=lambda device: device.name,
    )
