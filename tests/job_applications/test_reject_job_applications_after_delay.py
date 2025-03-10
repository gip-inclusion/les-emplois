import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from itou.job_applications.enums import (
    AUTO_REJECT_JOB_APPLICATION_DELAY,
    AUTO_REJECT_JOB_APPLICATION_STATES,
    JobApplicationState,
    RefusalReason,
)
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory


@pytest.mark.parametrize("state", AUTO_REJECT_JOB_APPLICATION_STATES)
def test_reject_job_applications_after_delay(state, django_capture_on_commit_callbacks, mailoutbox, snapshot, caplog):
    limit = 2

    # first job_seeker with the oldest and the most recent job applications
    oldest_expected_job_application = JobApplicationFactory(
        state=state,
        answer="",
        updated_at=timezone.now() - AUTO_REJECT_JOB_APPLICATION_DELAY - datetime.timedelta(days=4),
    )
    recent_job_application_of_the_same_job_seeker = JobApplicationFactory(
        state=state,
        answer="",
        job_seeker=oldest_expected_job_application.job_seeker,
        updated_at=timezone.now() - AUTO_REJECT_JOB_APPLICATION_DELAY,
    )
    # second job_seeker with numerous oldish job applications
    job_seeker = JobSeekerFactory()
    other_expected_job_applications = JobApplicationFactory.create_batch(
        limit + 1,
        job_seeker=job_seeker,
        state=state,
        answer="",
        updated_at=timezone.now() - AUTO_REJECT_JOB_APPLICATION_DELAY - datetime.timedelta(days=3),
    )
    # unselected oldish job application of the third job_seeker
    unexpected_job_application = JobApplicationFactory(
        state=state,
        answer="",
        updated_at=timezone.now() - AUTO_REJECT_JOB_APPLICATION_DELAY - datetime.timedelta(days=2),
    )

    with django_capture_on_commit_callbacks(execute=True):
        call_command("reject_job_applications_after_delay", "--limit", limit)

    assert "5 auto rejected job applications for 2 job seekers." in caplog.messages

    # selected job applications
    for job_application, mail in list(
        zip(
            [
                oldest_expected_job_application,
                recent_job_application_of_the_same_job_seeker,
                *other_expected_job_applications,
            ],
            mailoutbox,
        )
    ):
        job_application.refresh_from_db()
        assert job_application.state == JobApplicationState.REFUSED
        assert job_application.refusal_reason == RefusalReason.AUTO
        assert job_application.answer == snapshot(name="auto.txt")
        assert mail.to == [job_application.job_seeker.email]
        assert job_application.answer in mail.body

    # unselected job application
    unexpected_job_application.refresh_from_db()
    assert unexpected_job_application.state == state
    assert unexpected_job_application.refusal_reason == ""
    assert unexpected_job_application.answer == ""
    assert unexpected_job_application.job_seeker.email not in [
        email_addr for mail in mailoutbox for email_addr in mail.to
    ]
