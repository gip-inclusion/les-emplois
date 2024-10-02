import dataclasses
import logging
from typing import ClassVar

from django.db import models

from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User

from ..models import OIDConnectState, OIDConnectUserData


logger = logging.getLogger(__name__)


class ProConnectState(OIDConnectState):
    data = models.JSONField(verbose_name="données de session", default=dict, blank=True)


@dataclasses.dataclass
class ProConnectUserData(OIDConnectUserData):
    @staticmethod
    def user_info_mapping_dict(user_info: dict):
        return {
            "username": user_info["sub"],
            "first_name": user_info["given_name"],
            "last_name": user_info["usual_name"],
            "email": user_info["email"],
        }

    def join_org(self, user: User, safir: str):
        if not user.is_prescriber:
            raise ValueError("Invalid user kind: %s", user.kind)
        try:
            organization = PrescriberOrganization.objects.get(code_safir_pole_emploi=safir)
        except PrescriberOrganization.DoesNotExist:
            logger.error(f"Organization with SAFIR {safir} does not exist. Unable to add user {user.email}.")
            raise
        if not organization.has_member(user):
            organization.add_or_activate_member(user)


@dataclasses.dataclass
class ProConnectPrescriberData(ProConnectUserData):
    kind: UserKind = UserKind.PRESCRIBER
    identity_provider: IdentityProvider = IdentityProvider.PRO_CONNECT
    allowed_identity_provider_migration: ClassVar[tuple[IdentityProvider]] = (
        IdentityProvider.DJANGO,
        IdentityProvider.INCLUSION_CONNECT,
    )


@dataclasses.dataclass
class ProConnectEmployerData(ProConnectUserData):
    kind: UserKind = UserKind.EMPLOYER
    identity_provider: IdentityProvider = IdentityProvider.PRO_CONNECT
    allowed_identity_provider_migration: ClassVar[tuple[IdentityProvider]] = (
        IdentityProvider.DJANGO,
        IdentityProvider.INCLUSION_CONNECT,
    )
