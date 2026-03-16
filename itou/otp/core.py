from django_otp.plugins.otp_totp.models import TOTPDevice


FAKE_DEVICE_NAME = "___ fake: placeholder for a MFA that happened on ProConnect"


def create_placeholder_totp_device(user):
    """When a user connects through ProConnect with MFA, we do not
    want to ask again for our own MFA process. Instead, we create a
    fake TOTPDevice that is seen by django_otp but is invisible from
    the user.
    """
    device, _created = TOTPDevice.objects.get_or_create(
        user=user,
        name=FAKE_DEVICE_NAME,
        confirmed=True,
    )
    return device
