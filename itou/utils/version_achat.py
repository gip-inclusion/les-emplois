from itou.siaes.models import Siae


# FIXME use middleware? => see session current_siae key
VERSION_ACHAT_KEY = "version_achat"


def disable_version_achat(request):
    if VERSION_ACHAT_KEY in request.session:
        del request.session[VERSION_ACHAT_KEY]


def enable_version_achat(request):
    request.session[VERSION_ACHAT_KEY] = True


def is_version_achat_enabled(request):
    return request.session.get(VERSION_ACHAT_KEY) == True


def get_version_achat_default_siae_kind():
    return Siae.KIND_ETTI
