import dataclasses

from itou.users.enums import IdentityProvider, UserKind

from ..models import OIDConnectState, OIDConnectUserData


class InclusionConnectState(OIDConnectState):
    class Meta:
        abstract = False


@dataclasses.dataclass
class InclusionConnectPrescriberData(OIDConnectUserData):
    kind: str = UserKind.PRESCRIBER
    identity_provider: IdentityProvider = IdentityProvider.INCLUSION_CONNECT


@dataclasses.dataclass
class InclusionConnectSiaeStaffData(OIDConnectUserData):
    kind: str = UserKind.SIAE_STAFF
    identity_provider: IdentityProvider = IdentityProvider.INCLUSION_CONNECT
