import datetime
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

from itou.otp.models import ItouStaticDevice, ItouStaticToken, ItouTOTPDevice
from itou.otp.utils import create_otp_backup_code
from itou.www.login.constants import ITOU_SESSION_LOGIN_EMAIL_KEY
from itou.www.otp_views.forms import ConfirmTOTPDeviceForm
from tests.otp.factories import ItouTOTPDeviceFactory
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


@pytest.mark.parametrize(
    "factory,expected_status",
    [
        (JobSeekerFactory, 403),
        (partial(EmployerFactory, membership=True), 200),
        (partial(PrescriberFactory, membership=True), 200),
        (partial(LaborInspectorFactory, membership=True), 200),
        (ItouStaffFactory, 200),
    ],
)
def test_permissions(client, factory, expected_status):
    user = factory()
    client.force_login(user)
    response = client.get(reverse("otp_views:otp_devices"))
    assert response.status_code == expected_status

    response = client.get(reverse("otp_views:enrollment_step_1_choose_device_type"))
    assert response.status_code == expected_status


@freeze_time("2025-03-11 05:18:56")
def test_device_list(client, snapshot):
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

        # The user removes his other device
        response = client.post(url, data={"delete-device": str(device_2.pk)})
        assertQuerySetEqual(ItouTOTPDevice.objects.all(), [device_1])
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


def test_enrollment_step_0_intro(client):
    user = ItouStaffFactory()

    client.force_login(user)
    url = reverse("otp_views:enrollment_step_0_intro")
    response = client.get(url)
    assertContains(response, "Nous vous guidons étape par étape")


def test_enrollment_step_1_choose_device_type(client):
    user = ItouStaffFactory()

    client.force_login(user)
    url = reverse("otp_views:enrollment_step_1_choose_device_type")
    response = client.get(url)
    assertContains(response, "<strong>Étape 1</strong>/3 : Choisissez votre méthode")


class TestEnrollmentSteps2And3ConfirmDevice:
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

    def test_get_unknown_device_type(self, client):
        user = ItouStaffFactory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_2_and_3_confirm_device")

        response = client.get(url, query_params={"device_type": "unknown"})
        assertRedirects(response, reverse("otp_views:enrollment_step_1_choose_device_type"))

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
