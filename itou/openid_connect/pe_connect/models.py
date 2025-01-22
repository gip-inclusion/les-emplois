import dataclasses
from typing import ClassVar

from itou.openid_connect.models import OIDConnectState, OIDConnectUserData
from itou.users.enums import IdentityProvider, UserKind


class PoleEmploiConnectState(OIDConnectState):
    pass


@dataclasses.dataclass
class PoleEmploiConnectUserData(OIDConnectUserData):
    # Attributes are User model ones.
    # Mapping is made in self.user_info_mapping_dict.
    kind: UserKind = UserKind.JOB_SEEKER
    identity_provider: IdentityProvider = IdentityProvider.PE_CONNECT
    allowed_identity_provider_migration: ClassVar[tuple[IdentityProvider]] = ()
