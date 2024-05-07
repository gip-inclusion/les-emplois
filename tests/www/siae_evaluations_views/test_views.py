import datetime

import httpx
from django.core.files.storage import default_storage
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertRedirects

from itou.siae_evaluations import enums as evaluation_enums
from itou.siae_evaluations.models import Sanctions
from itou.utils.types import InclusiveDateRange
from tests.companies.factories import CompanyMembershipFactory
from tests.files.factories import FileFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
)
from tests.users.factories import EmployerFactory
from tests.utils.test import TestCase


class EvaluatedSiaeSanctionViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        institution_membership = InstitutionMembershipFactory(institution__name="DDETS 87")
        cls.institution_user = institution_membership.user
        company_membership = CompanyMembershipFactory(company__name="Les petits jardins")
        cls.employer = company_membership.user
        cls.evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            evaluation_campaign__institution=institution_membership.institution,
            evaluation_campaign__name="Contrôle 2022",
            siae=company_membership.company,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat. Séparé de son chat pendant une journée.",
        )
        cls.sanctions = Sanctions.objects.create(
            evaluated_siae=cls.evaluated_siae,
            training_session="RDV le 18 avril à 14h dans les locaux de Pôle Emploi.",
        )
        cls.return_evaluated_siae_list_link_html = (
            '<a class="btn btn-primary float-end" '
            f'href="/siae_evaluation/institution_evaluated_siae_list/{cls.evaluated_siae.evaluation_campaign_id}/">'
            "Revenir à la liste des SIAE</a>"
        )
        cls.return_dashboard_link_html = (
            '<a class="btn btn-primary float-end" href="/dashboard/">Retour au Tableau de bord</a>'
        )

    def assertSanctionContent(self, response):
        self.assertContains(
            response,
            '<h1>Notification de sanction pour <span class="text-info">Les petits jardins</span></h1>',
            html=True,
            count=1,
        )
        self.assertContains(
            response,
            '<b>Résultat :</b> <b class="text-danger">Négatif</b>',
            count=1,
        )
        self.assertContains(
            response,
            '<b>Raison principale :</b> <b class="text-info">Pièce justificative incorrecte</b>',
            count=1,
        )
        self.assertContains(
            response,
            """
            <p>
                <b>Commentaire de votre DDETS</b>
            </p>
            <div class="card">
                <div class="card-body">
                    <p>A envoyé une photo de son chat. Séparé de son chat pendant une journée.</p>
                </div>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_anonymous_view_siae(self):
        url = reverse(
            "siae_evaluations_views:siae_sanction",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        response = self.client.get(url)
        self.assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_anonymous_view_institution(self):
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_sanction",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        response = self.client.get(url)
        self.assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_view_as_institution(self):
        self.client.force_login(self.institution_user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)
        self.assertContains(
            response,
            self.return_evaluated_siae_list_link_html,
            html=True,
            count=1,
        )
        self.assertNotContains(
            response,
            self.return_dashboard_link_html,
            html=True,
        )

    def test_view_as_other_institution(self):
        other = InstitutionMembershipFactory()
        self.client.force_login(other.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    def test_view_as_siae(self):
        self.client.force_login(self.employer)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)
        self.assertContains(
            response,
            self.return_dashboard_link_html,
            html=True,
            count=1,
        )
        self.assertNotContains(
            response,
            self.return_evaluated_siae_list_link_html,
            html=True,
        )

    def test_view_as_other_siae(self):
        company_membership = CompanyMembershipFactory()
        self.client.force_login(company_membership.user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    def test_training_session(self):
        self.client.force_login(self.institution_user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)
        self.assertContains(
            response,
            """
            <div class="card-body">
             <h2>
              Sanction
             </h2>
             <h3 class="mt-5">
              Participation à une session de présentation de l’auto-prescription
             </h3>
             <div class="card">
              <div class="card-body">
               <p>RDV le 18 avril à 14h dans les locaux de Pôle Emploi.</p>
              </div>
             </div>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_temporary_suspension(self):
        self.sanctions.training_session = ""
        self.sanctions.suspension_dates = InclusiveDateRange(datetime.date(2023, 1, 1), datetime.date(2023, 6, 1))
        self.sanctions.save()
        self.client.force_login(self.institution_user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)
        self.assertContains(
            response,
            """
            <div class="card-body">
             <h2>
              Sanction
             </h2>
             <h3 class="mt-5">
              Retrait temporaire de la capacité d’auto-prescription
             </h3>
             <p>
              La capacité d’auto-prescrire un parcours d'insertion par l'activité économique est suspendue pour une
              durée déterminée par l'autorité administrative.
             </p>
             <p>
              Dans votre cas, le retrait temporaire de la capacité d’auto-prescription sera effectif à partir du
              1 janvier 2023 et jusqu’au 1 juin 2023.
             </p>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_permanent_suspension(self):
        self.sanctions.training_session = ""
        self.sanctions.suspension_dates = InclusiveDateRange(datetime.date(2023, 1, 1))
        self.sanctions.save()
        self.client.force_login(self.institution_user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)
        self.assertContains(
            response,
            """
            <div class="card-body">
             <h2>
              Sanction
             </h2>
             <h3 class="mt-5">
              Retrait définitif de la capacité d’auto-prescription
             </h3>
             <p>
              La capacité à prescrire un parcours est rompue, elle peut être rétablie par le préfet, à la demande de la
              structure, sous réserve de la participation de ses dirigeants ou salariés à des actions de formation
              définies par l'autorité administrative.
             </p>
             <p>
              Dans votre cas, le retrait définitif de la capacité d’auto-prescription sera effectif à partir du
              1 janvier 2023.
             </p>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_subsidy_cut_rate(self):
        self.sanctions.training_session = ""
        self.sanctions.subsidy_cut_dates = InclusiveDateRange(datetime.date(2023, 1, 1), datetime.date(2023, 6, 1))
        self.sanctions.subsidy_cut_percent = 35
        self.sanctions.save()
        self.client.force_login(self.institution_user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)
        self.assertContains(
            response,
            """
            <div class="card-body">
             <h2>
              Sanction
             </h2>
             <h3 class="mt-5">
              Suppression d’une partie de l’aide au poste
             </h3>
             <p>
              La suppression de l’aide attribuée aux salariés s’apprécie par l'autorité administrative, par imputation
              de l’année N+1. Cette notification s’accompagne d’une demande conforme auprès de l’ASP de la part du
              préfet. Lorsque le département a participé aux aides financières concernées en application de l'article
              L. 5132-2, le préfet informe le président du conseil départemental de sa décision en vue de la
              récupération, le cas échéant, des montants correspondants.
             </p>
             <p>
              Dans votre cas, la suppression de 35 % de l’aide au poste sera effective à partir du 1 janvier 2023 et
              jusqu’au 1 juin 2023.
             </p>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_subsidy_cut_full(self):
        self.sanctions.training_session = ""
        self.sanctions.subsidy_cut_dates = InclusiveDateRange(datetime.date(2023, 1, 1), datetime.date(2023, 6, 1))
        self.sanctions.subsidy_cut_percent = 100
        self.sanctions.save()
        self.client.force_login(self.institution_user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)
        self.assertContains(
            response,
            """
            <div class="card-body">
             <h2>
              Sanction
             </h2>
             <h3 class="mt-5">
              Suppression de l’aide au poste
             </h3>
             <p>
              La suppression de l’aide attribuée aux salariés s’apprécie par l'autorité administrative, par imputation
              de l’année N+1. Cette notification s’accompagne d’une demande conforme auprès de l’ASP de la part du
              préfet. Lorsque le département a participé aux aides financières concernées en application de l'article
              L. 5132-2, le préfet informe le président du conseil départemental de sa décision en vue de la
              récupération, le cas échéant, des montants correspondants.
             </p>
             <p>
              Dans votre cas, la suppression de l’aide au poste sera effective à partir du 1 janvier 2023 et
              jusqu’au 1 juin 2023.
             </p>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_deactivation(self):
        self.sanctions.training_session = ""
        self.sanctions.deactivation_reason = "Mauvais comportement, rien ne va. On arrête tout."
        self.sanctions.save()
        self.client.force_login(self.institution_user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)
        self.assertContains(
            response,
            """
            <div class="card-body">
             <h2>
              Sanction
             </h2>
             <h3 class="mt-5">
              Déconventionnement de la structure
             </h3>
             <p>
              La suppression du conventionnement s’apprécie par l'autorité administrative. Cette notification
              s’accompagne d’une demande conforme auprès de l’ASP de la part du préfet. Lorsque le département a
              participé aux aides financières concernées en application de l'article L. 5132-2, le préfet informe le
              président du conseil départemental de sa décision.
             </p>
             <div class="card">
              <div class="card-body">
               Mauvais comportement, rien ne va. On arrête tout.
              </div>
             </div>
            </div>
            """,
            html=True,
            count=1,
        )

    def test_no_sanction(self):
        self.sanctions.training_session = ""
        self.sanctions.no_sanction_reason = "Ça ira pour cette fois."
        self.sanctions.save()
        self.client.force_login(self.institution_user)
        response = self.client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(response)
        self.assertContains(
            response,
            """
            <div class="card-body">
             <h2>
              Sanction
             </h2>
             <h3 class="mt-5">
              Ne pas sanctionner
             </h3>
             <div class="card">
              <div class="card-body">
              Ça ira pour cette fois.
              </div>
             </div>
            </div>
            """,
            html=True,
            count=1,
        )


def test_sanctions_helper_view(client):
    response = client.get(reverse("siae_evaluations_views:sanctions_helper"))
    assert response.status_code == 200


class TestViewProof:
    def test_anonymous_access(self, client):
        job_app = EvaluatedJobApplicationFactory()
        crit = EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=job_app)
        url = reverse("siae_evaluations_views:view_proof", kwargs={"evaluated_administrative_criteria_id": crit.pk})
        response = client.get(url)
        assertRedirects(response, f"{reverse('account_login')}?next={url}")

    def test_access_nonexistent_id(self, client):
        client.force_login(EmployerFactory(with_company=True))
        url = reverse("siae_evaluations_views:view_proof", kwargs={"evaluated_administrative_criteria_id": 0})
        response = client.get(url)
        assert response.status_code == 404

    def test_access_no_proof(self, client):
        job_app = EvaluatedJobApplicationFactory()
        crit = EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=job_app, proof=None)
        membership = CompanyMembershipFactory(company_id=job_app.evaluated_siae.siae_id)
        client.force_login(membership.user)
        url = reverse("siae_evaluations_views:view_proof", kwargs={"evaluated_administrative_criteria_id": crit.pk})
        response = client.get(url)
        assert response.status_code == 404

    def test_access_siae(self, client, pdf_file):
        job_app = EvaluatedJobApplicationFactory()
        key = default_storage.save("evaluations/test.pdf", pdf_file)
        crit = EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=job_app, proof=FileFactory(key=key))
        membership = CompanyMembershipFactory(company_id=job_app.evaluated_siae.siae_id)
        url = reverse("siae_evaluations_views:view_proof", kwargs={"evaluated_administrative_criteria_id": crit.pk})
        client.force_login(membership.user)
        # Boto3 signed requests depend on the current date, with a second resolution.
        # See X-Amz-Date in
        # https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
        with freeze_time():
            response = client.get(url)
            assertRedirects(response, default_storage.url(crit.proof_id), fetch_redirect_response=False)
        pdf_file.seek(0)
        assert httpx.get(response.url).content == pdf_file.read()

    def test_access_other_siae(self, client):
        job_app = EvaluatedJobApplicationFactory()
        crit = EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=job_app)
        other_evaluated_siae = EvaluatedSiaeFactory()
        membership = CompanyMembershipFactory(company=other_evaluated_siae.siae)
        url = reverse("siae_evaluations_views:view_proof", kwargs={"evaluated_administrative_criteria_id": crit.pk})
        client.force_login(membership.user)
        response = client.get(url)
        assert response.status_code == 404

    def test_access_institution(self, client, pdf_file):
        membership = InstitutionMembershipFactory()
        job_app = EvaluatedJobApplicationFactory(
            evaluated_siae__evaluation_campaign__institution=membership.institution
        )
        key = default_storage.save("evaluations/test.pdf", pdf_file)
        crit = EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=job_app, proof=FileFactory(key=key))
        EvaluationCampaignFactory(institution=membership.institution)
        url = reverse("siae_evaluations_views:view_proof", kwargs={"evaluated_administrative_criteria_id": crit.pk})
        client.force_login(membership.user)
        # Boto3 signed requests depend on the current date, with a second resolution.
        # See X-Amz-Date in
        # https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
        with freeze_time():
            response = client.get(url)
            assertRedirects(response, default_storage.url(crit.proof_id), fetch_redirect_response=False)
        pdf_file.seek(0)
        assert httpx.get(response.url).content == pdf_file.read()

    def test_access_other_institution(self, client):
        job_app = EvaluatedJobApplicationFactory()
        crit = EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=job_app)
        membership = InstitutionMembershipFactory()
        EvaluationCampaignFactory(institution=membership.institution)
        url = reverse("siae_evaluations_views:view_proof", kwargs={"evaluated_administrative_criteria_id": crit.pk})
        client.force_login(membership.user)
        response = client.get(url)
        assert response.status_code == 404


def test_active_campaign_calendar_for_admin_no_crash(admin_client):
    calendar_html = """
        <table class="table">
            <thead class="thead-light">
                <tr>
                    <th></th>
                    <th scope="col">Dates</th>
                    <th scope="col">Acteurs</th>
                    <th scope="col">Actions attendues</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <th scope="row">Phase 1</th>
                    <td>Du 15 mai 2023 au 11 juin 2023</td>

                    <td>DDETS</td>
                    <td>Sélection du taux de SIAE</td>
                </tr>
            </tbody>
        </table>
    """
    evaluation_campaign = EvaluationCampaignFactory(calendar__html=calendar_html)
    calendar_url = reverse("siae_evaluations_views:campaign_calendar", args=[evaluation_campaign.pk])
    response = admin_client.get(calendar_url)
    assert response.status_code == 200
