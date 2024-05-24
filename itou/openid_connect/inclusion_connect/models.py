import dataclasses
import logging

from django.db import models

from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import User

from ..models import OIDConnectState, OIDConnectUserData


logger = logging.getLogger(__name__)


class InclusionConnectState(OIDConnectState):
    data = models.JSONField(verbose_name="données de session", default=dict, blank=True)

    class Meta:
        abstract = False


@dataclasses.dataclass
class InclusionConnectPrescriberData(OIDConnectUserData):
    kind: str = UserKind.PRESCRIBER
    identity_provider: IdentityProvider = IdentityProvider.INCLUSION_CONNECT
    login_allowed_user_kinds = [UserKind.PRESCRIBER, UserKind.EMPLOYER]

    def join_org(self, user: User, safir: str):
        try:
            organization = PrescriberOrganization.objects.get(code_safir_pole_emploi=safir)
        except PrescriberOrganization.DoesNotExist:
            logger.info(f"Organization with SAFIR {safir} does not exist. Unable to add user {user.id}.")
            raise
        if not organization.has_member(user):
            organization.add_member(user)


@dataclasses.dataclass
class InclusionConnectEmployerData(OIDConnectUserData):
    kind: str = UserKind.EMPLOYER
    identity_provider: IdentityProvider = IdentityProvider.INCLUSION_CONNECT
    login_allowed_user_kinds = [UserKind.PRESCRIBER, UserKind.EMPLOYER]
