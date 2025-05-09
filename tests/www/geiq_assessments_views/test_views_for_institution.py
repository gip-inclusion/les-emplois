import datetime
import uuid

from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertQuerySetEqual, assertRedirects

from itou.companies.enums import CompanyKind
from itou.geiq_assessments.models import AssessmentInstitutionLink
from itou.institutions.enums import InstitutionKind
from tests.companies.factories import CompanyMembershipFactory
from tests.geiq_assessments.factories import (
    AssessmentCampaignFactory,
    AssessmentFactory,
)
from tests.institutions.factories import InstitutionMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup, pretty_indented


class TestListAssessmentsView:
    def test_anonymous_access(self, client):
        url = reverse("geiq_assessments_views:list_for_institution")
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        url = reverse("geiq_assessments_views:list_for_institution")
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 403),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_empty_list(self, client, snapshot):
        membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
        client.force_login(membership.user)
        response = client.get(reverse("geiq_assessments_views:list_for_institution"))
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments empty list"
        )

    @freeze_time("2025-05-21 12:00", tick=True)
    def test_complex_list(self, client, snapshot):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ,
            institution__name="Un DREETS GEIQ",
        )
        client.force_login(membership.user)
        campaign = AssessmentCampaignFactory(year=timezone.localdate().year - 1)
        new_assessment = AssessmentFactory(
            id=uuid.UUID("00000000-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            with_main_geiq=True,
            label_geiq_name="Un Joli GEIQ",
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
        )
        AssessmentInstitutionLink.objects.create(
            assessment=new_assessment, institution=membership.institution, with_convention=True
        )
        submitted_assessment = AssessmentFactory(
            id=uuid.UUID("11111111-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            created_by__first_name="Marie",
            created_by__last_name="Curie",
            with_main_geiq=True,
            label_geiq_name="Un Beau GEIQ",
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=submitted_assessment, institution=membership.institution, with_convention=True
        )

        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        reviewed_assessment = AssessmentFactory(
            id=uuid.UUID("22222222-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            created_by__first_name="Marie",
            created_by__last_name="Curie",
            label_antennas=[{"id": 1, "name": "Un Superbe GEIQ"}],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            reviewed_by=ddets_membership.user,
            reviewed_by_institution=ddets_membership.institution,
            review_comment="Bravo !",
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=100_000,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=reviewed_assessment, institution=membership.institution, with_convention=True
        )
        final_reviewed_assessment = AssessmentFactory(
            id=uuid.UUID("33333333-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            created_by__first_name="Marie",
            created_by__last_name="Curie",
            label_antennas=[{"id": 1, "name": "Un Superbe GEIQ"}],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            reviewed_by=membership.user,
            reviewed_by_institution=membership.institution,
            review_comment="Bravo !",
            final_reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            final_reviewed_by=membership.user,
            final_reviewed_by_institution=membership.institution,
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=80_000,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=final_reviewed_assessment, institution=membership.institution, with_convention=True
        )
        AssessmentFactory(campaign=campaign)  # Another assessment not linked to the institution

        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(reverse("geiq_assessments_views:list_for_institution"))
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments complex list"
        )
        assertQuerySetEqual(
            response.context["assessments"],
            [submitted_assessment, reviewed_assessment, final_reviewed_assessment, new_assessment],
        )


class TestAssessmentDetailsForInstitutionView:
    def test_anonymous_access(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
        )
        url = reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
        )
        url = reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 403),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    @freeze_time("2025-05-27 12:00")
    def test_details_for_institution(self, client, snapshot):
        ddets_membership = InstitutionMembershipFactory(
            institution__name="DDETS 29",
            institution__kind=InstitutionKind.DDETS_GEIQ,
            user__email="paul@dd.ets",
            user__first_name="Jean",
            user__last_name="Dupont",
        )
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
            user__first_name="Paul",
            user__last_name="Martin",
            user__email="paul.martin@example.com",
        )
        client.force_login(ddets_membership.user)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2024,
            companies=[geiq_membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            created_by__email="jean.dupont@example.com",
            label_geiq_name="Un Joli GEIQ",
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
            with_submission_requirements=True,
            geiq_comment="Bonjour, merci, au revoir !",
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        response = client.get(reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}))
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="assessment details title waiting for submission"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details section for submission"
        )
        assessment.submitted_at = timezone.now() + datetime.timedelta(hours=3)
        assessment.submitted_by = geiq_membership.user
        assessment.save()
        response = client.get(reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}))
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="assessment details title after submission"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details section after submission"
        )

        assessment.grants_selection_validated_at = timezone.now() + datetime.timedelta(hours=4)
        assessment.save()
        response = client.get(reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}))
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="assessment details title"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details section with grants selection validated"
        )

        assessment.decision_validated_at = timezone.now() + datetime.timedelta(hours=5)
        assessment.convention_amount = 100_000
        assessment.advance_amount = 50_000
        assessment.granted_amount = 80_000
        assessment.save()
        response = client.get(reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}))
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="assessment details title"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details section ready for review"
        )

        assessment.reviewed_at = timezone.now() + datetime.timedelta(hours=6)
        assessment.reviewed_by = ddets_membership.user
        assessment.reviewed_by_institution = ddets_membership.institution
        assessment.review_comment = "Bravo !"
        assessment.save()
        response = client.get(reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}))
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="reviewed assessment details title"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details section with review"
        )

        dreets_membership = InstitutionMembershipFactory(
            institution__name="DREETS BRET",
            institution__kind=InstitutionKind.DREETS_GEIQ,
        )
        assessment.final_reviewed_at = timezone.now() + datetime.timedelta(hours=7)
        assessment.final_reviewed_by = dreets_membership.user
        assessment.final_reviewed_by_institution = dreets_membership.institution
        assessment.save()
        response = client.get(reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}))
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="final reviewed assessment details title"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details section with final review"
        )

    def test_ddets_review_and_dreets_final_review(self, client):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
            user__first_name="Paul",
            user__last_name="Martin",
            user__email="paul.martin@example.com",
        )
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2024,
            companies=[geiq_membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            created_by__email="jean.dupont@example.com",
            label_geiq_name="Un Joli GEIQ",
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=80_000,
            review_comment="Bravo !",
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=dreets_membership.institution,
        )

        with freeze_time(timezone.now() + datetime.timedelta(hours=6)):
            client.force_login(ddets_membership.user)
            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "review"},
            )
            assertRedirects(
                response, reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
            )
            assessment.refresh_from_db()
            assert assessment.reviewed_at == timezone.now()
            assert assessment.reviewed_by == ddets_membership.user
            assert assessment.reviewed_by_institution == ddets_membership.institution

        with freeze_time(timezone.now() + datetime.timedelta(hours=7)):
            client.force_login(dreets_membership.user)
            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "review"},
            )
            assertRedirects(
                response, reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
            )
            assessment.refresh_from_db()
            assert assessment.final_reviewed_at == timezone.now()
            assert assessment.final_reviewed_by == dreets_membership.user
            assert assessment.final_reviewed_by_institution == dreets_membership.institution

    def test_ddets_review_dreets_fix_and_dreets_review(self, client, snapshot):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        dreets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
            user__first_name="Paul",
            user__last_name="Martin",
            user__email="paul.martin@example.com",
        )
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2024,
            companies=[geiq_membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            created_by__email="jean.dupont@example.com",
            label_geiq_name="Un Joli GEIQ",
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=80_000,
            review_comment="Bravo !",
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=dreets_membership.institution,
        )

        # DDETS review
        with freeze_time(timezone.now() + datetime.timedelta(hours=6)):
            client.force_login(ddets_membership.user)
            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "review"},
            )
            assertRedirects(
                response, reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
            )
            assessment.refresh_from_db()
            assert assessment.reviewed_at == timezone.now()
            assert assessment.reviewed_by == ddets_membership.user
            assert assessment.reviewed_by_institution == ddets_membership.institution

        # DREETS fix
        client.force_login(dreets_membership.user)
        response = client.post(
            reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
            data={"action": "fix"},
        )
        assertRedirects(
            response, reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
        )
        assessment.refresh_from_db()
        assert assessment.reviewed_at is None
        assert assessment.reviewed_by is None
        assert assessment.reviewed_by_institution is None

        # DREETS review
        with freeze_time(timezone.now() + datetime.timedelta(hours=6)):
            client.force_login(dreets_membership.user)
            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "review"},
            )
            assertRedirects(
                response, reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
            )
            assessment.refresh_from_db()
            assert assessment.reviewed_at == timezone.now()
            assert assessment.reviewed_by == dreets_membership.user
            assert assessment.reviewed_by_institution == dreets_membership.institution
            assert assessment.final_reviewed_at == timezone.now()
            assert assessment.final_reviewed_by == dreets_membership.user
            assert assessment.final_reviewed_by_institution == dreets_membership.institution


