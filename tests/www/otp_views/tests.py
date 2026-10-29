import datetime
import logging
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

from itou.otp.models import ItouStaticDevice, ItouStaticToken, ItouTOTPDevice
from itou.otp.utils import create_otp_backup_code, create_placeholder_for_external_totp_device
from itou.www.otp_views.enums import DeviceType
from itou.www.otp_views.forms import ConfirmTOTPDeviceForm
from tests.otp.factories import ItouTOTPDeviceFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
    random_pro_user_factory,
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
    "enrollment_step_2_download_app",
    "enrollment_step_3_and_4_confirm_device",
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
        "factory", [JobSeekerFactory, EmployerFactory, PrescriberFactory, LaborInspectorFactory, ItouStaffFactory]
    )
    def test_hidden_when_otp_is_not_required(self, client, factory, url_name, settings):
        settings.REQUIRE_MFA_FOR_PROS = False
        client.force_login(factory())
        response = client.get(reverse(f"otp_views:{url_name}"))
        assert response.status_code == 404

    @pytest.mark.parametrize("url_name", OTP_URL_NAMES)
    def test_visible_for_a_concerned_user_with_a_device(self, client, settings, url_name):
        settings.REQUIRE_MFA_FOR_PROS = True
        user = random_pro_user_factory()
        client.force_login(user)
        attach_device_to_user_session(client, ItouTOTPDeviceFactory(user=user))
        response = client.get(reverse(f"otp_views:{url_name}"))
        if url_name in ("enrollment_step_2_download_app", "enrollment_step_3_and_4_confirm_device"):
            # without a `device_type` query param it redirects to step-1
            assert response.status_code == 302
        else:
            assert response.status_code == 200

    @pytest.mark.parametrize("url_name", OTP_URL_NAMES)
    def test_hidden_without_a_device_but_for_enrollment(self, client, settings, url_name):
        # A concerned user without any enabled device is sent to enrollment by the middleware:
        # the other pages have nothing to show
        settings.REQUIRE_MFA_FOR_PROS = True
        user = random_pro_user_factory()
        device = ItouTOTPDeviceFactory(user=user)
        client.force_login(user)
        attach_device_to_user_session(client, device)  # avoid the middleware redirection
        device.disabled_at = timezone.now()
        device.save(update_fields=["disabled_at"])

        response = client.get(reverse(f"otp_views:{url_name}"))
        if url_name in ("enrollment_step_2_download_app", "enrollment_step_3_and_4_confirm_device"):
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
        user = EmployerFactory()
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
        user = EmployerFactory()
        if is_concerned:
            settings.REQUIRE_MFA_ON_COMPANY_IDS = {user.company_set.get().id}
        response = self._get_dashboard(client, user, verified=is_concerned)
        if is_concerned:
            assertContains(response, self.OTP_CONFIG_MARKUP)
        else:
            assertNotContains(response, self.OTP_CONFIG_MARKUP)

    def test_hidden_when_mfa_comes_from_identity_provider(self, client, settings):
        # The user is concerned by 2FA but was verified by ProConnect: they never enroll
        # a TOTP device on our side, so there is nothing to configure
        settings.REQUIRE_MFA_FOR_PROS = True
        user = EmployerFactory()
        settings.REQUIRE_MFA_ON_COMPANY_IDS = {user.company_set.get().id}
        client.force_login(user)
        attach_external_device_to_user_session(client, user)
        response = client.get(reverse("dashboard:index"), follow=True)
        assertNotContains(response, self.OTP_CONFIG_MARKUP)

    def test_hidden_when_only_device_is_disabled(self, client, settings):
        settings.REQUIRE_MFA_FOR_PROS = True
        user = random_pro_user_factory()
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
    settings.REQUIRE_MFA_FOR_PROS = True
    user = random_pro_user_factory()
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
    settings.REQUIRE_MFA_FOR_PROS = True
    user = random_pro_user_factory()
    url = reverse("otp_views:otp_devices")

    with freeze_time("2025-03-11 05:18:56") as frozen_time:
        device_1 = ItouTOTPDeviceFactory(user=user, name="authenticator")
        frozen_time.tick(60)
        device_2 = ItouTOTPDeviceFactory(user=user, name="bitwarden")
        frozen_time.tick(60)

        client.force_login(user)
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


