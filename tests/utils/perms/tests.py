from functools import partial

import pytest
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertRedirects

from itou.employee_record import enums as employee_record_enums
from itou.users.enums import IdentityProvider
from itou.utils.perms import employee_record
from itou.utils.perms.utils import can_edit_personal_information, can_view_personal_information
from tests.companies.factories import CompanyFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


@pytest.mark.parametrize(
    "user_factory,identity_provider,is_redirected",
    [
        (ItouStaffFactory, IdentityProvider.DJANGO, False),
        (JobSeekerFactory, IdentityProvider.DJANGO, False),
        (JobSeekerFactory, IdentityProvider.PE_CONNECT, False),
        (JobSeekerFactory, IdentityProvider.FRANCE_CONNECT, False),
        (PrescriberFactory, IdentityProvider.DJANGO, True),
        (PrescriberFactory, IdentityProvider.INCLUSION_CONNECT, True),
        (PrescriberFactory, IdentityProvider.PRO_CONNECT, False),
        (partial(EmployerFactory, with_company=True), IdentityProvider.DJANGO, True),
        (partial(EmployerFactory, with_company=True), IdentityProvider.INCLUSION_CONNECT, True),
        (partial(EmployerFactory, with_company=True), IdentityProvider.PRO_CONNECT, False),
        (LaborInspectorFactory, IdentityProvider.DJANGO, False),
    ],
)
def test_redirect_to_pc_activation_view(client, user_factory, identity_provider, is_redirected):
    user = user_factory(identity_provider=identity_provider)
    client.force_login(user)
    response = client.get(reverse("search:employers_home"), follow=True)
    if is_redirected:
        assertRedirects(response, reverse("dashboard:activate_pro_connect_account"))
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


class TestUtils:
    def test_can_edit_personal_information(self):
        request = RequestFactory()
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        unauthorized_prescriber = PrescriberFactory()
        employer = CompanyFactory(with_membership=True).members.first()
        job_seeker = JobSeekerFactory()
        user_created_by_prescriber = JobSeekerFactory(created_by=unauthorized_prescriber, last_login=None)
        logged_user_created_by_prescriber = JobSeekerFactory(
            created_by=unauthorized_prescriber, last_login=timezone.now()
        )
        user_created_by_employer = JobSeekerFactory(created_by=employer, last_login=None)
        logged_user_created_by_employer = JobSeekerFactory(created_by=employer, last_login=timezone.now())

        specs = {
            "authorized_prescriber": {
                "authorized_prescriber": True,
                "unauthorized_prescriber": False,
                "employer": False,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "logged_user_created_by_prescriber": False,
                "user_created_by_employer": True,
                "logged_user_created_by_employer": False,
            },
            "unauthorized_prescriber": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": True,
                "employer": False,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "logged_user_created_by_prescriber": False,
                "user_created_by_employer": False,
                "logged_user_created_by_employer": False,
            },
            "employer": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "employer": True,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "logged_user_created_by_prescriber": False,
                "user_created_by_employer": True,
                "logged_user_created_by_employer": False,
            },
            "job_seeker": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "employer": False,
                "job_seeker": True,
                "user_created_by_prescriber": False,
                "logged_user_created_by_prescriber": False,
                "user_created_by_employer": False,
                "logged_user_created_by_employer": False,
            },
        }
        for user_type, user_specs in specs.items():
            for other_user_type, expected in user_specs.items():
                request.user = locals()[user_type]
                assert can_edit_personal_information(request, locals()[other_user_type]) is expected, (
                    f"{user_type} can_edit_personal_information {other_user_type}"
                )

    def test_can_view_personal_information(self):
        request = RequestFactory()
        authorized_prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.first()
        unauthorized_prescriber = PrescriberFactory()
        employer = CompanyFactory(with_membership=True).members.first()
        job_seeker = JobSeekerFactory()
        user_created_by_prescriber = JobSeekerFactory(created_by=unauthorized_prescriber, last_login=None)
        user_created_by_employer = JobSeekerFactory(created_by=employer, last_login=None)

        specs = {
            "authorized_prescriber": {
                "authorized_prescriber": True,
                "unauthorized_prescriber": False,
                "employer": False,
                "job_seeker": True,
                "user_created_by_prescriber": True,
                "user_created_by_employer": True,
            },
            "unauthorized_prescriber": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": True,
                "employer": False,
                "job_seeker": False,
                "user_created_by_prescriber": True,
                "user_created_by_employer": False,
            },
            "employer": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "employer": True,
                "job_seeker": True,
                "user_created_by_prescriber": True,
                "user_created_by_employer": True,
            },
            "job_seeker": {
                "authorized_prescriber": False,
                "unauthorized_prescriber": False,
                "employer": False,
                "job_seeker": True,
                "user_created_by_prescriber": False,
                "user_created_by_employer": False,
            },
        }
        for user_type, user_specs in specs.items():
            for other_user_type, expected in user_specs.items():
                request.user = locals()[user_type]
                assert can_view_personal_information(request, locals()[other_user_type]) is expected, (
                    f"{user_type} can_view_personal_information {other_user_type}"
                )
