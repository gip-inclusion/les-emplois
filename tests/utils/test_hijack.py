import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice
from pytest_django.asserts import assertRedirects

from itou.users.enums import IdentityProvider
from tests.users.factories import (
    ItouStaffFactory,
    JobSeekerFactory,
    PrescriberFactory,
)


class TestUserHijack:
    def test_user_does_not_exist(self, client):
        hijacker = ItouStaffFactory(is_superuser=True)
        client.force_login(hijacker)
        response = client.post(reverse("hijack:acquire"), {"user_pk": 0, "next": "/foo/"})
        assert response.status_code == 404

    def test_superuser(self, client, caplog):
        hijacked = JobSeekerFactory()
        hijacker = ItouStaffFactory(is_superuser=True)
        client.force_login(hijacker)

        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assertRedirects(response, "/foo/", fetch_redirect_response=False)
        assert caplog.records[0].message == f"admin={hijacker.pk} has started impersonation of user={hijacked.pk}"
        caplog.clear()

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk, "next": "/bar/"})
        assertRedirects(response, "/bar/", fetch_redirect_response=False)
        assert caplog.records[0].message == f"admin={hijacker.pk} has ended impersonation of user={hijacked.pk}"

    def test_disallowed_hijackers(self, client):
        hijacked = PrescriberFactory()

        hijacker = PrescriberFactory(is_active=False)  # Not staff nor active
        client.force_login(hijacker)
        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assertRedirects(response, "/accounts/login/?next=/hijack/acquire/", fetch_redirect_response=False)

        hijacker = PrescriberFactory()  # active but not staff or superuser
        client.force_login(hijacker)
        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 403

    @pytest.mark.parametrize("param", ["is_active", "is_superuser", "is_staff"])
    def test_disallowed_hijacked(self, client, param):
        hijacker = ItouStaffFactory(is_superuser=True)
        client.force_login(hijacker)

        hijacked = ItouStaffFactory(**{param: True})
        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 403

    def test_permission_staff_hijacker(self, client, caplog):
        hijacked = PrescriberFactory()
        hijacker = ItouStaffFactory(is_staff=True)
        hijacker.user_permissions.add(Permission.objects.get(codename="hijack"))
        client.force_login(hijacker)

        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assertRedirects(response, "/foo/", fetch_redirect_response=False)
        assert caplog.records[0].message == f"admin={hijacker.pk} has started impersonation of user={hijacked.pk}"
        caplog.clear()

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk, "next": "/bar/"})
        assertRedirects(response, "/bar/", fetch_redirect_response=False)
        assert caplog.records[0].message == f"admin={hijacker.pk} has ended impersonation of user={hijacked.pk}"

    def test_allowed_django_prescriber(self, client, caplog, settings):
        hijacked = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)
        hijacker = ItouStaffFactory(is_superuser=True)
        client.force_login(hijacker)

        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assertRedirects(response, "/foo/", fetch_redirect_response=False)
        assert caplog.records[0].message == f"admin={hijacker.pk} has started impersonation of user={hijacked.pk}"
        caplog.clear()

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk, "next": "/bar/"})
        assertRedirects(response, "/bar/", fetch_redirect_response=False)
        assert caplog.records[0].message == f"admin={hijacker.pk} has ended impersonation of user={hijacked.pk}"

    def test_release_redirects_to_admin(self, client):
        hijacked = JobSeekerFactory()
        hijacker = ItouStaffFactory(is_superuser=True)
        client.force_login(hijacker)

        initial_url = reverse("admin:users_user_changelist")

        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk}, HTTP_REFERER=initial_url)
        assertRedirects(response, reverse("dashboard:index"), fetch_redirect_response=False)

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk})
        assertRedirects(response, initial_url, fetch_redirect_response=False)

    def test_keep_otp_after_hijack(self, client, settings):
        settings.REQUIRE_OTP_FOR_STAFF = True
        hijacked = JobSeekerFactory()
        hijacker = ItouStaffFactory(is_superuser=True)
        client.force_login(hijacker)

        device = TOTPDevice.objects.create(user=hijacker, confirmed=True, name="my device")
        post_data = {
            "name": "Mon appareil",
            "otp_token": TOTP(device.bin_key).token(),
        }
        client.post(reverse("login:verify_otp"), data=post_data)

        response = client.get(reverse("dashboard:index"))
        assert response.status_code == 200

        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk})
        assertRedirects(response, reverse("dashboard:index"), fetch_redirect_response=False)

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk}, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
