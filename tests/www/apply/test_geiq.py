import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertTemplateNotUsed, assertTemplateUsed

from itou.companies.enums import CompanyKind
from itou.job_applications.enums import JobApplicationState
from itou.users.enums import UserKind
from itou.www.apply.views.process_views import _get_geiq_eligibility_diagnosis
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory, JobSeekerWithAddressFactory


@pytest.mark.ignore_unknown_variable_template_error("with_matomo_event")
class TestJobApplicationGEIQEligibilityDetails:
    VALID_DIAGNOSIS = "Éligibilité public prioritaire GEIQ validée"
    # this string does not depends on the diagnosis author
    ALLOWANCE_AND_COMPANY = "à une aide financière de l’État s’élevant à <b>1400 €</b>"
    NO_ALLOWANCE = (
        "Les critères que vous avez sélectionnés ne vous permettent pas de bénéficier d’une aide financière de l’État."
    )
    NO_VALID_DIAGNOSIS = "Éligibilité public prioritaire GEIQ non confirmée"
    EXPIRED_DIAGNOSIS_EXPLANATION = "Le diagnostic du candidat a expiré"

    def get_response(self, client, job_application, user):
        client.force_login(user)
        url_name = {
            UserKind.EMPLOYER: "apply:details_for_company",
            UserKind.PRESCRIBER: "apply:details_for_prescriber",
            UserKind.JOB_SEEKER: "apply:details_for_jobseeker",
        }[user.kind]
        url = reverse(url_name, kwargs={"job_application_id": job_application.pk})
        return client.get(url)

    def test_with_valid_diagnosis(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
        job_application = JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
            eligibility_diagnosis=None,
        )

        # as employer, I see the prescriber diagnosis
        response = self.get_response(client, job_application, job_application.to_company.members.first())
        assertContains(response, self.VALID_DIAGNOSIS)
        assertContains(response, self.ALLOWANCE_AND_COMPANY)
        assertNotContains(response, self.NO_ALLOWANCE)

        # as job seeker, I see the prescriber diagnosis
        response = self.get_response(client, job_application, job_application.job_seeker)
        assertContains(response, self.VALID_DIAGNOSIS)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)
        assertNotContains(response, self.NO_ALLOWANCE)

        # as a prescriber, I see my diagnosis
        assert diagnosis.author.is_prescriber
        response = self.get_response(client, job_application, diagnosis.author)
        assertContains(response, self.VALID_DIAGNOSIS)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)
        assertNotContains(response, self.NO_ALLOWANCE)

    def test_with_expired_diagnosis(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
        job_application = JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
            eligibility_diagnosis=None,
        )

        # as employer, I see the prescriber diagnosis isn't valid anymore
        response = self.get_response(client, job_application, job_application.to_company.members.first())
        assertContains(response, self.NO_VALID_DIAGNOSIS)
        assertNotContains(response, self.NO_ALLOWANCE)
        assertContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)

        # as job seeker, I see the prescriber diagnosis isn't valid anymore without further details
        response = self.get_response(client, job_application, job_application.job_seeker)
        assertContains(response, self.NO_VALID_DIAGNOSIS)
        assertNotContains(response, self.VALID_DIAGNOSIS)
        assertNotContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)

        # as a prescriber, I see the prescriber diagnosis isn't valid anymore
        assert diagnosis.author.is_prescriber
        response = self.get_response(client, job_application, diagnosis.author)
        assertContains(response, self.NO_VALID_DIAGNOSIS)
        assertNotContains(response, self.NO_ALLOWANCE)
        assertNotContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)

    def test_without_diagnosis(self, client):
        # No GEIQ diagnosis for this job seeker / job application
        job_application = JobApplicationFactory(to_company__kind=CompanyKind.GEIQ)

        # as employer, I see there's no diagnosis
        response = self.get_response(client, job_application, job_application.to_company.members.first())
        assertContains(response, self.NO_VALID_DIAGNOSIS)

        # as job seeker, I see there's no diagnosis
        response = self.get_response(client, job_application, job_application.job_seeker)
        assertContains(response, self.NO_VALID_DIAGNOSIS)

        # as a prescriber, I don't see anything
        assert job_application.sender.is_prescriber
        response = self.get_response(client, job_application, job_application.sender)
        assertContains(response, self.NO_VALID_DIAGNOSIS)

    def test_accepted_job_app_with_valid_diagnosis(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True)
        job_application = JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
            eligibility_diagnosis=None,
            geiq_eligibility_diagnosis=diagnosis,
            was_hired=True,
        )

        # as employer, I see the prescriber diagnosis
        response = self.get_response(client, job_application, job_application.to_company.members.first())
        assertContains(response, self.VALID_DIAGNOSIS)
        assertContains(response, self.ALLOWANCE_AND_COMPANY)

        # as job seeker, I see the prescriber diagnosis
        response = self.get_response(client, job_application, job_application.job_seeker)
        assertContains(response, self.VALID_DIAGNOSIS)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)

        # as a prescriber, I see my diagnosis
        assert diagnosis.author.is_prescriber
        response = self.get_response(client, job_application, diagnosis.author)
        assertContains(response, self.VALID_DIAGNOSIS)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)

    def test_accepted_job_app_with_expired_diagnosis(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_prescriber=True, expired=True)
        # Create a valid diangosis to check we don't use this one in the display
        GEIQEligibilityDiagnosisFactory(
            job_seeker=diagnosis.job_seeker,
            author=diagnosis.author,
            author_kind=diagnosis.author_kind,
            author_prescriber_organization=diagnosis.author_prescriber_organization,
        )
        job_application = JobApplicationFactory(
            to_company__kind=CompanyKind.GEIQ,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
            eligibility_diagnosis=None,
            geiq_eligibility_diagnosis=diagnosis,
            was_hired=True,
        )

        # as employer, I still see the prescriber diagnosis
        response = self.get_response(client, job_application, job_application.to_company.members.first())
        assertContains(response, self.VALID_DIAGNOSIS)
        assertContains(response, self.ALLOWANCE_AND_COMPANY)
        assert response.context["geiq_eligibility_diagnosis"] == diagnosis

        # as job seeker, I still see the prescriber diagnosis
        response = self.get_response(client, job_application, job_application.job_seeker)
        assertContains(response, self.VALID_DIAGNOSIS)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)
        assert response.context["geiq_eligibility_diagnosis"] == diagnosis

        # as a prescriber, I still see my diagnosis
        assert diagnosis.author.is_prescriber
        response = self.get_response(client, job_application, diagnosis.author)
        assertContains(response, self.VALID_DIAGNOSIS)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)
        assert response.context["geiq_eligibility_diagnosis"] == diagnosis

    def test_with_valid_diagnosis_no_allowance(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_geiq=True)
        job_application = JobApplicationFactory(
            to_company=diagnosis.author_geiq,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
            eligibility_diagnosis=None,
        )

        # as employer, I see the prescriber diagnosis
        response = self.get_response(client, job_application, job_application.to_company.members.first())
        assertContains(response, self.NO_VALID_DIAGNOSIS)
        assertContains(response, self.NO_ALLOWANCE)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)
        assertNotContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)

        # as job seeker, I see the prescriber diagnosis
        response = self.get_response(client, job_application, job_application.job_seeker)
        assertContains(response, self.NO_VALID_DIAGNOSIS)
        assertNotContains(response, self.NO_ALLOWANCE)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)
        assertNotContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)

    def test_with_expired_diagnosis_no_allowance(self, client):
        diagnosis = GEIQEligibilityDiagnosisFactory(from_geiq=True, expired=True)
        job_application = JobApplicationFactory(
            to_company=diagnosis.author_geiq,
            job_seeker=diagnosis.job_seeker,
            sender=diagnosis.author,
            eligibility_diagnosis=None,
        )

        # as employer, I see the prescriber diagnosis
        response = self.get_response(client, job_application, job_application.to_company.members.first())
        assertContains(response, self.NO_VALID_DIAGNOSIS)
        assertNotContains(response, self.NO_ALLOWANCE)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)
        assertContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)

        # as job seeker, I see the prescriber diagnosis
        response = self.get_response(client, job_application, job_application.job_seeker)
        assertContains(response, self.NO_VALID_DIAGNOSIS)
        assertNotContains(response, self.NO_ALLOWANCE)
        assertNotContains(response, self.ALLOWANCE_AND_COMPANY)
        assertNotContains(response, self.EXPIRED_DIAGNOSIS_EXPLANATION)


