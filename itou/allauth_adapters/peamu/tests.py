# Heavily inspired by
# https://github.com/pennersr/django-allauth/blob/master/allauth/socialaccount/providers/google/tests.py
from unittest import mock

from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.account.signals import user_signed_up
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.tests import OAuth2TestsMixin
from allauth.tests import MockedResponse
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from itou.allauth_adapters.peamu.provider import PEAMUProvider
from itou.users import enums as users_enums
from itou.users.factories import JobSeekerFactory
from itou.users.models import User
from itou.utils import constants as global_constants


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
        self.assertEqual(mock_login_signal.call_count, 1)
        email_address = EmailAddress.objects.get(email=test_email)
        account = email_address.user.socialaccount_set.get()
        self.assertEqual(account.extra_data["email"], "john.doe@example.com")
        self.assertEqual(account.extra_data["gender"], "male")
        self.assertEqual(account.extra_data["given_name"], "John")
        self.assertEqual(account.extra_data["family_name"], "Doe")
        # This mysterious 'testac' value actually comes from
        # https://github.com/pennersr/django-allauth/blob/master/allauth/socialaccount/tests.py#L150
        self.assertEqual(account.extra_data["id_token"], "testac")
        self.assertEqual(account.extra_data["sub"], "108204268033311374519")
        self.assertEqual(email_address.user.email, "john.doe@example.com")
        self.assertEqual(email_address.user.first_name, "John")
        self.assertEqual(email_address.user.last_name, "Doe")
        self.assertEqual(email_address.user.username, "john")
        self.assertEqual(email_address.user.is_active, True)
        self.assertEqual(email_address.user.identity_provider, users_enums.IdentityProvider.PE_CONNECT)
        # Note that a PEAMU user is automatically set as a job seeker.
        self.assertEqual(email_address.user.is_job_seeker, True)
        self.assertEqual(email_address.user.is_prescriber, False)
        self.assertEqual(email_address.user.is_siae_staff, False)
        self.assertEqual(email_address.user.is_staff, False)

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_peamu_connection_for_existing_non_peamu_user(self, mock_login_signal):
        email = "user@example.com"
        user = User.objects.create(username="user", is_active=True, email=email, is_job_seeker=True)
        user.set_password("test")
        user.save()
        EmailAddress.objects.create(user=user, email=email, primary=True)
        self.assertFalse(SocialAccount.objects.filter(user=user, provider=PEAMUProvider.id).exists())
        self.client.login(username=user.username, password="test")
        self.assertEqual(mock_login_signal.call_count, 0)

        self.login(self.get_mocked_response(), process="connect")
        # FIXME Seems strange to me
        self.assertEqual(mock_login_signal.call_count, 0)

        self.assertTrue(SocialAccount.objects.filter(user=user, provider=PEAMUProvider.id).exists())
        self.assertEqual(EmailAddress.objects.filter(user=user).count(), 1)
        # User email is not updated.
        self.assertEqual(EmailAddress.objects.filter(email=email).count(), 1)
        self.assertEqual(EmailAddress.objects.filter(email="john.doe@example.com").count(), 0)

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_email_verification_is_skipped_for_peamu_account(self, mock_login_signal):
        test_email = "john.doe@example.com"
        self.login(self.get_mocked_response())
        self.assertEqual(mock_login_signal.call_count, 1)

        email_address = EmailAddress.objects.get(email=test_email)
        self.assertFalse(email_address.verified)
        self.assertFalse(EmailConfirmation.objects.filter(email_address__email=test_email).exists())
        self.assertEqual(len(mail.outbox), 0)

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_username_is_based_on_first_name(self, mock_login_signal):
        first_name = "jessica"
        last_name = "parker"
        email = "john.doe@example.com"
        self.login(self.get_mocked_response(email=email, given_name=first_name, family_name=last_name))
        self.assertEqual(mock_login_signal.call_count, 1)
        user = User.objects.get(email=email)
        self.assertEqual(user.username, "jessica")

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_username_is_based_on_email_if_first_name_is_exotic(self, mock_login_signal):
        first_name = "明"
        last_name = "小"
        email = "john.doe@example.com"
        self.login(self.get_mocked_response(email=email, given_name=first_name, family_name=last_name))
        self.assertEqual(mock_login_signal.call_count, 1)
        user = User.objects.get(email=email)
        self.assertEqual(user.username, "john.doe")

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_user_signed_up_signal(self, mock_login_signal):
        sent_signals = []

        def on_signed_up(sender, request, user, **kwargs):
            sociallogin = kwargs["sociallogin"]
            self.assertEqual(sociallogin.account.provider, PEAMUProvider.id)
            self.assertEqual(sociallogin.account.user, user)
            sent_signals.append(sender)

        user_signed_up.connect(on_signed_up)
        self.login(self.get_mocked_response())
        self.assertEqual(mock_login_signal.call_count, 1)
        self.assertTrue(len(sent_signals) > 0)

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
        self.assertIn(global_constants.ITOU_SESSION_NIR_KEY, list(self.client.session.keys()))
        self.assertTrue(self.client.session.get(global_constants.ITOU_SESSION_NIR_KEY))

        url = reverse("signup:job_seeker")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        pe_url = reverse("peamu_login")
        self.assertContains(response, pe_url)

        self.login(self.get_mocked_response())
        job_seeker = User.objects.get(email="john.doe@example.com")
        self.assertEqual(nir, job_seeker.nir)

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_job_seeker_temporary_nir_with_pe_conect(self, mock_login_signal):
        # Complete signup with a discarded temporary NIR is tested in
        # JobSeekerSignupTest.test_job_seeker_temporary_nir

        self.assertNotIn(global_constants.ITOU_SESSION_NIR_KEY, list(self.client.session.keys()))
        self.assertFalse(self.client.session.get(global_constants.ITOU_SESSION_NIR_KEY))

        # Temporary NIR is not stored with user information.
        url = reverse("signup:job_seeker")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        pe_url = reverse("peamu_login")
        self.assertContains(response, pe_url)

        self.login(self.get_mocked_response())
        job_seeker = User.objects.get(email="john.doe@example.com")
        self.assertIsNone(job_seeker.nir)

    def test_anonymous_user_logout(self):
        # An AnonymousUser does not have the peamu_id_token attribute
        # but logout should not raise an error
        self.client.post(reverse("account_logout"))
