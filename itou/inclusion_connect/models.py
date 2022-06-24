import dataclasses

from itou.common_apps.openid_connect.models import OIDConnectState, OIDConnectUserData
from itou.users import enums as users_enums


class InclusionConnectState(OIDConnectState):
    class Meta:
        abstract = False


@dataclasses.dataclass
class InclusionConnectUser(OIDConnectUserData):
    is_prescriber: bool = True
    identity_provider: str = users_enums.IdentityProvider.INCLUSION_CONNECT