def test_enrollment_step_0_intro(client, settings):
    settings.REQUIRE_MFA_FOR_PROS = True
    user = random_pro_user_factory()

    client.force_login(user)
    url = reverse("otp_views:enrollment_step_0_intro")
    response = client.get(url)
    assertContains(response, "Nous vous guidons étape par étape")


def test_enrollment_step_1_choose_device_type(client, settings):
    settings.REQUIRE_MFA_FOR_PROS = True
    user = random_pro_user_factory()

    client.force_login(user)
    url = reverse("otp_views:enrollment_step_1_choose_device_type")
    response = client.get(url)
    assertContains(response, "<strong>Étape 1</strong>/4 : choisissez votre méthode")


class TestEnrollmentSteps2And3ConfirmDevice:
    @pytest.fixture(autouse=True)
    def require_otp_for_pros(self, settings):
        # Enrollment pages are only reachable when our own 2FA applies to the user
        settings.REQUIRE_MFA_FOR_PROS = True

    @pytest.mark.parametrize(
        "device_type,should_show_qr_code",
        (
            ("smartphone", True),
            ("desktop", False),
        ),
    )
    def test_get_known_device_type(self, client, device_type, should_show_qr_code):
        user = random_pro_user_factory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_3_and_4_confirm_device")

        response = client.get(url, query_params={"device_type": device_type})

        assertContains(response, "<strong>Étape 3</strong>/4 : associez votre compte")
        qr_code_text = "scannez ce QR code"
        if should_show_qr_code:
            assertContains(response, qr_code_text)
        else:
            assertNotContains(response, qr_code_text)

    def test_post_valid_totp(self, client):
        user = random_pro_user_factory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_3_and_4_confirm_device")
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
        user = random_pro_user_factory()
        existing_device = ItouTOTPDeviceFactory(user=user)
        client.force_login(user)  # authenticated but NOT OTP-verified: no device attached to session

        url = reverse("otp_views:enrollment_step_3_and_4_confirm_device")
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
        user = random_pro_user_factory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_3_and_4_confirm_device")
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
        user = random_pro_user_factory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_3_and_4_confirm_device")
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
    @pytest.mark.parametrize(
        "device_type,expected_redirection",
        [
            (
                DeviceType.SMARTPHONE,
                add_url_params(
                    reverse("otp_views:enrollment_step_2_download_app"), {"device_type": DeviceType.SMARTPHONE}
                ),
            ),
            (DeviceType.DESKTOP, reverse("otp_views:enrollment_step_1_choose_device_type")),
        ],
    )
    def test_post_invalid_key_redirects(self, client, key, device_type, expected_redirection):
        user = random_pro_user_factory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_3_and_4_confirm_device")

        data = {"name": "whatever", "device_type": device_type, "otp_token": "123456"}
        if key is not None:
            data["key"] = key
        response = client.post(url, data)

        assertRedirects(response, expected_redirection)
        assert user.itou_totp_devices.count() == 0


