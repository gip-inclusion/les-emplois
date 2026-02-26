import random
from functools import partial
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.shortcuts import reverse
from django.urls import reverse_lazy
from django.utils.html import escape
from freezegun import freeze_time
from itoutils.urls import add_url_params
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertNotContains,
    assertRedirects,
)

from itou.invitations.models import EmployerInvitation, LaborInspectorInvitation, PrescriberWithOrgInvitation
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.users.enums import UserKind
from itou.users.models import User
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory
from tests.invitations.factories import (
    EmployerInvitationFactory,
    LaborInspectorInvitationFactory,
    PrescriberWithOrgInvitationFactory,
)
from tests.openid_connect.pro_connect.testing import ID_TOKEN
from tests.prescribers.factories import PrescriberMembershipFactory, PrescriberOrganizationFactory
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.testing import ItouClient, assert_previous_step


class PrescriberMixin:
    org_factory = staticmethod(partial(PrescriberOrganizationFactory, kind=PrescriberOrganizationKind.CAP_EMPLOI))
    org_name = "organization"
    membership_factory = PrescriberMembershipFactory
    user_factory = PrescriberFactory
    user_kind = UserKind.PRESCRIBER
    invitation_factory = PrescriberWithOrgInvitationFactory
    invitation_model = PrescriberWithOrgInvitation
    invitation_url = reverse_lazy("invitations_views:invite_prescriber_with_org")
    members_url = reverse_lazy("prescribers_views:members")
    login_url = reverse_lazy("login:prescriber")

    def join_url(self, invitation):
        return reverse("invitations_views:join_prescriber_organization", kwargs={"invitation_id": invitation.id})


class CompanyMixin:
    org_factory = CompanyFactory
    membership_factory = CompanyMembershipFactory
    org_name = "company"
    user_factory = EmployerFactory
    user_kind = UserKind.EMPLOYER
    invitation_factory = EmployerInvitationFactory
    invitation_model = EmployerInvitation
    invitation_url = reverse_lazy("invitations_views:invite_employer")
    members_url = reverse_lazy("companies_views:members")
    login_url = reverse_lazy("login:employer")

    def join_url(self, invitation):
        return reverse("invitations_views:join_company", kwargs={"invitation_id": invitation.id})


class InstitutionMixin:
    org_factory = InstitutionFactory
    membership_factory = InstitutionMembershipFactory
    org_name = "institution"
    user_factory = LaborInspectorFactory
    user_kind = UserKind.LABOR_INSPECTOR
    invitation_factory = LaborInspectorInvitationFactory
    invitation_model = LaborInspectorInvitation
    invitation_url = reverse_lazy("invitations_views:invite_labor_inspector")
    members_url = reverse_lazy("institutions_views:members")
    login_url = reverse_lazy("login:labor_inspector")

    def join_url(self, invitation):
        return reverse("invitations_views:join_institution", kwargs={"invitation_id": invitation.id})


