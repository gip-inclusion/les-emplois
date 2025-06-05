import datetime
import uuid

import pytest
from django.contrib import messages
from django.core.files.storage import default_storage
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertQuerySetEqual, assertRedirects

from itou.companies.enums import CompanyKind
from itou.geiq_assessments.models import Assessment, AssessmentInstitutionLink, LabelInfos
from itou.institutions.enums import InstitutionKind
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.files.factories import FileFactory
from tests.geiq_assessments.factories import (
    AssessmentCampaignFactory,
    AssessmentFactory,
    EmployeeContractFactory,
)
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup, pretty_indented


@pytest.fixture
def label_settings(settings):
    settings.API_GEIQ_LABEL_BASE_URL = "https://geiq.label"
    settings.API_GEIQ_LABEL_TOKEN = "S3cr3t!"
    return settings


class TestListAssessmentsView:
    def test_anonymous_access(self, client):
        url = reverse("geiq_assessments_views:list_for_geiq")
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        url = reverse("geiq_assessments_views:list_for_geiq")
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 403),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_setting_check(self, client, settings):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        client.force_login(membership.user)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = []

        response = client.get(reverse("geiq_assessments_views:list_for_geiq"))
        assert response.status_code == 404

        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        response = client.get(reverse("geiq_assessments_views:list_for_geiq"))
        assert response.status_code == 200

    def test_empty_list(self, client, settings, snapshot):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        client.force_login(membership.user)
        response = client.get(reverse("geiq_assessments_views:list_for_geiq"))
        assertContains(response, reverse("geiq_assessments_views:create"))
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(name="assessments empty list")

    @freeze_time("2025-05-21 12:00", tick=True)
    def test_complex_list(self, client, settings, snapshot):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        client.force_login(membership.user)
        campaign = AssessmentCampaignFactory(year=timezone.localdate().year - 1)
        new_assessment = AssessmentFactory(
            id=uuid.UUID("00000000-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            companies=[membership.company, CompanyFactory(kind=CompanyKind.GEIQ)],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            with_main_geiq=True,
            label_geiq_name="Un Joli GEIQ",
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
        )
        submitted_assessment = AssessmentFactory(
            id=uuid.UUID("11111111-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            companies=[membership.company],
            created_by__first_name="Marie",
            created_by__last_name="Curie",
            with_main_geiq=True,
            label_geiq_name="Un Beau GEIQ",
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=membership.user,
        )

        dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
        final_reviewed_assessment = AssessmentFactory(
            id=uuid.UUID("22222222-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            companies=[membership.company],
            created_by__first_name="Marie",
            created_by__last_name="Curie",
            label_antennas=[{"id": 1, "name": "Un Superbe GEIQ"}],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            reviewed_by=dreets_membership.user,
            reviewed_by_institution=dreets_membership.institution,
            review_comment="Bravo !",
            final_reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            final_reviewed_by=dreets_membership.user,
            final_reviewed_by_institution=dreets_membership.institution,
        )
        AssessmentFactory(campaign=campaign)  # Another assessment not linked to the GEIQ

        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(reverse("geiq_assessments_views:list_for_geiq"))
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(name="assessments complex list")
        assertQuerySetEqual(
            response.context["assessments"],
            [new_assessment, submitted_assessment, final_reviewed_assessment],
        )


class TestCreateAssessmentView:
    def test_anonymous_access(self, client):
        url = reverse("geiq_assessments_views:create")
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        url = reverse("geiq_assessments_views:create")
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 403),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_setting_check(self, client, settings):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        client.force_login(membership.user)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = []

        response = client.get(reverse("geiq_assessments_views:create"))
        assert response.status_code == 404

        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        response = client.get(reverse("geiq_assessments_views:create"))
        assert response.status_code == 200

    def test_info_missing_for_creation(self, client, settings, snapshot):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ, company__siret="12345678901234")
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        client.force_login(membership.user)
        response = client.get(reverse("geiq_assessments_views:create"))
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(name="no campaign or data")
        campaign = AssessmentCampaignFactory(year=timezone.localdate().year - 1)
        response = client.get(reverse("geiq_assessments_views:create"))
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(name="no campaign or data")
        LabelInfos.objects.create(campaign=campaign, data=[])
        response = client.get(reverse("geiq_assessments_views:create"))
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(name="unknown SIRET")

    def test_create_assessment_no_antenna(self, client, settings, snapshot):
        membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ, company__siret="12345678901234", company__post_code="29840"
        )
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = ["29"]
        ddets = InstitutionFactory(
            pk=1,
            name="DDETS 29",
            kind=InstitutionKind.DDETS_GEIQ,
            department=membership.company.department,
        )
        dreets = InstitutionFactory(
            pk=2,
            name="DREETS BRET",
            kind=InstitutionKind.DREETS_GEIQ,
            department=35,  # The DREETS matching deets
        )
        client.force_login(membership.user)
        campaign = AssessmentCampaignFactory(year=timezone.localdate().year - 1)
        LabelInfos.objects.create(
            campaign=campaign,
            data=[{"id": 1234, "nom": "Un Joli GEIQ", "siret": membership.company.siret, "antennes": []}],
        )
        response = client.get(reverse("geiq_assessments_views:create"))
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(name="No antenna")
        response = client.post(
            reverse("geiq_assessments_views:create"),
            {"main_geiq": True, "convention_with_ddets": True, "ddets": ddets.pk},
        )
        assessment = Assessment.objects.get()
        assertRedirects(response, reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}))
        assert assessment.companies.get() == membership.company
        assert assessment.label_geiq_name == "Un Joli GEIQ"
        assert assessment.with_main_geiq is True
        assert assessment.label_antennas == []
        assertQuerySetEqual(assessment.institutions.order_by("kind"), [ddets, dreets])
        assert assessment.conventionned_institutions() == [ddets]

        # Try to recreate the same assessment
        response = client.post(
            reverse("geiq_assessments_views:create"),
            {"main_geiq": True, "convention_with_ddets": True, "ddets": ddets.pk},
        )
        assert response.status_code == 200
        assert str(parse_response_to_soup(response, ".alert-dismissible")) == snapshot(
            name="Assessment already exists"
        )

    def test_create_assessment_multiple_antennas(self, client, settings, snapshot):
        membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ, company__siret="12345678901234", company__post_code="29840"
        )
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = ["29"]
        ddets = InstitutionFactory(
            pk=1,
            name="DDETS 29",
            kind=InstitutionKind.DDETS_GEIQ,
            department=membership.company.department,
        )
        dreets = InstitutionFactory(
            pk=2,
            name="DREETS BRET",
            kind=InstitutionKind.DREETS_GEIQ,
            department=35,  # The DREETS matching deets
        )
        client.force_login(membership.user)
        campaign = AssessmentCampaignFactory(year=timezone.localdate().year - 1)
        other_antenna = CompanyFactory(siret="12345678903456", kind=CompanyKind.GEIQ)
        non_geiq_antenna = CompanyFactory(siret="12345678902345", kind=CompanyKind.ACI)
        LabelInfos.objects.create(
            campaign=campaign,
            data=[
                {
                    "id": 1234,
                    "nom": "Un Joli GEIQ",
                    "siret": membership.company.siret,
                    "antennes": [
                        {"id": 2345, "nom": "Une antenne", "siret": non_geiq_antenna.siret},
                        {"id": 3456, "nom": "Une autre antenne", "siret": other_antenna.siret},
                        {"id": 4567, "nom": "Une dernière antenne", "siret": "12345678904567"},
                    ],
                }
            ],
        )
        response = client.get(reverse("geiq_assessments_views:create"))
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(name="Multiple antennas")

        response = client.post(
            reverse("geiq_assessments_views:create"),
            {
                "main_geiq": True,
                "convention_with_ddets": True,
                "ddets": ddets.pk,
                "convention_with_dreets": True,
                "dreets": dreets.pk,
                "antenna_2345": True,
                "antenna_3456": True,
            },
        )
        assessment = Assessment.objects.get()
        assertRedirects(response, reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}))
        assertQuerySetEqual(assessment.companies.order_by("siret"), [membership.company, other_antenna])
        assert assessment.label_geiq_name == "Un Joli GEIQ"
        assert assessment.with_main_geiq is True
        assert assessment.label_antennas == [
            {"id": 2345, "name": "Une antenne"},
            {"id": 3456, "name": "Une autre antenne"},
        ]
        assertQuerySetEqual(assessment.institutions.order_by("kind"), [ddets, dreets])
        assert assessment.conventionned_institutions() == [ddets, dreets]

        # Try to recreate an overlapping assessment
        response = client.post(
            reverse("geiq_assessments_views:create"),
            {
                "main_geiq": True,
                "convention_with_ddets": True,
                "ddets": ddets.pk,
                "antenna_3456": True,
            },
        )
        assert response.status_code == 200
        assert str(parse_response_to_soup(response, ".alert-dismissible")) == snapshot(
            name="Assessment already exists for main & 1 antenna"
        )

        # Check the form
        response = client.get(reverse("geiq_assessments_views:create"))
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="Create form with disabled choices"
        )

        # Create the assessment for the last antenna succeeds
        response = client.post(
            reverse("geiq_assessments_views:create"),
            {
                "convention_with_dreets": True,
                "dreets": dreets.pk,
                "antenna_4567": True,
            },
        )
        second_assessment = Assessment.objects.latest("created_at")
        assertRedirects(
            response, reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": second_assessment.pk})
        )
        assert second_assessment.companies.get() == membership.company
        assert second_assessment.label_geiq_name == "Un Joli GEIQ"
        assert second_assessment.with_main_geiq is False
        assert second_assessment.label_antennas == [
            {"id": 4567, "name": "Une dernière antenne"},
        ]
        assertQuerySetEqual(second_assessment.institutions.order_by("kind"), [dreets])
        assert second_assessment.conventionned_institutions() == [dreets]


