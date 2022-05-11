import dataclasses
import datetime
from typing import Optional

from itou.common_apps.openid_connect.models import OIDConnectState, OIDConnectUserData
from itou.users.enums import IdentityProvider


class FranceConnectState(OIDConnectState):
    pass


@dataclasses.dataclass
class FranceConnectUserData(OIDConnectUserData):  # pylint: disable=too-many-instance-attributes
    phone: Optional[str] = None
    birthdate: Optional[datetime.date] = None
    address_line_1: Optional[str] = None
    post_code: Optional[str] = None
    city: Optional[str] = None
    is_job_seeker: bool = True
    identity_provider: IdentityProvider = IdentityProvider.FRANCE_CONNECT

    @classmethod
    def from_user_info(cls, user_info: dict):
        attrs = {
            "username": user_info["sub"],
            "email": user_info["email"],
            "first_name": user_info.get("given_name"),
            "last_name": user_info.get("family_name"),
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

        return cls(**attrs)
