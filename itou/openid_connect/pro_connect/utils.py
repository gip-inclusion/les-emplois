from itou.otp import utils as otp_utils
from itou.otp.models import ItouTOTPDevice


def get_acr_configuration(user):
    """Return ACR configuration, i.e. whether or not we want to
    enforce MFA from ProConnect.
    """
    do_not_enforce_mfa = {"essential": False, "values": ["eidas2", "eidas3"]}
    enforce_mfa = {
        "essential": True,
        # eIDAS levels: https://partenaires.proconnect.gouv.fr/docs/ressources/norme_eidas
        "values": [
            # "eidas{0,1}-mfa" levels make ProConnect fallback to
            # "OTP-by-email" if the identity provider does not
            # implement strong MFA.
            # https://partenaires.proconnect.gouv.fr/docs/fournisseur-service/double_authentification
            # We need "eidas0-mfa" (even though eidas0 is too low for
            # our taste), otherwise the user is stuck in an infinite
            # loop trying to input the e-mail-sent validation code,
            # when the identity provider returns "eidas0".
            "eidas0-mfa",
            "eidas1-mfa",
            "eidas2",
            "eidas3",
        ],
    }
    if not user:
        return do_not_enforce_mfa
    if not otp_utils.require_otp_for_pro(user):
        return do_not_enforce_mfa
    if ItouTOTPDevice.objects.active().filter(user=user).exists():
        # For now, do not enforce on ProConnect, and keep our own MFA
        # implementation, since the user already enrolled with us. We
        # will switch them in a few months.
        return do_not_enforce_mfa
    return enforce_mfa