class TestAssessmentDetailsForGEIQView:
    def test_anonymous_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 403),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_setting_check(self, client, settings):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        client.force_login(membership.user)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = []

        assessment = AssessmentFactory(companies=[membership.company])
        url = reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assert response.status_code == 404

        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        response = client.get(url)
        assert response.status_code == 200

    def test_details_for_geiq(self, client, settings, snapshot):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            companies=[membership.company, CompanyFactory(kind=CompanyKind.GEIQ)],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            label_antennas=[{"id": 0, "name": "Un Joli GEIQ"}, {"id": 1234, "name": "Une antenne"}],
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=InstitutionMembershipFactory(
                institution__name="DDETS 29", institution__kind=InstitutionKind.DDETS_GEIQ, user__email="paul@dd.ets"
            ).institution,
            with_convention=True,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=InstitutionMembershipFactory(
                institution__name="DREETS BRET",
                institution__kind=InstitutionKind.DREETS_GEIQ,
                user__email="paul@dre.ets",
            ).institution,
            with_convention=True,
        )
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}))
        assert str(parse_response_to_soup(response, ".s-title-02")) == snapshot(name="assessment details title")
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(name="assessment details section")

    def test_htmx_load(self, client, settings, label_settings, respx_mock, pdf_file):
        pdf_file_content = pdf_file.read()
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2023,
            companies=[membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            label_geiq_id=1234,
            label_antennas=[{"id": 0, "name": "Un Joli GEIQ"}, {"id": 1234, "name": "Une antenne"}],
        )
        response = client.get(
            reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
        )
        simulated_page = parse_response_to_soup(response, selector="#main")

        # Retrieve Summary Document PDF
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SynthesePDF?id={assessment.label_geiq_id}"
        ).respond(
            200,
            content=pdf_file_content,
            headers={
                "content-length": str(len(pdf_file_content)),
                "content-transfer-encoding": "binary",
                "content-type": "application/pdf",
            },
        )
        response = client.post(
            reverse("geiq_assessments_views:sync_summary_document", kwargs={"pk": assessment.pk}),
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, "#summary-document-section .c-box--summary__footer button", response)
        response = client.get(
            reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
        )
        fresh_page = parse_response_to_soup(response, selector="#main")
        assertSoupEqual(simulated_page, fresh_page)

        # Retrieve Structure Financial Assessment PDF
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/DownloadCompte?id={assessment.label_geiq_id}"
        ).respond(
            200,
            content=pdf_file_content,
            headers={
                "content-length": str(len(pdf_file_content)),
                "content-transfer-encoding": "binary",
                "content-type": "application/pdf",
            },
        )
        response = client.post(
            reverse("geiq_assessments_views:sync_structure_financial_assessment", kwargs={"pk": assessment.pk}),
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(
            simulated_page, "#structure-financial-assessment-section .c-box--summary__footer button", response
        )
        response = client.get(
            reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
        )
        fresh_page = parse_response_to_soup(response, selector="#main")
        assertSoupEqual(simulated_page, fresh_page)

        # Retrieve Contracts infos
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalarieContrat"
            f"?join=salariecontrat.salarie,s&count=true&where[]=s.geiq,=,{assessment.label_geiq_id}&where[]=salariecontrat.date_fin,>,2022-09-30",
        ).respond(200, json={"status": "Success", "result": 0})
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalarieContrat"
            f"?join=salariecontrat.salarie,s&where[]=s.geiq,=,{assessment.label_geiq_id}&where[]=salariecontrat.date_fin,>,2022-09-30&sort=salariecontrat.id&n=100&p=1"
        ).respond(200, json={"status": "Success", "result": []})
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalariePreQualification"
            f"?join=salarieprequalification.salarie,s&where=s.geiq,=,{assessment.label_geiq_id}&count=true"
        ).respond(200, json={"status": "Success", "result": 0})
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalariePreQualification"
            f"?join=salarieprequalification.salarie,s&where=s.geiq,=,{assessment.label_geiq_id}&sort=salarieprequalification.id&n=100&p=1"
        ).respond(200, json={"status": "Success", "result": []})
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/TauxGeiq?where=geiq,=,{assessment.label_geiq_id}"
        ).respond(
            200,
            json={
                "status": "Success",
                "result": [
                    {
                        "geiq_id": assessment.label_geiq_id,
                        "taux_rupture_periode_essai": "25.0",
                        "taux_rupture_hors_periode_essai": "",
                        "taux_sortie_emploi_durable": "50.0",
                        "taux_sortie_emploi": "50.0",
                        "taux_obtention_qualification": "75.0",
                    }
                ],
            },
        )
        response = client.post(
            reverse("geiq_assessments_views:assessment_contracts_sync", kwargs={"pk": assessment.pk}),
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, "#contracts-box .c-box--summary__footer button", response)
        response = client.get(
            reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
        )
        fresh_page = parse_response_to_soup(response, selector="#main")
        assertSoupEqual(simulated_page, fresh_page)

    def test_assessment_status_content(self, client, settings, snapshot):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2023,
            companies=[membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            label_geiq_id=1234,
            label_geiq_name="Un Joli GEIQ",
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
            action_financial_assessment_file=FileFactory(),
            geiq_comment="Un commentaire",
        )
        # summary document, structure financial assessment & contracts are missing
        response = client.get(
            reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
        )
        status_box = parse_response_to_soup(response, selector="#assessment-status-box")
        assert pretty_indented(status_box) == snapshot(
            name="assessment status: contracts, summary document & structure financial assessment missing"
        )

        assessment.contracts_synced_at = timezone.now()
        assessment.contracts_selection_validated_at = timezone.now()
        assessment.save()
        # summary document & structure financial assessment are missing
        response = client.get(
            reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
        )
        status_box = parse_response_to_soup(response, selector="#assessment-status-box")
        assert pretty_indented(status_box) == snapshot(
            name="assessment status: summary document & structure financial assessment missing"
        )

        assessment.structure_financial_assessment_file = FileFactory()
        assessment.summary_document_file = FileFactory()
        assessment.save()

        # Ready for submission
        response = client.get(
            reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
        )
        status_box = parse_response_to_soup(response, selector="#assessment-status-box")
        assert pretty_indented(status_box) == snapshot(name="assessment status: ready for submission")

    @freeze_time("2025-05-27 12:00", tick=True)
    def test_submission(self, client, mailoutbox, settings, snapshot):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        ddets_membership = InstitutionMembershipFactory(
            institution__name="DDETS 29",
            institution__kind=InstitutionKind.DDETS_GEIQ,
            user__email="paul@dd.ets",
        )
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2023,
            companies=[membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            label_geiq_id=1234,
            label_geiq_name="Un Joli GEIQ",
            label_antennas=[{"id": 1234, "name": "Une antenne"}, {"id": 2345, "name": "Une autre antenne"}],
            with_submission_requirements=True,
            geiq_comment="Un commentaire important qui se trouve dans le snapshot",
        )
        requested_contract = EmployeeContractFactory(
            employee__assessment=assessment,
            employee__allowance_amount=0,
            start_at=datetime.date(2024, 1, 1),
            end_at=datetime.date(2024, 4, 30),
            planned_end_at=datetime.date(2024, 5, 31),
            allowance_requested=True,
        )
        not_requested_contract = EmployeeContractFactory(
            employee__assessment=assessment,
            employee__allowance_amount=814,
            start_at=datetime.date(2024, 2, 1),
            end_at=datetime.date(2024, 3, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=False,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        details_url = reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk})
        response = client.post(details_url)
        assertRedirects(response, details_url)

        assessment.refresh_from_db()
        assert assessment.submitted_at is not None
        assert assessment.submitted_by == membership.user
        requested_contract.refresh_from_db()
        # Requested allowance are automatically granted by default
        assert requested_contract.allowance_granted is True
        assert not_requested_contract.allowance_granted is False

        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert (
            f"[DEV] Transmission du bilan d’exécution par la structure {assessment.label_geiq_name}" == email.subject
        )
        assert email.to[0] == ddets_membership.user.email
        assert email.body == snapshot(name="body of mail sent to institution members")

        response = client.get(details_url)
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="submitted assessment details title"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="submitted assessment details section"
        )

        origin_submitted_at = assessment.submitted_at
        response = client.post(details_url)
        assertMessages(
            response,
            [messages.Message(messages.INFO, "Ce bilan a déjà été soumis. Vous ne pouvez plus le modifier.")],
        )
        assessment.refresh_from_db()
        assert assessment.submitted_at == origin_submitted_at

    def test_early_submission_fails(self, client, settings):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            companies=[membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            label_antennas=[{"id": 0, "name": "Un Joli GEIQ"}, {"id": 1234, "name": "Une antenne"}],
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=InstitutionMembershipFactory(
                institution__name="DDETS 29", institution__kind=InstitutionKind.DDETS_GEIQ, user__email="paul@dd.ets"
            ).institution,
            with_convention=True,
        )
        response = client.post(reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}))
        assertContains(response, "Ce bilan ne peut pas encore être soumis. Ces actions sont manquantes")
        assessment.refresh_from_db()
        assert assessment.submitted_at is None


