import random
from urllib.parse import urlencode

import pytest
import respx
from django.conf import settings
from django.contrib import messages
from django.shortcuts import reverse
from django.utils.html import escape
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.invitations.models import EmployerInvitation
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.perms.company import get_current_company_or_404
from itou.utils.urls import add_url_params
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.invitations.factories import EmployerInvitationFactory
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.test import ItouClient, assert_previous_step


INVITATION_URL = reverse("invitations_views:invite_employer")


class TestSendCompanyInvitation:
    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.company = CompanyFactory(with_membership=True)
        self.sender = self.company.members.first()
        self.guest_data = {"first_name": "Léonie", "last_name": "Bathiat", "email": "leonie@example.com"}
        self.post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": self.guest_data["first_name"],
            "form-0-last_name": self.guest_data["last_name"],
            "form-0-email": self.guest_data["email"],
        }
        client.force_login(self.sender)

    def assert_created_invitation(self):
        invitation = EmployerInvitation.objects.get(company=self.company)
        assert invitation.first_name == self.post_data["form-0-first_name"]
        assert invitation.last_name == self.post_data["form-0-last_name"]
        assert invitation.email == self.post_data["form-0-email"]
        assert invitation.company == self.company

    def test_invite_previous_step_link(self, client):
        response = client.get(INVITATION_URL)
        assert_previous_step(response, reverse("companies_views:members"))

    @freeze_time("2025-4-10")
    def test_invite_not_existing_user(self, client, mailoutbox):
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS,
                    (
                        "Collaborateur ajouté||Pour rejoindre votre organisation, il suffira à votre collaborateur "
                        "de cliquer sur le lien d'activation contenu dans l'e-mail avant le 24 avril 2025."
                    ),
                    extra_tags="toast",
                ),
            ],
        )
        self.assert_created_invitation()

        # Make sure an email has been sent to the invited person
        outbox_emails = [receiver for message in mailoutbox for receiver in message.to]
        assert self.post_data["form-0-email"] in outbox_emails

    def test_invite_existing_user(self, client):
        guest = EmployerFactory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertRedirects(response, reverse("companies_views:members"))
        self.assert_created_invitation()

    def test_invite_multiple_users(self, client):
        guest = EmployerFactory.build()
        self.post_data["form-TOTAL_FORMS"] = "2"
        self.post_data["form-1-first_name"] = guest.first_name
        self.post_data["form-1-last_name"] = guest.last_name
        self.post_data["form-1-email"] = self.post_data["form-0-email"]
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertContains(
            response,
            escape("Les collaborateurs doivent avoir des adresses e-mail différentes."),
        )
        assert EmployerInvitation.objects.count() == 0

        self.post_data["form-1-email"] = guest.email
        client.post(INVITATION_URL, data=self.post_data, follow=True)
        assert EmployerInvitation.objects.count() == 2

    def test_invite_former_member(self, client):
        """
        Admins can "deactivate" members of the organization (making the membership inactive).
        A deactivated member must be able to receive new invitations.
        """
        # Invite user (part 1)
        guest = EmployerFactory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertRedirects(response, reverse("companies_views:members"))
        self.assert_created_invitation()

        # Deactivate user
        self.company.members.add(guest)
        guest.save()
        membership = guest.companymembership_set.first()
        self.company.deactivate_membership(membership, updated_by=self.company.members.first())
        assert guest not in self.company.active_members
        # Invite user (the revenge)
        response = client.post(INVITATION_URL, data=self.post_data, follow=True)
        assertRedirects(response, reverse("companies_views:members"))
        assert EmployerInvitation.objects.filter(company=self.company).count() == 2

    def test_two_employers_invite_the_same_guest(self, client):
        # company 1 invites guest.
        client.post(INVITATION_URL, data=self.post_data, follow=True)
        assert EmployerInvitation.objects.count() == 1

        # company 2 invites guest as well.
        company = CompanyFactory(with_membership=True)
        sender_2 = company.members.first()
        client.force_login(sender_2)
        client.post(INVITATION_URL, data=self.post_data)
        assert EmployerInvitation.objects.count() == 2
        invitation = EmployerInvitation.objects.get(company=company)
        assert invitation.first_name == self.guest_data["first_name"]
        assert invitation.last_name == self.guest_data["last_name"]
        assert invitation.email == self.guest_data["email"]