class BaseTestSendInvitation:
    def setup_test(self, client):
        self.organization = self.org_factory()
        self.sender = self.membership_factory(**{self.org_name: self.organization}).user

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
        invitation = self.invitation_model.objects.get(**{self.org_name: self.organization})
        assert invitation.first_name == self.post_data["form-0-first_name"]
        assert invitation.last_name == self.post_data["form-0-last_name"]
        assert invitation.email == self.post_data["form-0-email"]
        assert getattr(invitation, self.org_name) == self.organization

    def assert_no_invitation(self, response, reason):
        assert not response.context["formset"].is_valid()
        assert response.context["formset"].errors[0]["email"][0] == reason
        assert not self.invitation_model.objects.exists()

    def test_previous_step_link(self, client):
        self.setup_test(client)
        response = client.get(self.invitation_url)
        assert_previous_step(response, self.members_url)

    @freeze_time("2025-04-10")
    def test_new_user(self, client, mailoutbox):
        self.setup_test(client)
        response = client.post(self.invitation_url, data=self.post_data, follow=True)
        assertRedirects(response, self.members_url)
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

    def test_existing_user(self, client):
        self.setup_test(client)
        guest = self.user_factory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = client.post(self.invitation_url, data=self.post_data, follow=True)
        assertRedirects(response, self.members_url)
        self.assert_created_invitation()

    def test_multiple_users(self, client):
        self.setup_test(client)
        guest = self.user_factory.build()
        self.post_data["form-TOTAL_FORMS"] = "2"
        self.post_data["form-1-first_name"] = guest.first_name
        self.post_data["form-1-last_name"] = guest.last_name
        self.post_data["form-1-email"] = self.post_data["form-0-email"]
        response = client.post(self.invitation_url, data=self.post_data, follow=True)
        assertContains(
            response,
            escape("Les collaborateurs doivent avoir des adresses e-mail différentes."),
        )
        assert self.invitation_model.objects.count() == 0

        self.post_data["form-1-email"] = guest.email
        client.post(self.invitation_url, data=self.post_data, follow=True)
        assert self.invitation_model.objects.count() == 2

    def test_former_member(self, client):
        """
        Admins can "deactivate" members of the organization (making the membership inactive).
        A deactivated member must be able to receive new invitations.
        """
        self.setup_test(client)
        # Invite user (part 1)
        guest = self.user_factory()
        self.post_data["form-0-first_name"] = guest.first_name
        self.post_data["form-0-last_name"] = guest.last_name
        self.post_data["form-0-email"] = guest.email
        response = client.post(self.invitation_url, data=self.post_data, follow=True)
        assertRedirects(response, self.members_url)
        self.assert_created_invitation()

        # Deactivate user
        membership = self.membership_factory(user=guest, **{self.org_name: self.organization})
        self.organization.deactivate_membership(membership, updated_by=self.organization.members.first())
        assert guest not in self.organization.active_members
        # Invite user (the revenge)
        response = client.post(self.invitation_url, data=self.post_data, follow=True)
        assertRedirects(response, self.members_url)
        assert self.invitation_model.objects.filter(**{self.org_name: self.organization}).count() == 2

    def test_two_institutions_invite_the_same_guest(self, client):
        self.setup_test(client)
        # institution 1 invites guest.
        client.post(self.invitation_url, data=self.post_data, follow=True)
        assert self.invitation_model.objects.count() == 1

        # institution 2 invites guest as well.
        organization_2 = self.org_factory()
        sender_2 = self.membership_factory(**{self.org_name: organization_2}).user
        client.force_login(sender_2)
        client.post(self.invitation_url, data=self.post_data)
        assert self.invitation_model.objects.count() == 2
        invitation = self.invitation_model.objects.get(**{self.org_name: organization_2})
        assert invitation.first_name == self.guest_data["first_name"]
        assert invitation.last_name == self.guest_data["last_name"]
        assert invitation.email == self.guest_data["email"]

    def test_too_many_invitations(self, client, monkeypatch):
        monkeypatch.setattr("itou.www.invitations_views.views.MAX_PENDING_INVITATION", 1)
        self.setup_test(client)
        self.invitation_factory(**{self.org_name: self.organization})
        response = client.get(self.invitation_url)
        assertRedirects(response, self.members_url)
        assertMessages(response, [messages.Message(messages.ERROR, "Vous ne pouvez avoir plus de 1 invitations.")])

    def test_limit_new_invitations(self, client, monkeypatch):
        monkeypatch.setattr("itou.www.invitations_views.views.MAX_PENDING_INVITATION", 1)
        self.setup_test(client)
        guest = self.user_factory.build()
        self.post_data["form-TOTAL_FORMS"] = "2"
        self.post_data["form-1-first_name"] = guest.first_name
        self.post_data["form-1-last_name"] = guest.last_name
        self.post_data["form-1-email"] = guest.email
        response = client.post(self.invitation_url, data=self.post_data, follow=True)
        assert response.status_code == 200
        assertContains(response, "Veuillez soumettre au plus 1 formulaire")
        assert self.invitation_model.objects.count() == 0

        self.post_data["form-TOTAL_FORMS"] = "1"
        del self.post_data["form-1-first_name"]
        del self.post_data["form-1-last_name"]
        del self.post_data["form-1-email"]
        response = client.post(self.invitation_url, data=self.post_data, follow=True)
        assertRedirects(response, self.members_url)
        assert self.invitation_model.objects.count() == 1

    def test_existing_user_has_bad_kind(self, client):
        self.setup_test(client)
        user_factory_choices = {
            JobSeekerFactory,
            EmployerFactory,
            PrescriberFactory,
            LaborInspectorFactory,
            ItouStaffFactory,
        } - {self.user_factory}
        guest = random.choice(list(user_factory_choices))()
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }

        response = client.post(self.invitation_url, data=post_data)
        assert response.status_code == 200
        if self.user_kind == UserKind.PRESCRIBER:
            self.assert_no_invitation(response, "Cet utilisateur n'est pas un prescripteur.")
        elif self.user_kind == UserKind.EMPLOYER:
            self.assert_no_invitation(response, "Cet utilisateur n'est pas un employeur.")
        else:
            self.assert_no_invitation(response, "Cet utilisateur n'est pas un inspecteur du travail.")

    def test_already_a_member(self, client):
        self.setup_test(client)
        # The invited user is already a member
        guest = self.user_factory()
        self.membership_factory(user=guest, **{self.org_name: self.organization})
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }
        response = client.post(self.invitation_url, data=post_data)
        assert response.status_code == 200
        if self.user_kind == UserKind.PRESCRIBER:
            self.assert_no_invitation(response, "Cette personne fait déjà partie de votre organisation.")
        else:
            self.assert_no_invitation(response, "Cette personne fait déjà partie de votre structure.")


