import pytest
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.utils import constants as global_constants
from tests.approvals.factories import ApprovalFactory
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory


class TestDisplayApproval:
    WITH_DIAGNOSIS_STR = "Au vu du diagnostic individuel réalisé par"

    @freeze_time("2023-04-26")
    def test_display_job_app_approval(self, client):
        job_application = JobApplicationFactory(with_approval=True)

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
        job_application = JobApplicationFactory(with_approval=True)
        JobApplicationFactory(
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
            with_approval=True, eligibility_diagnosis=None, approval__number="625741810181"
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
    "user",
    [
        None,
        lambda: PrescriberFactory(),
        lambda: JobSeekerFactory(),
        lambda: EmployerFactory(with_company=True),
        lambda: InstitutionWithMembershipFactory().active_members.first(),
    ],
)
def test_redirect_to_display_printable_approval_on_user_kind(client, user):
    approval = ApprovalFactory()

    if user:
        user = user()
        client.force_login(user)

    url = reverse("approvals:redirect_to_display_printable_approval", kwargs={"approval_id": approval.id})
    response = client.get(url)

    if not user:
        assertRedirects(response, reverse("account_login") + f"?next={url}")
    elif not user.is_employer:
        assert response.status_code == 403
    else:
        assertRedirects(
            response,
            reverse("approvals:display_printable_approval", kwargs={"public_id": approval.public_id}),
            fetch_redirect_response=False,
        )


@pytest.mark.parametrize("approval", [None, lambda: ApprovalFactory()])
def test_redirect_to_display_printable_approval_on_approval_existence(client, approval):
    approval_id = 2025
    if approval:
        approval = approval()
        approval_id = approval.id
    client.force_login(EmployerFactory(with_company=True))

    response = client.get(
        reverse("approvals:redirect_to_display_printable_approval", kwargs={"approval_id": approval_id})
    )

    if not approval:
        assert response.status_code == 404
    else:
        assertRedirects(
            response,
            reverse("approvals:display_printable_approval", kwargs={"public_id": approval.public_id}),
            fetch_redirect_response=False,
        )