class TestAssessmentGetFile:
    def test_anonymous_access(self, client):
        assessment = AssessmentFactory(
            summary_document_file=FileFactory(),
            structure_financial_assessment_file=FileFactory(),
            action_financial_assessment_file=FileFactory(),
        )
        for url in [
            reverse("geiq_assessments_views:summary_document", kwargs={"pk": assessment.pk}),
            reverse("geiq_assessments_views:structure_financial_assessment", kwargs={"pk": assessment.pk}),
            reverse("geiq_assessments_views:action_financial_assessment", kwargs={"pk": assessment.pk}),
        ]:
            response = client.get(url)
            assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        assessment = AssessmentFactory(
            summary_document_file=FileFactory(),
            structure_financial_assessment_file=FileFactory(),
            action_financial_assessment_file=FileFactory(),
        )
        url = reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            for url in [
                reverse("geiq_assessments_views:summary_document", kwargs={"pk": assessment.pk}),
                reverse("geiq_assessments_views:structure_financial_assessment", kwargs={"pk": assessment.pk}),
                reverse("geiq_assessments_views:action_financial_assessment", kwargs={"pk": assessment.pk}),
            ]:
                response = client.get(url)
                assert response.status_code == expected_status

    def test_access(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
        filled_assessment = AssessmentFactory(
            campaign__year=2023,
            summary_document_file=FileFactory(),
            structure_financial_assessment_file=FileFactory(),
            action_financial_assessment_file=FileFactory(),
            companies=[geiq_membership.company],
        )
        AssessmentInstitutionLink.objects.create(
            assessment=filled_assessment, institution=dreets_membership.institution, with_convention=True
        )
        empty_assessment = AssessmentFactory(
            campaign__year=2023,
            companies=[geiq_membership.company],
        )
        AssessmentInstitutionLink.objects.create(
            assessment=empty_assessment, institution=dreets_membership.institution, with_convention=True
        )

        def check_access_to_files(assessment, has_access):
            for url, attr_name, expected_filename in [
                (
                    reverse("geiq_assessments_views:summary_document", kwargs={"pk": assessment.pk}),
                    "summary_document_file",
                    "Synthèse 2023.pdf",
                ),
                (
                    reverse("geiq_assessments_views:structure_financial_assessment", kwargs={"pk": assessment.pk}),
                    "structure_financial_assessment_file",
                    "Bilan financier structure 2023.pdf",
                ),
                (
                    reverse("geiq_assessments_views:action_financial_assessment", kwargs={"pk": assessment.pk}),
                    "action_financial_assessment_file",
                    "Bilan financier action 2023.pdf",
                ),
            ]:
                # Boto3 signed requests depend on the current date, with a second resolution.
                # See X-Amz-Date in
                # https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
                with freeze_time():
                    response = client.get(url)
                    if has_access:
                        assertRedirects(
                            response,
                            default_storage.url(
                                getattr(assessment, attr_name).key,
                                parameters={
                                    "ResponseContentDisposition": content_disposition_header(
                                        "inline", expected_filename
                                    ),
                                },
                            ),
                            fetch_redirect_response=False,
                        )
                    else:
                        assert response.status_code == 404

        client.force_login(geiq_membership.user)
        check_access_to_files(filled_assessment, has_access=True)
        check_access_to_files(empty_assessment, has_access=False)
        client.force_login(dreets_membership.user)
        check_access_to_files(filled_assessment, has_access=False)

        # Submit the filled_assessment
        filled_assessment.geiq_comment = "Un commentaire"
        filled_assessment.contracts_synced_at = timezone.now()
        filled_assessment.contracts_selection_validated_at = timezone.now()
        filled_assessment.submitted_by = geiq_membership.user
        filled_assessment.submitted_at = timezone.now()
        filled_assessment.save()

        # GEIQ & institution can now access the files
        client.force_login(geiq_membership.user)
        check_access_to_files(filled_assessment, has_access=True)
        client.force_login(dreets_membership.user)
        check_access_to_files(filled_assessment, has_access=True)


class TestAssessmentSyncFile:
    def test_anonymous_access(self, client):
        assessment = AssessmentFactory()
        for url in [
            reverse("geiq_assessments_views:sync_summary_document", kwargs={"pk": assessment.pk}),
            reverse("geiq_assessments_views:sync_structure_financial_assessment", kwargs={"pk": assessment.pk}),
        ]:
            response = client.post(url)
            assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 403),
        ]:
            client.force_login(user)
            for url in [
                reverse("geiq_assessments_views:sync_summary_document", kwargs={"pk": assessment.pk}),
                reverse("geiq_assessments_views:sync_structure_financial_assessment", kwargs={"pk": assessment.pk}),
            ]:
                response = client.post(url)
                assert response.status_code == expected_status

    def test_sync(self, client, pdf_file, respx_mock, label_settings):
        pdf_file_content = pdf_file.read()
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2023,
            companies=[membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            label_geiq_id=1234,
            label_antennas=[{"id": 0, "name": "Un Joli GEIQ"}, {"id": 1234, "name": "Une antenne"}],
        )

        # Sync Summary Document
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SynthesePDF?id={assessment.label_geiq_id}"
        ).respond(
            200,
            content=pdf_file_content,
            headers={
                "content-length": str(len(pdf_file_content)),
                "content-transfer-encoding": "binary",
                "content-type": "application/pdf",
            },
        )
        response = client.post(
            reverse("geiq_assessments_views:sync_summary_document", kwargs={"pk": assessment.pk}),
        )
        assertContains(response, reverse("geiq_assessments_views:summary_document", kwargs={"pk": assessment.pk}))
        assessment.refresh_from_db()
        assert assessment.summary_document_file is not None
        with default_storage.open(assessment.summary_document_file.key) as f:
            assert f.read() == pdf_file_content

        # Sync Structure Financial Assessment
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/DownloadCompte?id={assessment.label_geiq_id}"
        ).respond(
            200,
            content=pdf_file_content,
            headers={
                "content-length": str(len(pdf_file_content)),
                "content-transfer-encoding": "binary",
                "content-type": "application/pdf",
            },
        )
        response = client.post(
            reverse("geiq_assessments_views:sync_structure_financial_assessment", kwargs={"pk": assessment.pk}),
        )
        assertContains(
            response, reverse("geiq_assessments_views:structure_financial_assessment", kwargs={"pk": assessment.pk})
        )
        assessment.refresh_from_db()
        assert assessment.structure_financial_assessment_file is not None
        with default_storage.open(assessment.structure_financial_assessment_file.key) as f:
            assert f.read() == pdf_file_content

    def test_with_existing_files(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        summary_document_file = FileFactory()
        structure_financial_assessment_file = FileFactory()
        assessment = AssessmentFactory(
            campaign__year=2023,
            summary_document_file=summary_document_file,
            structure_financial_assessment_file=structure_financial_assessment_file,
            companies=[geiq_membership.company],
        )
        client.force_login(geiq_membership.user)
        response = client.post(reverse("geiq_assessments_views:sync_summary_document", kwargs={"pk": assessment.pk}))
        assertContains(response, reverse("geiq_assessments_views:summary_document", kwargs={"pk": assessment.pk}))
        assessment.refresh_from_db()
        assert assessment.summary_document_file == summary_document_file

        response = client.post(
            reverse("geiq_assessments_views:sync_structure_financial_assessment", kwargs={"pk": assessment.pk})
        )
        assertContains(
            response, reverse("geiq_assessments_views:structure_financial_assessment", kwargs={"pk": assessment.pk})
        )
        assessment.refresh_from_db()
        assert assessment.structure_financial_assessment_file == structure_financial_assessment_file

    def test_error(self, client, snapshot, settings):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        settings.API_GEIQ_LABEL_TOKEN = None  # Make sure client initialization will fail
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2023,
            companies=[membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            label_geiq_id=1234,
            label_antennas=[{"id": 0, "name": "Un Joli GEIQ"}, {"id": 1234, "name": "Une antenne"}],
        )
        detail_response = client.get(
            reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
        )

        # Retrieve Summary Document PDF
        # This will error due to lack of settings.API_GEIQ_LABEL_TOKEN
        simulated_page = parse_response_to_soup(detail_response, selector=".s-section")
        response = client.post(
            reverse("geiq_assessments_views:sync_summary_document", kwargs={"pk": assessment.pk}),
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, "#summary-document-section .c-box--summary__footer button", response)
        assert str(simulated_page) == snapshot(name="details page with error for summary document")

        # Retrieve Structure Financial Assessment PDF
        # This will error due to lack of settings.API_GEIQ_LABEL_TOKEN
        simulated_page = parse_response_to_soup(detail_response, selector=".s-section")
        response = client.post(
            reverse("geiq_assessments_views:sync_structure_financial_assessment", kwargs={"pk": assessment.pk}),
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(
            simulated_page, "#structure-financial-assessment-section .c-box--summary__footer button", response
        )
        assert str(simulated_page) == snapshot(name="details page with error for structure financial assessment")


class TestAssessmentUploadActionFinancialAssessment:
    def test_anonymous_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:upload_action_financial_assessment", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:upload_action_financial_assessment", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 403),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_access_and_upload(self, client, pdf_file, settings, snapshot):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [geiq_membership.company.post_code[:2]]
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2023,
            companies=[geiq_membership.company],
        )
        url = reverse("geiq_assessments_views:upload_action_financial_assessment", kwargs={"pk": assessment.pk})
        client.force_login(geiq_membership.user)
        response = client.get(url)
        assertContains(
            response, "/static/pdf/cerfa_15059-02"
        )  # Due to Django's ManifestStaticFilesStorage, the URL looks like /static/pdf/cerfa_15059-02.60ee0b03a492.pdf
        soup = parse_response_to_soup(response, ".s-section")
        for a_tags in soup.find_all("a", attrs={"href": True}):
            if a_tags["href"].startswith("/static/pdf/cerfa_15059-02"):
                a_tags["href"] = "/static/pdf/cerfa_15059-02.pdf"  # Normalize href for CI
        assert pretty_indented(soup) == snapshot(name="upload action financial assessment")

        response = client.post(url, data={"assessment_file": pdf_file})
        assertRedirects(response, reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}))
        assessment.refresh_from_db()
        assert assessment.action_financial_assessment_file is not None
        pdf_file.seek(0)
        with default_storage.open(assessment.action_financial_assessment_file.key) as f:
            assert f.read() == pdf_file.read()

    def test_no_access_after_submission(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            campaign__year=2023,
            summary_document_file=FileFactory(),
            structure_financial_assessment_file=FileFactory(),
            action_financial_assessment_file=FileFactory(),
            companies=[geiq_membership.company],
        )
        url = reverse("geiq_assessments_views:upload_action_financial_assessment", kwargs={"pk": assessment.pk})
        client.force_login(geiq_membership.user)
        response = client.get(url)
        assertContains(
            response, "/static/pdf/cerfa_15059-02"
        )  # Due to Django's ManifestStaticFilesStorage, the URL looks like /static/pdf/cerfa_15059-02.60ee0b03a492.pdf

        # Submit the assessment
        assessment.geiq_comment = "Un commentaire"
        assessment.contracts_synced_at = timezone.now()
        assessment.contracts_selection_validated_at = timezone.now()
        assessment.submitted_by = geiq_membership.user
        assessment.submitted_at = timezone.now()
        assessment.save()
        response = client.get(url)
        assert response.status_code == 404