def test_get_geiq_eligibility_diagnosis(subtests):
    expired_prescriber_diagnosis = GEIQEligibilityDiagnosisFactory(
        from_prescriber=True,
        expired=True,
    )
    job_seeker = expired_prescriber_diagnosis.job_seeker
    expired_company_diagnosis = GEIQEligibilityDiagnosisFactory(
        from_geiq=True,
        expired=True,
        job_seeker=job_seeker,
    )
    geiq = expired_company_diagnosis.author_geiq
    newer_company_diagnosis = GEIQEligibilityDiagnosisFactory(
        from_geiq=True,
        job_seeker=job_seeker,
        author_geiq=geiq,
    )
    valid_prescriber_diagnosis = GEIQEligibilityDiagnosisFactory(
        from_prescriber=True,
        job_seeker=job_seeker,
    )

    # The new prescriber diagnosis changed the valid_company_diagnosis expiry date : it's now expired
    newer_company_diagnosis.refresh_from_db()
    assert not newer_company_diagnosis.is_valid

    new_job_application = JobApplicationFactory(
        to_company=geiq,
        job_seeker=job_seeker,
        eligibility_diagnosis=None,
    )
    accepted_job_application_with_company_diagnosis = JobApplicationFactory(
        to_company=geiq,
        job_seeker=job_seeker,
        geiq_eligibility_diagnosis=expired_company_diagnosis,
        eligibility_diagnosis=None,
        state=JobApplicationState.ACCEPTED,
    )
    accepted_job_application_with_prescriber_diagnosis = JobApplicationFactory(
        to_company=geiq,
        job_seeker=job_seeker,
        geiq_eligibility_diagnosis=expired_prescriber_diagnosis,
        eligibility_diagnosis=None,
        state=JobApplicationState.ACCEPTED,
    )

    # on accepted job application:
    # the hiring company and jobseeker get the linked diagnosis
    # a prescriber only sees the diagnosis if it was created by a prescriber
    assert (
        _get_geiq_eligibility_diagnosis(accepted_job_application_with_company_diagnosis, only_prescriber=False)
        == expired_company_diagnosis
    )
    assert (
        _get_geiq_eligibility_diagnosis(accepted_job_application_with_company_diagnosis, only_prescriber=True) is None
    )
    assert (
        _get_geiq_eligibility_diagnosis(accepted_job_application_with_prescriber_diagnosis, only_prescriber=False)
        == expired_prescriber_diagnosis
    )
    assert (
        _get_geiq_eligibility_diagnosis(accepted_job_application_with_prescriber_diagnosis, only_prescriber=True)
        == expired_prescriber_diagnosis
    )

    # On not accepted job application: if there's a valid prescriber diagnosis, return it
    assert _get_geiq_eligibility_diagnosis(new_job_application, only_prescriber=False) == valid_prescriber_diagnosis
    assert _get_geiq_eligibility_diagnosis(new_job_application, only_prescriber=True) == valid_prescriber_diagnosis

    # If there's no prescriber valid diagnosis :
    # the hiring company and jobseeker get the most recent diagnosis
    # a prescriber get the most revent among prescriber diangoses
    valid_prescriber_diagnosis.delete()
    _valid_diagnois_from_other_company = GEIQEligibilityDiagnosisFactory(from_geiq=True, job_seeker=job_seeker)
    assert _get_geiq_eligibility_diagnosis(new_job_application, only_prescriber=False) == newer_company_diagnosis
    assert _get_geiq_eligibility_diagnosis(new_job_application, only_prescriber=True) == expired_prescriber_diagnosis


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
