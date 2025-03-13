import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

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
        assert response.status_code == 302
        assert response["Location"] == "/foo/"
        assert caplog.records[0].message == f"admin={hijacker} has started impersonation of user={hijacked}"
        caplog.clear()

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk, "next": "/bar/"})
        assert response.status_code == 302
        assert response["Location"] == "/bar/"
        assert caplog.records[0].message == f"admin={hijacker} has ended impersonation of user={hijacked}"

    def test_disallowed_hijackers(self, client):
        hijacked = PrescriberFactory()

        hijacker = PrescriberFactory(is_active=False)  # Not staff nor active
        client.force_login(hijacker)
        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 302
        assert response["Location"] == "/accounts/login/?next=/hijack/acquire/"

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
        hijacker.user_permissions.add(Permission.objects.get(codename="hijack_user"))
        client.force_login(hijacker)

        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 302
        assert response["Location"] == "/foo/"
        assert caplog.records[0].message == f"admin={hijacker} has started impersonation of user={hijacked}"
        caplog.clear()

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk, "next": "/bar/"})
        assert response.status_code == 302
        assert response["Location"] == "/bar/"
        assert caplog.records[0].message == f"admin={hijacker} has ended impersonation of user={hijacked}"

    def test_allowed_django_prescriber(self, client, caplog, settings):
        hijacked = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)
        hijacker = ItouStaffFactory(is_superuser=True)
        client.force_login(hijacker)

        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 302
        assert response["Location"] == "/foo/"
        assert caplog.records[0].message == f"admin={hijacker} has started impersonation of user={hijacked}"
        caplog.clear()

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk, "next": "/bar/"})
        assert response.status_code == 302
        assert response["Location"] == "/bar/"
        assert caplog.records[0].message == f"admin={hijacker} has ended impersonation of user={hijacked}"

    def test_release_redirects_to_admin(self, client):
        hijacked = JobSeekerFactory()
        hijacker = ItouStaffFactory(is_superuser=True)
        client.force_login(hijacker)

        initial_url = reverse("admin:users_user_changelist")

        response = client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk}, HTTP_REFERER=initial_url)
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"

        response = client.post(reverse("hijack:release"), {"user_pk": hijacked.pk})
        assert response.status_code == 302
        assert response["Location"] == "/admin/users/user/"
