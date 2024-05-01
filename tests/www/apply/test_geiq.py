from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import dateformat, timezone
from freezegun import freeze_time

from itou.companies.enums import CompanyKind
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from itou.utils.session import SessionNamespace
from tests.companies.factories import CompanyWithMembershipAndJobsFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory, JobSeekerWithAddressFactory


@freeze_time("2024-02-15")
class JobApplicationGEIQEligibilityDetailsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.geiq = CompanyWithMembershipAndJobsFactory(kind=CompanyKind.GEIQ)
        cls.valid_diagnosis = GEIQEligibilityDiagnosisFactory(with_prescriber=True)
        cls.expired_diagnosis = GEIQEligibilityDiagnosisFactory(
            with_prescriber=True, expires_at=timezone.now() - relativedelta(months=1)
        )
        cls.prescriber_org = cls.valid_diagnosis.author_prescriber_organization
        cls.author = cls.prescriber_org.members.first()
        cls.job_seeker = cls.valid_diagnosis.job_seeker
        cls.job_application = JobApplicationFactory(
            to_company=cls.geiq,
            job_seeker=cls.job_seeker,
        )
        cls.url = reverse(
            "apply:details_for_company",
            kwargs={"job_application_id": cls.job_application.pk},
        )

    def test_with_geiq_eligibility_details(self):
        self.client.force_login(self.geiq.members.first())
        response = self.client.get(self.url)

        assert response.status_code == 200
        self.assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")

    def test_without_geiq_eligibility_details(self):
        # No GEIQ diagnosis for this job seeker / job application
        job_application = JobApplicationFactory(to_company=self.geiq)
        self.client.force_login(self.geiq.members.first())
        response = self.client.get(
            reverse(
                "apply:details_for_company",
                kwargs={"job_application_id": job_application.pk},
            )
        )

        assert response.status_code == 200
        self.assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")

    def test_details_as_geiq_with_valid_eligibility_diagnosis(self):
        diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True)
        job_application = JobApplicationFactory(
            to_company=diagnosis.author_geiq,
            geiq_eligibility_diagnosis=diagnosis,
            eligibility_diagnosis=None,
        )

        self.client.force_login(diagnosis.author_geiq.members.first())
        response = self.client.get(
            reverse(
                "apply:details_for_company",
                kwargs={"job_application_id": job_application.pk},
            )
        )

        self.assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")
        self.assertContains(
            response,
            "Éligibilité public prioritaire GEIQ non confirmée",
        )
        self.assertContains(
            response,
            "Les critères que vous avez sélectionnés ne vous permettent pas de bénéficier d’une aide financière de l’État.",  # noqa: E501
        )
        self.assertNotContains(response, "Le diagnostic du candidat a expiré")
        # More in `test_allowance_details_for_geiq`

    def test_details_as_geiq_with_expired_eligibility_diagnosis(self):
        diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True, expired=True)
        job_application = JobApplicationFactory(
            to_company=diagnosis.author_geiq,
            geiq_eligibility_diagnosis=diagnosis,
            eligibility_diagnosis=None,
        )

        self.client.force_login(diagnosis.author_geiq.members.first())
        response = self.client.get(
            reverse(
                "apply:details_for_company",
                kwargs={"job_application_id": job_application.pk},
            )
        )

        self.assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")
        self.assertContains(response, "Le diagnostic du candidat a expiré")
        self.assertContains(
            response,
            "Éligibilité public prioritaire GEIQ non confirmée",
        )

    def test_details_as_authorized_prescriber_with_valid_diagnosis(self):
        self.client.force_login(self.geiq.members.first())
        response = self.client.get(self.url)

        self.assertContains(
            response,
            f"Éligibilité GEIQ confirmée par "
            f"<b>{self.author.get_full_name()} ({self.prescriber_org.display_name})</b>",
        )
        self.assertContains(response, "<b>Durée de validité du diagnostic :</b> du 15/02/2024 au 15/08/2024")

    def test_details_as_authorized_prescriber_with_expired_diagnosis(self):
        job_application = JobApplicationFactory(to_company=self.geiq, job_seeker=self.expired_diagnosis.job_seeker)
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(self.geiq.members.first())
        response = self.client.get(url)

        self.assertContains(
            response,
            f"Le diagnostic du candidat a expiré le {dateformat.format(self.expired_diagnosis.expires_at, 'd F Y')}",
        )

    def test_allowance_details_for_prescriber(self):
        # Allowance amount is constant when diagnosis is made by an authorized prescriber
        self.client.force_login(self.geiq.members.first())
        response = self.client.get(self.url)

        self.assertContains(
            response,
            "Ce diagnostic émis par un prescripteur habilité vous donnera droit en cas d’embauche",
        )
        self.assertContains(
            response,
            f"une aide financière de l’État s’élevant à <b>{self.valid_diagnosis.allowance_amount} €</b> ",
        )

    def test_allowance_details_for_geiq(self):
        # Slightly more complex than for prescribers :
        # allowance amount is variable in function of chosen administrative criteria
        diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True)
        job_application = JobApplicationFactory(to_company=diagnosis.author_geiq, job_seeker=diagnosis.job_seeker)
        url = reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk})

        # Annex 2, level 2 criteria: no allowance for GEIQ
        diagnosis.administrative_criteria.set([GEIQAdministrativeCriteria.objects.get(pk=17)])
        diagnosis.save()

        self.client.force_login(diagnosis.author_geiq.members.first())
        response = self.client.get(url)

        self.assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")
        self.assertContains(response, "Éligibilité public prioritaire GEIQ non confirmée")
        self.assertContains(response, "Renseignée par")
        self.assertContains(response, "Situation administrative du candidat")
        self.assertContains(response, "Mettre à jour")
        self.assertContains(
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
        response = self.client.get(url)

        self.assertTemplateUsed(response, "apply/includes/geiq/geiq_diagnosis_details.html")
        self.assertContains(response, "Éligibilité public prioritaire GEIQ validée")
        self.assertContains(response, "Éligibilité GEIQ confirmée par")
        self.assertContains(response, "Situation administrative du candidat")
        self.assertContains(
            response,
            "Les critères que vous avez sélectionnés vous donnent droit en cas d’embauche",
        )
        self.assertContains(
            response,
            f"une aide financière de l’État s’élevant à <b>{diagnosis.allowance_amount} €</b> ",
        )


class TestJobSeekerGeoDetailsForGEIQDiagnosis(TestCase):
    """Check that QPV and ZRR details for job seeker are displayed in GEIQ eligibility diagnosis form"""

    @classmethod
    def setUpTestData(cls):
        cls.job_seeker = JobSeekerFactory()
        cls.job_seeker_in_qpv = JobSeekerWithAddressFactory(with_address_in_qpv=True)
        cls.job_seeker_in_zrr = JobSeekerWithAddressFactory(with_city_in_zrr=True)
        cls.geiq = CompanyWithMembershipAndJobsFactory(kind=CompanyKind.GEIQ, with_jobs=True)
        cls.prescriber_org = PrescriberOrganizationWithMembershipFactory(authorized=True)

    def _setup_session(self):
        apply_session = SessionNamespace(self.client.session, f"job_application-{self.geiq.pk}")
        apply_session.init(
            {
                "selected_jobs": self.geiq.job_description_through.all(),
            }
        )
        apply_session.save()

    def test_job_seeker_not_resident_in_qpv_or_zrr(self):
        # ZRR / QPV criteria info fragment is loaded before HTMX "zone"
        diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True, job_seeker=self.job_seeker)
        job_application = JobApplicationFactory(job_seeker=self.job_seeker, to_company=diagnosis.author_geiq)
        url = reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk})
        self.client.force_login(diagnosis.author_geiq.members.first())
        response = self.client.get(url)

        self.assertTemplateNotUsed(response, "apply/includes/known_criteria.html")

    def test_job_seeker_not_resident_in_qpv_or_zrr_for_prescriber(self):
        self.client.force_login(self.prescriber_org.members.first())
        self._setup_session()
        response = self.client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": self.job_seeker.pk},
            )
        )

        self.assertTemplateNotUsed(response, "apply/includes/known_criteria.html")

    def test_job_seeker_qpv_details_display(self):
        # Check QPV fragment is displayed:
        diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True, job_seeker=self.job_seeker_in_qpv)
        job_application = JobApplicationFactory(job_seeker=self.job_seeker_in_qpv, to_company=diagnosis.author_geiq)
        url = reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(diagnosis.author_geiq.members.first())
        response = self.client.get(url)

        self.assertTemplateUsed(response, "apply/includes/known_criteria.html")
        self.assertContains(response, "Résident QPV")

    def test_job_seeker_qpv_details_display_for_prescriber(self):
        # Check QPV fragment is displayed for prescriber:
        self.client.force_login(self.prescriber_org.members.first())
        self._setup_session()
        response = self.client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": self.job_seeker_in_qpv.pk},
            )
        )

        self.assertTemplateUsed(response, "apply/includes/known_criteria.html")
        self.assertContains(response, "Résident QPV")

    def test_job_seeker_zrr_details_display(self):
        # Check ZRR fragment is displayed

        diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True, job_seeker=self.job_seeker_in_zrr)
        job_application = JobApplicationFactory(job_seeker=self.job_seeker_in_zrr, to_company=diagnosis.author_geiq)
        url = reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(diagnosis.author_geiq.members.first())
        response = self.client.get(url)

        self.assertTemplateUsed(response, "apply/includes/known_criteria.html")
        self.assertContains(response, "Résident en ZRR")

    def test_job_seeker_zrr_details_display_for_prescriber(self):
        # Check QPV fragment is displayed for prescriber:
        self.client.force_login(self.prescriber_org.members.first())
        self._setup_session()
        response = self.client.get(
            reverse(
                "apply:application_geiq_eligibility",
                kwargs={"company_pk": self.geiq.pk, "job_seeker_pk": self.job_seeker_in_zrr.pk},
            )
        )

        self.assertTemplateUsed(response, "apply/includes/known_criteria.html")
        self.assertContains(response, "Résident en ZRR")

    def test_jobseeker_cannot_create_geiq_diagnosis(self):
        job_application = JobApplicationFactory(job_seeker=self.job_seeker, to_company=self.geiq)
        self.client.force_login(self.job_seeker)
        # Needed to setup session
        response = self.client.get(
            reverse("apply:geiq_eligibility", kwargs={"job_application_id": job_application.pk})
        )
        assert response.status_code == 404
        response = self.client.post(
            reverse("apply:geiq_eligibility_criteria", kwargs={"job_application_id": job_application.pk}),
            data={
                "jeune_26_ans": "on",
                "sortant_ase": "on",
            },
        )
        assert not self.job_seeker.geiq_eligibility_diagnoses.exists()
        assert response.status_code == 404