class TestSendInstitutionInvitation(InstitutionMixin, BaseTestSendInvitation):
    pass


class TestSendPrescriberInvitation(PrescriberMixin, BaseTestSendInvitation):
    def test_new_user_with_prefill(self, client):
        self.setup_test(client)
        response = client.get(
            self.invitation_url, data={"first_name": "Emma", "last_name": "Watson", "email": "emma@example.com"}
        )
        # The form is prefilled with GET params (if valid)
        assertContains(response, "Emma")

    def test_prescriber_without_organization(self, client):
        client.force_login(PrescriberFactory())
        response = client.get(self.invitation_url)
        assert response.status_code == 403


class TestSendCompanyInvitation(CompanyMixin, BaseTestSendInvitation):
    pass


class BaseTestAcceptInvitation:
    def assert_invitation_is_accepted(self, response, user, invitation, mailoutbox):
        user.refresh_from_db()
        invitation.refresh_from_db()
        assert user.kind == self.user_kind

        assert invitation.accepted_at
        organization = getattr(invitation, self.org_name)
        assert organization.members.count() == 2

        # Make sure there's a welcome message.
        if self.user_kind == UserKind.EMPLOYER:
            assertContains(
                response, escape(f"Vous êtes désormais membre de la structure {organization.display_name}.")
            )
        else:
            assertContains(
                response, escape(f"Vous êtes désormais membre de l'organisation {organization.display_name}.")
            )
        assertNotContains(response, escape("Ce lien n'est plus valide."))

        # A confirmation e-mail is sent to the invitation sender.
        assert len(mailoutbox) == 1
        assert len(mailoutbox[0].to) == 1
        assert invitation.sender.email == mailoutbox[0].to[0]

        # Assert the user sees his new organization dashboard.
        assert response.wsgi_request.user == user
        assert response.wsgi_request.current_organization == organization

    def test_existing_user(self, client, mailoutbox):
        user = self.user_factory(has_completed_welcoming_tour=True)
        invitation = self.invitation_factory(email=user.email)
        client.force_login(user)

        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        # /invitations/<uuid>/join_xxxx then /dashboard
        assert len(response.redirect_chain) == 2
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_existing_user__different_email_case(self, client, mailoutbox):
        user = self.user_factory(has_completed_welcoming_tour=True)
        invitation = self.invitation_factory(email=user.email.upper())
        client.force_login(user)

        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_existing_user__belongs_to_another_organization(self, client, mailoutbox):
        user = self.membership_factory(user__has_completed_welcoming_tour=True).user
        invitation = self.invitation_factory(email=user.email)
        client.force_login(user)

        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)
        if self.user_kind == UserKind.PRESCRIBER:
            assert user.prescriberorganization_set.count() == 2
        elif self.user_kind == UserKind.EMPLOYER:
            assert user.company_set.count() == 2
        else:
            assert user.institution_set.count() == 2

    def test_existing_user__login_with_django(self, client, mailoutbox):
        user = self.user_factory(
            with_verified_email=True,
            has_completed_welcoming_tour=True,
            identity_provider="DJANGO",
        )
        invitation = self.invitation_factory(email=user.email)

        response = client.get(invitation.acceptance_link, follow=True)
        assert str(self.login_url) in response.wsgi_request.get_full_path()
        assert not invitation.accepted_at

        response = client.post(
            response.wsgi_request.get_full_path(),
            data={"login": user.email, "password": DEFAULT_PASSWORD},
            follow=True,
        )
        assert response.context["user"].is_authenticated
        if self.user_kind == UserKind.LABOR_INSPECTOR:
            assertRedirects(response, reverse("dashboard:index"))
        else:
            assertRedirects(response, reverse("dashboard:activate_pro_connect_account"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_auto_accept_invitation__django_login(self, client, mailoutbox):
        # The user's invitations are automatically accepted at login
        user = self.user_factory(
            with_verified_email=True,
            has_completed_welcoming_tour=True,
            identity_provider="DJANGO",
        )
        invitation = self.invitation_factory(email=user.email)

        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(self.login_url, data=form_data, follow=True)
        if self.user_kind == UserKind.LABOR_INSPECTOR:
            assertRedirects(response, reverse("dashboard:index"))
        else:
            assertRedirects(response, reverse("dashboard:activate_pro_connect_account"))
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_existing_user_has_bad_kind(self, client):
        user_factory_choices = {
            JobSeekerFactory,
            EmployerFactory,
            PrescriberFactory,
            LaborInspectorFactory,
            ItouStaffFactory,
        } - {self.user_factory}
        user = random.choice(list(user_factory_choices))()
        invitation = self.invitation_factory(email=user.email)

        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assert response.status_code == 403
        invitation.refresh_from_db()
        assert not invitation.accepted_at

    def test_connected_user_is_not_the_invited_user(self, client):
        invitation = self.invitation_factory()
        user = self.membership_factory().user
        client.force_login(user)
        response = client.get(invitation.acceptance_link, follow=True)
        assertRedirects(response, reverse("account_logout"))
        invitation.refresh_from_db()
        assert not invitation.accepted_at
        assertContains(response, escape("Un utilisateur est déjà connecté."))

    def test_expired_invitation_with_new_user(self, client):
        invitation = self.invitation_factory(expired=True)

        # User wants to join our website but it's too late!
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, "Lien d'activation expiré", html=True)
        assertContains(response, escape("Ce lien n'est plus valide."))

    def test_expired_invitation_with_existing_user(self, client):
        user = self.user_factory()
        invitation = self.invitation_factory(expired=True, email=user.email)

        # GET or POST in this case
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, escape("Ce lien n'est plus valide."))

        client.force_login(user)
        # Try to bypass the first check by directly reaching the join endpoint
        response = client.get(self.join_url(invitation), follow=True)
        # The 2 views return the same error message
        assertContains(response, escape("Ce lien n'est plus valide."))

    def test_non_existent_invitation(self, client):
        invitation = self.invitation_factory(first_name="Léonie", last_name="Bathiat", email="leonie@bathiat.com")
        url = invitation.acceptance_link
        invitation.delete()
        response = client.get(url, follow=True)
        assert response.status_code == 404

    def test_already_accepted_invitation(self, client):
        invitation = self.invitation_factory(accepted=True)
        response = client.get(invitation.acceptance_link, follow=True)
        assertContains(response, "Lien d'activation déjà accepté", html=True)


