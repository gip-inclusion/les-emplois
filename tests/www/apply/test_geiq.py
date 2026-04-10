import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertTemplateNotUsed, assertTemplateUsed

from itou.companies.enums import CompanyKind
from itou.job_applications.enums import JobApplicationState
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory
from tests.www.apply.test_submit import fake_session_initialization


class TestJobApplicationGEIQEligibilityDetails:
    VALID_DIAGNOSIS_BADGE = """<span class="badge badge-sm rounded-pill bg-success-lighter text-success">
        <i class="ri-check-line" aria-hidden="true"></i>
        Éligibilité GEIQ confirmée
      </span>"""
    # this string does not depends on the diagnosis author
    ALLOWANCE_AND_COMPANY = "à une aide financière de l’État s’élevant à <b>1400 €</b>"
    NO_ALLOWANCE = (
        "Les critères que vous avez sélectionnés ne vous permettent pas de bénéficier d’une aide financière de l’État."
    )
    NO_VALID_DIAGNOSIS_BADGE = """<span class="badge badge-sm rounded-pill bg-warning-lighter text-warning">
        <i class="ri-error-warning-line" aria-hidden="true"></i>
        Éligibilité GEIQ non confirmée
      </span>"""
    EXPIRED_DIAGNOSIS_EXPLANATION = "Le diagnostic du candidat a expiré"

    def get_response(self, client, job_application, viewer_kind, *, diagnosis=None):
        user = {
            "company": job_application.to_company.members.first(),
            "jobseeker": job_application.job_seeker,
            "prescriber": diagnosis.author if diagnosis else job_application.sender,
        }[viewer_kind]
        client.force_login(user)
        url = reverse(f"apply:details_for_{viewer_kind}", kwargs={"job_application_id": job_application.pk})
        return client.get(url)

    @pytest.mark.parametrize("viewer_kind", ["company", "jobseeker", "prescriber"])
    def test_with_valid_diagnosis(self, client, viewer_kind):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
        )

        response = self.get_response(client, job_application, viewer_kind, diagnosis=diagnosis)

        assertContains(response, self.VALID_DIAGNOSIS_BADGE, html=True)
        assertNotContains(response, self.NO_ALLOWANCE)
        if viewer_kind == "company":
            assertContains(response, self.ALLOWANCE_AND_COMPANY)
        else:
            assertNotContains(response, self.ALLOWANCE_AND_COMPANY)

    @pytest.mark.parametrize("viewer_kind", ["company", "jobseeker", "prescriber"])
    def test_with_expired_diagnosis(self, client, viewer_kind):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
        )

        response = self.get_response(client, job_application, viewer_kind, diagnosis=diagnosis)

        assertContains(response, self.NO_VALID_DIAGNOSIS_BADGE, html=True)
        assertNotContains(response, self.VALID_DIAGNOSIS_BADGE, html=True)
        assertNotContains(response, self.NO_ALLOWANCE)
        if viewer_kind == "company":
            assertContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)
        else:
            assertNotContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)

    @pytest.mark.parametrize("viewer_kind", ["company", "jobseeker", "prescriber"])
    def test_without_diagnosis(self, client, viewer_kind):
        job_application = JobApplicationFactory(sent_by_prescriber=True, to_company__kind=CompanyKind.GEIQ)

        response = self.get_response(client, job_application, viewer_kind)

        assertContains(response, self.NO_VALID_DIAGNOSIS_BADGE, html=True)
        if viewer_kind == "prescriber":
            assert job_application.sender.is_prescriber

    @pytest.mark.parametrize("viewer_kind", ["company", "jobseeker", "prescriber"])
    def test_accepted_job_app_with_valid_diagnosis(self, client, viewer_kind):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
            geiq_eligibility_diagnosis=diagnosis,
            was_hired=True,
        )

        response = self.get_response(client, job_application, viewer_kind, diagnosis=diagnosis)

        assertContains(response, self.VALID_DIAGNOSIS_BADGE, html=True)
        if viewer_kind == "company":
            assertContains(response, self.ALLOWANCE_AND_COMPANY)
        else:
            assertNotContains(response, self.ALLOWANCE_AND_COMPANY)

    @pytest.mark.parametrize("viewer_kind", ["company", "jobseeker", "prescriber"])
    def test_accepted_job_app_with_expired_diagnosis(self, client, viewer_kind):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
        # Create a valid diagnosis to check we don't use this one in the display
        GEIQEligibilityDiagnosisFactory(
            job_seeker=diagnosis.job_seeker,
            author=diagnosis.author,
            author_kind=diagnosis.author_kind,
            author_prescriber_organization=diagnosis.author_prescriber_organization,
        )
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
            geiq_eligibility_diagnosis=diagnosis,
            was_hired=True,
        )

        response = self.get_response(client, job_application, viewer_kind, diagnosis=diagnosis)

        assertTemplateUsed(response, "eligibility/includes/geiq/diagnosis_details.html")
        assertContains(response, self.VALID_DIAGNOSIS_BADGE, html=True)
        assertNotContains(response, self.NO_VALID_DIAGNOSIS_BADGE, html=True)
        assert response.context["geiq_eligibility_diagnosis"] == diagnosis
        assertNotContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)
        if viewer_kind == "company":
            assertContains(response, self.ALLOWANCE_AND_COMPANY)
        else:
            assertNotContains(response, self.ALLOWANCE_AND_COMPANY)

    @pytest.mark.parametrize("viewer_kind", ["company", "jobseeker"])
    def test_with_valid_diagnosis_no_allowance(self, client, viewer_kind):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company=diagnosis.author_geiq,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
        )

        response = self.get_response(client, job_application, viewer_kind, diagnosis=diagnosis)

        assertContains(response, self.NO_VALID_DIAGNOSIS_BADGE, html=True)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)
        assertNotContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)
        if viewer_kind == "company":
            assertContains(response, self.NO_ALLOWANCE)
        else:
            assertNotContains(response, self.NO_ALLOWANCE)

    @pytest.mark.parametrize("viewer_kind", ["company", "jobseeker"])
    def test_with_expired_diagnosis_no_allowance(self, client, viewer_kind):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True, expired=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True,
            to_company=diagnosis.author_geiq,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
        )

        response = self.get_response(client, job_application, viewer_kind, diagnosis=diagnosis)

        assertContains(response, self.NO_VALID_DIAGNOSIS_BADGE, html=True)
        assertNotContains(response, self.NO_ALLOWANCE)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)
        if viewer_kind == "company":
            assertContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)
        else:
            assertNotContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)

    @pytest.mark.parametrize("viewer_kind", ["company", "jobseeker", "prescriber"])
    def test_accepted_without_diagnosis(self, client, viewer_kind):
        """An accepted application without a diagnosis should not display an unlinked expired diagnosis as valid."""
        expired_diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
        job_application = JobApplicationFactory(
            sent_by_prescriber=True,
            sender_prescriber_organization=expired_diagnosis.author_prescriber_organization,
            state=JobApplicationState.ACCEPTED,
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=expired_diagnosis.job_seeker,
            sender=expired_diagnosis.author,
            geiq_eligibility_diagnosis=None,
        )

        response = self.get_response(client, job_application, viewer_kind, diagnosis=expired_diagnosis)

        # The expired diagnosis exists for the job seeker but is NOT linked
        # to the job application, so it must not be shown as valid.
        assertContains(response, self.NO_VALID_DIAGNOSIS_BADGE, html=True)
        assertNotContains(response, self.VALID_DIAGNOSIS_BADGE, html=True)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)


