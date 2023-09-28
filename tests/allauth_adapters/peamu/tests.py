# Heavily inspired by
# https://github.com/pennersr/django-allauth/blob/master/allauth/socialaccount/providers/google/tests.py
from unittest import mock

import pytest
from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.account.signals import user_signed_up
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.tests import OAuth2TestsMixin
from allauth.tests import MockedResponse
from django.core import mail
from django.test import override_settings
from django.urls import reverse

from itou.allauth_adapters.peamu.provider import PEAMUProvider
from itou.users import enums as users_enums
from itou.users.models import User
from itou.utils import constants as global_constants
from tests.users.factories import JobSeekerFactory
from tests.utils.test import TestCase


pytestmark = pytest.mark.ignore_template_errors


@override_settings(
    PEAMU_AUTH_BASE_URL="https://peamu.auth.fake.url",
    API_ESD={
        "BASE_URL": "https://some.auth.domain",
        "AUTH_BASE_URL": "https://some-authentication-domain.fr",
        "KEY": "somekey",
        "SECRET": "somesecret",
    },
    SOCIALACCOUNT_PROVIDERS={
        "peamu": {
            "APP": {"key": "peamu", "client_id": "somekey", "secret": "somesecret"},
        },
    },
)  # noqa
class PEAMUTests(OAuth2TestsMixin, TestCase):
    provider_id = PEAMUProvider.id

    def get_mocked_response(self, given_name="John", family_name="Doe", email="john.doe@example.com"):
        return MockedResponse(
            200,
            f"""
            {{
                "email": "{email}",
                "gender": "male",
                "given_name": "{given_name}",
                "family_name": "{family_name}",
                "sub": "108204268033311374519"
            }}
            """,
        )

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_data_created_by_peamu_login(self, mock_login_signal):
        test_email = "john.doe@example.com"
        response = self.get_mocked_response()
        self.login(response)
        assert mock_login_signal.call_count == 1
        email_address = EmailAddress.objects.get(email=test_email)
        account = email_address.user.socialaccount_set.get()
        assert account.extra_data["email"] == "john.doe@example.com"
        assert account.extra_data["gender"] == "male"
        assert account.extra_data["given_name"] == "John"
        assert account.extra_data["family_name"] == "Doe"
        # This mysterious 'testac' value actually comes from
        # https://github.com/pennersr/django-allauth/blob/master/allauth/socialaccount/tests.py#L150
        assert account.extra_data["id_token"] == "testac"
        assert account.extra_data["sub"] == "108204268033311374519"
        assert email_address.user.email == "john.doe@example.com"
        assert email_address.user.first_name == "John"
        assert email_address.user.last_name == "Doe"
        assert email_address.user.username == "john"
        assert email_address.user.is_active is True
        assert email_address.user.identity_provider == users_enums.IdentityProvider.PE_CONNECT
        # Note that a PEAMU user is automatically set as a job seeker.
        assert email_address.user.kind == users_enums.UserKind.JOB_SEEKER
        assert email_address.user.is_staff is False

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_do_not_crash_if_user_already_exists(self, _mock_login_signal):
        JobSeekerFactory(
            username="user",
            is_active=True,
            email="john.doe@example.com",
            kind=users_enums.UserKind.JOB_SEEKER,
            with_verified_email=True,
        )
        self.login(self.get_mocked_response())
        [email] = mail.outbox
        assert email.to == ["john.doe@example.com"]
        assert email.subject == "Ce compte existe déjà"
        assert email.body == (
            "Bonjour, c'est example.com !\n\n"
            # https://github.com/pennersr/django-allauth/pull/3454
            "Vous recevez cet email car vous ou quelqu'un d'autre a demandé à créer an\n"
            "un compte en utilisant cette adresse email :\n\n"
            "john.doe@example.com\n\n"
            "Cependant, un compte utilisant cette adresse existe déjà. Au cas où vous auriez\n"
            "oublié, merci d'utiliser la fonction de récupération de mot de passe pour\n"
            "récupérer votre compte :\n\n"
            "http://testserver/accounts/password/reset/\n\n"
            "Merci d'utiliser example.com !\n"
            "example.com"
        )

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_peamu_connection_for_existing_non_peamu_user(self, mock_login_signal):
        email = "user@example.com"
        user = User.objects.create(username="user", is_active=True, email=email, kind=users_enums.UserKind.JOB_SEEKER)
        user.set_password("test")
        user.save()
        EmailAddress.objects.create(user=user, email=email, primary=True)
        assert not SocialAccount.objects.filter(user=user, provider=PEAMUProvider.id).exists()
        self.client.login(username=user.username, password="test")
        assert mock_login_signal.call_count == 0

        self.login(self.get_mocked_response(), process="connect")
        # FIXME Seems strange to me
        assert mock_login_signal.call_count == 0

        assert SocialAccount.objects.filter(user=user, provider=PEAMUProvider.id).exists()
        assert EmailAddress.objects.filter(user=user).count() == 1
        # User email is not updated.
        assert EmailAddress.objects.filter(email=email).count() == 1
        assert EmailAddress.objects.filter(email="john.doe@example.com").count() == 0

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_email_verification_is_skipped_for_peamu_account(self, mock_login_signal):
        test_email = "john.doe@example.com"
        self.login(self.get_mocked_response())
        assert mock_login_signal.call_count == 1

        email_address = EmailAddress.objects.get(email=test_email)
        assert not email_address.verified
        assert not EmailConfirmation.objects.filter(email_address__email=test_email).exists()
        assert len(mail.outbox) == 0

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_username_is_based_on_first_name(self, mock_login_signal):
        first_name = "jessica"
        last_name = "parker"
        email = "john.doe@example.com"
        self.login(self.get_mocked_response(email=email, given_name=first_name, family_name=last_name))
        assert mock_login_signal.call_count == 1
        user = User.objects.get(email=email)
        assert user.username == "jessica"

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_username_is_based_on_email_if_first_name_is_exotic(self, mock_login_signal):
        first_name = "明"
        last_name = "小"
        email = "john.doe@example.com"
        self.login(self.get_mocked_response(email=email, given_name=first_name, family_name=last_name))
        assert mock_login_signal.call_count == 1
        user = User.objects.get(email=email)
        assert user.username == "john.doe"

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_user_signed_up_signal(self, mock_login_signal):
        sent_signals = []

        def on_signed_up(sender, request, user, **kwargs):
            sociallogin = kwargs["sociallogin"]
            assert sociallogin.account.provider == PEAMUProvider.id
            assert sociallogin.account.user == user
            sent_signals.append(sender)

        user_signed_up.connect(on_signed_up)
        self.login(self.get_mocked_response())
        assert mock_login_signal.call_count == 1
        assert len(sent_signals) > 0

    def test_redirect_to_dashboard_after_signup(self):
        """
        Curiously, this allauth adapter does not take into account the User account
        adapter configured in settings.ACCOUNT_ADAPTER.
        Successful signups are redirected to settings.LOGIN_REDIRECT_URL
        (default Allauth behavior) even if we specified another URL in our
        own account adapter.
        I was not able to test a login locally because PE does not allow us to
        specify the callback domains in its interface.
        The most secure option was to simply redirect the default path to our own.
        """
        user = JobSeekerFactory(has_completed_welcoming_tour=True)
        self.client.force_login(user)
        response = self.client.get("/accounts/profile/")
        self.assertRedirects(response, reverse("dashboard:index"))

    def test_redirect_to_dashboard_anonymous(self):
        response = self.client.get("/accounts/profile/")
        self.assertRedirects(response, reverse("account_login"))

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_job_seeker_signup_with_nir_with_pe_connect(self, mock_login_signal):
        # Complete signup with NIR is tested in JobSeekerSignupTest.test_job_seeker_nir

        nir = "141068078200557"
        self.client.post(reverse("signup:job_seeker_nir"), {"nir": nir})
        assert global_constants.ITOU_SESSION_NIR_KEY in list(self.client.session.keys())
        assert self.client.session.get(global_constants.ITOU_SESSION_NIR_KEY)

        url = reverse("signup:job_seeker")
        response = self.client.get(url)
        pe_url = reverse("peamu_login")
        self.assertContains(response, pe_url)

        self.login(self.get_mocked_response())
        job_seeker = User.objects.get(email="john.doe@example.com")
        assert nir == job_seeker.nir

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_job_seeker_temporary_nir_with_pe_conect(self, mock_login_signal):
        # Complete signup with a discarded temporary NIR is tested in
        # JobSeekerSignupTest.test_job_seeker_temporary_nir

        assert global_constants.ITOU_SESSION_NIR_KEY not in list(self.client.session.keys())
        assert not self.client.session.get(global_constants.ITOU_SESSION_NIR_KEY)

        # Temporary NIR is not stored with user information.
        url = reverse("signup:job_seeker")
        response = self.client.get(url)
        pe_url = reverse("peamu_login")
        self.assertContains(response, pe_url)

        self.login(self.get_mocked_response())
        job_seeker = User.objects.get(email="john.doe@example.com")
        assert job_seeker.nir == ""

    def test_anonymous_user_logout(self):
        # An AnonymousUser does not have the peamu_id_token attribute
        # but logout should not raise an error
        self.client.post(reverse("account_logout"))
