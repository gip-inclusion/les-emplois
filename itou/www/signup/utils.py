from django.conf import settings
from django.utils.http import urlsafe_base64_decode

from itou.siaes.models import Siae
from itou.utils.tokens import siae_signup_token_generator


def get_siae_from_session(session):
    encoded_siae_id = session[settings.ITOU_SESSION_SIAE_SIGNUP_ID]
    if encoded_siae_id:
        siae_id = int(urlsafe_base64_decode(encoded_siae_id))
        siae = Siae.objects.get(pk=siae_id)
    else:
        siae = None
    return siae


def check_siae_signup_credentials(session):
    siae = get_siae_from_session(session)
    token = session[settings.ITOU_SESSION_SIAE_SIGNUP_TOKEN]
    return siae_signup_token_generator.check_token(siae=siae, token=token)
