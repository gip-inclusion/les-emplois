from django.conf import settings

from itou.companies.models import CompanyMembership
from itou.otp.models import ItouStaticDevice, ItouStaticToken, ItouTOTPDevice
from itou.prescribers.models import PrescriberMembership
from itou.utils.emails import get_email_message


FAKE_DEVICE_MODEL = "fake-for-external-totp-device"
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


def notify_backup_code_has_been_used(user):
    email = get_email_message(
        to=[user.email],
        context={"user": user},
        subject="common/emails/used_otp_backup_code_subject.txt",
        body="common/emails/used_otp_backup_code_body.txt",
    )
    email.send()


def require_otp(user):
    if not user.is_authenticated:
        return False

    if user.is_verified():  # user has already authenticated with MFA
        return False

    if settings.REQUIRE_OTP_FOR_STAFF and user.is_itou_staff:
        return True

    if user.is_professional and _require_otp_for_pro(user):
        return True

    return False


def _require_otp_for_pro(user):
    assert user.is_professional
    if not settings.REQUIRE_MFA_FOR_PROS:
        return False
    org_ids = set(
        PrescriberMembership.objects.active().filter(user_id=user.id).values_list("organization_id", flat=True)
    )
    if org_ids & settings.REQUIRE_MFA_ON_ORGANIZATION_IDS:
        return True
    company_ids = set(CompanyMembership.objects.active().filter(user_id=user.id).values_list("company_id", flat=True))
    if company_ids & settings.REQUIRE_MFA_ON_COMPANY_IDS:
        return True
    return False


def create_placeholder_for_external_totp_device(user):
    """When a user connects through ProConnect with MFA, we do not
    want to ask again for our own MFA process. Instead, we create a
    fake TOTPDevice that is seen by django_otp but is invisible from
    the user.
    """
    return ExternalTOTPDevice(user.id)


def load_placeholder_for_external_totp_device(persistent_id):
    """Load placeholder from session.

    See `create_placeholder_for_external_totp_device` for further
    details.
    """
    try:
        model_label, user_id = persistent_id.split("/")
        user_id = int(user_id)
    except ValueError:  # unexpected format, should not happen
        return None
    if model_label != FAKE_DEVICE_MODEL:
        return None
    return ExternalTOTPDevice(user_id)


class ExternalTOTPDevice:
    """This placeholder is a session-only marker: verification already happened on ProConnect's side."""

    def __init__(self, user_id: int):
        self.user_id = user_id

    @property
    def persistent_id(self):
        return f"{FAKE_DEVICE_MODEL}/{self.user_id}"
