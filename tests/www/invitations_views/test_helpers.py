from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory

from itou.www.invitations_views.helpers import accept_all_pending_invitations
from tests.invitations.factories import (
    EmployerInvitationFactory,
    LaborInspectorInvitationFactory,
    PrescriberWithOrgInvitationFactory,
)
from tests.users.factories import EmployerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.tests import get_response_for_middlewaremixin


def test_anonymous_user():
    request = RequestFactory()
    request.user = AnonymousUser()
    assert accept_all_pending_invitations(request) == 0


def fake_request():
    request = RequestFactory().get("/")
    SessionMiddleware(get_response_for_middlewaremixin).process_request(request)
    MessageMiddleware(get_response_for_middlewaremixin).process_request(request)
    return request


def test_accept_prescriber_invitations():
    request = fake_request()
    prescriber = PrescriberFactory()
    request.user = prescriber

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
    request = fake_request()
    prescriber = EmployerFactory()
    request.user = prescriber

    valid_invitation_1 = EmployerInvitationFactory(email=prescriber.email)
    valid_invitation_2 = EmployerInvitationFactory(email=prescriber.email)
    # non pending invitations
    EmployerInvitationFactory(email=prescriber.email, expired=True)
    EmployerInvitationFactory(email=prescriber.email, accepted=True)
    # other user kind invitations
    PrescriberWithOrgInvitationFactory(email=prescriber.email)
    LaborInspectorInvitationFactory(email=prescriber.email)

    assert accept_all_pending_invitations(request) == [valid_invitation_1, valid_invitation_2]


def test_accept_labor_inspector_invitations():
    request = fake_request()
    prescriber = LaborInspectorFactory()
    request.user = prescriber

    valid_invitation_1 = LaborInspectorInvitationFactory(email=prescriber.email)
    valid_invitation_2 = LaborInspectorInvitationFactory(email=prescriber.email)
    # non pending invitations
    LaborInspectorInvitationFactory(email=prescriber.email, expired=True)
    LaborInspectorInvitationFactory(email=prescriber.email, accepted=True)
    # other user kind invitations
    EmployerInvitationFactory(email=prescriber.email)
    PrescriberWithOrgInvitationFactory(email=prescriber.email)

    assert accept_all_pending_invitations(request) == [valid_invitation_1, valid_invitation_2]
