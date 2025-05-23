from urllib.parse import urlencode

import respx
from django.conf import settings
from django.contrib import messages
from django.shortcuts import reverse
from django.utils.html import escape
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.users.enums import KIND_EMPLOYER, UserKind
from itou.users.models import User
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.templatetags.theme_inclusion import static_theme_images
from itou.utils.urls import add_url_params
from tests.companies.factories import CompanyFactory
from tests.invitations.factories import EmployerInvitationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import DEFAULT_PASSWORD, EmployerFactory
from tests.utils.test import ItouClient


class TestAcceptInvitation:
    def assert_accepted_invitation(self, response, invitation, user, mailoutbox):
        user.refresh_from_db()
        invitation.refresh_from_db()
        assert user.kind == UserKind.EMPLOYER
        assert invitation.accepted_at

        # A confirmation e-mail is sent to the invitation sender.
        assert len(mailoutbox) == 1
        assert len(mailoutbox[0].to) == 1
        assert invitation.sender.email == mailoutbox[0].to[0]

        # Make sure there's a welcome message.
        assertContains(
            response, escape(f"Vous êtes désormais membre de la structure {invitation.company.display_name}.")
        )
        assertNotContains(response, escape("Ce lien n'est plus valide."))

        # Assert the user sees his new siae dashboard
        current_company = get_current_company_or_404(response.wsgi_request)
        # A user can be member of one or more siae
        assert current_company in user.company_set.all()

    @respx.mock
    def test_accept_invitation_signup(self, client, mailoutbox, pro_connect):
        invitation = EmployerInvitationFactory(email=pro_connect.oidc_userinfo["email"])
        response = client.get(invitation.acceptance_link, follow=True)
        pro_connect.assertContainsButton(response)

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_company", args=(invitation.pk,))
        params = {
            "user_kind": KIND_EMPLOYER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        total_users_before = User.objects.count()

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url, follow=True)
        # Check user is redirected to the welcoming tour
        last_url, _status_code = response.redirect_chain[-1]
        assert last_url == reverse("welcoming_tour:index")

        total_users_after = User.objects.count()
        assert (total_users_before + 1) == total_users_after

        user = User.objects.get(email=invitation.email)
        self.assert_accepted_invitation(response, invitation, user, mailoutbox)

    @respx.mock
    def test_accept_invitation_signup_returns_on_other_browser(self, client, mailoutbox, pro_connect):
        invitation = EmployerInvitationFactory(email=pro_connect.oidc_userinfo["email"])
        response = client.get(invitation.acceptance_link, follow=True)
        pro_connect.assertContainsButton(response)

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_company", args=(invitation.pk,))
        params = {
            "user_kind": KIND_EMPLOYER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        total_users_before = User.objects.count()

        # coming back from another browser without the next_url
        other_client = ItouClient()
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            other_client=other_client,
        )
        response = other_client.get(response.url, follow=True)

        total_users_after = User.objects.count()
        assert (total_users_before + 1) == total_users_after

        user = User.objects.get(email=invitation.email)
        self.assert_accepted_invitation(response, invitation, user, mailoutbox)

    @respx.mock
    def test_auto_accept_invitation_on_pro_connect_login(self, client, mailoutbox, pro_connect):
        # The user's invitations are automatically accepted at login
        invitation = EmployerInvitationFactory(email=pro_connect.oidc_userinfo["email"])

        total_users_before = User.objects.count()

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            user_email=invitation.email,
        )
        response = client.get(response.url, follow=True)

        total_users_after = User.objects.count()
        assert (total_users_before + 1) == total_users_after

        user = User.objects.get(email=invitation.email)
        self.assert_accepted_invitation(response, invitation, user, mailoutbox)

    def test_auto_accept_invitation_on_django_login(self, client, mailoutbox, settings):
        settings.FORCE_PROCONNECT_LOGIN = False
        # The user's invitations are automatically accepted at login
        user = EmployerFactory()
        user.emailaddress_set.create(email=user.email, verified=True, primary=True)
        invitation = EmployerInvitationFactory(email=user.email)

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(reverse("login:employer"), data=form_data)
        assertRedirects(response, reverse("welcoming_tour:index"), fetch_redirect_response=False)
        response = client.get(response.url)

        self.assert_accepted_invitation(response, invitation, user, mailoutbox)

    @respx.mock
    def test_accept_invitation_signup_bad_email_case(self, client, mailoutbox, pro_connect):
        invitation = EmployerInvitationFactory(email=pro_connect.oidc_userinfo["email"].upper())
        response = client.get(invitation.acceptance_link, follow=True)
        pro_connect.assertContainsButton(response)

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_company", args=(invitation.pk,))
        params = {
            "user_kind": KIND_EMPLOYER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        assert User.objects.filter(email=invitation.email).first() is None

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            # Using the same email with a different case should not fail
            user_email=invitation.email.lower(),
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url, follow=True)
        # Check user is redirected to the welcoming tour
        last_url, _ = response.redirect_chain[-1]
        assert last_url == reverse("welcoming_tour:index")

        user = User.objects.get(email=invitation.email)
        self.assert_accepted_invitation(response, invitation, user, mailoutbox)

    @respx.mock
    def test_accept_existing_user_not_logged_in_using_ProConnect(self, client, mailoutbox, pro_connect):
        invitation = EmployerInvitationFactory(email=pro_connect.oidc_userinfo["email"])
        user = EmployerFactory(
            username=pro_connect.oidc_userinfo["sub"],
            email=pro_connect.oidc_userinfo["email"],
            has_completed_welcoming_tour=True,
        )
        response = client.get(invitation.acceptance_link, follow=True)
        assert reverse("login:employer") in response.wsgi_request.get_full_path()
        assert not invitation.accepted_at
        next_url = reverse("invitations_views:join_company", args=(invitation.pk,))
        previous_url = f"{reverse('login:employer')}?{urlencode({'next': next_url})}"
        params = {
            "user_kind": UserKind.EMPLOYER,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.EMPLOYER,
            user_email=user.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)

        assert response.context["user"].is_authenticated
        self.assert_accepted_invitation(response, invitation, user, mailoutbox)

    def test_accept_invitation_logged_in_user(self, client):
        # A logged in user should log out before accepting an invitation.
        logged_in_user = EmployerFactory()
        client.force_login(logged_in_user)
        # Invitation for another user
        invitation = EmployerInvitationFactory(email="loutre@example.com")
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("account_logout"))

    @respx.mock
    def test_accept_invitation_signup_wrong_email(self, client, pro_connect):
        invitation = EmployerInvitationFactory()
        response = client.get(invitation.acceptance_link, follow=True)
        pro_connect.assertContainsButton(response)

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_company", args=(invitation.pk,))
        params = {
            "user_kind": KIND_EMPLOYER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        url = reverse("dashboard:index")
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            # the login hint is different from the email used to create the SSO account
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            expected_redirect_url=add_url_params(pro_connect.logout_url, {"redirect_url": previous_url}),
        )
        # After logout, the SSO redirects to previous_url (see redirect_url param in expected_redirect_url)
        response = client.get(previous_url, follow=True)
        # Signup should have failed : as the email used in IC isn't the one from the invitation
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "L’adresse e-mail que vous avez utilisée pour vous connecter avec "
                    f"{pro_connect.identity_provider.label} (michel@lestontons.fr) ne correspond pas à "
                    f"l’adresse e-mail de l’invitation ({invitation.email}).",
                )
            ],
        )
        assert response.wsgi_request.get_full_path() == previous_url
        assert not User.objects.filter(email=invitation.email).exists()

    def test_expired_invitation(self, client):
        invitation = EmployerInvitationFactory(expired=True)
        assert invitation.has_expired

        # User wants to join our website but it's too late!
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Lien d'activation expiré"), html=True)

        user = EmployerFactory(email=invitation.email)
        client.force_login(user)
        join_url = reverse("invitations_views:join_company", kwargs={"invitation_id": invitation.id})
        response = client.get(join_url, follow=True)
        assertContains(response, escape("Ce lien n'est plus valide"))

    def test_inactive_siae(self, client):
        company = CompanyFactory(convention__is_active=False, with_membership=True)
        invitation = EmployerInvitationFactory(company=company)
        user = EmployerFactory(email=invitation.email)
        client.force_login(user)
        join_url = reverse("invitations_views:join_company", kwargs={"invitation_id": invitation.id})
        response = client.get(join_url, follow=True)
        assertContains(response, escape("Cette structure n'est plus active."))

    def test_non_existent_invitation(self, client):
        invitation = EmployerInvitationFactory(first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com")
        url = invitation.acceptance_link
        invitation.delete()
        response = client.get(url, follow=True)
        assert response.status_code == 404

    def test_accepted_invitation(self, client):
        invitation = EmployerInvitationFactory(accepted=True)
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Lien d'activation déjà accepté"), html=True)

    def test_accept_existing_user_already_member_of_inactive_siae(self, client, mailoutbox):
        """
        An inactive SIAE user (i.e. attached to a single inactive SIAE)
        can only be ressucitated by being invited to a new SIAE.
        We test here that this is indeed possible.
        """
        company = CompanyFactory(with_membership=True)
        sender = company.members.first()
        user = CompanyFactory(convention__is_active=False, with_membership=True).members.first()
        invitation = EmployerInvitationFactory(
            sender=sender,
            company=company,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("welcoming_tour:index"))
        # /invitations/<uui>/join-company then /welcoming_tour/index
        assert len(response.redirect_chain) == 2

        current_company = get_current_company_or_404(response.wsgi_request)
        assert company.pk == current_company.pk
        self.assert_accepted_invitation(response, invitation, user, mailoutbox)

    @respx.mock
    def test_accept_new_user_to_inactive_siae(self, client, pro_connect):
        company = CompanyFactory(convention__is_active=False, with_membership=True)
        sender = company.members.first()
        invitation = EmployerInvitationFactory(
            sender=sender,
            company=company,
            email=pro_connect.oidc_userinfo["email"],
        )
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("La structure que vous souhaitez rejoindre n'est plus active."))
        assertNotContains(response, static_theme_images("logo-inclusion-connect-one-line.svg"))

        # If the user still manages to signup with IC
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_company", args=(invitation.pk,))
        response = pro_connect.mock_oauth_dance(
            client,
            KIND_EMPLOYER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        # Follow the redirection.
        response = client.get(response.url, follow=True)
        assertRedirects(response, reverse("logout:warning", kwargs={"kind": "employer_no_company"}))

        user = User.objects.get(email=invitation.email)
        assert user.company_set.count() == 0

    def test_accept_existing_user_is_not_employer(self, client):
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        invitation = EmployerInvitationFactory(
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
        )

        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)

        assert response.status_code == 403
        assert not invitation.accepted_at

    def test_accept_connected_user_is_not_the_invited_user(self, client):
        invitation = EmployerInvitationFactory()
        client.force_login(invitation.sender)
        response = client.get(invitation.acceptance_link, follow=True)

        assert reverse("account_logout") == response.wsgi_request.path
        assert not invitation.accepted_at
        assertContains(response, "Un utilisateur est déjà connecté.")

    def test_accept_existing_user_email_different_case(self, client, mailoutbox):
        user = EmployerFactory(has_completed_welcoming_tour=True, email="HEY@example.com")
        invitation = EmployerInvitationFactory(
            email="hey@example.com",
        )
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        self.assert_accepted_invitation(response, invitation, user, mailoutbox)

    def test_expired_invitation_old_link(self, client):
        user = EmployerFactory()
        # Invitation for another user
        invitation = EmployerInvitationFactory(email=user.email)
        acceptance_link = reverse(
            "invitations_views:new_user",
            kwargs={
                "invitation_type": "siae_staff",
                "invitation_id": invitation.pk,
            },
        )
        response = client.get(acceptance_link, follow=True)
        assertRedirects(response, reverse("search:employers_home"))
        invitation.refresh_from_db()
        assert not invitation.accepted_at
