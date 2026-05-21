import contextlib
import dataclasses
import datetime
from typing import ClassVar

from itou.openid_connect.models import OIDConnectState, OIDConnectUserData
from itou.users.enums import IdentityProvider, Title, UserKind


class FranceConnectState(OIDConnectState):
    pass


TITLE_MAP = {"male": Title.M, "female": Title.MME}


@dataclasses.dataclass
class FranceConnectUserData(OIDConnectUserData):
    # Attributes are User model ones.
    # Mapping is made in self.user_info_mapping_dict.
    phone: str | None = None
    birth_name: str = ""
    birthdate: datetime.date | None = None
    address_line_1: str | None = None
    post_code: str | None = None
    city: str | None = None
    kind: UserKind = UserKind.JOB_SEEKER
    title: str | None = None
    identity_provider: IdentityProvider = IdentityProvider.FRANCE_CONNECT
    allowed_identity_provider_migration: ClassVar[tuple[IdentityProvider]] = ()

    @staticmethod
    def user_info_mapping_dict(user_info: dict):
        """
        Map Django-User class attributes to the identity provider ones.
        See https://openid.net/specs/openid-connect-core-1_0.html#StandardClaims
        """
        # Python 3's zero-argument super() only works in class or instance methods.
        standard_attrs = super(FranceConnectUserData, FranceConnectUserData).user_info_mapping_dict(
            user_info=user_info
        )
        attrs = standard_attrs | {
            "last_name": user_info.get("preferred_username"),
            "birth_name": user_info.get("family_name"),
            "birthdate": datetime.date.fromisoformat(user_info["birthdate"]) if user_info.get("birthdate") else None,
        }
        with contextlib.suppress(KeyError):
            gender = user_info["gender"]
            attrs["title"] = TITLE_MAP[gender]
        return attrs
