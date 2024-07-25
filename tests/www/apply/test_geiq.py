from django.urls import reverse
from django.utils import dateformat
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertTemplateNotUsed, assertTemplateUsed

from itou.companies.enums import CompanyKind
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory, JobSeekerWithAddressFactory


class TestJobApplicationGEIQEligibilityDetails:
    EXPIRED_DIAGNOSIS_EXPLANATION = "Le diagnostic du candidat a expiré"

    def test_with_geiq_eligibility_details(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
        job_application = JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
            eligibility_diagnosis=None,
        )
        client.force_login(job_application.to_company.members.first())
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        assert response.status_code == 200
        assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")
        assertContains(response, "Éligibilité public prioritaire GEIQ validée")
        assertContains(
            response,
            "Ce diagnostic émis par un prescripteur habilité vous donnera droit en cas d’embauche",
        )
        assertContains(
            response,
            f"une aide financière de l’État s’élevant à <b>{diagnosis.allowance_amount} €</b> ",
        )

    def test_without_geiq_eligibility_details(self, client):
        # No GEIQ diagnosis for this job seeker / job application
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ)
        client.force_login(job_application.to_company.members.first())
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        assert response.status_code == 200
        assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")
        assertContains(response, "Éligibilité public prioritaire GEIQ non confirmée")

    def test_details_as_geiq_with_valid_eligibility_diagnosis(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_geiq=True)
        job_application = JobApplicationFactory(
            job_seeker=diagnosis.job_seeker,
            to_company=diagnosis.author_geiq,
            eligibility_diagnosis=None,
        )

        client.force_login(diagnosis.author_geiq.members.first())
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")
        assertContains(
            response,
            "Éligibilité public prioritaire GEIQ non confirmée",
        )
        assertContains(
            response,
            "Les critères que vous avez sélectionnés ne vous permettent pas de bénéficier d’une aide financière de l’État.",  # noqa: E501
        )
        assertNotContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)
        # More in `test_allowance_details_for_geiq`

    def test_details_as_geiq_with_expired_eligibility_diagnosis(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_geiq=True, expired=True)
        job_application = JobApplicationFactory(
            to_company=diagnosis.author_geiq,
            job_seeker=diagnosis.job_seeker,
            eligibility_diagnosis=None,
        )

        client.force_login(diagnosis.author_geiq.members.first())
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")
        assertContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)
        assertContains(
            response,
            "Éligibilité public prioritaire GEIQ non confirmée",
        )

    @freeze_time("2024-02-15")
    def test_details_as_authorized_prescriber_with_valid_diagnosis(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
        job_application = JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            eligibility_diagnosis=None,
        )
        client.force_login(job_application.to_company.members.first())
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        assertContains(
            response,
            f"Éligibilité GEIQ confirmée par "
            f"<b>{diagnosis.author.get_full_name()} ({diagnosis.author_prescriber_organization.display_name})</b>",
        )
        assertContains(response, "<b>Durée de validité du diagnostic :</b> du 15/02/2024 au 15/08/2024")

    def test_details_as_authorized_prescriber_with_expired_diagnosis(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(expired=True, from_prescriber=True)
        job_application = JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            eligibility_diagnosis=None,
        )

        client.force_login(job_application.to_company.members.first())
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        assertContains(
            response,
            f"{self.EXPIRED_DIAGNOSIS_EXPLANATION} le {dateformat.format(diagnosis.expires_at, 'd F Y')}",
        )

    def test_allowance_details_for_geiq(self, client):
        # Slightly more complex than for prescribers :
        # allowance amount is variable in function of chosen administrative criteria
        diagnosis = GEIQEligibilityDiagnosisFactory(from_geiq=True)
        job_application = JobApplicationFactory(
            to_company=diagnosis.author_geiq,
            job_seeker=diagnosis.job_seeker,
            eligibility_diagnosis=None,
        )
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})
        response = client.get(url)

        # Annex 2, level 2 criteria: no allowance for GEIQ
        diagnosis.administrative_criteria.set([GEIQAdministrativeCriteria.objects.get(pk=17)])
        diagnosis.save()

        client.force_login(diagnosis.author_geiq.members.first())
        response = client.get(url)

        assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")
        assertContains(response, "Éligibilité public prioritaire GEIQ non confirmée")
        assertContains(response, "Renseignée par")
        assertContains(response, "Situation administrative du candidat")
        assertContains(response, "Mettre à jour")
        assertContains(
            response,
            "Les critères que vous avez sélectionnés ne vous permettent pas de "
            "bénéficier d’une aide financière de l’État.",
        )

        diagnosis.administrative_criteria.set(
            [
                GEIQAdministrativeCriteria.objects.get(pk=18),
                GEIQAdministrativeCriteria.objects.get(pk=17),
            ]
        )
        # Diagnosis must be saved to reset cached properties (allowance amount)
        diagnosis.save()
        response = client.get(url)

        assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")
        assertContains(response, "Éligibilité public prioritaire GEIQ validée")
        assertContains(response, "Éligibilité GEIQ confirmée par")
        assertContains(response, "Situation administrative du candidat")
        assertContains(
            response,
            "Les critères que vous avez sélectionnés vous donnent droit en cas d’embauche",
        )
        assertContains(
            response,
            f"une aide financière de l’État s’élevant à <b>{diagnosis.allowance_amount} €</b> ",
        )