class TestAssessmentComment:
    def test_anonymous_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:assessment_comment", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:assessment_comment", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 403),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_access_and_comment(self, client, settings, snapshot):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [geiq_membership.company.post_code[:2]]
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2023,
            companies=[geiq_membership.company],
        )
        url = reverse("geiq_assessments_views:assessment_comment", kwargs={"pk": assessment.pk})
        client.force_login(geiq_membership.user)
        response = client.get(url)
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(name="comment assessment")

        response = client.post(url, data={"geiq_comment": ""})
        assertContains(response, "Ce champ est obligatoire.")

        some_comment = "Un commentaire très pertinent"
        response = client.post(url, data={"geiq_comment": some_comment})
        assertRedirects(response, reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}))
        assessment.refresh_from_db()
        assert assessment.geiq_comment == some_comment

        some_updated_comment = "Un commentaire très pertinent et mis à jour"
        response = client.post(url, data={"geiq_comment": some_updated_comment})
        assertRedirects(response, reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}))
        assessment.refresh_from_db()
        assert assessment.geiq_comment == some_updated_comment

    def test_no_access_after_submission(self, client, settings, snapshot):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [geiq_membership.company.post_code[:2]]
        origin_comment = "Un commentaire initial"
        assessment = AssessmentFactory(
            campaign__year=2023,
            companies=[geiq_membership.company],
            with_submission_requirements=True,
            geiq_comment=origin_comment,
            submitted_by=geiq_membership.user,
            submitted_at=timezone.now() + datetime.timedelta(seconds=3),
        )
        url = reverse("geiq_assessments_views:assessment_comment", kwargs={"pk": assessment.pk})
        client.force_login(geiq_membership.user)
        response = client.get(url)
        assert response.status_code == 404
        response = client.post(url, data={"geiq_comment": "un autre commentaire"})
        assert response.status_code == 404
        assessment.refresh_from_db()
        assert assessment.geiq_comment == origin_comment


