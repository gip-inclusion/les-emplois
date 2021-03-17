# Heavily inspired by
# https://github.com/pennersr/django-allauth/blob/master/allauth/socialaccount/providers/google/tests.py
from unittest import mock

from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.account.signals import user_signed_up
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.tests import OAuth2TestsMixin
from allauth.tests import MockedResponse, TestCase
from django.contrib.auth import get_user_model
from django.core import mail

from itou.allauth_adapters.peamu.provider import PEAMUProvider


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
        self.login(self.get_mocked_response())
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
        # Note that a PEAMU user is automatically set as a job seeker.
        self.assertEqual(email_address.user.is_job_seeker, True)
        self.assertEqual(email_address.user.is_prescriber, False)
        self.assertEqual(email_address.user.is_siae_staff, False)
        self.assertEqual(email_address.user.is_staff, False)

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_peamu_connection_for_existing_non_peamu_user(self, mock_login_signal):
        email = "user@example.com"
        user = get_user_model().objects.create(username="user", is_active=True, email=email, is_job_seeker=True)
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
        user = get_user_model().objects.get(email=email)
        self.assertEqual(user.username, "jessica")

    @mock.patch("itou.external_data.signals.import_user_pe_data_on_peamu_login")
    def test_username_is_based_on_email_if_first_name_is_exotic(self, mock_login_signal):
        first_name = "明"
        last_name = "小"
        email = "john.doe@example.com"
        self.login(self.get_mocked_response(email=email, given_name=first_name, family_name=last_name))
        self.assertEqual(mock_login_signal.call_count, 1)
        user = get_user_model().objects.get(email=email)
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
