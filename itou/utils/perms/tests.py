from django.test import override_settings
from django.urls import reverse

from itou.users.factories import ItouStaffFactory, JobSeekerFactory, PrescriberFactory
from itou.utils.test import TestCase


class UserHijackPermTestCase(TestCase):
    def test_user_does_not_exist(self):
        hijacker = ItouStaffFactory(is_superuser=True)
        self.client.force_login(hijacker)
        response = self.client.post(reverse("hijack:acquire"), {"user_pk": 0, "next": "/foo/"})
        assert response.status_code == 404

    def test_superuser(self):
        hijacked = JobSeekerFactory()
        hijacker = ItouStaffFactory(is_superuser=True)
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
        hijacked = PrescriberFactory()

        hijacker = PrescriberFactory(is_active=False)  # Not staff nor active
        self.client.force_login(hijacker)
        response = self.client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 302
        assert response["Location"] == "/accounts/login/?next=/hijack/acquire/"

        hijacker = PrescriberFactory()  # active but not staff or superuser
        self.client.force_login(hijacker)
        response = self.client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
        assert response.status_code == 403

        with override_settings(HIJACK_ALLOWED_USER_EMAILS=["foo@test.com", "bar@baz.org"]):
            # active staff but not superuser and email not in the whitelist
            hijacker = ItouStaffFactory(email="not@inthelist.com")
            self.client.force_login(hijacker)
            response = self.client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk, "next": "/foo/"})
            assert response.status_code == 403

    @override_settings(HIJACK_ALLOWED_USER_EMAILS=["foo@test.com", "bar@baz.org"])
    def test_allowed_staff_hijacker(self):
        hijacked = PrescriberFactory()
        hijacker = ItouStaffFactory(email="bar@baz.org")
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
