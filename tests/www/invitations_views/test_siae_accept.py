from urllib.parse import urlencode

import pytest
import respx
from django.conf import settings
from django.contrib import messages
from django.core import mail
from django.shortcuts import reverse
from django.test import Client
from django.utils.html import escape

from itou.users.enums import KIND_EMPLOYER, UserKind
from itou.users.models import User
from itou.utils.perms.siae import get_current_siae_or_404
from itou.utils.urls import add_url_params
from tests.companies.factories import SiaeFactory
from tests.invitations.factories import ExpiredEmployerInvitationFactory, SentEmployerInvitationFactory
from tests.openid_connect.inclusion_connect.test import InclusionConnectBaseTestCase
from tests.openid_connect.inclusion_connect.tests import OIDC_USERINFO, mock_oauth_dance
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import EmployerFactory
from tests.utils.test import assertMessages


pytestmark = pytest.mark.ignore_template_errors


class TestAcceptInvitation(InclusionConnectBaseTestCase):
    def assert_accepted_invitation(self, response, invitation, user):
        user.refresh_from_db()
        invitation.refresh_from_db()
        assert user.kind == UserKind.EMPLOYER
        assert invitation.accepted
        assert invitation.accepted_at

        # A confirmation e-mail is sent to the invitation sender.
        assert len(mail.outbox) == 1
        assert len(mail.outbox[0].to) == 1
        assert invitation.sender.email == mail.outbox[0].to[0]

        # Make sure there's a welcome message.
        self.assertContains(
            response, escape(f"Vous êtes désormais membre de la structure {invitation.siae.display_name}.")
        )

        # Assert the user sees his new siae dashboard
        current_siae = get_current_siae_or_404(response.wsgi_request)
        # A user can be member of one or more siae
        assert current_siae in user.company_set.all()

    @respx.mock
    def test_accept_invitation_signup(self):
        invitation = SentEmployerInvitationFactory(email=OIDC_USERINFO["email"])
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_siae", args=(invitation.pk,))
        params = {
            "user_kind": KIND_EMPLOYER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        total_users_before = User.objects.count()

        response = mock_oauth_dance(
            self.client,
            KIND_EMPLOYER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        response = self.client.get(response.url, follow=True)
        # Check user is redirected to the welcoming tour
        last_url, _status_code = response.redirect_chain[-1]
        assert last_url == reverse("welcoming_tour:index")

        total_users_after = User.objects.count()
        assert (total_users_before + 1) == total_users_after

        user = User.objects.get(email=invitation.email)
        self.assert_accepted_invitation(response, invitation, user)

    @respx.mock
    def test_accept_invitation_signup_returns_on_other_browser(self):
        invitation = SentEmployerInvitationFactory(email=OIDC_USERINFO["email"])
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_siae", args=(invitation.pk,))
        params = {
            "user_kind": KIND_EMPLOYER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        total_users_before = User.objects.count()

        other_client = Client()
        response = mock_oauth_dance(
            self.client,
            KIND_EMPLOYER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            other_client=other_client,
        )
        response = other_client.get(response.url, follow=True)
        # Check user is redirected to the welcoming tour
        last_url, _status_code = response.redirect_chain[-1]
        assert last_url == reverse("welcoming_tour:index")

        total_users_after = User.objects.count()
        assert (total_users_before + 1) == total_users_after

        user = User.objects.get(email=invitation.email)
        self.assert_accepted_invitation(response, invitation, user)

    @respx.mock
    def test_accept_invitation_signup_bad_email_case(self):
        invitation = SentEmployerInvitationFactory(email=OIDC_USERINFO["email"].upper())
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_siae", args=(invitation.pk,))
        params = {
            "user_kind": KIND_EMPLOYER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        assert User.objects.filter(email=invitation.email).first() is None

        response = mock_oauth_dance(
            self.client,
            KIND_EMPLOYER,
            # Using the same email with a different case should not fail
            user_email=invitation.email.lower(),
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        response = self.client.get(response.url, follow=True)
        # Check user is redirected to the welcoming tour
        last_url, _ = response.redirect_chain[-1]
        assert last_url == reverse("welcoming_tour:index")

        user = User.objects.get(email=invitation.email)
        self.assert_accepted_invitation(response, invitation, user)

    @respx.mock
    def test_accept_existing_user_not_logged_in_using_IC(self):
        invitation = SentEmployerInvitationFactory(email=OIDC_USERINFO["email"])
        user = EmployerFactory(email=OIDC_USERINFO["email"], has_completed_welcoming_tour=True)
        response = self.client.get(invitation.acceptance_link, follow=True)
        assert reverse("login:employer") in response.wsgi_request.get_full_path()
        assert not invitation.accepted
        next_url = reverse("invitations_views:join_siae", args=(invitation.pk,))
        previous_url = f"{reverse('login:employer')}?{urlencode({'next': next_url})}"
        params = {
            "user_kind": UserKind.EMPLOYER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        response = mock_oauth_dance(
            self.client,
            UserKind.EMPLOYER,
            user_email=user.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)

        assert response.context["user"].is_authenticated
        self.assert_accepted_invitation(response, invitation, user)

    def test_accept_invitation_logged_in_user(self):
        # A logged in user should log out before accepting an invitation.
        logged_in_user = EmployerFactory()
        self.client.force_login(logged_in_user)
        # Invitation for another user
        invitation = SentEmployerInvitationFactory(email="loutre@example.com")
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertRedirects(response, reverse("account_logout"))

    @respx.mock
    def test_accept_invitation_signup_wrong_email(self):
        invitation = SentEmployerInvitationFactory()
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_siae", args=(invitation.pk,))
        params = {
            "user_kind": KIND_EMPLOYER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        url = reverse("dashboard:index")
        response = mock_oauth_dance(
            self.client,
            KIND_EMPLOYER,
            # the login hint is different from OIDC_USERINFO["email"] which is used to create the IC account
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            expected_redirect_url=add_url_params(reverse("inclusion_connect:logout"), {"redirect_url": previous_url}),
        )
        # After logout, Inclusion connect redirects to previous_url (see redirect_url param in expected_redirect_url)
        response = self.client.get(previous_url, follow=True)
        # Signup should have failed : as the email used in IC isn't the one from the invitation
        assertMessages(
            response,
            [
                (
                    messages.ERROR,
                    "L’adresse e-mail que vous avez utilisée pour vous connecter avec "
                    "Inclusion Connect (michel@lestontons.fr) ne correspond pas à "
                    f"l’adresse e-mail de l’invitation ({invitation.email}).",
                )
            ],
        )
        assert response.wsgi_request.get_full_path() == previous_url
        assert not User.objects.filter(email=invitation.email).exists()

    def test_expired_invitation(self):
        invitation = ExpiredEmployerInvitationFactory()
        assert invitation.has_expired

        # User wants to join our website but it's too late!
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, "expirée")

        user = EmployerFactory(email=invitation.email)
        self.client.force_login(user)
        join_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": invitation.id})
        response = self.client.get(join_url, follow=True)
        self.assertContains(response, escape("Cette invitation n'est plus valide."))

    def test_inactive_siae(self):
        siae = SiaeFactory(convention__is_active=False)
        invitation = SentEmployerInvitationFactory(siae=siae)
        user = EmployerFactory(email=invitation.email)
        self.client.force_login(user)
        join_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": invitation.id})
        response = self.client.get(join_url, follow=True)
        self.assertContains(response, escape("Cette structure n'est plus active."))

    def test_non_existent_invitation(self):
        invitation = SentEmployerInvitationFactory.build(
            first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com"
        )
        response = self.client.get(invitation.acceptance_link, follow=True)
        assert response.status_code == 404

    def test_accepted_invitation(self):
        invitation = SentEmployerInvitationFactory(accepted=True)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, escape("Invitation acceptée"))

    def test_accept_existing_user_already_member_of_inactive_siae(self):
        """
        An inactive SIAE user (i.e. attached to a single inactive SIAE)
        can only be ressucitated by being invited to a new SIAE.
        We test here that this is indeed possible.
        """
        siae = SiaeFactory(with_membership=True)
        sender = siae.members.first()
        user = SiaeFactory(convention__is_active=False, with_membership=True).members.first()
        invitation = SentEmployerInvitationFactory(
            sender=sender,
            siae=siae,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        self.client.force_login(user)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertRedirects(response, reverse("welcoming_tour:index"))
        # /invitations/<uui>/join_siae then /welcoming_tour/index
        assert len(response.redirect_chain) == 2

        current_siae = get_current_siae_or_404(response.wsgi_request)
        assert siae.pk == current_siae.pk
        self.assert_accepted_invitation(response, invitation, user)

    @respx.mock
    def test_accept_new_user_to_inactive_siae(self):
        siae = SiaeFactory(convention__is_active=False, with_membership=True)
        sender = siae.members.first()
        invitation = SentEmployerInvitationFactory(
            sender=sender,
            siae=siae,
            email=OIDC_USERINFO["email"],
        )
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, escape("La structure que vous souhaitez rejoindre n'est plus active."))
        self.assertNotContains(response, "logo-inclusion-connect-one-line.svg")

        # If the user still manages to signup with IC
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_siae", args=(invitation.pk,))
        response = mock_oauth_dance(
            self.client,
            KIND_EMPLOYER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertContains(response, escape("Cette structure n'est plus active."))
        user = User.objects.get(email=invitation.email)
        assert user.company_set.count() == 0

    def test_accept_existing_user_is_not_employer(self):
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        invitation = SentEmployerInvitationFactory(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )

        self.client.force_login(user)
        response = self.client.get(invitation.acceptance_link, follow=True)

        assert response.status_code == 403
        assert not invitation.accepted

    def test_accept_connected_user_is_not_the_invited_user(self):
        invitation = SentEmployerInvitationFactory()
        self.client.force_login(invitation.sender)
        response = self.client.get(invitation.acceptance_link, follow=True)

        assert reverse("account_logout") == response.wsgi_request.path
        assert not invitation.accepted
        self.assertContains(response, "Un utilisateur est déjà connecté.")

    def test_accept_existing_user_email_different_case(self):
        user = EmployerFactory(has_completed_welcoming_tour=True, email="HEY@example.com")
        invitation = SentEmployerInvitationFactory(
            email="hey@example.com",
        )
        self.client.force_login(user)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assert_accepted_invitation(response, invitation, user)

    def test_invitatin_old_link(self):
        # A logged in user should log out before accepting an invitation.
        logged_in_user = EmployerFactory()
        self.client.force_login(logged_in_user)
        # Invitation for another user
        invitation = SentEmployerInvitationFactory(email=logged_in_user.email)
        acceptance_link = reverse(
            "invitations_views:new_user",
            kwargs={
                "invitation_type": "siae_staff",
                "invitation_id": invitation.pk,
            },
        )
        response = self.client.get(acceptance_link, follow=True)
        self.assertRedirects(response, reverse("welcoming_tour:index"))
        self.assert_accepted_invitation(response, invitation, logged_in_user)
