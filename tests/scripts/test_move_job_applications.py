import pytest
from django.core import management

from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory, IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import ItouStaffFactory


@pytest.mark.parametrize("wet_run", [True, False])
def test_command(wet_run, caplog):
    admin = ItouStaffFactory()

    membership = PrescriberMembershipFactory()
    prescriber = membership.user
    target_org = membership.organization

    iae_diag = IAEEligibilityDiagnosisFactory(author=prescriber, from_prescriber=True)
    current_org = iae_diag.author_prescriber_organization
    iae_application = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=prescriber,
        eligibility_diagnosis=iae_diag,
        sender_prescriber_organization=current_org,
    )
    geiq_diag = GEIQEligibilityDiagnosisFactory(
        author=prescriber, from_prescriber=True, author_prescriber_organization=current_org
    )
    geiq_application = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        sender=prescriber,
        geiq_eligibility_diagnosis=geiq_diag,
        sender_prescriber_organization=current_org,
    )

    management.call_command(
        "move_job_applications",
        prescriber.pk,
        on_behalf_of=admin.pk,
        from_org=current_org.pk,
        to_org=target_org.pk,
        wet_run=wet_run,
    )
    expected_logs = [
        (
            f"Moving job applications for prescriber={prescriber.pk} from "
            f"pk={current_org.pk} to pk={target_org.pk} for staff={admin.pk}"
        ),
        "Job applications sent by the prescriber count=2",
        "IAE eligibility diagnosis created by the prescriber count=1",
        "Created log entries for IAE eligibility diagnosis count=1",
        "Updated IAE eligibility diagnosis count=1",
        "GEIQ eligibility diagnosis created by the prescriber count=1",
        "Created log entries for GEIQ eligibility diagnosis count=1",
        "Updated GEIQ eligibility diagnosis count=1",
        "Created log entries for job applications count=2",
        "Updated job applications count=2",
    ]
    if not wet_run:
        expected_logs = (
            ["Command launched with wet_run=False"]
            + expected_logs
            + ["Setting transaction to be rollback as wet_run=False"]
        )
    assert caplog.messages[:-1] == expected_logs
    assert caplog.messages[-1].startswith(
        "Management command itou.scripts.management.commands.move_job_applications succeeded in"
    )
    for diag in [iae_diag, geiq_diag]:
        diag.refresh_from_db()
        assert diag.author_prescriber_organization == target_org if wet_run else current_org
    for application in [iae_application, geiq_application]:
        application.refresh_from_db()
        assert application.sender_prescriber_organization == target_org if wet_run else current_org