class DjangoSignupTestAcceptInvitation:
    def test_new_user__django_signup(self, client, mailoutbox):
        invitation = self.invitation_factory()
        form_data = {
            "first_name": "Joe",
            "last_name": "Dalton",
            "password1": DEFAULT_PASSWORD,
            "password2": DEFAULT_PASSWORD,
        }
        response = client.post(invitation.acceptance_link, data=form_data, follow=True)
        assertRedirects(response, reverse("dashboard:index"))

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)


class ProConnectSignupTestAcceptInvitation:
    def test_new_user__ProConnect_signup(self, client, mailoutbox, pro_connect):
        invitation = self.invitation_factory(email=pro_connect.oidc_userinfo["email"])
        response = client.get(invitation.acceptance_link, follow=True)
        pro_connect.assertContainsButton(response)

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = self.join_url(invitation)
        params = {
            "user_kind": self.user_kind,
            "user_email": invitation.email,
            "channel": "invitation",
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            self.user_kind,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url, follow=True)
        assertRedirects(response, reverse("welcoming_tour:index"))

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_new_user__ProConnect_signup__returns_on_other_browser(self, client, mailoutbox, pro_connect):
        invitation = self.invitation_factory(email=pro_connect.oidc_userinfo["email"])
        response = client.get(invitation.acceptance_link)
        pro_connect.assertContainsButton(response)

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = self.join_url(invitation)
        params = {
            "user_kind": self.user_kind,
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
            self.user_kind,
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            other_client=other_client,
        )
        response = other_client.get(response.url, follow=True)
        assertRedirects(response, reverse("welcoming_tour:index"))

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_auto_accept_invitation__ProConnect_login(self, client, mailoutbox, pro_connect):
        # The user's invitations are automatically accepted at login
        invitation = self.invitation_factory(email=pro_connect.oidc_userinfo["email"])

        response = pro_connect.mock_oauth_dance(
            client,
            self.user_kind,
            user_email=invitation.email,
        )
        assertRedirects(response, reverse("welcoming_tour:index"), fetch_redirect_response=False)
        response = client.get(response.url, follow=True)

        user = User.objects.get(email=invitation.email)
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_existing_user__login_with_ProConnect(self, client, mailoutbox, pro_connect):
        invitation = self.invitation_factory(email=pro_connect.oidc_userinfo["email"])
        user = self.user_factory(
            username=pro_connect.oidc_userinfo["sub"],
            email=pro_connect.oidc_userinfo["email"],
            has_completed_welcoming_tour=True,
        )
        response = client.get(invitation.acceptance_link, follow=True)
        assert str(self.login_url) in response.wsgi_request.get_full_path()
        assert not invitation.accepted_at

        next_url = self.join_url(invitation)
        previous_url = f"{self.login_url}?{urlencode({'next': next_url})}"
        params = {
            "user_kind": self.user_kind,
            "previous_url": previous_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            self.user_kind,
            user_email=user.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
        )
        response = client.get(response.url, follow=True)
        assertRedirects(response, reverse("dashboard:index"))

        assert response.context["user"].is_authenticated
        self.assert_invitation_is_accepted(response, user, invitation, mailoutbox)

    def test_new_user__ProConnect_signup__wrong_email(self, client, pro_connect):
        invitation = self.invitation_factory()
        response = client.get(invitation.acceptance_link, follow=True)
        pro_connect.assertContainsButton(response)

        # We don't put the full path with the FQDN in the parameters
        previous_url = invitation.acceptance_link.split(settings.ITOU_FQDN)[1]
        next_url = self.join_url(invitation)
        params = {
            "user_kind": self.user_kind,
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
            self.user_kind,
            # the login hint is different from the email used to create the SSO account
            user_email=invitation.email,
            channel="invitation",
            previous_url=previous_url,
            next_url=next_url,
            expected_redirect_url=add_url_params(
                pro_connect.logout_url,
                {
                    "redirect_url": previous_url,
                    "token": ID_TOKEN,
                },
            ),
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


class TestAcceptInstitutionInvitation(InstitutionMixin, BaseTestAcceptInvitation, DjangoSignupTestAcceptInvitation):
    pass


class TestAcceptPrescriberInvitation(PrescriberMixin, BaseTestAcceptInvitation, ProConnectSignupTestAcceptInvitation):
    pass


class TestAcceptCompanyInvitation(CompanyMixin, BaseTestAcceptInvitation, ProConnectSignupTestAcceptInvitation):
    def test_existing_user__already_belongs_to_another_inactive_company(self, client, mailoutbox):
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

    def test_inactive_siae(self, client):
        company = CompanyFactory(convention__is_active=False, with_membership=True, subject_to_iae_rules=True)
        invitation = EmployerInvitationFactory(company=company)
        user = EmployerFactory(email=invitation.email)
        client.force_login(user)
        join_url = reverse("invitations_views:join_company", kwargs={"invitation_id": invitation.id})
        response = client.get(join_url, follow=True)
        assertContains(response, escape("Cette structure n'est plus active."))


def test_job_seeker_no_access(client, subtests):
    client.force_login(JobSeekerFactory())

    for view_name in [
        "invitations_views:invite_labor_inspector",
        "invitations_views:invite_prescriber_with_org",
        "invitations_views:invite_employer",
    ]:
        with subtests.test(view_name):
            response = client.get(reverse(view_name))
            assert response.status_code == 403