class TestAssessmentContractsSync:
    def test_anonymous_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:assessment_contracts_sync", kwargs={"pk": assessment.pk})
        response = client.post(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:assessment_contracts_sync", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 403),
        ]:
            client.force_login(user)
            response = client.post(url)
            assert response.status_code == expected_status

    def test_sync(self, client, respx_mock, label_settings):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2023,
            companies=[membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            label_geiq_id=1234,
            label_antennas=[{"id": 0, "name": "Un Joli GEIQ"}, {"id": 1234, "name": "Une antenne"}],
        )

        # Retrieve Contracts infos
        # TODO(xfernandez): add contracts & pre-qualifications data to test sync
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalarieContrat"
            f"?join=salariecontrat.salarie,s&count=true&where[]=s.geiq,=,{assessment.label_geiq_id}&where[]=salariecontrat.date_fin,>,2022-09-30",
        ).respond(200, json={"status": "Success", "result": 0})
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalarieContrat"
            f"?join=salariecontrat.salarie,s&where[]=s.geiq,=,{assessment.label_geiq_id}&where[]=salariecontrat.date_fin,>,2022-09-30&sort=salariecontrat.id&n=100&p=1"
        ).respond(200, json={"status": "Success", "result": []})
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalariePreQualification"
            f"?join=salarieprequalification.salarie,s&where=s.geiq,=,{assessment.label_geiq_id}&count=true"
        ).respond(200, json={"status": "Success", "result": 0})
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/SalariePreQualification"
            f"?join=salarieprequalification.salarie,s&where=s.geiq,=,{assessment.label_geiq_id}&sort=salarieprequalification.id&n=100&p=1"
        ).respond(200, json={"status": "Success", "result": []})
        EXPECTED_LABEL_RATES = {
            "geiq_id": assessment.label_geiq_id,
            "taux_rupture_periode_essai": "25.0",
            "taux_rupture_hors_periode_essai": "",
            "taux_sortie_emploi_durable": "50.0",
            "taux_sortie_emploi": "50.0",
            "taux_obtention_qualification": "75.0",
        }
        respx_mock.get(
            f"{label_settings.API_GEIQ_LABEL_BASE_URL}/rest/TauxGeiq?where=geiq,=,{assessment.label_geiq_id}"
        ).respond(
            200,
            json={
                "status": "Success",
                "result": [EXPECTED_LABEL_RATES],
            },
        )
        response = client.post(
            reverse("geiq_assessments_views:assessment_contracts_sync", kwargs={"pk": assessment.pk}),
        )
        assertContains(
            response, reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        )
        assessment.refresh_from_db()
        assert assessment.label_rates == EXPECTED_LABEL_RATES
        assert assessment.contracts_synced_at is not None

    def test_with_contracts_synced(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            campaign__year=2023,
            companies=[geiq_membership.company],
            contracts_synced_at=timezone.now() + datetime.timedelta(seconds=1),
        )
        client.force_login(geiq_membership.user)
        response = client.post(
            reverse("geiq_assessments_views:assessment_contracts_sync", kwargs={"pk": assessment.pk})
        )
        assertContains(
            response, reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        )
        previous_synced_at = assessment.contracts_synced_at
        assessment.refresh_from_db()
        assert assessment.contracts_synced_at == previous_synced_at

    def test_error(self, client, snapshot, settings):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        settings.GEIQ_ASSESSMENT_CAMPAIGN_POSTCODE_PREFIXES = [membership.company.post_code[:2]]
        settings.API_GEIQ_LABEL_TOKEN = None  # Make sure client initialization will fail
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2023,
            companies=[membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            label_geiq_id=1234,
            label_antennas=[{"id": 0, "name": "Un Joli GEIQ"}, {"id": 1234, "name": "Une antenne"}],
        )
        detail_response = client.get(
            reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
        )

        # Retrieve Contracts
        # This will error due to lack of settings.API_GEIQ_LABEL_TOKEN
        simulated_page = parse_response_to_soup(detail_response, selector=".s-section")
        response = client.post(
            reverse("geiq_assessments_views:assessment_contracts_sync", kwargs={"pk": assessment.pk}),
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, "#contracts-box .c-box--summary__footer button", response)
        assert str(simulated_page) == snapshot(name="details page with error for contracts")


