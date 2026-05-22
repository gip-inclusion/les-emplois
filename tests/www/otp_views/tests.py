from functools import partial

import pytest
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice
from freezegun import freeze_time
from pytest_django.asserts import (
    assertContains,
    assertMessages,
    assertNotContains,
    assertQuerySetEqual,
    assertRedirects,
)

from tests.users.factories import (
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
        (partial(EmployerFactory, membership=True), 403),
        (partial(PrescriberFactory, membership=True), 403),
        (partial(LaborInspectorFactory, membership=True), 403),
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
    device = TOTPDevice.objects.create(
        user=user,
        name="Mon appareil",
        confirmed=True,
    )

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
        device_1 = TOTPDevice.objects.create(
            user=staff_user,
            confirmed=True,
            name="authenticator",
        )
        frozen_time.tick(60)
        device_2 = TOTPDevice.objects.create(user=staff_user, confirmed=True, name="bitwarden")
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
        assertQuerySetEqual(TOTPDevice.objects.all(), [device_1, device_2], ordered=False)
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
        assertQuerySetEqual(TOTPDevice.objects.all(), [device_1])
        assertContains(response, device_1.name)
        assertNotContains(response, device_2.name)
        assertMessages(response, [messages.Message(messages.SUCCESS, "L’appareil a été supprimé.")])


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
    assertContains(response, "<strong>Étape 1</strong>/2 : Choisissez votre méthode")


class TestEnrollmentStep2ConfirmDevice:
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
        url = reverse("otp_views:enrollment_step_2_confirm_device")

        response = client.get(url, query_params={"device_type": device_type})

        assertContains(response, "<strong>Étape 2</strong>/2 : Associez votre compte")
        qr_code_text = "scannez ce QR code"
        if should_show_qr_code:
            assertContains(response, qr_code_text)
        else:
            assertNotContains(response, qr_code_text)

    def test_get_unknown_device_type(self, client):
        user = ItouStaffFactory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_2_confirm_device")

        response = client.get(url, query_params={"device_type": "unknown"})
        assertRedirects(response, reverse("otp_views:enrollment_step_1_choose_device_type"))

    def test_post_valid_totp(self, client):
        user = ItouStaffFactory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_2_confirm_device")
        fake_device = TOTPDevice(key="8fe0a9983c7dddb4acb0146c5507553371e9f211")

        data = {
            "name": "My Apploogle IPixel 34",
            "device_type": "smartphone",
            "key": "R7QKTGB4PXO3JLFQCRWFKB2VGNY6T4QR",
            "otp_token": TOTP(fake_device.bin_key).token(),
        }
        response = client.post(url, data)

        assertRedirects(response, reverse("otp_views:otp_devices"))
        assertMessages(
            response, [messages.Message(messages.SUCCESS, "Votre nouvel appareil est confirmé", extra_tags="toast")]
        )
        device = user.totpdevice_set.get()
        assert device.key == fake_device.key
        assert client.session[DEVICE_ID_SESSION_KEY] == device.persistent_id

    def test_post_invalid_totp(self, client):
        user = ItouStaffFactory()
        client.force_login(user)
        url = reverse("otp_views:enrollment_step_2_confirm_device")
        fake_device = TOTPDevice(key="8fe0a9983c7dddb4acb0146c5507553371e9f211")

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
        assert user.totpdevice_set.count() == 0
