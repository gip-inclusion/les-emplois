import dataclasses

from django.db import models
from django.utils import timezone

from itou.common_apps.openid_connect.models import OIDConnectState, OIDConnectUserData
from itou.users import enums as users_enums
from itou.users.models import User


class InclusionConnectState(OIDConnectState):
    class Meta:
        abstract = False


@dataclasses.dataclass
class InclusionConnectUser(OIDConnectUserData):
    is_prescriber: bool = True
    identity_provider: str = users_enums.IdentityProvider.INCLUSION_CONNECT
