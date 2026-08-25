import datetime
import logging
from functools import partial
from unittest import mock

import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import TOTP
from freezegun import freeze_time
from itoutils.urls import add_url_params
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertNotContains,
    assertQuerySetEqual,
    assertRedirects,
)

from itou.otp.enums import ResetRequestState
from itou.otp.models import Itou2FAResetRequest, ItouStaticDevice, ItouStaticToken, ItouTOTPDevice
from itou.otp.utils import create_otp_backup_code, create_placeholder_for_external_totp_device
from itou.www.login.constants import ITOU_SESSION_LOGIN_EMAIL_KEY
from itou.www.otp_views.forms import ConfirmTOTPDeviceForm
from tests.otp.factories import Itou2FAResetRequestFactory, ItouTOTPDeviceFactory
from tests.prescribers.factories import PrescriberOrganizationWith2MembershipFactory
from tests.users.factories import (
    DEFAULT_PASSWORD,
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.testing import parse_response_to_soup, pretty_indented


def attach_device_to_user_session(client, device):
    # Mimic what is done when user enters a TOTP code.
    device.set_last_used_timestamp(timezone.now())
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()


def attach_external_device_to_user_session(client, user):
    # Mimic a ProConnect login through an identity provider that already implements MFA.
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = create_placeholder_for_external_totp_device(user).persistent_id
    session.save()


OTP_URL_NAMES = [
    "otp_devices",
    "enrollment_step_0_intro",
    "enrollment_step_1_choose_device_type",
    "enrollment_step_2_and_3_confirm_device",
    "verify_otp",
    "login_with_backup_code",
]
ENROLLMENT_URL_NAMES = [
    "enrollment_step_0_intro",
    "enrollment_step_1_choose_device_type",
]


class TestPermissions:
    """Pages of the OTP section are hidden (404) from users for whom our own 2FA is not
    required: job seekers, users of an organization that is not in the allowlist, and users
    whose identity provider already handled MFA for this session."""

    @pytest.mark.parametrize("url_name", OTP_URL_NAMES)
    @pytest.mark.parametrize(
        "factory",
        [
            JobSeekerFactory,
            partial(EmployerFactory, membership=True),
            partial(PrescriberFactory, membership=True),
            partial(LaborInspectorFactory, membership=True),
            ItouStaffFactory,
        ],
    )
    def test_hidden_when_otp_is_not_required(self, client, factory, url_name, settings):
        settings.REQUIRE_OTP_FOR_STAFF = False
        settings.REQUIRE_MFA_FOR_PROS = False
        client.force_login(factory())
        response = client.get(reverse(f"otp_views:{url_name}"))
        assert response.status_code == 404

    @pytest.mark.parametrize("url_name", OTP_URL_NAMES)
    def test_visible_for_a_concerned_user_with_a_device(self, client, settings, url_name):
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory()
        client.force_login(user)
        attach_device_to_user_session(client, ItouTOTPDeviceFactory(user=user))
        response = client.get(reverse(f"otp_views:{url_name}"))
        if url_name == "enrollment_step_2_and_3_confirm_device":
            # without a `device_type` query param it redirects to step-1
            assert response.status_code == 302
        else:
            assert response.status_code == 200

    @pytest.mark.parametrize("url_name", OTP_URL_NAMES)
    def test_hidden_without_a_device_but_for_enrollment(self, client, settings, url_name):
        # A concerned user without any enabled device is sent to enrollment by the middleware:
        # the other pages have nothing to show
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory()
        device = ItouTOTPDeviceFactory(user=user)
        client.force_login(user)
        attach_device_to_user_session(client, device)  # avoid the middleware redirection
        device.disabled_at = timezone.now()
        device.save(update_fields=["disabled_at"])

        response = client.get(reverse(f"otp_views:{url_name}"))
        if url_name == "enrollment_step_2_and_3_confirm_device":
            # without a `device_type` query param it redirects to step-1
            assert response.status_code == 302
        elif url_name in ENROLLMENT_URL_NAMES:
            assert response.status_code == 200
        else:
            assert response.status_code == 404

    @pytest.mark.parametrize("with_device", [True, False])
    @pytest.mark.parametrize("url_name", OTP_URL_NAMES)
    def test_hidden_when_mfa_comes_from_identity_provider(self, client, settings, url_name, with_device):
        settings.REQUIRE_MFA_FOR_PROS = True
        user = EmployerFactory(membership=True)
        settings.REQUIRE_MFA_ON_COMPANY_IDS = {user.company_set.get().id}
        if with_device:
            ItouTOTPDeviceFactory(user=user)  # shouldn't happen anyway
        client.force_login(user)
        attach_external_device_to_user_session(client, user)

        response = client.get(reverse(f"otp_views:{url_name}"))
        assert response.status_code == 404


class TestConfigurationOtpMenuLink:
    """The "Configuration 2FA" item in the "Mon espace" dropdown is shown to every user
    concerned by 2FA (`user_is_concerned_by_otp`), not only to staff, provided they enrolled
    at least one device of ours (users whose identity provider handles MFA have nothing to
    configure here)."""

    OTP_CONFIG_MARKUP = ">Configuration 2FA</a>"

    def _get_dashboard(self, client, user, verified=False):
        client.force_login(user)
        if verified:
            # Mark the session verified so the OTP middleware does not redirect a concerned
            # user to enrollment: the menu link must still show for a verified concerned user.
            attach_device_to_user_session(client, ItouTOTPDeviceFactory(user=user))
        return client.get(reverse("dashboard:index"), follow=True)

    def test_hidden_for_job_seeker(self, client):
        response = self._get_dashboard(client, JobSeekerFactory(with_address=True))
        assertNotContains(response, self.OTP_CONFIG_MARKUP)

    @pytest.mark.parametrize("is_concerned", [True, False])
    def test_professional_depends_on_allowlist(self, client, settings, is_concerned):
        settings.REQUIRE_MFA_FOR_PROS = True
        user = EmployerFactory(membership=True)
        if is_concerned:
            settings.REQUIRE_MFA_ON_COMPANY_IDS = {user.company_set.get().id}
        response = self._get_dashboard(client, user, verified=is_concerned)
        if is_concerned:
            assertContains(response, self.OTP_CONFIG_MARKUP)
        else:
            assertNotContains(response, self.OTP_CONFIG_MARKUP)

    def test_visible_for_staff(self, client, settings):
        settings.REQUIRE_OTP_FOR_STAFF = True
        response = self._get_dashboard(client, ItouStaffFactory(), verified=True)
        assertContains(response, self.OTP_CONFIG_MARKUP)

    def test_hidden_when_mfa_comes_from_identity_provider(self, client, settings):
        # The user is concerned by 2FA but was verified by ProConnect: they never enroll
        # a TOTP device on our side, so there is nothing to configure
        settings.REQUIRE_MFA_FOR_PROS = True
        user = EmployerFactory(membership=True)
        settings.REQUIRE_MFA_ON_COMPANY_IDS = {user.company_set.get().id}
        client.force_login(user)
        attach_external_device_to_user_session(client, user)
        response = client.get(reverse("dashboard:index"), follow=True)
        assertNotContains(response, self.OTP_CONFIG_MARKUP)

    def test_hidden_when_only_device_is_disabled(self, client, settings):
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory()
        device = ItouTOTPDeviceFactory(user=user)
        client.force_login(user)
        attach_device_to_user_session(client, device)
        device.disabled_at = timezone.now()
        device.save(update_fields=["disabled_at"])
        response = client.get(reverse("dashboard:index"), follow=True)
        assertNotContains(response, self.OTP_CONFIG_MARKUP)
        # anyway, the user is redirected to enrollment by the middleware,
        # they cannot reach the dashboard with a disabled device


@freeze_time("2025-03-11 05:18:56")
def test_device_list(client, snapshot, settings):
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory()
    device = ItouTOTPDeviceFactory(user=user, name="Mon appareil")

    client.force_login(user)
    attach_device_to_user_session(client, device)
    response = client.get(reverse("otp_views:otp_devices"))

    assert (
        pretty_indented(
            parse_response_to_soup(
                response,
                ".s-section",
                replace_in_attr=[
                    ("value", f"{device.pk}", "[PK of device]"),
                    ("id", f"delete_{device.pk}_modal", "delete_[PK of device]_modal"),
                    ("data-bs-target", f"#delete_{device.pk}_modal", "#delete_[PK of device]_modal"),
                ],
            )
        )
        == snapshot()
    )


def test_delete_devices(client, snapshot, settings):
    settings.REQUIRE_OTP_FOR_STAFF = True
    staff_user = ItouStaffFactory()
    url = reverse("otp_views:otp_devices")

    with freeze_time("2025-03-11 05:18:56") as frozen_time:
        device_1 = ItouTOTPDeviceFactory(user=staff_user, name="authenticator")
        frozen_time.tick(60)
        device_2 = ItouTOTPDeviceFactory(user=staff_user, name="bitwarden")
        frozen_time.tick(60)

        client.force_login(staff_user)
        attach_device_to_user_session(client, device_1)

        # List devices
        response = client.get(url)
        assertContains(response, device_1.name)
        assertContains(response, device_2.name)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".s-section",
                replace_in_attr=[
                    ("value", f"{device_1.pk}", "[PK of device_1]"),
                    ("id", f"delete_{device_1.pk}_modal", "delete_[PK of device_1]_modal"),
                    ("data-bs-target", f"#delete_{device_1.pk}_modal", "#delete_[PK of device_1]_modal"),
                    ("value", f"{device_2.pk}", "[PK of device_2]"),
                    ("id", f"delete_{device_2.pk}_modal", "delete_[PK of device_2]_modal"),
                    ("data-bs-target", f"#delete_{device_2.pk}_modal", "#delete_[PK of device_2]_modal"),
                ],
            )
        ) == snapshot(name="with_device")

        # We cannot remove the used device
        response = client.post(url, data={"delete-device": str(device_1.pk)}, follow=True)
        assertQuerySetEqual(ItouTOTPDevice.objects.all(), [device_1, device_2], ordered=False)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR, "Impossible de supprimer l’appareil qui a été utilisé pour se connecter."
                )
            ],
        )

        # The user removes his other device: it is soft-deleted (temporary kept for auditing)
        response = client.post(url, data={"delete-device": str(device_2.pk)})
        assertQuerySetEqual(ItouTOTPDevice.objects.all(), [device_1, device_2], ordered=False)
        assertQuerySetEqual(ItouTOTPDevice.objects.filter(disabled_at=None), [device_1])
        device_2.refresh_from_db()
        assert device_2.disabled_at is not None
        assertContains(response, device_1.name)
        assertNotContains(response, device_2.name)
        assertMessages(response, [messages.Message(messages.SUCCESS, "L’appareil a été supprimé.")])