class TestAssessmentKPI:
    def test_anonymous_access(self, client):
        assessment = AssessmentFactory(contracts_synced_at=timezone.now() + datetime.timedelta(seconds=1))
        url = reverse("geiq_assessments_views:assessment_kpi", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        assessment = AssessmentFactory(contracts_synced_at=timezone.now() + datetime.timedelta(seconds=1))
        url = reverse("geiq_assessments_views:assessment_kpi", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 403),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_access(self, client, snapshot):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            companies=[membership.company],
            contracts_synced_at=timezone.now() + datetime.timedelta(seconds=1),
            label_geiq_id=1234,
            label_rates={
                "geiq_id": 1234,
                "taux_rupture_periode_essai": "25.0",
                "taux_rupture_hors_periode_essai": "",
                "taux_sortie_emploi_durable": "50.0",
                "taux_sortie_emploi": "50.0",
                "taux_obtention_qualification": "75.0",
            },
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=InstitutionMembershipFactory(
                institution__name="DDETS 29", institution__kind=InstitutionKind.DDETS_GEIQ, user__email="paul@dd.ets"
            ).institution,
            with_convention=True,
        )
        response = client.get(reverse("geiq_assessments_views:assessment_kpi", kwargs={"pk": assessment.pk}))
        assert str(parse_response_to_soup(response, ".s-title-02")) == snapshot(name="assessment details title")
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(name="assessment details section")

    def test_no_access_before_sync(self, client):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        client.force_login(membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            companies=[membership.company],
            contracts_synced_at=None,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=InstitutionMembershipFactory(
                institution__name="DDETS 29", institution__kind=InstitutionKind.DDETS_GEIQ, user__email="paul@dd.ets"
            ).institution,
            with_convention=True,
        )
        response = client.get(reverse("geiq_assessments_views:assessment_kpi", kwargs={"pk": assessment.pk}))
        assert response.status_code == 404


