import pytest
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains

from itou.utils import constants as global_constants
from tests.companies.factories import CompanyFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory


class TestDisplayApproval:
    WITH_DIAGNOSIS_STR = "Au vu du diagnostic individuel réalisé par"

    @freeze_time("2023-04-26")
    def test_display_job_app_approval(self, client):
        job_application = JobApplicationFactory(sent_by_prescriber_alone=True, with_approval=True)

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        response = client.get(
            reverse("approvals:display_printable_approval", kwargs={"public_id": job_application.approval.public_id})
        )

        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_company
        assertContains(response, "le 26 avril 2023")
        assertContains(response, global_constants.ITOU_HELP_CENTER_URL)
        assertContains(response, "Imprimer ce PASS IAE")
        assertContains(response, job_application.approval.start_at.strftime("%d/%m/%Y"))
        assertContains(response, job_application.approval.get_remainder_display())
        assertContains(response, self.WITH_DIAGNOSIS_STR)

    def test_display_approval_multiple_job_applications(self, client):
        job_application = JobApplicationFactory(sent_by_prescriber_alone=True, with_approval=True)
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=job_application.job_seeker,
            approval=job_application.approval,
            to_company=job_application.to_company,
            state=job_application.state,
            created_at=job_application.created_at - relativedelta(days=1),
        )

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        response = client.get(
            reverse("approvals:display_printable_approval", kwargs={"public_id": job_application.approval.public_id})
        )

        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_company
        assertContains(response, global_constants.ITOU_HELP_CENTER_URL)
        assertContains(response, "Imprimer ce PASS IAE")
        assertContains(response, self.WITH_DIAGNOSIS_STR)

    def test_display_approval_even_if_diagnosis_is_missing(self, client):
        # An approval has been delivered but it does not come from Itou.
        # Therefore, the linked diagnosis exists but is not in our database.
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            with_approval=True,
            eligibility_diagnosis=None,
            approval__number="625741810181",
        )

        employer = job_application.to_company.members.first()
        client.force_login(employer)

        response = client.get(
            reverse("approvals:display_printable_approval", kwargs={"public_id": job_application.approval.public_id})
        )

        assert response.context["approval"] == job_application.approval
        assert response.context["siae"] == job_application.to_company
        assertContains(response, global_constants.ITOU_HELP_CENTER_URL)
        assertContains(response, "Imprimer ce PASS IAE")
        assertNotContains(response, self.WITH_DIAGNOSIS_STR)

    @pytest.mark.parametrize(
        "scenario,should_access",
        [
            ["this company", True],
            ["another company", False],
            ["this job seeker", False],
            ["another job seeker", False],
            ["a prescriber", False],
        ],
    )
    def test_access(self, client, scenario, should_access):
        job_application = JobApplicationFactory(
            with_approval=True,
            sent_by_prescriber=True,
            with_job_seeker_assignment=True,
        )
        approval = job_application.approval
        if scenario == "this job seeker":
            user = approval.user
        elif scenario == "this company":
            user = EmployerFactory(membership__company=job_application.to_company)
        elif scenario == "another job seeker":
            user = JobSeekerFactory()
        elif scenario == "another company":
            other_company = CompanyFactory(subject_to_iae_rules=True)
            user = EmployerFactory(membership__company=other_company)
        elif scenario == "a prescriber":
            user = job_application.sender
            assert user.prescribermembership_set.exists()
        else:
            raise ValueError(f"Unexpected {scenario=}")

        client.force_login(user)
        response = client.get(
            reverse(
                "approvals:display_printable_approval",
                kwargs={"public_id": approval.public_id},
            )
        )
        assert response.status_code == (200 if should_access else 404)