def test_otp_enforced_before_nexus_whitelist(client, settings):
    """An MFA-required professional must not reach the whitelisted Nexus views (/portal, ...) without OTP."""
    settings.REQUIRE_MFA_FOR_PROS = True
    user = EmployerFactory(membership=True)
    company = user.company_set.get()
    settings.REQUIRE_MFA_ON_COMPANY_IDS = {company.id}
    client.force_login(user)

    response = client.get(reverse("nexus:homepage"))
    assertRedirects(response, reverse("otp_views:enrollment_step_0_intro"), fetch_redirect_response=False)


def test_enrollment_step_0_intro(client, settings):
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory()

    client.force_login(user)
    url = reverse("otp_views:enrollment_step_0_intro")
    response = client.get(url)
    assertContains(response, "Nous vous guidons étape par étape")


def test_enrollment_step_1_choose_device_type(client, settings):
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory()

    client.force_login(user)
    url = reverse("otp_views:enrollment_step_1_choose_device_type")
    response = client.get(url)
    assertContains(response, "<strong>Étape 1</strong>/3 : Choisissez votre méthode")


class TestEnrollmentSteps2And3ConfirmDevice:
    @pytest.fixture(autouse=True)
    def require_otp_for_staff(self, settings):
        # Enrollment pages are only reachable when our own 2FA applies to the user
        settings.REQUIRE_OTP_FOR_STAFF = True

    @pytest.mark.parametrize(
        "device_type,should_show_qr_code",
        (
            ("smartphone", True),
            ("desktop", False),
        ),
    )
    def test_get_known_device_type(self, client, device_type, should_show_qr_code):
        user = ItouStaffFactory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_2_and_3_confirm_device")

        response = client.get(url, query_params={"device_type": device_type})

        assertContains(response, "<strong>Étape 2</strong>/3 : Associez votre compte")
        qr_code_text = "scannez ce QR code"
        if should_show_qr_code:
            assertContains(response, qr_code_text)
        else:
            assertNotContains(response, qr_code_text)

    def test_post_valid_totp(self, client):
        user = ItouStaffFactory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_2_and_3_confirm_device")
        fake_device = ItouTOTPDevice(key="8fe0a9983c7dddb4acb0146c5507553371e9f211")

        data = {
            "name": "My Apploogle IPixel 34",
            "device_type": "smartphone",
            "key": "R7QKTGB4PXO3JLFQCRWFKB2VGNY6T4QR",
            "otp_token": TOTP(fake_device.bin_key).token(),
        }
        with mock.patch(
            "itou.otp.models.ItouStaticToken.generate_random_token",
            lambda: "secret-backup-code",
        ):
            response = client.post(url, data)

        assertMessages(
            response, [messages.Message(messages.SUCCESS, "Votre nouvel appareil est confirmé", extra_tags="toast")]
        )
        assertContains(response, "Votre code de récupération à conserver")
        assertContains(response, "secret-backup-code")
        device = user.itou_totp_devices.get()
        assert device.key == fake_device.key
        assert client.session[DEVICE_ID_SESSION_KEY] == device.persistent_id
        backup_token = ItouStaticToken.objects.get()
        assert backup_token.check_token("secret-backup-code")

    def test_unverified_user_with_device_cannot_enroll_another(self, client):
        # Security regression (2FA bypass): a user who knows the password (first factor) but has
        # NOT passed 2FA must not be able to enroll a brand-new device and be silently verified by
        # `otp_login()`. The OTP middleware redirects them to `verify_otp` before the view runs.
        user = ItouStaffFactory()
        existing_device = ItouTOTPDeviceFactory(user=user)
        client.force_login(user)  # authenticated but NOT OTP-verified: no device attached to session

        url = reverse("otp_views:enrollment_step_2_and_3_confirm_device")
        fake_device = ItouTOTPDevice(key="8fe0a9983c7dddb4acb0146c5507553371e9f211")
        data = {
            "name": "attacker device",
            "device_type": "smartphone",
            "key": "R7QKTGB4PXO3JLFQCRWFKB2VGNY6T4QR",
            "otp_token": TOTP(fake_device.bin_key).token(),
        }
        response = client.post(url, data)

        # Redirected to verification instead of enrolling the new device...
        assertRedirects(response, add_url_params(reverse("otp_views:verify_otp"), {"next": url}))
        # ...no new device was created and the session is still unverified.
        assert user.itou_totp_devices.exclude(pk=existing_device.pk).count() == 0
        assert DEVICE_ID_SESSION_KEY not in client.session

    def test_post_invalid_totp(self, client):
        user = ItouStaffFactory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_2_and_3_confirm_device")
        fake_device = ItouTOTPDevice(key="8fe0a9983c7dddb4acb0146c5507553371e9f211")

        expired_token = TOTP(fake_device.bin_key, drift=100).token()
        data = {
            "name": "My Apploogle IPixel 34",
            "device_type": "smartphone",
            "key": "R7QKTGB4PXO3JLFQCRWFKB2VGNY6T4QR",
            "otp_token": expired_token,
        }
        response = client.post(url, data)

        assertContains(response, "Le code unique de validation (OTP) n’est pas correct.")
        assertContains(response, data["key"])
        assert user.itou_totp_devices.count() == 0

    def test_post_name_already_used(self, client):
        user = ItouStaffFactory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_2_and_3_confirm_device")
        existing_user_device = ItouTOTPDeviceFactory(
            name="existing",
            user=user,
        )
        # The user already enrolled a device: they must be verified to add another one.
        attach_device_to_user_session(client, existing_user_device)
        new_devices = user.itou_totp_devices.exclude(pk=existing_user_device.pk)
        fake_device = ItouTOTPDevice(key="8fe0a9983c7dddb4acb0146c5507553371e9f211")

        # Use existing name.
        data = {
            "name": "existing",
            "device_type": "smartphone",
            "key": "R7QKTGB4PXO3JLFQCRWFKB2VGNY6T4QR",
            "otp_token": TOTP(fake_device.bin_key).token(),
        }
        response = client.post(url, data)
        assertContains(response, "Vous avez déjà enregistré un appareil sous le même nom.")
        assert new_devices.count() == 0

        # Use another name, which is used by another user, but not _our_ user.
        ItouTOTPDeviceFactory(name="new-name")
        data["name"] = "new-name"
        response = client.post(url, data)
        assertMessages(
            response, [messages.Message(messages.SUCCESS, "Votre nouvel appareil est confirmé", extra_tags="toast")]
        )
        device = new_devices.get()
        assert device.key == fake_device.key
        assert device.name == data["name"]

    @pytest.mark.parametrize("key", ["", "not-base32!", None])
    def test_post_invalid_key_redirects(self, client, key):
        user = ItouStaffFactory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_2_and_3_confirm_device")

        data = {"name": "whatever", "device_type": "smartphone", "otp_token": "123456"}
        if key is not None:
            data["key"] = key
        response = client.post(url, data)

        assertRedirects(response, reverse("otp_views:enrollment_step_1_choose_device_type"))
        assert user.itou_totp_devices.count() == 0