class TestAssessmentResult:
    def test_anonymous_access(self, client):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
        assessment = AssessmentFactory(
            companies=[membership.company],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            reviewed_by=dreets_membership.user,
            reviewed_by_institution=dreets_membership.institution,
            review_comment="Bravo !",
            final_reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            final_reviewed_by=dreets_membership.user,
            final_reviewed_by_institution=dreets_membership.institution,
        )
        url = reverse("geiq_assessments_views:assessment_result", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
        assessment = AssessmentFactory(
            companies=[membership.company],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            reviewed_by=dreets_membership.user,
            reviewed_by_institution=dreets_membership.institution,
            review_comment="Bravo !",
            final_reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            final_reviewed_by=dreets_membership.user,
            final_reviewed_by_institution=dreets_membership.institution,
        )
        url = reverse("geiq_assessments_views:assessment_result", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 403),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_access(self, client, snapshot):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            companies=[membership.company],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            reviewed_by=dreets_membership.user,
            reviewed_by_institution=dreets_membership.institution,
            review_comment="Bravo !",
            convention_amount=100_000,
            advance_amount=20_000,
            granted_amount=80_000,
            final_reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            final_reviewed_by=dreets_membership.user,
            final_reviewed_by_institution=dreets_membership.institution,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=InstitutionMembershipFactory(
                institution__name="DDETS 29", institution__kind=InstitutionKind.DDETS_GEIQ, user__email="paul@dd.ets"
            ).institution,
            with_convention=True,
        )
        client.force_login(membership.user)
        response = client.get(reverse("geiq_assessments_views:assessment_result", kwargs={"pk": assessment.pk}))
        assert str(parse_response_to_soup(response, ".s-title-02")) == snapshot(name="assessment details title")
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details positive balance"
        )
        assessment.advance_amount = 80_000
        assessment.granted_amount = 20_000
        assessment.save()
        response = client.get(reverse("geiq_assessments_views:assessment_result", kwargs={"pk": assessment.pk}))
        assert str(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details negative balance"
        )

    def test_no_access_before_final_review(self, client):
        membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
        assessment = AssessmentFactory(
            companies=[membership.company],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            reviewed_by=dreets_membership.user,
            reviewed_by_institution=dreets_membership.institution,
            review_comment="Bravo !",
            convention_amount=100_000,
            advance_amount=20_000,
            granted_amount=80_000,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=InstitutionMembershipFactory(
                institution__name="DDETS 29", institution__kind=InstitutionKind.DDETS_GEIQ, user__email="paul@dd.ets"
            ).institution,
            with_convention=True,
        )
        client.force_login(membership.user)
        response = client.get(reverse("geiq_assessments_views:assessment_result", kwargs={"pk": assessment.pk}))
        assert response.status_code == 404
