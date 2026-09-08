import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse
from django_otp.oath import TOTP
from pytest_django.asserts import assertContains, assertRedirects

from itou.users.enums import IdentityProvider
from tests.otp.factories import ItouTOTPDeviceFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    PrescriberFactory,
    ProfessionalFactory,
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
        hijacked = ProfessionalFactory()

        hijacker = ProfessionalFactory(is_active=False)  # Not staff nor active
        client.force_login(hijacker)
        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assertRedirects(response, "/accounts/login/?next=/hijack/acquire/", fetch_redirect_response=False)

        hijacker = PrescriberFactory(membership=True)  # active but not staff or superuser
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
        hijacked = ProfessionalFactory()
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
        hijacked = ProfessionalFactory(identity_provider=IdentityProvider.DJANGO)
        hijacker = ItouStaffFactory(is_superuser=True)
        client.force_login(hijacker)

        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assertRedirects(response, "/foo/", fetch_redirect_response=False)
        assert caplog.records[0].message == f"admin={hijacker.pk} has started impersonation of user={hijacked.pk}"
        caplog.clear()

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk, "next": "/bar/"})
        assertRedirects(response, "/bar/", fetch_redirect_response=False)
        assert caplog.records[0].message == f"admin={hijacker.pk} has ended impersonation of user={hijacked.pk}"

    def test_circumvent_2fa_on_hijacked_user(self, client, settings):
        # If hijacked (target) user must use 2FA, circumvent it for hijacker.
        settings.REQUIRE_MFA_FOR_PROS = True
        hijacked = EmployerFactory(membership=True)
        settings.REQUIRE_MFA_ON_COMPANY_IDS = {hijacked.company_set.get().id}

        # 2FA is required for hijacked user.
        client.force_login(hijacked)
        dashboard_url = reverse("dashboard:index")
        response = client.get(dashboard_url)
        assertRedirects(response, reverse("otp_views:enrollment_step_0_intro"))

        # 2FA is _not_ required for hijacker.
        hijacker = ItouStaffFactory(is_superuser=True)
        client.force_login(hijacker)
        response = client.post(
            reverse("hijack:acquire"),
            {"user_pk": hijacked.pk, "next": dashboard_url},
            follow=True,
        )
        assertContains(response, "Voir toutes les candidatures")

    @pytest.mark.parametrize("hijacked_must_accept_terms", [True, False])
    def test_release_redirects_to_admin(self, client, hijacked_must_accept_terms):
        kwargs = {"terms_accepted_at": None} if hijacked_must_accept_terms else {}
        hijacked = ProfessionalFactory(**kwargs)
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

        device = ItouTOTPDeviceFactory(user=hijacker, name="my device")
        post_data = {
            "name": "Mon appareil",
            "otp_token": TOTP(device.bin_key).token(),
        }
        client.post(reverse("otp_views:verify_otp"), data=post_data)

        response = client.get(reverse("dashboard:index"))
        assert response.status_code == 200

        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk})
        assertRedirects(response, reverse("dashboard:index"), fetch_redirect_response=False)

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk}, follow=True)
        assertRedirects(response, reverse("dashboard:index"))
