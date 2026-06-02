import datetime

from django.core.management import call_command
from django.db import transaction
from django.utils import timezone
from pytest_django.asserts import assertQuerySetEqual

from itou.job_applications.enums import ARCHIVABLE_JOB_APPLICATION_STATES, JobApplicationState
from itou.job_applications.models import JobApplication
from tests.job_applications.factories import JobApplicationFactory


def test_archive(caplog):
    real_now = timezone.now()
    for state in JobApplicationState.values:
        JobApplicationFactory(sent_by_prescriber_alone=True, state=state)
    already_archived_job_app = JobApplicationFactory(
        sent_by_prescriber_alone=True, archived_at=real_now - datetime.timedelta(days=365)
    )
    recently_archived_job_app = JobApplicationFactory(
        sent_by_prescriber_alone=True, archived_at=real_now - datetime.timedelta(days=1)
    )
    cutoff = real_now - datetime.timedelta(days=180)
    old_job_apps = {
        state: JobApplicationFactory(
            sent_by_prescriber_alone=True,
            state=state,
            updated_at=cutoff,
        )
        for state in JobApplicationState.values
    }
    # Updated job application.
    JobApplicationFactory(
        sent_by_prescriber_alone=True,
        state=JobApplicationState.PROCESSING,
        updated_at=cutoff + datetime.timedelta(hours=1),
    )

    already_archived_count = JobApplication.objects.exclude(archived_at=None).count()
    expected_log = f"Archived {len(ARCHIVABLE_JOB_APPLICATION_STATES)} job applications"

    # Dry run
    with transaction.atomic():
        call_command("archive_job_applications")
    assert caplog.messages[:-1] == [
        "Command launched with wet_run=False",
        expected_log,
        "Setting transaction to be rollback as wet_run=False",
    ]
    assert caplog.messages[-1].startswith(
        "Management command itou.job_applications.management.commands.archive_job_applications succeeded in"
    )
    assert JobApplication.objects.exclude(archived_at=None).count() == already_archived_count

    # Wet run
    caplog.clear()
    with transaction.atomic():
        call_command("archive_job_applications", wet_run=True)
    assert JobApplication.objects.exclude(archived_at=None).count() == already_archived_count + len(
        ARCHIVABLE_JOB_APPLICATION_STATES
    )
    assertQuerySetEqual(
        JobApplication.objects.exclude(archived_at=None),
        [
            recently_archived_job_app,
            old_job_apps[JobApplicationState.NEW],
            old_job_apps[JobApplicationState.PROCESSING],
            old_job_apps[JobApplicationState.POSTPONED],
            old_job_apps[JobApplicationState.REFUSED],
            old_job_apps[JobApplicationState.CANCELLED],
            old_job_apps[JobApplicationState.OBSOLETE],
            already_archived_job_app,
        ],
        ordered=False,
    )
    assert caplog.messages[:-1] == [expected_log]
    assert caplog.messages[-1].startswith(
        "Management command itou.job_applications.management.commands.archive_job_applications succeeded in"
    )
