from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import dateformat, timezone

from itou.companies.enums import SiaeKind
from itou.eligibility.models.geiq import GEIQAdministrativeCriteria
from tests.companies.factories import SiaeWithMembershipAndJobsFactory
from tests.eligibility.factories import GEIQEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory


class JobApplicationGEIQEligibilityDetailsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.diagnosis = GEIQEligibilityDiagnosisFactory(with_prescriber=True)
        cls.expired_diagnosis = GEIQEligibilityDiagnosisFactory(
            with_prescriber=True, expires_at=timezone.now() - relativedelta(months=1)
        )
        cls.prescriber = cls.diagnosis.author_prescriber_organization
        cls.author = cls.prescriber.members.first()
        cls.job_seeker = cls.diagnosis.job_seeker
        cls.siae = SiaeWithMembershipAndJobsFactory(kind=SiaeKind.GEIQ)
        cls.job_application = JobApplicationFactory(to_siae=cls.siae, job_seeker=cls.job_seeker)
        cls.url = reverse("apply:details_for_siae", kwargs={"job_application_id": cls.job_application.pk})

    def test_with_geiq_eligibility_details(self):
        self.client.force_login(self.siae.members.first())
        response = self.client.get(self.url)

        assert response.status_code == 200
        self.assertTemplateUsed("apply/includes/geiq_diagnosis_details.html")

    def test_without_geiq_eligibility_details(self):
        job_application = JobApplicationFactory(to_siae=self.siae)
        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(self.siae.members.first())
        response = self.client.get(url)

        assert response.status_code == 200
        self.assertTemplateNotUsed("apply/includes/geiq_diagnosis_details.html")

    def test_details_as_authorized_prescriber_with_valid_diagnosis(self):
        self.client.force_login(self.siae.members.first())
        response = self.client.get(self.url)

        self.assertContains(
            response,
            f"Éligibilité GEIQ confirmée par <b>{self.author.get_full_name()} ({self.prescriber.display_name})</b>",
        )
        self.assertContains(
            response,
            f"<b>Durée de validité du diagnostic :</b> du {self.diagnosis.created_at:%d/%m/%Y} "
            f"au {self.diagnosis.expires_at:%d/%m/%Y}",
        )

    def test_allowance_details_for_prescriber(self):
        self.client.force_login(self.siae.members.first())
        response = self.client.get(self.url)

        self.assertContains(
            response, "Ce diagnostic émis par un prescripteur habilité vous donnera droit en cas d’embauche"
        )
        self.assertContains(
            response, f"une aide financière de l’État s’élevant à <b>{self.diagnosis.allowance_amount} €</b> "
        )

    def test_allowance_details_for_geiq(self):
        diagnosis = GEIQEligibilityDiagnosisFactory(with_geiq=True)
        job_application = JobApplicationFactory(to_siae=diagnosis.author_geiq, job_seeker=diagnosis.job_seeker)
        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})

        # Annex 2, level 2 criteria: no allowance for GEIQ
        diagnosis.administrative_criteria.set([GEIQAdministrativeCriteria.objects.get(pk=17)])
        diagnosis.save()

        self.client.force_login(diagnosis.author_geiq.members.first())
        response = self.client.get(url)

        self.assertTemplateUsed("apply/includes/geiq_diagnosis_details.html")
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
            [GEIQAdministrativeCriteria.objects.get(pk=18), GEIQAdministrativeCriteria.objects.get(pk=17)]
        )
        # Diagnosis must be saved to reset cached properties (allowance amount)
        diagnosis.save()
        response = self.client.get(url)

        self.assertTemplateUsed("apply/includes/geiq_diagnosis_details.html")
        self.assertContains(response, "Éligibilité public prioritaire GEIQ validée")
        self.assertContains(response, "Éligibilité GEIQ confirmée par")
        self.assertContains(response, "Situation administrative du candidat")
        self.assertContains(response, "Les critères que vous avez sélectionnés vous donnent droit en cas d’embauche")
        self.assertContains(
            response, f"une aide financière de l’État s’élevant à <b>{diagnosis.allowance_amount} €</b> "
        )

    def test_details_as_authorized_prescriber_with_expired_diagnosis(self):
        job_application = JobApplicationFactory(to_siae=self.siae, job_seeker=self.expired_diagnosis.job_seeker)
        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})

        self.client.force_login(self.siae.members.first())
        response = self.client.get(url)

        self.assertContains(
            response,
            f"Le diagnostic du candidat a expiré le {dateformat.format(self.expired_diagnosis.expires_at, 'd F Y')}",
        )
