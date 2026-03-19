from django.contrib import messages
from django.urls import reverse
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

from tests.users.factories import ItouStaffFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


@freeze_time("2025-03-11 05:18:56")
def test_devices(client, snapshot):
    staff_user = ItouStaffFactory()
    client.force_login(staff_user)
    url = reverse("otp_views:otp_devices")

    response = client.get(url)
    assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(name="no_device")

    response = client.post(url, data={"action": "new"})
    device = TOTPDevice.objects.get()
    assertRedirects(response, reverse("otp_views:otp_confirm_device", args=(device.pk,)))

    # As long as the device isn't confirmed it isn't shown, and we don't create a new one.
    response = client.get(url)
    assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(name="no_device")

    response = client.post(url, data={"action": "new"})
    device = TOTPDevice.objects.get()  # Still only one
    assertRedirects(response, reverse("otp_views:otp_confirm_device", args=(device.pk,)))

    # When the user already confirmed a device he must first confirm the otp token
    device.name = "Mon appareil"
    device.confirmed = True
    device.save()
    post_data = {
        "name": "Mon appareil",
        "otp_token": TOTP(device.bin_key).token(),
    }
    response = client.post(reverse("login:verify_otp"), data=post_data)
    # The devices page is different
    response = client.get(url)
    assert pretty_indented(
        parse_response_to_soup(
            response,
            ".s-section",
            replace_in_attr=[
                ("value", f"{device.pk}", "[PK of device]"),
                ("id", f"delete_{device.pk}_modal", "delete_[PK of device]_modal"),
                ("data-bs-target", f"#delete_{device.pk}_modal", "#delete_[PK of device]_modal"),
            ],
        )
    ) == snapshot(name="with_device")

    response = client.post(url, data={"action": "new"})
    device = TOTPDevice.objects.exclude(pk=device.pk).get()
    assertRedirects(response, reverse("otp_views:otp_confirm_device", args=(device.pk,)))


def test_confirm(client):
    staff_user = ItouStaffFactory()
    client.force_login(staff_user)

    device = TOTPDevice.objects.create(
        user=staff_user, confirmed=False, key="8fe0a9983c7dddb4acb0146c5507553371e9f211"
    )
    url = reverse("otp_views:otp_confirm_device", args=(device.pk,))
    response = client.get(url)
    assertContains(response, "R7QKTGB4PXO3JLFQCRWFKB2VGNY6T4QR")  # the otp secret matching the hex key

    totp = TOTP(device.bin_key, drift=100)
    post_data = {
        "name": "Mon appareil",
        "otp_token": totp.token(),  # a token from a long time ago
    }
    response = client.post(url, data=post_data)
    assert response.status_code == 200
    assert response.context["form"].errors == {"otp_token": ["Mauvais code OTP"]}
    device.refresh_from_db()
    assert device.confirmed is False

    # there's throttling
    totp = TOTP(device.bin_key)
    post_data["otp_token"] = totp.token()
    response = client.post(url, data=post_data)
    assert response.status_code == 200
    assert response.context["form"].errors == {"otp_token": ["Mauvais code OTP"]}
    device.refresh_from_db()
    assert device.confirmed is False

    # When resetting the failure count
    device.throttling_failure_timestamp = None
    device.throttling_failure_count = 0
    device.save()
    response = client.post(url, data=post_data)
    assertMessages(
        response, [messages.Message(messages.SUCCESS, "Votre nouvel appareil est confirmé", extra_tags="toast")]
    )
    assertRedirects(response, reverse("otp_views:otp_devices"))
    device.refresh_from_db()
    assert device.confirmed is True


def test_delete_devices(client, snapshot, settings):
    # settings.REQUIRE_OTP_FOR_STAFF = True
    staff_user = ItouStaffFactory()
    url = reverse("otp_views:otp_devices")

    with freeze_time("2025-03-11 05:18:56") as frozen_time:
        client.force_login(staff_user)

        device_1 = TOTPDevice.objects.create(user=staff_user, confirmed=True, name="bitwarden")
        frozen_time.tick(60)

        device_2 = TOTPDevice.objects.create(user=staff_user, confirmed=True, name="authenticator")
        frozen_time.tick(60)

        # Verify user
        post_data = {
            "name": "Mon appareil",
            "otp_token": TOTP(device_1.bin_key).token(),
        }
        client.post(reverse("login:verify_otp"), data=post_data)

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
