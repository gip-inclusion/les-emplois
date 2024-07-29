import datetime

from django.core.management import call_command
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.job_applications.enums import ARCHIVABLE_JOB_APPLICATION_STATES, JobApplicationState
from itou.job_applications.models import JobApplication
from tests.job_applications.factories import JobApplicationFactory


def test_archive(capsys):
    real_now = timezone.now()
    for state in JobApplicationState.values:
        JobApplicationFactory(state=state)
    already_archived_job_app = JobApplicationFactory(archived_at=real_now - datetime.timedelta(days=365))
    cutoff = real_now - datetime.timedelta(days=183)
    with freeze_time(cutoff):
        old_job_apps = {state: JobApplicationFactory(state=state) for state in JobApplicationState.values}
        updated_job_app = JobApplicationFactory()
    with freeze_time(cutoff + datetime.timedelta(hours=1)):
        updated_job_app.state = JobApplicationState.PROCESSING
        updated_job_app.save()

    call_command("archive_job_applications")

    assertQuerySetEqual(
        JobApplication.objects.exclude(archived_at=None),
        [
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
    captured = capsys.readouterr()
    assert captured.out == f"Archived {len(ARCHIVABLE_JOB_APPLICATION_STATES)} job applications.\n"
    assert captured.err == ""
