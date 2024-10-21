from django.template.defaultfilters import urlencode
from django.urls import reverse

from itou.companies.enums import CompanyKind
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication, JobApplicationState
from tests.cities.factories import create_city_guerande
from tests.companies.factories import CompanyWithMembershipAndJobsFactory, JobDescriptionFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import JobSeekerFactory, PrescriberFactory
from tests.utils.test import TestCase


class ApplyAsPrescriberTest(TestCase):
    def test_apply_as_prescriber(self):
        guerande = create_city_guerande()
        guerande_company = CompanyWithMembershipAndJobsFactory(
            romes=("N1101", "N1105"),
            department="44",
            coords=guerande.coords,
            post_code="44350",
            kind=CompanyKind.AI,
            with_membership=True,
        )
        JobDescriptionFactory(company=guerande_company, location=guerande)
        prescriber = PrescriberFactory(membership__organization__authorized=True)
        job_seeker = JobSeekerFactory(
            first_name="Alain",
            last_name="Zorro",
            public_id="11111111-2222-3333-4444-555566667777",
        )
        # This is to have a job seeker in "Mes candidats" (job_seekers_views:list)
        JobApplicationFactory(
            job_seeker=job_seeker,
            sender=prescriber,
        )

        self.client.force_login(prescriber)

        # Entry point: job seekers list
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("job_seekers_views:list"))
        assert response.status_code == 200
        next_url = f"{reverse('search:employers_results')}?job_seeker={job_seeker.public_id}"
        self.assertContains(
            response,
            (
                '<a class="btn btn-sm btn-link btn-ico-only" '
                'aria-label="Postuler pour ce candidat" '
                f'href="{next_url}">'
            ),
        )

        # Alternative entry point: job seeker details
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id}))
        assert response.status_code == 200
        next_url = f"{reverse('search:employers_results')}?job_seeker={job_seeker.public_id}"
        self.assertContains(
            response,
            (
                f'<a href="{next_url}"'
                'class="btn btn-lg btn-primary btn-ico">'
                '<i class="ri-draft-line fw-medium" aria-hidden="true"></i>'
                "<span>Postuler pour ce candidat</span>"
            ),
            html=True,
        )

        # Step search company
        # ----------------------------------------------------------------------

        response = self.client.get(
            reverse("search:employers_results"), {"city": guerande.slug, "job_seeker": job_seeker.public_id}
        )
        self.assertContains(response, "Vous postulez actuellement pour Alain ZORRO")

        # Has link to company card with job_seeker public_id
        company_url_with_job_seeker_id = (
            f"{guerande_company.get_card_url()}?job_seeker={job_seeker.public_id}"
            f"&back_url={urlencode(response.wsgi_request.get_full_path())}"
        )
        self.assertContains(
            response,
            company_url_with_job_seeker_id,
        )

        # Step apply to company
        # ----------------------------------------------------------------------

        apply_company_url = (
            reverse("apply:start", kwargs={"company_pk": guerande_company.pk}) + f"?job_seeker={job_seeker.public_id}"
        )
        response = self.client.get(apply_company_url)
        assert response.status_code == 302

        next_url = reverse(
            "apply:application_jobs",
            kwargs={"company_pk": guerande_company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assert response.url == next_url

        # Step apply to job
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        selected_job = guerande_company.job_description_through.first()
        response = self.client.post(next_url, data={"selected_jobs": [selected_job.pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{guerande_company.pk}"] == {"selected_jobs": [selected_job.pk]}

        next_url = reverse(
            "apply:application_eligibility",
            kwargs={"company_pk": guerande_company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assert response.url == next_url

        # Step application's eligibility
        # ----------------------------------------------------------------------

        # job seeker is getting RSA
        response = self.client.post(next_url, {"level_1_1": True})
        assert response.status_code == 302

        assert EligibilityDiagnosis.objects.has_considered_valid(job_seeker, for_siae=guerande_company)

        next_url = reverse(
            "apply:application_resume",
            kwargs={"company_pk": guerande_company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertContains(response, "Envoyer la candidature")

        response = self.client.post(
            next_url,
            data={
                "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            },
        )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=prescriber, to_company=guerande_company)
        assert job_application.job_seeker == job_seeker
        assert job_application.sender_kind == SenderKind.PRESCRIBER
        assert job_application.sender_company is None
        assert job_application.sender_prescriber_organization == prescriber.prescriberorganization_set.first()
        assert job_application.state == JobApplicationState.NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert job_application.selected_jobs.get() == selected_job

        assert f"job_application-{guerande_company.pk}" not in self.client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": guerande_company.pk, "application_pk": job_application.pk}
        )
        assert response.url == next_url

    def test_cannot_apply_as_prescriber_with_incorrect_public_id(self):
        company = CompanyWithMembershipAndJobsFactory()
        job_description = JobDescriptionFactory(company=company)
        prescriber = PrescriberFactory(membership__organization__authorized=True)

        self.client.force_login(prescriber)

        # Step apply to company
        # ----------------------------------------------------------------------

        apply_company_url_incorrect_uuid = (
            reverse("apply:start", kwargs={"company_pk": company.pk}) + "?job_seeker=123"
        )
        response = self.client.get(apply_company_url_incorrect_uuid)
        assert response.status_code == 302

        # same URL without ?job_seeker
        next_url = reverse(
            "apply:start",
            kwargs={
                "company_pk": company.pk,
            },
        )
        assert response.url == next_url

        # Step apply to job
        # ----------------------------------------------------------------------

        apply_job_description_url_incorrect_uuid = (
            reverse("apply:start", kwargs={"company_pk": company.pk})
            + f"?job_description_id={job_description.pk}&job_seeker=123"
        )

        response = self.client.get(apply_job_description_url_incorrect_uuid)
        assert response.status_code == 302

        # same URL without ?job_seeker
        next_url = (
            reverse("apply:start", kwargs={"company_pk": company.pk}) + f"?job_description_id={job_description.pk}"
        )
        assert response.url == next_url


class ApplyAsCompanyTest(TestCase):
    """As an employer, I can apply for a job seeker in another company"""

    def test_apply_as_company(self):
        guerande = create_city_guerande()
        guerande_company = CompanyWithMembershipAndJobsFactory(
            romes=("N1101", "N1105"),
            department="44",
            coords=guerande.coords,
            post_code="44350",
            kind=CompanyKind.ETTI,
            with_membership=True,
        )
        other_company = CompanyWithMembershipAndJobsFactory(
            romes=("N1101", "N1105"),
            department="44",
            coords=guerande.coords,
            post_code="44350",
            kind=CompanyKind.ETTI,
            with_membership=True,
        )
        JobDescriptionFactory(company=other_company, location=guerande)
        employer = guerande_company.members.first()
        job_seeker = JobSeekerFactory(
            first_name="Alain",
            last_name="Zorro",
            public_id="11111111-2222-3333-4444-555566667777",
        )

        self.client.force_login(employer)

        # Entry point: job seeker details
        # ----------------------------------------------------------------------

        response = self.client.get(reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id}))
        assert response.status_code == 200
        next_url = f"{reverse('search:employers_results')}?job_seeker={job_seeker.public_id}"
        self.assertContains(
            response,
            (
                f'<a href="{next_url}"'
                'class="btn btn-lg btn-primary btn-ico">'
                '<i class="ri-draft-line fw-medium" aria-hidden="true"></i>'
                "<span>Postuler pour ce candidat</span>"
            ),
            html=True,
        )

        # Step search company
        # ----------------------------------------------------------------------

        response = self.client.get(
            reverse("search:employers_results"), {"city": guerande.slug, "job_seeker": job_seeker.public_id}
        )
        self.assertContains(response, "Vous postulez actuellement pour Alain ZORRO")

        # Has link to company card with job_seeker public_id
        company_url_with_job_seeker_id = (
            f"{other_company.get_card_url()}?job_seeker={job_seeker.public_id}"
            f"&back_url={urlencode(response.wsgi_request.get_full_path())}"
        )
        self.assertContains(
            response,
            company_url_with_job_seeker_id,
        )

        # Step apply to company
        # ----------------------------------------------------------------------

        apply_company_url = (
            reverse("apply:start", kwargs={"company_pk": other_company.pk}) + f"?job_seeker={job_seeker.public_id}"
        )
        response = self.client.get(apply_company_url)
        assert response.status_code == 302

        next_url = reverse(
            "apply:application_jobs",
            kwargs={"company_pk": other_company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assert response.url == next_url

        # Step application's jobs.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        assert response.status_code == 200

        selected_job = other_company.job_description_through.first()
        response = self.client.post(next_url, data={"selected_jobs": [selected_job.pk]})
        assert response.status_code == 302

        assert self.client.session[f"job_application-{other_company.pk}"] == {"selected_jobs": [selected_job.pk]}

        next_url = reverse(
            "apply:application_eligibility",
            kwargs={"company_pk": other_company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assert response.url == next_url

        # Step application's eligibility
        # ----------------------------------------------------------------------
        response = self.client.get(next_url)

        next_url = reverse(
            "apply:application_resume",
            kwargs={"company_pk": other_company.pk, "job_seeker_public_id": job_seeker.public_id},
        )
        assert response.url == next_url

        # Step application's resume.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)

        response = self.client.post(
            next_url,
            data={
                "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            },
        )
        assert response.status_code == 302

        job_application = JobApplication.objects.get(sender=employer, to_company=other_company)
        assert job_application.job_seeker == job_seeker
        assert job_application.sender_kind == SenderKind.EMPLOYER
        assert job_application.sender_company == guerande_company
        assert job_application.sender_prescriber_organization is None
        assert job_application.state == JobApplicationState.NEW
        assert job_application.message == "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        assert job_application.selected_jobs.get() == selected_job

        assert f"job_application-{other_company.pk}" not in self.client.session

        next_url = reverse(
            "apply:application_end", kwargs={"company_pk": other_company.pk, "application_pk": job_application.pk}
        )
        assert response.url == next_url

    def test_cannot_apply_as_company_with_incorrect_public_id(self):
        company = CompanyWithMembershipAndJobsFactory()
        other_company = CompanyWithMembershipAndJobsFactory()
        employer = company.members.first()
        job_description = JobDescriptionFactory(company=other_company)

        self.client.force_login(employer)

        # Step apply to company
        # ----------------------------------------------------------------------

        apply_company_url_incorrect_uuid = (
            reverse("apply:start", kwargs={"company_pk": other_company.pk}) + "?job_seeker=123"
        )
        response = self.client.get(apply_company_url_incorrect_uuid)
        assert response.status_code == 302

        # same URL without ?job_seeker
        next_url = reverse(
            "apply:start",
            kwargs={
                "company_pk": other_company.pk,
            },
        )
        assert response.url == next_url

        # Step apply to job
        # ----------------------------------------------------------------------

        apply_job_description_url_incorrect_uuid = (
            reverse("apply:start", kwargs={"company_pk": other_company.pk})
            + f"?job_description_id={job_description.pk}&job_seeker=123"
        )

        response = self.client.get(apply_job_description_url_incorrect_uuid)
        assert response.status_code == 302

        # same URL without ?job_seeker
        next_url = (
            reverse("apply:start", kwargs={"company_pk": other_company.pk})
            + f"?job_description_id={job_description.pk}"
        )
        assert response.url == next_url


class ApplyAsJobSeekerTest(TestCase):
    def test_cannot_apply_as_job_seeker_for_someone_else(self):
        company = CompanyWithMembershipAndJobsFactory()
        job_description = JobDescriptionFactory(company=company)
        job_seeker = JobSeekerFactory()
        other_job_seeker = JobSeekerFactory()

        self.client.force_login(job_seeker)

        # Step apply to company
        # ----------------------------------------------------------------------

        apply_company_url_incorrect_uuid = (
            reverse("apply:start", kwargs={"company_pk": company.pk}) + f"?job_seeker={other_job_seeker.public_id}"
        )
        response = self.client.get(apply_company_url_incorrect_uuid)
        assert response.status_code == 302

        # same URL without ?job_seeker
        next_url = reverse(
            "apply:start",
            kwargs={
                "company_pk": company.pk,
            },
        )
        assert response.url == next_url

        # Step apply to job
        # ----------------------------------------------------------------------

        apply_job_description_url_incorrect_uuid = (
            reverse("apply:start", kwargs={"company_pk": company.pk})
            + f"?job_description_id={job_description.pk}&job_seeker=123"
        )

        response = self.client.get(apply_job_description_url_incorrect_uuid)
        assert response.status_code == 302

        # same URL without ?job_seeker
        next_url = (
            reverse("apply:start", kwargs={"company_pk": company.pk}) + f"?job_description_id={job_description.pk}"
        )
        assert response.url == next_url
