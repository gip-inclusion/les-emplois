import datetime

import httpx
import pytest
from django.core.files.storage import default_storage
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.siae_evaluations import enums as evaluation_enums
from itou.utils.types import InclusiveDateRange
from tests.companies.factories import CompanyMembershipFactory
from tests.files.factories import FileFactory
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory
from tests.siae_evaluations.factories import (
    EvaluatedAdministrativeCriteriaFactory,
    EvaluatedJobApplicationFactory,
    EvaluatedJobApplicationSanctionFactory,
    EvaluatedSiaeFactory,
    EvaluationCampaignFactory,
    SanctionsFactory,
)
from tests.users.factories import EmployerFactory
from tests.utils.testing import parse_response_to_soup, pretty_indented


class TestEvaluatedSiaeSanctionView:
    @pytest.fixture(autouse=True)
    def setup_method(self):
        institution_membership = InstitutionMembershipFactory(institution__name="DDETS 87")
        self.institution_user = institution_membership.user
        company_membership = CompanyMembershipFactory(company__name="Les petits jardins", company__for_snapshot=True)
        self.employer = company_membership.user
        self.evaluated_siae = EvaluatedSiaeFactory(
            complete=True,
            job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            job_app__job_application__for_snapshot=True,
            evaluation_campaign__institution=institution_membership.institution,
            evaluation_campaign__name="Contrôle 2022",
            siae=company_membership.company,
            notified_at=timezone.now(),
            notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            notification_text="A envoyé une photo de son chat. Séparé de son chat pendant une journée.",
        )
        self.sanctions = SanctionsFactory(
            evaluated_siae=self.evaluated_siae,
            training_session="RDV le 18 avril à 14h dans les locaux de Pôle Emploi.",
            suspension_dates=None,
        )
        # Generating a bad history for that company
        SanctionsFactory.create_batch(
            3,
            evaluated_siae__complete=True,
            evaluated_siae__job_app__criteria__review_state=evaluation_enums.EvaluatedJobApplicationsState.REFUSED_2,
            evaluated_siae__evaluation_campaign__institution=institution_membership.institution,
            evaluated_siae__siae=company_membership.company,
            evaluated_siae__notified_at=timezone.now(),  # Not realistic but still working
            evaluated_siae__notification_reason=evaluation_enums.EvaluatedSiaeNotificationReason.INVALID_PROOF,
            evaluated_siae__notification_text="A encore envoyé une photo de son chat.",
        )

        self.return_evaluated_siae_list_link_html = (
            '<a class="btn btn-ico btn-link ps-0" aria-label="Retour à la page précédente" '
            f'href="/siae_evaluation/institution_evaluated_siae_list/{self.evaluated_siae.evaluation_campaign_id}/">'
            '<i class="ri-arrow-drop-left-line ri-xl fw-medium" aria-hidden="true"></i>'
            "<span>Retour</span>"
            "</a>"
        )
        self.return_dashboard_link_html = (
            '<a class="btn btn-ico btn-link ps-0" aria-label="Retour à la page précédente" href="/dashboard/">'
            '<i class="ri-arrow-drop-left-line ri-xl fw-medium" aria-hidden="true"></i>'
            "<span>Retour</span>"
            "</a>"
        )
        self.letter_document_href = static("templates/modele_decision_sanction_controle_a_posteriori.docx")
        self.letter_document_link_html = (
            f'<a href="{self.letter_document_href}" target="_blank"'
            'class="btn btn-primary">Télécharger le modèle de courrier</a>'
        )

    def assertSanctionContent(self, snapshot, response, is_siae, subsidy_cut_percent=None):
        assertContains(
            response,
            '<h1>Décision de sanction pour <span class="text-info">Les petits jardins</span></h1>',
            html=True,
            count=1,
        )
        assertContains(
            response,
            '<b>Résultat de cette campagne de contrôle :</b> <b class="text-danger">Négatif</b>',
            count=1,
        )
        assertContains(
            response,
            '<b>Raison principale :</b> <b class="text-info">Pièce justificative incorrecte</b>',
            count=1,
        )

        soup = parse_response_to_soup(response, "#decision-summary")
        assert pretty_indented(soup) == snapshot(name="decision_summary")

        assertContains(
            response,
            """
            <p class="mb-1">
                <b>Commentaire de votre DDETS</b>
            </p>
            <blockquote class="blockquote mb-0">
                <p>A envoyé une photo de son chat. Séparé de son chat pendant une journée.</p>
            </blockquote>
            """,
            html=True,
            count=1,
        )
        subsidy_cut_str = (
            f"<br>Pourcentage d’aide au poste retirée : {subsidy_cut_percent} %"
            if subsidy_cut_percent is not None
            else ""
        )

        assertContains(
            response,
            f"""
            <p>
             <strong>PASS IAE <span>99999</span><span class="ms-1">99</span><span class="ms-1">99999</span>,
             Jane DOE</strong>
             <br> Motif de l'irrégularité : Les documents fournis se sont révélés incomplets ou non conformes
             aux exigences réglementaires.
             {subsidy_cut_str}
            </p>
            """,
            html=True,
            count=0 if is_siae else 1,
        )

    def test_anonymous_view_siae(self, client):
        url = reverse(
            "siae_evaluations_views:siae_sanction",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_anonymous_view_institution(self, client):
        url = reverse(
            "siae_evaluations_views:institution_evaluated_siae_sanction",
            kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
        )
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    @pytest.mark.parametrize(
        "suspension_dates,has_significant_sanction",
        [
            (None, False),
            (InclusiveDateRange(datetime.date(2023, 1, 1)), True),
        ],
        ids=["non_significant_sanction", "significant_sanction"],
    )
    def test_view_as_institution(self, client, snapshot, suspension_dates, has_significant_sanction):
        self.sanctions.suspension_dates = suspension_dates
        self.sanctions.save(update_fields=["suspension_dates"])
        client.force_login(self.institution_user)

        with assertSnapshotQueries(snapshot(name="queries")):
            response = client.get(
                reverse(
                    "siae_evaluations_views:institution_evaluated_siae_sanction",
                    kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
                )
            )
        self.assertSanctionContent(snapshot, response, is_siae=False)
        assertContains(
            response,
            self.return_evaluated_siae_list_link_html,
            html=True,
            count=1,
        )
        assertNotContains(
            response,
            self.return_dashboard_link_html,
            html=True,
        )
        assertContains(
            response,
            self.letter_document_link_html,
            html=True,
            count=int(has_significant_sanction),
        )
        assertContains(
            response,
            """
            <b>Mode de notification :</b>
            <b class="text-danger">Lettre recommandée avec accusé de réception envoyée par la DDETS</b>
            """,
            html=True,
            count=int(has_significant_sanction),
        )
        assertContains(
            response,
            f"""
            <b>Mode de notification :</b>
            Transmis par e-mail le {self.evaluated_siae.notified_at.strftime("%d/%m/%Y")}
            """,
            html=True,
            count=int(not has_significant_sanction),
        )
        assertContains(response, "<h2>Structure concernée</h2>")
        assertContains(response, f"<h2>Détail{'s' if suspension_dates else ''} de la décision</h2>")
        assertContains(response, "<h2>Irrégularités constatées</h2>")

    def test_view_as_other_institution(self, client):
        other = InstitutionMembershipFactory()
        client.force_login(other.user)
        response = client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "suspension_dates",
        [None, InclusiveDateRange(datetime.date(2023, 1, 1))],
        ids=["non_significant_sanction", "significant_sanction"],
    )
    def test_view_as_siae(self, client, snapshot, suspension_dates):
        self.sanctions.suspension_dates = suspension_dates
        self.sanctions.save(update_fields=["suspension_dates"])
        client.force_login(self.employer)
        response = client.get(
            reverse(
                "siae_evaluations_views:siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(snapshot, response, is_siae=True)
        assertContains(
            response,
            self.return_dashboard_link_html,
            html=True,
            count=1,
        )
        assertNotContains(
            response,
            self.return_evaluated_siae_list_link_html,
            html=True,
        )
        assertNotContains(
            response,
            self.letter_document_link_html,
            html=True,
        )
        assertNotContains(response, "<h2>Structure concernée</h2>")
        assertNotContains(response, f"<h2>Détail{'s' if suspension_dates else ''} de la décision</h2>")
        assertNotContains(response, "<h2>Irrégularités constatées</h2>")

    def test_view_as_other_siae(self, client):
        company_membership = CompanyMembershipFactory()
        client.force_login(company_membership.user)
        response = client.get(
            reverse(
                "siae_evaluations_views:siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        assert response.status_code == 404

    def test_training_session(self, client, snapshot):
        client.force_login(self.institution_user)
        response = client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(snapshot, response, is_siae=False)
        assert pretty_indented(parse_response_to_soup(response, ".card .card-body:nth-of-type(2)")) == snapshot(
            name="sanction_details"
        )

    def test_temporary_suspension(self, client, snapshot):
        self.sanctions.training_session = ""
        self.sanctions.suspension_dates = InclusiveDateRange(datetime.date(2023, 1, 1), datetime.date(2023, 6, 1))
        self.sanctions.save()
        client.force_login(self.institution_user)
        response = client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(snapshot, response, is_siae=False)
        assert pretty_indented(parse_response_to_soup(response, ".card .card-body:nth-of-type(2)")) == snapshot(
            name="sanction_details"
        )

    def test_permanent_suspension(self, client, snapshot):
        self.sanctions.training_session = ""
        self.sanctions.suspension_dates = InclusiveDateRange(datetime.date(2023, 1, 1))
        self.sanctions.save()
        client.force_login(self.institution_user)
        response = client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(snapshot, response, is_siae=False)
        assert pretty_indented(parse_response_to_soup(response, ".card .card-body:nth-of-type(2)")) == snapshot(
            name="sanction_details"
        )

    @pytest.mark.parametrize("subsidy_cut_percent", [10, 100])
    def test_subsidy_cut_rate(self, client, subsidy_cut_percent, snapshot):
        self.sanctions.training_session = ""
        self.sanctions.save()
        EvaluatedJobApplicationSanctionFactory(
            sanctions=self.sanctions,
            evaluated_job_application=self.evaluated_siae.evaluated_job_applications.first(),
            subsidy_cut_percent=subsidy_cut_percent,
        )
        client.force_login(self.institution_user)
        response = client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(snapshot, response, is_siae=False, subsidy_cut_percent=subsidy_cut_percent)
        assert pretty_indented(parse_response_to_soup(response, ".card .card-body:nth-of-type(2)")) == snapshot(
            name=f"sanctions with subsidy_cut_percent={subsidy_cut_percent}"
        )

    def test_subsidy_cut_queries(self, client, snapshot):
        self.sanctions.training_session = ""
        self.sanctions.save()
        EvaluatedJobApplicationSanctionFactory.create_batch(4, sanctions=self.sanctions)
        client.force_login(self.institution_user)
        with assertSnapshotQueries(snapshot(name="queries")):
            client.get(
                reverse(
                    "siae_evaluations_views:institution_evaluated_siae_sanction",
                    kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
                )
            )

    def test_no_sanction(self, client, snapshot):
        self.sanctions.training_session = ""
        self.sanctions.no_sanction_reason = "Ça ira pour cette fois."
        self.sanctions.save()
        client.force_login(self.institution_user)
        response = client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(snapshot, response, is_siae=False)
        assert pretty_indented(parse_response_to_soup(response, ".card .card-body:nth-of-type(2)")) == snapshot(
            name="sanction_details"
        )

    def test_combined_sanctions(self, client, snapshot):
        self.sanctions.suspension_dates = InclusiveDateRange(datetime.date(2023, 1, 1), datetime.date(2023, 6, 1))
        self.sanctions.save()
        EvaluatedJobApplicationSanctionFactory(
            sanctions=self.sanctions,
            evaluated_job_application=self.evaluated_siae.evaluated_job_applications.first(),
            subsidy_cut_percent=50,
        )
        client.force_login(self.institution_user)
        response = client.get(
            reverse(
                "siae_evaluations_views:institution_evaluated_siae_sanction",
                kwargs={"evaluated_siae_pk": self.evaluated_siae.pk},
            )
        )
        self.assertSanctionContent(snapshot, response, is_siae=False, subsidy_cut_percent=50)
        assert pretty_indented(parse_response_to_soup(response, ".card .card-body:nth-of-type(2)")) == snapshot(
            name="sanction_details"
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
        client.force_login(EmployerFactory(membership=True))
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

    @pytest.mark.usefixtures("temporary_bucket")
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
            assertRedirects(response, crit.proof.url(), fetch_redirect_response=False)
        pdf_file.seek(0)
        assert httpx.get(response.url).content == pdf_file.read()

    def test_access_other_siae(self, client):
        institution = InstitutionFactory(name="DDETS 01", department="01")
        job_app = EvaluatedJobApplicationFactory(evaluated_siae__evaluation_campaign__institution=institution)
        crit = EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=job_app)
        other_evaluated_siae = EvaluatedSiaeFactory(evaluation_campaign__institution=institution)
        membership = CompanyMembershipFactory(company=other_evaluated_siae.siae)
        url = reverse("siae_evaluations_views:view_proof", kwargs={"evaluated_administrative_criteria_id": crit.pk})
        client.force_login(membership.user)
        response = client.get(url)
        assert response.status_code == 404

    @pytest.mark.usefixtures("temporary_bucket")
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
            assertRedirects(response, crit.proof.url(), fetch_redirect_response=False)
        pdf_file.seek(0)
        assert httpx.get(response.url).content == pdf_file.read()

    def test_access_other_institution(self, client):
        job_app = EvaluatedJobApplicationFactory(evaluated_siae__evaluation_campaign__institution__department="01")
        crit = EvaluatedAdministrativeCriteriaFactory(evaluated_job_application=job_app)
        membership = InstitutionMembershipFactory(institution__department="02")
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
