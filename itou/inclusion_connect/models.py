import dataclasses

from itou.common_apps.openid_connect.models import OIDConnectState, OIDConnectUserData
from itou.users.enums import IdentityProvider


class InclusionConnectState(OIDConnectState):
    class Meta:
        abstract = False


@dataclasses.dataclass
class InclusionConnectUserData(OIDConnectUserData):
    is_prescriber: bool = True
    identity_provider: IdentityProvider = IdentityProvider.INCLUSION_CONNECT
