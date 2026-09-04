from pytest_django.asserts import assertQuerySetEqual

from itou.job_applications.models import JobApplication
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory


def test_with_last_name_for_display():
    user1 = JobSeekerFactory(last_name="", jobseeker_profile__birth_name="1")
    ja1 = JobApplicationFactory(sent_by_job_seeker=True, job_seeker=user1)
    user2 = JobSeekerFactory(last_name="4", jobseeker_profile__birth_name="2")
    ja2 = JobApplicationFactory(sent_by_job_seeker=True, job_seeker=user2)

    applications = JobApplication.objects.with_job_seeker_last_name_for_display().order_by(
        "job_seeker_last_name_for_display"
    )

    assertQuerySetEqual(applications, [ja1, ja2])
    assert applications[0].job_seeker_last_name_for_display == "1"
    assert applications[1].job_seeker_last_name_for_display == "4"
