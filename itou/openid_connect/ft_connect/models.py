import contextlib
import dataclasses
from typing import ClassVar

from itou.openid_connect.models import OIDConnectState, OIDConnectUserData
from itou.users.enums import IdentityProvider, Title, UserKind


TITLE_MAP = {"male": Title.M, "female": Title.MME}


class PoleEmploiConnectState(OIDConnectState):
    class Meta:
        db_table = "pe_connect_poleemploiconnectstate"


@dataclasses.dataclass
class PoleEmploiConnectUserData(OIDConnectUserData):
    # Attributes are User model ones.
    # Mapping is made in self.user_info_mapping_dict.
    kind: UserKind = UserKind.JOB_SEEKER
    identity_provider: IdentityProvider = IdentityProvider.PE_CONNECT
    allowed_identity_provider_migration: ClassVar[tuple[IdentityProvider]] = ()
    title: str | None = None

    @staticmethod
    def user_info_mapping_dict(user_info: dict):
        # Python 3's zero-argument super() only works in class or instance methods.
        attrs = super(PoleEmploiConnectUserData, PoleEmploiConnectUserData).user_info_mapping_dict(user_info=user_info)
        with contextlib.suppress(KeyError):
            gender = user_info["gender"]
            attrs["title"] = TITLE_MAP[gender]
        return attrs
