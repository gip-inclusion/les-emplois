from itou.audit_trail.models import AuditTrail, AuditTrailEventType
from itou.openid_connect.france_connect.constants import FRANCE_CONNECT_SESSION_TOKEN
from itou.openid_connect.ft_connect.constants import FRANCETRAVAIL_CONNECT_SESSION_TOKEN
from itou.openid_connect.pro_connect.constants import PRO_CONNECT_SESSION_KEY
from itou.otp.utils import require_otp


def _get_login_data(request):
    data = {}

    if PRO_CONNECT_SESSION_KEY in request.session:
        data["idp"] = "ProConnect"

    if FRANCETRAVAIL_CONNECT_SESSION_TOKEN in request.session:
        data["idp"] = "FranceTravail"

    if FRANCE_CONNECT_SESSION_TOKEN in request.session:
        data["idp"] = "FranceConnect"

    return data


def on_user_logged_in(sender, request, user, **kwargs):
    AuditTrail.objects.create(
        AuditTrailEventType.PARTIAL_LOG_IN if require_otp(user) else AuditTrailEventType.LOG_IN,
        request,
        user=user,
        data=_get_login_data(request),
    )


def on_user_logged_in_with_2fa(sender, request, user, **kwargs):
    otp_device = user.otp_device
    try:
        device_pk = str(otp_device.pk)
    except AttributeError:
        device_pk = "(external)"
    AuditTrail.objects.create(
        AuditTrailEventType.LOG_IN, request, user=user, data={"device_pk": device_pk} | _get_login_data(request)
    )