class TestItouStaffLogin:
    def test_login_with_totp(self, client, settings):
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
        admin_url = reverse("admin:users_user_change", args=(user.pk,))
        pre_login_url = add_url_params(reverse("account_login"), {"next": admin_url})
        login_url = add_url_params(
            reverse("login:existing_user"),
            {"back_url": pre_login_url, "next": admin_url},
        )
        verify_otp_url = reverse("otp_views:verify_otp")
        setup_otp_url = reverse("otp_views:enrollment_step_0_intro")

        response = client.get(admin_url)
        assertRedirects(response, pre_login_url)

        response = client.post(pre_login_url, {"email": user.email})
        assertRedirects(response, login_url)

        # Without a device, the user is redirected to the otp setup page
        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(login_url, data=form_data, follow=True)
        assertRedirects(response, setup_otp_url)

        # Same with an unconfirmed device
        client.logout()
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
        session.save()
        device = ItouTOTPDeviceFactory(name="1", user=user)
        response = client.post(login_url, data=form_data, follow=True)
        next_url = add_url_params(verify_otp_url, {"next": admin_url})
        assertRedirects(response, next_url)

        # The user should not be able to access the setup otp pages
        response = client.get(setup_otp_url)
        assertRedirects(response, add_url_params(verify_otp_url, {"next": setup_otp_url}))
        setup_otp_confirm_device_url = reverse("otp_views:enrollment_step_2_and_3_confirm_device")
        response = client.get(setup_otp_confirm_device_url)
        assertRedirects(response, add_url_params(verify_otp_url, {"next": setup_otp_confirm_device_url}))

        # Give a bad token
        totp = TOTP(device.bin_key, drift=100)
        post_data = {
            "name": "Mon appareil",
            "otp_token": totp.token(),  # a token from a long time ago
        }
        response = client.post(next_url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {
            "otp_token": ["Le code de validation unique (OTP) n’est pas correct."]
        }

        # there's throttling
        totp = TOTP(device.bin_key)
        post_data["otp_token"] = totp.token()
        response = client.post(next_url, data=post_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {
            "otp_token": ["Le code de validation unique (OTP) n’est pas correct."]
        }

        # When resetting the failure count it works
        device.throttling_failure_timestamp = None
        device.throttling_failure_count = 0
        device.save()
        response = client.post(next_url, data=post_data)
        assertRedirects(response, admin_url)

    def test_verify_with_wrong_token_throttles_every_device(self, client, settings, caplog):
        # `VerifyOTPForm` tries every enrolled device, so a single wrong code counts against each of them
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory(with_verified_email=True)
        device_1 = ItouTOTPDeviceFactory(name="1", user=user)
        device_2 = ItouTOTPDeviceFactory(name="2", user=user)
        client.force_login(user)
        verify_otp_url = reverse("otp_views:verify_otp")

        with caplog.at_level(logging.INFO):
            response = client.post(verify_otp_url, data={"otp_token": "000000"})
        assert response.context["form"].errors == {
            "otp_token": ["Le code de validation unique (OTP) n’est pas correct."]
        }
        assert f"User {user.id} failed 2FA verification" in caplog.messages
        for device in (device_1, device_2):
            device.refresh_from_db()
            assert device.throttling_failure_count == 1

    def test_verify_with_valid_token_logs_success(self, client, settings, caplog):
        # Throttle-rollback behaviour is tested in tests/otp/test_utils.py, here we
        # cover the view wiring: a valid code verifies the user and logs the success
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory(with_verified_email=True)
        device = ItouTOTPDeviceFactory(name="1", user=user)
        client.force_login(user)
        verify_otp_url = reverse("otp_views:verify_otp")

        with caplog.at_level(logging.INFO):
            response = client.post(verify_otp_url, data={"otp_token": TOTP(device.bin_key).token()})
        assert response.status_code == 302
        assert f"User {user.id} authenticated with 2FA" in caplog.messages

    def test_login_with_backup_code(self, client, settings, mailoutbox):
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
        device = ItouTOTPDeviceFactory(user=user)
        backup_code = create_otp_backup_code(user)

        admin_url = reverse("admin:users_user_change", args=(user.pk,))
        pre_login_url = add_url_params(reverse("account_login"), {"next": admin_url})
        login_url = add_url_params(
            reverse("login:existing_user"),
            {"back_url": pre_login_url, "next": admin_url},
        )
        verify_otp_url = add_url_params(reverse("otp_views:verify_otp"), {"next": admin_url})
        login_with_backup_code_url = reverse("otp_views:login_with_backup_code")

        response = client.get(admin_url)
        assertRedirects(response, pre_login_url)

        response = client.post(pre_login_url, {"email": user.email})
        assertRedirects(response, login_url)

        # When user inputs their credentials, they are redirected to a
        # form where they can input the TOTP.
        credentials = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(login_url, data=credentials, follow=True)
        assertRedirects(response, verify_otp_url)

        # User has lost their device, they click the link to input
        # their backup code.
        response = client.get(login_with_backup_code_url, data=credentials)
        assertContains(response, "Entrez le code de récupération")

        # Send a bogus backup code.
        wrong_code_data = {"code": backup_code[::-1]}
        response = client.post(login_with_backup_code_url, data=wrong_code_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {"code": ["Le code de récupération n’est pas correct."]}

        # Test throttling.
        correct_code_data = {"code": backup_code}
        response = client.post(login_with_backup_code_url, data=correct_code_data)
        assert response.status_code == 200
        assert response.context["form"].errors == {"code": ["Le code de récupération n’est pas correct."]}

        # Reset throttling, user can log in.
        static_device = ItouStaticDevice.objects.get(user=user)
        static_device.throttling_failure_timestamp = None
        static_device.throttling_failure_count = 0
        static_device.save()
        correct_code_data = {"code": backup_code}
        response = client.post(login_with_backup_code_url, data=correct_code_data)
        assertRedirects(response, reverse("otp_views:enrollment_step_0_intro") + "?after_recovery=1")
        assertMessages(
            response,
            [
                messages.Message(
                    messages.SUCCESS,
                    "Code de récupération validé. Votre identité a été vérifiée. "
                    "Vous pouvez maintenant reconfigurer votre double authentification",
                    extra_tags=["toast"],
                )
            ],
        )
        device.refresh_from_db()
        assert device.disabled_at is not None
        [email] = mailoutbox
        assert "Utilisation d'un code de récupération" in email.subject

    def test_login_with_backup_code_preserves_existing_disabled_at(self, client, settings):
        # Logging in with a backup code soft-deletes the user's *active* TOTP
        # devices, but must not overwrite the `disabled_at` of devices that were
        # already disabled earlier (see `purge_disabled_otp_devices`)
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory()

        with freeze_time("2025-01-01") as frozen_time:
            old_disabled_device = ItouTOTPDeviceFactory(user=user, name="old")
            old_disabled_device.disabled_at = timezone.now()
            old_disabled_device.save()
            already_disabled_at = old_disabled_device.disabled_at

            frozen_time.move_to("2026-07-09")
            active_device = ItouTOTPDeviceFactory(user=user, name="active")
            backup_code = create_otp_backup_code(user)

            client.force_login(user)
            response = client.post(reverse("otp_views:login_with_backup_code"), data={"code": backup_code})
            assertRedirects(response, reverse("otp_views:enrollment_step_0_intro") + "?after_recovery=1")

        active_device.refresh_from_db()
        old_disabled_device.refresh_from_db()
        # The active device is soft-deleted at login time
        assert active_device.disabled_at == datetime.datetime(2026, 7, 9, tzinfo=datetime.UTC)
        # The already-disabled device keeps its original timestamp
        assert old_disabled_device.disabled_at == already_disabled_at

    def test_login_otp_not_required(self, client):
        user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
        admin_url = reverse("admin:users_user_change", args=(user.pk,))
        pre_login_url = add_url_params(reverse("account_login"), {"next": admin_url})
        login_url = add_url_params(
            reverse("login:existing_user"),
            {"back_url": pre_login_url, "next": admin_url},
        )

        response = client.get(admin_url)
        assertRedirects(response, pre_login_url)

        response = client.post(pre_login_url, {"email": user.email})
        assertRedirects(response, login_url)

        # Without a device, the user is logged and redirected to the next_url
        form_data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(login_url, data=form_data, follow=True)
        assertRedirects(response, admin_url)

        # Same with an device
        client.logout()
        session = client.session
        session[ITOU_SESSION_LOGIN_EMAIL_KEY] = user.email
        session.save()
        ItouTOTPDeviceFactory(user=user)
        response = client.post(login_url, data=form_data, follow=True)
        assertRedirects(response, admin_url)

    def test_login_shows_list_of_devices(self, client, snapshot, settings):
        settings.REQUIRE_OTP_FOR_STAFF = True
        user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
        ItouTOTPDeviceFactory(
            name="Mon appareil",
            user=user,
            last_used_at=timezone.make_aware(datetime.datetime(2026, 6, 1, 12, 0)),
        )

        admin_url = reverse("admin:users_user_change", args=(user.pk,))
        pre_login_url = add_url_params(reverse("account_login"), {"next": admin_url})
        login_url = add_url_params(
            reverse("login:existing_user"),
            {"back_url": pre_login_url, "next": admin_url},
        )
        client.post(pre_login_url, {"email": user.email})
        login_url = reverse("login:existing_user")
        data = {
            "login": user.email,
            "password": DEFAULT_PASSWORD,
        }
        response = client.post(login_url, data=data, follow=True)

        response = client.get(reverse("otp_views:verify_otp"))

        assert pretty_indented(parse_response_to_soup(response, selector=".c-form")) == snapshot()


class TestConfirmTOTPDeviceForm:
    def test_name_unicity(self):
        user = ItouStaffFactory()
        existing_device = ItouTOTPDeviceFactory(name="Mon appareil", user=user)

        unsaved_device_for_form = ItouTOTPDeviceFactory.build(user=user)
        data = {"name": "Mon appareil", "otp_token": "123456"}
        form = ConfirmTOTPDeviceForm(
            data=data,
            device_type="smartphone",
            device=unsaved_device_for_form,
        )
        assert "name" in form.errors

        # Disabled device is ignored when checking name.
        existing_device.disabled_at = timezone.now()
        existing_device.save()
        form = ConfirmTOTPDeviceForm(
            data=data,
            device_type="smartphone",
            device=unsaved_device_for_form,
        )
        assert "name" not in form.errors


def test_2fa_reset_full_process(client, settings, mailoutbox, django_capture_on_commit_callbacks):
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
    ItouTOTPDeviceFactory(name="1", user=user)
    client.force_login(user)

    # Step 1: the user asks for a reset:
    assert not Itou2FAResetRequest.objects.exists()
    response = client.post(reverse("otp_views:reset_request_init"), follow=True)
    assertContains(response, "Votre demande a bien été transmise.")
    assert Itou2FAResetRequest.objects.exists()

    reset_request = Itou2FAResetRequest.objects.first()

    # Step 2: admin validate the request
    with django_capture_on_commit_callbacks(execute=True):  # To run _async_send_message huey task
        reset_request.accept()

    email = mailoutbox.pop()
    assert email.to == [user.email]
    assert "Réinitialisation de vos paramètres de 2FA" in email.subject
    assert reset_request.nonce in email.body

    # Step 3: User clicks the reset link
    assert ItouTOTPDevice.objects.exists()
    response = client.get(reverse("otp_views:reset_request_do_reset", kwargs={"nonce": reset_request.nonce}))
    assert not ItouTOTPDevice.objects.filter(disabled_at__isnull=True).exists()
    assert not ItouStaticDevice.objects.exists()
    assert not ItouStaticToken.objects.exists()
    assertContains(response, "Votre double authentification a été réinitialisée")


def test_2fa_reset_mail_to_admins_when_reset_request_submitted(client, settings, mailoutbox):
    settings.REQUIRE_MFA_FOR_PROS = True
    org = PrescriberOrganizationWith2MembershipFactory(membership=True)
    user = org.members.filter(prescribermembership__is_admin=False).first()

    ItouTOTPDeviceFactory(name="1", user=user)
    client.force_login(user)
    client.post(reverse("otp_views:reset_request_init"))
    assert len(mailoutbox) == 2
    assert any("demande une réinitialisation de ses paramètres de 2FA" in mail.subject for mail in mailoutbox)
    assert any("demandé une réinitialisation de vos paramètres de 2FA" in mail.subject for mail in mailoutbox)


@pytest.mark.parametrize("accept_it", [True, False])
def test_2fa_reset_cannot_request_twice(client, settings, accept_it):
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
    ItouTOTPDeviceFactory(name="1", user=user)
    client.force_login(user)

    assert Itou2FAResetRequest.objects.count() == 0
    client.post(reverse("otp_views:reset_request_init"))
    assert Itou2FAResetRequest.objects.count() == 1
    if accept_it:
        Itou2FAResetRequest.objects.first().accept()
    response = client.post(reverse("otp_views:reset_request_init"))
    assertContains(response, "Une demande de réinitialisation est déjà en cours pour votre compte.")
    assert Itou2FAResetRequest.objects.count() == 1


@pytest.mark.parametrize("accept_it", [True, False])
def test_2fa_reset_self_cancel(client, settings, accept_it):
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
    ItouTOTPDeviceFactory(name="1", user=user)
    client.force_login(user)
    reset_request_cancel_url = reverse("otp_views:reset_request_self_cancel")

    response = client.get(reset_request_cancel_url)
    assertContains(response, "Vous n’avez pas de demande de réinitialisation en cours.")
    reset_request = Itou2FAResetRequestFactory(user=user)
    response = client.get(reset_request_cancel_url)
    assertContains(response, "Vous avez une demande de réinitialisation en cours")
    if accept_it:
        reset_request.accept()
    response = client.post(reset_request_cancel_url, follow=True)
    assertContains(response, "Demande de réinitialisation annulée")
    reset_request.refresh_from_db()
    assert reset_request.state == ResetRequestState.DENIED


def test_2fa_reset_mail_to_self_when_reset_request_submitted(client, settings, mailoutbox):
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory(
        with_verified_email=True, is_superuser=True
    )  # TODO c'st vraiment utile qu'il soit superuser ?
    ItouTOTPDeviceFactory(name="1", user=user)
    client.force_login(user)

    client.post(reverse("otp_views:reset_request_init"))
    email = mailoutbox.pop()
    assert email.to == [user.email]
    assert "Vous avez demandé une réinitialisation de vos paramètres de 2FA" in email.subject


@pytest.mark.parametrize("accept_it", [True, False])
def test_2fa_reset_cleaned_after_successful_login(client, settings, accept_it):
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
    client.force_login(user)
    device = ItouTOTPDeviceFactory(name="1", user=user)
    reset_request = Itou2FAResetRequestFactory(user=user)

    assert Itou2FAResetRequest.objects.first().state == ResetRequestState.PENDING
    if accept_it:
        reset_request.accept()
        assert Itou2FAResetRequest.objects.first().state == ResetRequestState.ACCEPTED
    client.post(reverse("otp_views:verify_otp"), data={"otp_token": TOTP(device.bin_key).token()})
    assert Itou2FAResetRequest.objects.first().state == ResetRequestState.DENIED


def test_2fa_reset_cannot_use_reset_link_twice(client, settings):
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
    ItouTOTPDeviceFactory(name="1", user=user)
    client.force_login(user)

    reset_request = Itou2FAResetRequestFactory(user=user)
    reset_request.accept()

    # User use its reset link a first time: should work
    response = client.get(reverse("otp_views:reset_request_do_reset", kwargs={"nonce": reset_request.nonce}))
    assert response.status_code == 200
    assert not ItouTOTPDevice.objects.filter(disabled_at__isnull=True).exists()

    # User enrolls a new device
    ItouTOTPDeviceFactory(name="2", user=user)

    # User use its reset link a second time: should not work
    response = client.get(reverse("otp_views:reset_request_do_reset", kwargs={"nonce": reset_request.nonce}))
    assert response.status_code >= 400
    assert ItouTOTPDevice.objects.filter(disabled_at__isnull=True).exists()


def test_2fa_reset_mail_sent_when_request_accepted(client, settings, mailoutbox, django_capture_on_commit_callbacks):
    settings.REQUIRE_OTP_FOR_STAFF = True
    user = ItouStaffFactory(with_verified_email=True, is_superuser=True)
    ItouTOTPDeviceFactory(name="1", user=user)
    client.force_login(user)

    reset_request = Itou2FAResetRequestFactory(user=user)
    assert not mailoutbox
    with django_capture_on_commit_callbacks(execute=True):  # To run _async_send_message huey task
        reset_request.accept()
    assert mailoutbox


# TODO test resend
