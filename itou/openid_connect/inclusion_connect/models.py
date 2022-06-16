import dataclasses

from itou.users.enums import IdentityProvider

from ..models import OIDConnectState, OIDConnectUserData


class InclusionConnectState(OIDConnectState):
    class Meta:
        abstract = False


@dataclasses.dataclass
class InclusionConnectUserData(OIDConnectUserData):
    is_prescriber: bool = True
    identity_provider: IdentityProvider = IdentityProvider.INCLUSION_CONNECT
