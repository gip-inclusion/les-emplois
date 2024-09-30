import dataclasses
from typing import ClassVar

from itou.users.enums import IdentityProvider, UserKind

from ..models import OIDConnectState, OIDConnectUserData


class PoleEmploiConnectState(OIDConnectState):
    pass


@dataclasses.dataclass
class PoleEmploiConnectUserData(OIDConnectUserData):
    # Attributes are User model ones.
    # Mapping is made in self.user_info_mapping_dict.
    kind: UserKind = UserKind.JOB_SEEKER
    identity_provider: IdentityProvider = IdentityProvider.PE_CONNECT
    login_allowed_user_kinds: ClassVar[tuple[UserKind]] = (UserKind.JOB_SEEKER,)
    allowed_identity_provider_migration: ClassVar[tuple[IdentityProvider]] = ()