class TestJobSeekerGeoDetailsForGEIQDiagnosis:
    """Check that QPV and ZRR details for job seeker are displayed in GEIQ eligibility diagnosis form"""

    def test_job_seeker_not_resident_in_qpv_or_zrr(self, client):
        # ZRR / QPV criteria info fragment is loaded before HTMX "zone"
        job_seeker = JobSeekerFactory()
        diagnosis = GEIQEligibilityDiagnosisFactory(from_geiq=True, job_seeker=job_seeker)
        job_application = JobApplicationFactory(job_seeker=job_seeker, to_company=diagnosis.author_geiq)
        url = reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk})
        client.force_login(diagnosis.author_geiq.members.first())
        response = client.get(url)

        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")
        assertTemplateNotUsed(response, "apply/includes/known_criteria.html")

    def test_job_seeker_not_resident_in_qpv_or_zrr_for_prescriber(self, client):
        job_seeker = JobSeekerFactory()
        geiq = CompanyWithMembershipAndJobsFactory(kind=CompanyKind.GEIQ, with_jobs=True)
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.get()
        client.force_login(prescriber)
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": geiq.pk, "job_seeker_public_id": job_seeker.public_id},
            )
        )
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")
        assertTemplateNotUsed(response, "apply/includes/known_criteria.html")

    def test_job_seeker_qpv_details_display(self, client):
        # Check QPV fragment is displayed:
        job_seeker_in_qpv = JobSeekerWithAddressFactory(with_address_in_qpv=True)
        diagnosis = GEIQEligibilityDiagnosisFactory(from_geiq=True, job_seeker=job_seeker_in_qpv)
        job_application = JobApplicationFactory(job_seeker=job_seeker_in_qpv, to_company=diagnosis.author_geiq)
        url = reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk})

        client.force_login(diagnosis.author_geiq.members.first())
        response = client.get(url)

        assertTemplateUsed(response, "apply/includes/known_criteria.html")
        assertContains(response, "Résident QPV")

    def test_job_seeker_qpv_details_display_for_prescriber(self, client):
        # Check QPV fragment is displayed for prescriber:
        job_seeker_in_qpv = JobSeekerWithAddressFactory(with_address_in_qpv=True)
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.get()
        client.force_login(prescriber)
        geiq = CompanyWithMembershipAndJobsFactory(kind=CompanyKind.GEIQ, with_jobs=True)
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": geiq.pk, "job_seeker_public_id": job_seeker_in_qpv.public_id},
            )
        )

        assertTemplateUsed(response, "apply/includes/known_criteria.html")
        assertContains(response, "Résident QPV")

    def test_job_seeker_zrr_details_display(self, client):
        # Check ZRR fragment is displayed
        job_seeker_in_zrr = JobSeekerWithAddressFactory(with_city_in_zrr=True)
        diagnosis = GEIQEligibilityDiagnosisFactory(from_geiq=True, job_seeker=job_seeker_in_zrr)
        job_application = JobApplicationFactory(job_seeker=job_seeker_in_zrr, to_company=diagnosis.author_geiq)
        url = reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk})

        client.force_login(diagnosis.author_geiq.members.first())
        response = client.get(url)

        assertTemplateUsed(response, "apply/includes/known_criteria.html")
        assertContains(response, "Résident en ZRR")

    def test_job_seeker_zrr_details_display_for_prescriber(self, client):
        # Check QPV fragment is displayed for prescriber:
        job_seeker_in_zrr = JobSeekerWithAddressFactory(with_city_in_zrr=True)
        geiq = CompanyWithMembershipAndJobsFactory(kind=CompanyKind.GEIQ, with_jobs=True)
        prescriber = PrescriberOrganizationWithMembershipFactory(authorized=True).members.get()
        client.force_login(prescriber)
        response = client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": geiq.pk, "job_seeker_public_id": job_seeker_in_zrr.public_id},
            )
        )

        assertTemplateUsed(response, "apply/includes/known_criteria.html")
        assertContains(response, "Résident en ZRR")

    def test_jobseeker_cannot_create_geiq_diagnosis(self, client):
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ)
        client.force_login(job_application.job_seeker)
        # Needed to setup session
        response = client.get(reverse("apply:geiq_eligibility", kwargs={"job_application_id": job_application.pk}))
        assert response.status_code == 404
        response = client.post(
            reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk}),
            data={
                "jeune_26_ans": "on",
                "sortant_ase": "on",
            },
        )
        assert not job_application.job_seeker.geiq_eligibility_diagnoses.exists()
        assert response.status_code == 404