class TestAssessmentReviewView:
    def test_anonymous_access(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
        )
        url = reverse("geiq_assessments_views:assessment_review", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
        )
        url = reverse("geiq_assessments_views:assessment_review", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 403),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_review_assessment(self, client, snapshot):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            with_main_geiq=True,
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        url = reverse("geiq_assessments_views:assessment_review", kwargs={"pk": assessment.pk})
        client.force_login(ddets_membership.user)
        response = client.get(url)
        assert response.status_code == 404

        assessment.grants_selection_validated_at = timezone.now() + datetime.timedelta(hours=4)
        assessment.save()

        response = client.get(url)
        assert response.status_code == 200
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments review form"
        )
        response = client.post(
            url,
            data={
                "convention_amount": "10000",
                "advance_amount": "50000",
                "granted_amount": "80000",
                "review_comment": "",
            },
        )
        assertContains(response, "Ce champ est obligatoire.")
        assertContains(response, "Le montant total accordé ne peut être supérieur au montant conventionné.")
        assertContains(response, "Le montant du premier versement ne peut être supérieur au montant conventionné.")
        assert response.context["form"].errors == {
            "review_comment": ["Ce champ est obligatoire."],
            "granted_amount": ["Le montant total accordé ne peut être supérieur au montant conventionné."],
            "advance_amount": ["Le montant du premier versement ne peut être supérieur au montant conventionné."],
        }

        with freeze_time(timezone.now() + datetime.timedelta(hours=5)):
            response = client.post(
                url,
                data={
                    "convention_amount": "100000",
                    "advance_amount": "50000",
                    "granted_amount": "80000",
                    "review_comment": "Bravo !",
                },
            )
        assertRedirects(
            response, reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
        )
        assessment.refresh_from_db()
        assert assessment.decision_validated_at is not None
        assert assessment.convention_amount == 100_000
        assert assessment.advance_amount == 50_000
        assert assessment.granted_amount == 80_000
        assert assessment.review_comment == "Bravo !"

    def test_review_already_reviewed_assessment(self, client, snapshot):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            with_main_geiq=True,
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            review_comment="Bravo !",
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=80_000,
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            reviewed_by=ddets_membership.user,
            reviewed_by_institution=ddets_membership.institution,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        url = reverse("geiq_assessments_views:assessment_review", kwargs={"pk": assessment.pk})
        client.force_login(ddets_membership.user)
        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="disabled assessments review form"
        )
        origin_decision_validated_at = assessment.decision_validated_at
        response = client.post(
            url,
            data={
                "convention_amount": "20000",
                "advance_amount": "4000",
                "granted_amount": "7000",
                "review_comment": "Un grand bravo !",
            },
        )
        assert response.status_code == 200
        assessment.refresh_from_db()
        assert assessment.decision_validated_at == origin_decision_validated_at
        assert assessment.convention_amount == 100_000
        assert assessment.advance_amount == 50_000
        assert assessment.granted_amount == 80_000
        assert assessment.review_comment == "Bravo !"
