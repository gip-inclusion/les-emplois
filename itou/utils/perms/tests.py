from django.test import override_settings
from django.urls import reverse

from itou.users.factories import UserFactory
from itou.utils.test import TestCase


class UserHijackPermTestCase(TestCase):
    def test_user_does_not_exist(self):
        hijacker = UserFactory(is_active=True, is_superuser=True)
        self.client.force_login(hijacker)
        response = self.client.post(reverse("hijack:acquire"), {"user_pk": 0, "next": "/foo/"})
        assert response.status_code == 404

    def test_superuser(self):
        hijacked = UserFactory()
        hijacker = UserFactory(is_superuser=True)
        self.client.force_login(hijacker)

        with self.assertLogs() as cm:
            response = self.client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 302
        assert response["Location"] == "/foo/"
        assert cm.records[0].message == f"admin={hijacker} has started impersonation of user={hijacked}"

        with self.assertLogs() as cm:
            response = self.client.post(reverse("hijack:release"), {"user_pk": hijacked.pk, "next": "/bar/"})
        assert response.status_code == 302
        assert response["Location"] == "/bar/"
        assert cm.records[0].message == f"admin={hijacker} has ended impersonation of user={hijacked}"

    def test_disallowed_hijackers(self):
        hijacked = UserFactory(is_active=True)

        hijacker = UserFactory(is_active=False)
        self.client.force_login(hijacker)
        response = self.client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 302
        assert response["Location"] == "/accounts/login/?next=/hijack/acquire/"

        hijacker = UserFactory(is_active=True, is_staff=False, is_superuser=False)
        self.client.force_login(hijacker)
        response = self.client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 403

        hijacker = UserFactory(is_active=True, is_staff=True, is_superuser=False)
        self.client.force_login(hijacker)
        response = self.client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 403

        with override_settings(HIJACK_ALLOWED_USER_EMAILS=["foo@test.com", "bar@baz.org"]):
            hijacker = UserFactory(is_active=True, is_staff=True, is_superuser=False, email="not@inthelist.com")
            self.client.force_login(hijacker)
            response = self.client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
            assert response.status_code == 403

    @override_settings(HIJACK_ALLOWED_USER_EMAILS=["foo@test.com", "bar@baz.org"])
    def test_allowed_staff_hijacker(self):
        hijacked = UserFactory(is_active=True)
        hijacker = UserFactory(is_active=True, is_staff=True, email="bar@baz.org")
        self.client.force_login(hijacker)

        with self.assertLogs() as cm:
            response = self.client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 302
        assert response["Location"] == "/foo/"
        assert cm.records[0].message == f"admin={hijacker} has started impersonation of user={hijacked}"

        with self.assertLogs() as cm:
            response = self.client.post(reverse("hijack:release"), {"user_pk": hijacked.pk, "next": "/bar/"})
        assert response.status_code == 302
        assert response["Location"] == "/bar/"
        assert cm.records[0].message == f"admin={hijacker} has ended impersonation of user={hijacked}"
