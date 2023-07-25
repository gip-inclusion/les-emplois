import dataclasses

from django.db import models

from itou.users.enums import IdentityProvider, UserKind

from ..models import OIDConnectState, OIDConnectUserData


class InclusionConnectState(OIDConnectState):
    data = models.JSONField(verbose_name="données de session", default=dict, blank=True)

    class Meta:
        abstract = False


@dataclasses.dataclass
class InclusionConnectPrescriberData(OIDConnectUserData):
    kind: str = UserKind.PRESCRIBER
    identity_provider: IdentityProvider = IdentityProvider.INCLUSION_CONNECT
    login_allowed_user_kinds = [UserKind.PRESCRIBER, UserKind.SIAE_STAFF]


@dataclasses.dataclass
class InclusionConnectSiaeStaffData(OIDConnectUserData):
    kind: str = UserKind.SIAE_STAFF
    identity_provider: IdentityProvider = IdentityProvider.INCLUSION_CONNECT
    login_allowed_user_kinds = [UserKind.PRESCRIBER, UserKind.SIAE_STAFF]
