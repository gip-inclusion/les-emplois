from django.contrib.auth.models import AnonymousUser

from itou.www.invitations_views.helpers import accept_all_pending_invitations
from tests.invitations.factories import (
    EmployerInvitationFactory,
    LaborInspectorInvitationFactory,
    PrescriberWithOrgInvitationFactory,
)
from tests.users.factories import EmployerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.testing import get_request


def test_anonymous_user():
    request = get_request(AnonymousUser())
    assert accept_all_pending_invitations(request) == 0


def test_accept_prescriber_invitations():
    prescriber = PrescriberFactory()
    request = get_request(prescriber)

    valid_invitation_1 = PrescriberWithOrgInvitationFactory(email=prescriber.email)
    valid_invitation_2 = PrescriberWithOrgInvitationFactory(email=prescriber.email)
    # non pending invitations
    PrescriberWithOrgInvitationFactory(email=prescriber.email, expired=True)
    PrescriberWithOrgInvitationFactory(email=prescriber.email, accepted=True)
    # other user kind invitations
    EmployerInvitationFactory(email=prescriber.email)
    LaborInspectorInvitationFactory(email=prescriber.email)

    assert accept_all_pending_invitations(request) == [valid_invitation_1, valid_invitation_2]


def test_accept_employer_invitations():
    employer = EmployerFactory()
    request = get_request(employer)

    valid_invitation_1 = EmployerInvitationFactory(email=employer.email)
    valid_invitation_2 = EmployerInvitationFactory(email=employer.email)
    # non pending invitations
    EmployerInvitationFactory(email=employer.email, expired=True)
    EmployerInvitationFactory(email=employer.email, accepted=True)
    # other user kind invitations
    PrescriberWithOrgInvitationFactory(email=employer.email)
    LaborInspectorInvitationFactory(email=employer.email)

    assert accept_all_pending_invitations(request) == [valid_invitation_1, valid_invitation_2]


def test_accept_labor_inspector_invitations():
    labor_inspector = LaborInspectorFactory()
    request = get_request(labor_inspector)

    valid_invitation_1 = LaborInspectorInvitationFactory(email=labor_inspector.email)
    valid_invitation_2 = LaborInspectorInvitationFactory(email=labor_inspector.email)
    # non pending invitations
    LaborInspectorInvitationFactory(email=labor_inspector.email, expired=True)
    LaborInspectorInvitationFactory(email=labor_inspector.email, accepted=True)
    # other user kind invitations
    EmployerInvitationFactory(email=labor_inspector.email)
    PrescriberWithOrgInvitationFactory(email=labor_inspector.email)

    assert accept_all_pending_invitations(request) == [valid_invitation_1, valid_invitation_2]