class TestLogin:
    def test_login_with_totp(self, client, settings, pro_connect, mocker):
        settings.REQUIRE_MFA_FOR_PROS = True
        # For a user conserned with totp
        mocker.patch("itou.otp.utils._require_otp_for_pro", return_value=True)
        user = random_pro_user_factory(email=pro_connect.oidc_userinfo["email"], has_completed_welcoming_tour=True)

        verify_otp_url = reverse("otp_views:verify_otp")
        setup_otp_url = reverse("otp_views:enrollment_step_0_intro")

        # Without a device, the user is redirected to the otp setup page
        response = pro_connect.mock_oauth_dance(client, expected_redirect_url=reverse("dashboard:index"))
        response = client.get(response.url)
        assertRedirects(response, setup_otp_url)

        # With a device, the user is redirected to the otp verification page
        client.logout()
        device = ItouTOTPDeviceFactory(name="1", user=user)
        response = pro_connect.mock_oauth_dance(client, expected_redirect_url=reverse("dashboard:index"))
        response = client.get(response.url)
        next_url = add_url_params(verify_otp_url, {"next": reverse("dashboard:index")})
        assertRedirects(response, next_url)

        # The user should not be able to access the setup otp pages
        response = client.get(setup_otp_url)
        assertRedirects(response, add_url_params(verify_otp_url, {"next": setup_otp_url}))
        setup_otp_confirm_device_url = reverse("otp_views:enrollment_step_3_and_4_confirm_device")
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
        assertRedirects(response, reverse("dashboard:index"))

    def test_verify_with_wrong_token_throttles_every_device(self, client, settings, caplog):
        # `VerifyOTPForm` tries every enrolled device, so a single wrong code counts against each of them
        settings.REQUIRE_MFA_FOR_PROS = True
        user = random_pro_user_factory()
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
        settings.REQUIRE_MFA_FOR_PROS = True
        user = random_pro_user_factory()
        device = ItouTOTPDeviceFactory(name="1", user=user)
        client.force_login(user)
        verify_otp_url = reverse("otp_views:verify_otp")

        with caplog.at_level(logging.INFO):
            response = client.post(verify_otp_url, data={"otp_token": TOTP(device.bin_key).token()})
        assert response.status_code == 302
        assert f"User {user.id} authenticated with 2FA" in caplog.messages

    def test_login_with_backup_code(self, client, settings, mailoutbox, pro_connect):
        settings.REQUIRE_MFA_FOR_PROS = True
        user = random_pro_user_factory(email=pro_connect.oidc_userinfo["email"])
        device = ItouTOTPDeviceFactory(user=user)
        backup_code = create_otp_backup_code(user)

        response = pro_connect.mock_oauth_dance(client)
        next_url = response.url
        verify_otp_url = add_url_params(reverse("otp_views:verify_otp"), {"next": next_url})
        login_with_backup_code_url = reverse("otp_views:login_with_backup_code")

        # After login the users are redirected to a form where they can input the TOTP.
        response = client.get(next_url)
        assertRedirects(response, verify_otp_url)

        # User has lost their device, they click the link to input
        # their backup code.
        response = client.get(login_with_backup_code_url)
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
        settings.REQUIRE_MFA_FOR_PROS = True
        user = random_pro_user_factory()

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

    def test_login_otp_not_required(self, client, pro_connect):
        user = random_pro_user_factory(email=pro_connect.oidc_userinfo["email"], has_completed_welcoming_tour=True)
        response = pro_connect.mock_oauth_dance(client, expected_redirect_url=reverse("dashboard:index"))
        response = client.get(response.url, follow=True)
        assert response.wsgi_request.path == "/dashboard/"  # Check the middleware doesn't send us elsewhere

        # Same with an device
        client.logout()
        ItouTOTPDeviceFactory(user=user)
        response = pro_connect.mock_oauth_dance(client, expected_redirect_url=reverse("dashboard:index"))
        response = client.get(response.url, follow=True)
        assert response.wsgi_request.path == "/dashboard/"  # Check the middleware doesn't send us elsewhere

    def test_login_shows_list_of_devices(self, client, snapshot, settings, pro_connect):
        settings.REQUIRE_MFA_FOR_PROS = True
        user = random_pro_user_factory(email=pro_connect.oidc_userinfo["email"])
        ItouTOTPDeviceFactory(
            name="Mon appareil",
            user=user,
            last_used_at=timezone.make_aware(datetime.datetime(2026, 6, 1, 12, 0)),
        )

        response = pro_connect.mock_oauth_dance(client)
        response = client.get(response.url, follow=True)
        assert response.wsgi_request.path == "/otp/verify"
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
