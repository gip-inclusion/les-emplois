import dataclasses

from itou.users.enums import IdentityProvider, UserKind

from ..models import OIDConnectState, OIDConnectUserData


class PoleEmploiConnectState(OIDConnectState):
    class Meta:
        abstract = False


@dataclasses.dataclass
class PoleEmploiConnectUserData(OIDConnectUserData):
    # Attributes are User model ones.
    # Mapping is made in self.user_info_mapping_dict.
    kind: str = UserKind.JOB_SEEKER
    identity_provider: IdentityProvider = IdentityProvider.PE_CONNECT
    login_allowed_user_kinds = [UserKind.JOB_SEEKER]
