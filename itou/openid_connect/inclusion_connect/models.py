import dataclasses

from itou.users.enums import IdentityProvider

from ..models import OIDConnectState, OIDConnectUserData


class InclusionConnectState(OIDConnectState):
    class Meta:
        abstract = False


@dataclasses.dataclass
class InclusionConnectPrescriberData(OIDConnectUserData):
    is_prescriber: bool = True
    identity_provider: IdentityProvider = IdentityProvider.INCLUSION_CONNECT


@dataclasses.dataclass
class InclusionConnectSiaeStaffData(OIDConnectUserData):
    is_siae_staff: bool = True
    identity_provider: IdentityProvider = IdentityProvider.INCLUSION_CONNECT
