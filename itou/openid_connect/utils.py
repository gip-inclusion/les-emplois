from itou.openid_connect.france_connect.models import FranceConnectUserData
from itou.openid_connect.ft_connect.models import FranceTravailConnectUserData
from itou.openid_connect.models import OIDConnectUserData
from itou.openid_connect.pro_connect.models import ProConnectUserData
from itou.users.enums import IdentityProvider
from itou.utils import constants as global_constants


def init_user_nir_from_session(request, user):
    existing_subscription_data = request.session.get(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY)
    if existing_subscription_data:
        user.jobseeker_profile.nir = existing_subscription_data["nir"]
        user.jobseeker_profile.lack_of_nir_reason = ""
        user.jobseeker_profile.save(update_fields=["nir", "lack_of_nir_reason"])
        request.session.pop(global_constants.ITOU_SESSION_JOB_SEEKER_SIGNUP_KEY)


# Not in `utils` or `constants` module to avoid circular dependency.
IdentityProviderToOIDCUserData: dict[IdentityProvider, type[OIDConnectUserData] | None] = {
    IdentityProvider.FT_CONNECT: FranceTravailConnectUserData,
    IdentityProvider.DJANGO: None,
    IdentityProvider.FRANCE_CONNECT: FranceConnectUserData,
    IdentityProvider.PRO_CONNECT: ProConnectUserData,
}
assert set(IdentityProviderToOIDCUserData) == set(IdentityProvider.values)
