import dataclasses
import datetime
from typing import Optional

from itou.users.enums import IdentityProvider

from ..models import OIDConnectState, OIDConnectUserData


class FranceConnectState(OIDConnectState):
    pass


@dataclasses.dataclass
class FranceConnectUserData(OIDConnectUserData):  # pylint: disable=too-many-instance-attributes
    # Attributes are User model ones.
    # Mapping is made in self.user_info_mapping_dict.
    phone: Optional[str] = None
    birthdate: Optional[datetime.date] = None
    address_line_1: Optional[str] = None
    post_code: Optional[str] = None
    city: Optional[str] = None
    is_job_seeker: bool = True
    identity_provider: IdentityProvider = IdentityProvider.FRANCE_CONNECT

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
            "birthdate": datetime.date.fromisoformat(user_info["birthdate"]) if user_info.get("birthdate") else None,
            "phone": user_info.get("phone_number"),
        }
        if "address" in user_info:
            if user_info["address"].get("country") == "France":
                attrs |= {
                    "address_line_1": user_info["address"].get("street_address"),
                    "post_code": user_info["address"].get("postal_code"),
                    "city": user_info["address"].get("locality"),
                }
        return attrs
