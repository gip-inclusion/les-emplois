from functools import partial

import pytest
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