class TestJobSeekerGeoDetailsForGEIQDiagnosis:
    """Check that QPV and ZRR details for job seeker are displayed in GEIQ eligibility diagnosis form"""

    def test_job_seeker_not_resident_in_qpv_or_zrr(self, client):
        # ZRR / QPV criteria info fragment is loaded before HTMX "zone"
        job_seeker = JobSeekerFactory()
        diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True, job_seeker=job_seeker)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True, job_seeker=job_seeker, to_company=diagnosis.author_geiq
        )
        url = reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk})
        client.force_login(diagnosis.author_geiq.members.first())
        response = client.get(url)

        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")
        assertTemplateNotUsed(response, "apply/includes/known_criteria.html")

    def test_job_seeker_not_resident_in_qpv_or_zrr_for_prescriber(self, client):
        job_seeker = JobSeekerFactory()
        geiq = CompanyFactory(kind=CompanyKind.GEIQ, with_jobs=True, with_membership=True)
        prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.get()
        client.force_login(prescriber)
        apply_session = fake_session_initialization(client, geiq, job_seeker, {"selected_jobs": []})
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name})
        )
        assertTemplateUsed(response, "apply/includes/geiq/geiq_administrative_criteria_form.html")
        assertTemplateNotUsed(response, "apply/includes/known_criteria.html")

    def test_job_seeker_qpv_details_display(self, client):
        # Check QPV fragment is displayed:
        job_seeker_in_qpv = JobSeekerFactory(with_address_in_qpv=True)
        diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True, job_seeker=job_seeker_in_qpv)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True, job_seeker=job_seeker_in_qpv, to_company=diagnosis.author_geiq
        )
        url = reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk})

        client.force_login(diagnosis.author_geiq.members.first())
        response = client.get(url)

        assertTemplateUsed(response, "apply/includes/known_criteria.html")
        assertContains(response, "Résident QPV")

    def test_job_seeker_qpv_details_display_for_prescriber(self, client):
        # Check QPV fragment is displayed for prescriber:
        job_seeker_in_qpv = JobSeekerFactory(with_address_in_qpv=True)
        geiq = CompanyFactory(kind=CompanyKind.GEIQ, with_jobs=True, with_membership=True)
        prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.get()
        client.force_login(prescriber)
        apply_session = fake_session_initialization(client, geiq, job_seeker_in_qpv, {"selected_jobs": []})
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name})
        )

        assertTemplateUsed(response, "apply/includes/known_criteria.html")
        assertContains(response, "Résident QPV")

    def test_job_seeker_zrr_details_display(self, client):
        # Check ZRR fragment is displayed
        job_seeker_in_zrr = JobSeekerFactory(with_city_in_zrr=True)
        diagnosis = GEIQEligibilityDiagnosisFactory(from_employer=True, job_seeker=job_seeker_in_zrr)
        job_application = JobApplicationFactory(
            sent_by_prescriber_alone=True, job_seeker=job_seeker_in_zrr, to_company=diagnosis.author_geiq
        )
        url = reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk})

        client.force_login(diagnosis.author_geiq.members.first())
        response = client.get(url)

        assertTemplateUsed(response, "apply/includes/known_criteria.html")
        assertContains(response, "Résident en ZRR")

    def test_job_seeker_zrr_details_display_for_prescriber(self, client):
        # Check QPV fragment is displayed for prescriber:
        job_seeker_in_zrr = JobSeekerFactory(with_city_in_zrr=True)
        geiq = CompanyFactory(kind=CompanyKind.GEIQ, with_jobs=True, with_membership=True)
        prescriber = PrescriberOrganizationFactory(authorized=True, with_membership=True).members.get()
        client.force_login(prescriber)
        apply_session = fake_session_initialization(client, geiq, job_seeker_in_zrr, {"selected_jobs": []})
        response = client.get(
            reverse("apply:application_geiq_eligibility", kwargs={"session_uuid": apply_session.name})
        )

        assertTemplateUsed(response, "apply/includes/known_criteria.html")
        assertContains(response, "Résident en ZRR")

    def test_jobseeker_cannot_create_geiq_diagnosis(self, client):
        job_application = JobApplicationFactory(sent_by_prescriber_alone=True, to_company__kind=CompanyKind.GEIQ)
        client.force_login(job_application.job_seeker)
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


def test_geiq_eligibility(client):
    job_application = JobApplicationFactory(
        sent_by_prescriber_alone=True,
        to_company__kind=CompanyKind.GEIQ,
    )
    client.force_login(job_application.to_company.members.first())
    response = client.get(reverse("apply:geiq_eligibility", kwargs={"job_application_id": job_application.pk}))
    assertContains(response, "Souhaitez-vous préciser la situation administrative du candidat ?")
    assertContains(response, reverse("companies_views:card", kwargs={"company_pk": job_application.to_company.pk}))