class TestSendCompanyInvitationExceptions:
    @pytest.fixture(autouse=True)
    def setup_method(self, client):
        self.company = CompanyFactory(with_membership=True)
        self.sender = self.company.members.first()
        client.force_login(self.sender)

    def assert_invalid_user(self, response, reason):
        assert not response.context["formset"].is_valid()
        assert response.context["formset"].errors[0]["email"][0] == reason
        assert not EmployerInvitation.objects.exists()

    def test_invite_existing_user_is_bad_kind(self, client):
        guest = random.choice([JobSeekerFactory, PrescriberFactory, LaborInspectorFactory, ItouStaffFactory])()
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }

        response = client.post(INVITATION_URL, data=post_data)
        assert response.status_code == 200
        self.assert_invalid_user(response, "Cet utilisateur n'est pas un employeur.")

    def test_already_a_member(self, client):
        # The invited user is already a member
        guest = EmployerFactory()
        self.company.members.add(guest)
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }
        response = client.post(INVITATION_URL, data=post_data)
        assert response.status_code == 200
        self.assert_invalid_user(response, "Cette personne fait déjà partie de votre structure.")


class TestAcceptCompanyInvitation:
    def assert_invitation_is_accepted(self, response, user, invitation, mailoutbox):
        user.refresh_from_db()
        invitation.refresh_from_db()
        assert user.kind == UserKind.EMPLOYER

        assert invitation.accepted_at
        assert invitation.company.members.count() == 2

        # Make sure there's a welcome message.
        assertContains(
            response, escape(f"Vous êtes désormais membre de la structure {invitation.company.display_name}.")
        )
        assertNotContains(response, escape("Ce lien n'est plus valide."))

        # A confirmation e-mail is sent to the invitation sender.
        assert len(mailoutbox) == 1
        assert len(mailoutbox[0].to) == 1
        assert invitation.sender.email == mailoutbox[0].to[0]

        # Assert the user sees his new siae dashboard
        current_company = get_current_company_or_404(response.wsgi_request)
        # A user can be member of one or more siae
        assert current_company in user.company_set.all()

    @respx.mock
    def test_accept_new_user(self, client, mailoutbox, pro_connect):
        invitation = EmployerInvitationFactory(email=pro_connect.oidc_userinfo["email"])
        response = client.get(invitation.acceptance_link, follow=True)
        pro_connect.assertContainsButton(response)

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_company", args=(invitation.pk,))
        params = {
            "user_kind": UserKind.EMPLOYER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.EMPLOYER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url, follow=True)
        assertRedirects(response, reverse("welcoming_tour:index"))

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    @respx.mock
    def test_accept_invitation_signup_returns_on_other_browser(self, client, mailoutbox, pro_connect):
        invitation = EmployerInvitationFactory(email=pro_connect.oidc_userinfo["email"])
        response = client.get(invitation.acceptance_link)
        pro_connect.assertContainsButton(response)

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_company", args=(invitation.pk,))
        params = {
            "user_kind": UserKind.EMPLOYER,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        other_client = ItouClient()
        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.EMPLOYER,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            other_client=other_client,
        )
        response = other_client.get(response.url, follow=True)

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    @respx.mock
    def test_auto_accept_invitation_on_ProConnect_login(self, client, mailoutbox, pro_connect):
        # The user's invitations are automatically accepted at login
        invitation = EmployerInvitationFactory(email=pro_connect.oidc_userinfo["email"])

        response = pro_connect.mock_oauth_dance(
            client,
            UserKind.EMPLOYER,
            user_email=invitation.email,
        )
        assertRedirects(response, reverse("welcoming_tour:index"), fetch_redirect_response=False)
        response = client.get(response.url, follow=True)

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_auto_accept_invitation_on_django_login(self, client, mailoutbox, settings):
        settings.FORCE_PROCONNECT_LOGIN = False
        user = EmployerFactory(with_verified_email=True)
        invitation = EmployerInvitationFactory(email=user.email)

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(reverse("login:employer"), data=form_data)
        assertRedirects(response, reverse("welcoming_tour:index"), fetch_redirect_response=False)
        response = client.get(response.url)

        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user(self, client, mailoutbox):
        user = EmployerFactory(with_company=True, has_completed_welcoming_tour=True)
        invitation = EmployerInvitationFactory(email=user.email)
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        # /invitations/<uuid>/join_company then /dashboard
        assert len(response.redirect_chain) == 2
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user_email_different_case(self, client, mailoutbox):
        user = EmployerFactory(has_completed_welcoming_tour=True)
        invitation = EmployerInvitationFactory(email=user.email.upper())
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user_already_belongs_to_another_company(self, client, mailoutbox):
        user = CompanyMembershipFactory().user
        invitation = EmployerInvitationFactory(email=user.email)
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("welcoming_tour:index"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)
        assert user.company_set.count() == 2

    def test_accept_existing_user_already_belongs_to_another_inactive_company(self, client, mailoutbox):
        """
        An inactive SIAE user (i.e. attached to a single inactive SIAE)
        can only be ressucitated by being invited to a new SIAE.
        We test here that this is indeed possible.
        """
        user = CompanyMembershipFactory(company__convention__is_active=False).user
        invitation = EmployerInvitationFactory(email=user.email)
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("welcoming_tour:index"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)
        assert user.company_set.count() == 2

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
        response = client.get(response.url, follow=True)
        assertRedirects(response, reverse("dashboard:index"))

        assert response.context["user"].is_authenticated
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_accept_existing_user_not_logged_in_using_django_auth(self, client, mailoutbox):
        user = EmployerFactory(has_completed_welcoming_tour=True, identity_provider="DJANGO", with_verified_email=True)
        invitation = EmployerInvitationFactory(email=user.email)
        response = client.get(invitation.acceptance_link, follow=True)
        assert reverse("login:employer") in response.wsgi_request.get_full_path()
        assert not invitation.accepted_at

        response = client.post(
            response.wsgi_request.get_full_path(),
            data={"login": user.email, "password": DEFAULT_PASSWORD},
            follow=True,
        )
        assert response.context["user"].is_authenticated
        assertRedirects(response, reverse("dashboard:activate_pro_connect_account"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)


class TestAcceptCompanyInvitationExceptions:
    def test_existing_user_is_bad_kind(self, client):
        user = random.choice([JobSeekerFactory, PrescriberFactory, LaborInspectorFactory, ItouStaffFactory])()
        invitation = EmployerInvitationFactory(email=user.email)

        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assert response.status_code == 403
        invitation.refresh_from_db()
        assert not invitation.accepted_at

    def test_connected_user_is_not_the_invited_user(self, client):
        invitation = EmployerInvitationFactory()
        client.force_login(EmployerFactory(with_company=True))
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("account_logout"))
        invitation.refresh_from_db()
        assert not invitation.accepted_at
        assertContains(response, escape("Un utilisateur est déjà connecté."))

    @respx.mock
    def test_accept_invitation_signup_wrong_email(self, client, pro_connect):
        invitation = EmployerInvitationFactory()
        response = client.get(invitation.acceptance_link, follow=True)
        pro_connect.assertContainsButton(response)

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = reverse("invitations_views:join_company", args=(invitation.pk,))
        params = {
            "user_kind": UserKind.EMPLOYER,
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
            UserKind.EMPLOYER,
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

    def test_expired_invitation_with_new_user(self, client):
        invitation = EmployerInvitationFactory(expired=True)

        # User wants to join our website but it's too late!
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Lien d'activation expiré"), html=True)
        assertContains(response, escape("Ce lien n'est plus valide"))

    def test_expired_invitation_with_existing_user(self, client):
        user = EmployerFactory()
        invitation = EmployerInvitationFactory(expired=True, email=user.email)

        # GET or POST in this case
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Ce lien n'est plus valide."))

        client.force_login(user)
        # Try to bypass the first check by directly reaching the join endpoint
        join_url = reverse("invitations_views:join_company", kwargs={"invitation_id": invitation.id})
        response = client.get(join_url, follow=True)
        # The 2 views return the same error message
        assertContains(response, escape("Ce lien n'est plus valide."))

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
