from functools import partial

import pytest
from django.test import override_settings
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from itou.employee_record import enums as employee_record_enums
from itou.users.enums import IdentityProvider
from itou.utils.perms import employee_record
from tests.employee_record.factories import EmployeeRecordFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)
from tests.utils.test import TestCase


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

    @override_settings(HIJACK_ALLOWED_USER_EMAILS=["foo@test.com", "bar@baz.org"])
    def test_allowed_django_prescriber(self):
        hijacked = PrescriberFactory(identity_provider=IdentityProvider.DJANGO)
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

    def test_release_redirects_to_admin(self):
        hijacked = JobSeekerFactory()
        hijacker = ItouStaffFactory(is_superuser=True)
        self.client.force_login(hijacker)

        initial_url = reverse("admin:users_user_changelist")

        response = self.client.post(reverse("hijack:acquire"), {"user_pk": hijacked.pk}, HTTP_REFERER=initial_url)
        assert response.status_code == 302
        assert response["Location"] == "/dashboard/"

        response = self.client.post(reverse("hijack:release"), {"user_pk": hijacked.pk})
        assert response.status_code == 302
        assert response["Location"] == "/admin/users/user/"


@pytest.mark.parametrize(
    "user_factory,identity_provider,is_redirected",
    [
        (ItouStaffFactory, IdentityProvider.DJANGO, False),
        (JobSeekerFactory, IdentityProvider.DJANGO, False),
        (JobSeekerFactory, IdentityProvider.PE_CONNECT, False),
        (JobSeekerFactory, IdentityProvider.FRANCE_CONNECT, False),
        (PrescriberFactory, IdentityProvider.DJANGO, True),
        (PrescriberFactory, IdentityProvider.INCLUSION_CONNECT, False),
        (partial(EmployerFactory, with_company=True), IdentityProvider.DJANGO, True),
        (partial(EmployerFactory, with_company=True), IdentityProvider.INCLUSION_CONNECT, False),
        (LaborInspectorFactory, IdentityProvider.DJANGO, False),
    ],
)
def test_redirect_to_ic_activation_view(client, user_factory, identity_provider, is_redirected):
    user = user_factory(identity_provider=identity_provider)
    client.force_login(user)
    response = client.get(reverse("search:employers_home"), follow=True)
    if is_redirected:
        assertRedirects(response, reverse("dashboard:activate_ic_account"))
    else:
        assert response.status_code == 200


class TestEmployeeRecord:
    @pytest.mark.parametrize(
        "status",
        [
            employee_record_enums.Status.NEW,
            employee_record_enums.Status.REJECTED,
            employee_record_enums.Status.DISABLED,
        ],
    )
    def test_tunnel_step_is_allowed_with_valid_status(self, status):
        job_application = EmployeeRecordFactory(status=status).job_application
        assert employee_record.tunnel_step_is_allowed(job_application) is True

    @pytest.mark.parametrize(
        "status",
        [
            employee_record_enums.Status.READY,
            employee_record_enums.Status.SENT,
            employee_record_enums.Status.PROCESSED,
            employee_record_enums.Status.ARCHIVED,
        ],
    )
    def test_tunnel_step_is_allowed_with_invalid_status(self, status):
        job_application = EmployeeRecordFactory(status=status).job_application
        assert employee_record.tunnel_step_is_allowed(job_application) is False
