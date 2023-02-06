from urllib.parse import urlencode

import respx
from django.conf import settings
from django.contrib.messages import get_messages
from django.core import mail
from django.shortcuts import reverse
from django.utils.html import escape

from itou.invitations.factories import ExpiredSiaeStaffInvitationFactory, SentSiaeStaffInvitationFactory
from itou.openid_connect.inclusion_connect.testing import InclusionConnectBaseTestCase
from itou.openid_connect.inclusion_connect.tests import OIDC_USERINFO, mock_oauth_dance
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeFactory
from itou.users.enums import KIND_SIAE_STAFF, UserKind
from itou.users.factories import SiaeStaffFactory
from itou.users.models import User
from itou.utils.perms.siae import get_current_siae_or_404


class TestAcceptInvitation(InclusionConnectBaseTestCase):
    def assert_accepted_invitation(self, response, invitation, user):
        user.refresh_from_db()
        invitation.refresh_from_db()
        assert user.kind == UserKind.SIAE_STAFF
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
        assert current_siae in user.siae_set.all()

    @respx.mock
    def test_accept_invitation_signup_(self):
        invitation = SentSiaeStaffInvitationFactory(email=OIDC_USERINFO["email"])
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_siae", args=(invitation.pk,))
        params = {
            "user_kind": KIND_SIAE_STAFF,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        total_users_before = User.objects.count()

        response = mock_oauth_dance(
            self,
            KIND_SIAE_STAFF,
            assert_redirects=False,
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

    def test_accept_invitation_logged_in_user(self):
        # A logged in user should log out before accepting an invitation.
        logged_in_user = SiaeStaffFactory()
        self.client.force_login(logged_in_user)
        # Invitation for another user
        invitation = SentSiaeStaffInvitationFactory(email="loutre@example.com")
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertRedirects(response, reverse("account_logout"))

    @respx.mock
    def test_accept_invitation_signup_wrong_email(self):
        invitation = SentSiaeStaffInvitationFactory()
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertContains(response, "logo-inclusion-connect-one-line.svg")

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_siae", args=(invitation.pk,))
        params = {
            "user_kind": KIND_SIAE_STAFF,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{reverse('inclusion_connect:authorize')}?{urlencode(params)}")
        self.assertContains(response, url + '"')

        url = reverse("dashboard:index")
        response = mock_oauth_dance(
            self,
            KIND_SIAE_STAFF,
            assert_redirects=False,
            # the login hint is different from OIDC_USERINFO["email"] which is used to create the IC account
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        # Signup should have failed : as the email used in IC isn't the one from the invitation
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "ne correspond pas à l’adresse e-mail de l’invitation" in messages[0].message
        assert response.wsgi_request.get_full_path() == previous_url
        assert not User.objects.filter(email=invitation.email).exists()

    def test_expired_invitation(self):
        invitation = ExpiredSiaeStaffInvitationFactory()
        assert invitation.has_expired

        # User wants to join our website but it's too late!
        response = self.client.get(invitation.acceptance_link, follow=True)
        assert response.status_code == 200
        self.assertContains(response, "expirée")

        user = SiaeStaffFactory(email=invitation.email)
        self.client.force_login(user)
        join_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": invitation.id})
        response = self.client.get(join_url, follow=True)
        self.assertContains(response, escape("Cette invitation n'est plus valide."))

    def test_inactive_siae(self):
        siae = SiaeFactory(convention__is_active=False)
        invitation = SentSiaeStaffInvitationFactory(siae=siae)
        user = SiaeStaffFactory(email=invitation.email)
        self.client.force_login(user)
        join_url = reverse("invitations_views:join_siae", kwargs={"invitation_id": invitation.id})
        response = self.client.get(join_url, follow=True)
        self.assertContains(response, escape("Cette structure n'est plus active."))

    def test_non_existent_invitation(self):
        invitation = SentSiaeStaffInvitationFactory.build(
            first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com"
        )
        response = self.client.get(invitation.acceptance_link, follow=True)
        assert response.status_code == 404

    def test_accepted_invitation(self):
        invitation = SentSiaeStaffInvitationFactory(accepted=True)
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
        invitation = SentSiaeStaffInvitationFactory(
            sender=sender,
            siae=siae,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        self.client.force_login(user)
        response = self.client.get(invitation.acceptance_link, follow=True)
        self.assertRedirects(response, reverse("welcoming_tour:index"))

        current_siae = get_current_siae_or_404(response.wsgi_request)
        assert siae.pk == current_siae.pk
        self.assert_accepted_invitation(response, invitation, user)

    @respx.mock
    def test_accept_new_user_to_inactive_siae(self):
        siae = SiaeFactory(convention__is_active=False, with_membership=True)
        sender = siae.members.first()
        invitation = SentSiaeStaffInvitationFactory(
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
            self,
            KIND_SIAE_STAFF,
            assert_redirects=False,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = self.client.get(response.url, follow=True)
        self.assertContains(response, escape("Cette structure n'est plus active."))
        user = User.objects.get(email=invitation.email)
        assert user.siae_set.count() == 0

    def test_accept_existing_user_is_not_employer(self):
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        invitation = SentSiaeStaffInvitationFactory(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )

        self.client.force_login(user)
        response = self.client.get(invitation.acceptance_link, follow=True)

        assert response.status_code == 403
        assert not invitation.accepted

    def test_accept_connected_user_is_not_the_invited_user(self):
        invitation = SentSiaeStaffInvitationFactory()
        self.client.force_login(invitation.sender)
        response = self.client.get(invitation.acceptance_link, follow=True)

        assert reverse("account_logout") == response.wsgi_request.path
        assert not invitation.accepted
        self.assertContains(response, "Un utilisateur est déjà connecté.")
