from django.contrib.auth.models import AnonymousUser

from itou.www.invitations_views.helpers import accept_all_pending_invitations
from tests.invitations.factories import (
    EmployerInvitationFactory,
    LaborInspectorInvitationFactory,
    PrescriberWithOrgInvitationFactory,
)
from tests.users.factories import random_pro_user_factory
from tests.utils.testing import get_request


def test_anonymous_user():
    request = get_request(AnonymousUser())
    assert accept_all_pending_invitations(request) is False


def test_accept_invitations():
    user = random_pro_user_factory()
    request = get_request(user)

    valid_invitation_1 = PrescriberWithOrgInvitationFactory(email=user.email)
    valid_invitation_2 = EmployerInvitationFactory(email=user.email)
    valid_invitation_3 = LaborInspectorInvitationFactory(email=user.email)

    # non pending invitations
    PrescriberWithOrgInvitationFactory(email=user.email, expired=True)
    PrescriberWithOrgInvitationFactory(email=user.email, accepted=True)
    EmployerInvitationFactory(email=user.email, expired=True)
    EmployerInvitationFactory(email=user.email, accepted=True)
    LaborInspectorInvitationFactory(email=user.email, expired=True)
    LaborInspectorInvitationFactory(email=user.email, accepted=True)

    assert accept_all_pending_invitations(request) == [valid_invitation_1, valid_invitation_2, valid_invitation_3]
