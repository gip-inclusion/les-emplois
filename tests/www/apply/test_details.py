from django.urls import reverse
from pytest_django.asserts import assertNotContains

from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import EmployerFactory


def test_missing_job_seeker_info(client):
    job_application = JobApplicationFactory(
        job_seeker__phone="",
        job_seeker__email=None,
        job_seeker__jobseeker_profile__birthdate=None,
        job_seeker__jobseeker_profile__nir="",
        job_seeker__jobseeker_profile__pole_emploi_id="",
    )
    user = EmployerFactory(with_company=True, with_company__company=job_application.to_company)
    client.force_login(user)
    url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
    response = client.get(url)

    assertNotContains(response, "None")
