import datetime
import random
import uuid

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertQuerySetEqual, assertRedirects

from itou.companies.enums import CompanyKind
from itou.geiq_assessments.enums import AssessmentState, AssessmentTransition
from itou.geiq_assessments.models import AssessmentInstitutionLink, AssessmentTransitionLog
from itou.institutions.enums import InstitutionKind
from itou.www.geiq_assessments_views.views import (
    INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_DETAILS,
    INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_LIST,
    get_allowance_stats_for_institution,
)
from tests.companies.factories import CompanyMembershipFactory
from tests.geiq_assessments.factories import (
    AssessmentCampaignFactory,
    AssessmentFactory,
    EmployeeContractFactory,
)
from tests.institutions.factories import InstitutionFactory, InstitutionMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import parse_response_to_soup, pretty_indented


class TestListAssessmentsView:
    URL = reverse("geiq_assessments_views:list_for_institution")

    def test_anonymous_access(self, client):
        response = client.get(self.URL)
        assertRedirects(response, reverse("account_login") + f"?next={self.URL}")

    def test_unauthorized_access(self, client):
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(membership=True), 403),
            (EmployerFactory(membership=True), 403),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(self.URL)
            assert response.status_code == expected_status

    def test_empty_list(self, client, snapshot):
        membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DREETS_GEIQ)
        client.force_login(membership.user)
        response = client.get(self.URL)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments empty list"
        )

    @pytest.mark.parametrize(
        "institution_kind",
        set(INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_LIST).difference(INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_DETAILS),
    )
    def test_limited_access_without_links_to_details(self, client, institution_kind, snapshot):
        user = InstitutionMembershipFactory(institution__kind=institution_kind).user

        campaign = AssessmentCampaignFactory(year=2024)
        AssessmentFactory(
            campaign=campaign,
            with_main_geiq=True,
            label_geiq_name="Un Joli GEIQ",
            label_geiq_post_code="12345",
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "12345"}],
        )

        client.force_login(user)
        response = client.get(self.URL)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".s-section",
                replace_in_attr=[
                    ("value", f"{campaign.pk}", "[PK of Campaign]"),
                ],
            )
        ) == snapshot(name="assessment list without links to details")

    @pytest.mark.parametrize("with_limited_access", [True, False], ids=["limited access", "unlimited access"])
    def test_display_amounts(self, client, with_limited_access, snapshot):
        if with_limited_access:
            kind = random.choice(
                list(
                    set(INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_LIST).difference(
                        INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_DETAILS
                    )
                )
            )
        else:
            kind = random.choice(INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_DETAILS)

        membership = InstitutionMembershipFactory(institution__kind=kind)
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        ddets_membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DDETS_GEIQ, institution__name="Une DDETS"
        )

        campaign = AssessmentCampaignFactory(year=2024)
        new = AssessmentFactory(
            id=uuid.UUID("00000000-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            with_main_geiq=True,
            label_geiq_name="Nouveau bilan",
        )
        submitted = AssessmentFactory(
            id=uuid.UUID("11111111-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            label_geiq_name="Bilan envoyé",
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            convention_amount=100_001,
            advance_amount=50_001,
            granted_amount=100_001,
        )
        reviewed = AssessmentFactory(
            id=uuid.UUID("22222222-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            label_geiq_name="Bilan à valider",
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
        final_reviewed = AssessmentFactory(
            id=uuid.UUID("33333333-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            label_geiq_name="Bilan validé",
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

        for idx, assessment in enumerate([new, submitted, reviewed, final_reviewed]):
            EmployeeContractFactory.create_batch(
                idx + 1,
                employee__assessment=assessment,
                allowance_requested=True,
                allowance_granted=True,
                employee__allowance_amount=814,
            )
            if not with_limited_access:
                # DDETS or DREETS need to have an institution link to see an assessment
                AssessmentInstitutionLink.objects.create(
                    assessment=assessment,
                    institution=membership.institution,
                )

        client.force_login(membership.user)
        response = client.get(self.URL)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".s-section",
                replace_in_attr=[
                    ("value", f"{campaign.pk}", "[PK of Campaign]"),
                ],
            )
        ) == snapshot(name="assessment list with amounts")

    @pytest.mark.parametrize(
        "institution_kind",
        set(INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_LIST).intersection(INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_DETAILS),
    )
    def test_full_access_with_links_to_details(self, client, institution_kind, snapshot):
        membership = InstitutionMembershipFactory(
            institution__kind=institution_kind, institution__name="Une institution GEIQ"
        )

        campaign = AssessmentCampaignFactory(year=2024)
        related_assessment = AssessmentFactory(
            id=uuid.UUID("00000000-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            with_main_geiq=True,
            label_geiq_name="Un Joli GEIQ",
            label_geiq_post_code="12345",
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "12345"}],
        )
        AssessmentInstitutionLink.objects.create(
            assessment=related_assessment,
            institution=membership.institution,
            with_convention=True,
        )
        _unrelated_assessment = AssessmentFactory()

        client.force_login(membership.user)
        response = client.get(self.URL)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".s-section",
                replace_in_attr=[
                    ("value", f"{campaign.pk}", "[PK of Campaign]"),
                    ("value", f"{membership.institution.pk}", "[PK of Institution]"),
                ],
            )
        ) == snapshot(name="assessment list with links to details")

    @freeze_time("2025-05-21 12:00", tick=True)
    def test_complex_list(self, client, snapshot):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ,
            institution__name="Un DREETS GEIQ",
        )
        client.force_login(membership.user)
        campaign = AssessmentCampaignFactory()
        new_assessment = AssessmentFactory(
            id=uuid.UUID("00000000-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            with_main_geiq=True,
            label_geiq_name="Un Joli GEIQ",
            label_geiq_post_code="12345",
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "12345"}],
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
            label_geiq_post_code="23456",
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
            label_antennas=[{"id": 1, "name": "Un Superbe GEIQ", "post_code": "12345"}],
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
            id=uuid.UUID("44444444-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            created_by__first_name="Marie",
            created_by__last_name="Curie",
            label_antennas=[{"id": 1, "name": "Un Superbe GEIQ", "post_code": "12345"}],
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
        later_final_reviewed_assessment = AssessmentFactory(
            id=uuid.UUID("33333333-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            created_by__first_name="Marie",
            created_by__last_name="Curie",
            label_antennas=[{"id": 1, "name": "Un Superbe GEIQ", "post_code": "12345"}],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            reviewed_by=membership.user,
            reviewed_by_institution=membership.institution,
            review_comment="Bravo !",
            final_reviewed_at=timezone.now() + datetime.timedelta(hours=8),
            final_reviewed_by=membership.user,
            final_reviewed_by_institution=membership.institution,
            convention_amount=100_000,
            advance_amount=60_000,
            granted_amount=90_000,
        )  # Assessment has been finally reviewed (i.e. updated) later than previous one: it must appear before.
        AssessmentInstitutionLink.objects.create(
            assessment=later_final_reviewed_assessment, institution=membership.institution, with_convention=True
        )
        AssessmentFactory(campaign=campaign)  # Another assessment not linked to the institution

        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(self.URL)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                ".s-section",
                replace_in_attr=[
                    ("value", f"{campaign.pk}", "[PK of Campaign]"),
                    ("value", f"{membership.institution.pk}", "[PK of Institution]"),
                ],
            )
        ) == snapshot(name="assessments complex list")
        assertQuerySetEqual(
            response.context["assessments"],
            [
                reviewed_assessment,
                submitted_assessment,
                new_assessment,
                later_final_reviewed_assessment,
                final_reviewed_assessment,
            ],
        )

    @freeze_time("2025-05-21 12:00", tick=True)
    def test_potential_allowance_amount_coherence(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ,
            institution__name="Un DREETS GEIQ",
        )
        client.force_login(membership.user)
        campaign = AssessmentCampaignFactory()
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        assessment = AssessmentFactory(
            id=uuid.UUID("11111111-0d2c-4f29-ba5b-a27ffb8ecc84"),
            campaign=campaign,
            created_by__first_name="Marie",
            created_by__last_name="Curie",
            label_antennas=[{"id": 1, "name": "Un Superbe GEIQ", "post_code": "12345"}],
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
            assessment=assessment, institution=membership.institution, with_convention=True
        )
        # Contracts taken into account for potential_allowance_amount
        contract = EmployeeContractFactory(
            allowance_requested=True,
            allowance_granted=True,
            employee__assessment=assessment,
            employee__allowance_amount=1400,
        )
        EmployeeContractFactory(allowance_requested=True, allowance_granted=True, employee=contract.employee)
        EmployeeContractFactory(
            allowance_requested=True,
            allowance_granted=True,
            employee__assessment=assessment,
            employee__allowance_amount=814,
        )
        # Contracts not taken into account for potential_allowance_amount
        EmployeeContractFactory(allowance_requested=False, allowance_granted=False, employee=contract.employee)
        EmployeeContractFactory(
            allowance_requested=False,
            allowance_granted=False,
            employee__assessment=assessment,
            employee__allowance_amount=814,
        )
        EmployeeContractFactory(
            allowance_requested=True,
            allowance_granted=False,
            employee__assessment=assessment,
            employee__allowance_amount=1400,
        )

        response = client.get(self.URL)
        context_potential_amout = response.context["assessments"].get().potential_allowance_amount
        expected_potential_amout = get_allowance_stats_for_institution(assessment, for_assessment_details=False)[
            "potential_allowance_amount"
        ]
        assert context_potential_amout == 3614
        assert context_potential_amout == expected_potential_amout

    @freeze_time("2025-05-21 12:00", tick=True)
    def test_campaigns_filter(self, client, snapshot):
        membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ,
            institution__name="Un DREETS GEIQ",
        )
        campaign_2023 = AssessmentCampaignFactory(year=2023)
        campaign_2024 = AssessmentCampaignFactory(year=2024)

        assessment_2023 = AssessmentFactory(campaign=campaign_2023)
        AssessmentInstitutionLink.objects.create(assessment=assessment_2023, institution=membership.institution)

        assessment_2024 = AssessmentFactory(campaign=campaign_2024)
        AssessmentInstitutionLink.objects.create(assessment=assessment_2024, institution=membership.institution)

        another_assessment_2024 = AssessmentFactory(campaign=campaign_2024)
        AssessmentInstitutionLink.objects.create(
            assessment=another_assessment_2024, institution=membership.institution
        )

        # Another unlinked assessment that should not be seen anywhere
        AssessmentFactory(campaign=campaign_2024)

        client.force_login(membership.user)
        # No filter
        response = client.get(self.URL)
        assertQuerySetEqual(
            response.context["assessments"], [assessment_2023, assessment_2024, another_assessment_2024], ordered=False
        )

        # Filter on 2024
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(self.URL, {"campaigns": campaign_2024.pk})
        assertQuerySetEqual(response.context["assessments"], [assessment_2024, another_assessment_2024], ordered=False)

        # Filter on 2023
        response = client.get(self.URL, {"campaigns": campaign_2023.pk})
        assertQuerySetEqual(response.context["assessments"], [assessment_2023])

        # Filter on both 2023 and 2024
        response = client.get(self.URL, {"campaigns": [campaign_2023.pk, campaign_2024.pk]})
        assertQuerySetEqual(
            response.context["assessments"], [assessment_2023, assessment_2024, another_assessment_2024], ordered=False
        )

        # Invalid data: do nothing, ie. do not filter
        response = client.get(self.URL, {"campaigns": "invalid"})
        assertQuerySetEqual(
            response.context["assessments"], [assessment_2023, assessment_2024, another_assessment_2024], ordered=False
        )

    @freeze_time("2025-05-21 12:00", tick=True)
    def test_institutions_filter(self, client, snapshot):
        membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ,
            institution__name="Un DREETS GEIQ",
        )
        ddets = InstitutionFactory(kind=InstitutionKind.DDETS_GEIQ, name="Une DDETS GEIQ")
        campaign = AssessmentCampaignFactory()
        assessment_dreets_ddets = AssessmentFactory(campaign=campaign)
        # User selected both institutions in the creation form
        AssessmentInstitutionLink.objects.create(
            assessment=assessment_dreets_ddets, institution=membership.institution, with_convention=True
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment_dreets_ddets, institution=ddets, with_convention=True
        )

        assessment_ddets = AssessmentFactory(campaign=campaign)
        # User selected only the DDETS in the creation form
        AssessmentInstitutionLink.objects.create(assessment=assessment_ddets, institution=membership.institution)
        AssessmentInstitutionLink.objects.create(assessment=assessment_ddets, institution=ddets, with_convention=True)

        # Another unlinked assessment that should not be seen anywhere
        AssessmentFactory(campaign=campaign)

        client.force_login(membership.user)
        # No filter
        response = client.get(self.URL)
        assertQuerySetEqual(
            response.context["assessments"], [assessment_dreets_ddets, assessment_ddets], ordered=False
        )

        # Filter on the DDETS
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(self.URL, {"institutions": ddets.pk})
        assertQuerySetEqual(
            response.context["assessments"], [assessment_dreets_ddets, assessment_ddets], ordered=False
        )

        # Filter on the DREETS
        response = client.get(self.URL, {"institutions": membership.institution.pk})
        assertQuerySetEqual(response.context["assessments"], [assessment_dreets_ddets])
        # Filter on both the DDETS and the DREETS
        response = client.get(self.URL, {"institutions": [membership.institution.pk, ddets.pk]})
        assertQuerySetEqual(
            response.context["assessments"], [assessment_dreets_ddets, assessment_ddets], ordered=False
        )

        # Invalid data: do nothing, ie. do not filter
        response = client.get(self.URL, {"institutions": "invalid"})
        assertQuerySetEqual(
            response.context["assessments"], [assessment_dreets_ddets, assessment_ddets], ordered=False
        )

    @freeze_time("2025-05-21 12:00", tick=True)
    def test_states_filter(self, client, snapshot):
        membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ,
            institution__name="Un DREETS GEIQ",
        )
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        campaign = AssessmentCampaignFactory()

        assessment_new = AssessmentFactory(campaign=campaign)
        AssessmentInstitutionLink.objects.create(assessment=assessment_new, institution=membership.institution)

        assessment_submitted = AssessmentFactory(
            campaign=campaign,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=80_000,
        )
        AssessmentInstitutionLink.objects.create(assessment=assessment_submitted, institution=membership.institution)

        assessment_reviewed = AssessmentFactory(
            campaign=campaign,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=80_000,
            review_comment="Bravo !",
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_by=membership.user,
            reviewed_by_institution=membership.institution,
        )
        AssessmentInstitutionLink.objects.create(assessment=assessment_reviewed, institution=membership.institution)

        assessment_final_reviewed = AssessmentFactory(
            campaign=campaign,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=80_000,
            review_comment="Bravo !",
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_by=membership.user,
            reviewed_by_institution=membership.institution,
            final_reviewed_at=timezone.now() + datetime.timedelta(hours=6),
            final_reviewed_by=membership.user,
            final_reviewed_by_institution=membership.institution,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment_final_reviewed, institution=membership.institution
        )

        # Another unlinked assessment that should not be seen anywhere
        AssessmentFactory(campaign=campaign)

        client.force_login(membership.user)
        # No filter
        response = client.get(self.URL)
        assertQuerySetEqual(
            response.context["assessments"],
            [assessment_new, assessment_submitted, assessment_reviewed, assessment_final_reviewed],
            ordered=False,
        )

        # Filter on NEW
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(self.URL, {"states": AssessmentState.NEW.value})
        assertQuerySetEqual(response.context["assessments"], [assessment_new], ordered=False)

        # Filter on SUBMITTED
        response = client.get(self.URL, {"states": AssessmentState.SUBMITTED.value})
        assertQuerySetEqual(response.context["assessments"], [assessment_submitted], ordered=False)

        # Filter on both REVIEWED and FINAL_REVIEWED
        response = client.get(
            self.URL, {"states": [AssessmentState.REVIEWED.value, AssessmentState.FINAL_REVIEWED.value]}
        )
        assertQuerySetEqual(
            response.context["assessments"], [assessment_reviewed, assessment_final_reviewed], ordered=False
        )

        # Invalid data: do nothing, ie. do not filter
        response = client.get(self.URL, {"states": "invalid"})
        assertQuerySetEqual(
            response.context["assessments"],
            [assessment_new, assessment_submitted, assessment_reviewed, assessment_final_reviewed],
            ordered=False,
        )

    def test_mishmash(self, client, snapshot):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ,
            institution__name="Un DREETS GEIQ",
        )
        ddets = InstitutionFactory(kind=InstitutionKind.DDETS_GEIQ, name="Une DDETS GEIQ")
        campaign_2023 = AssessmentCampaignFactory(year=2023)
        campaign_2024 = AssessmentCampaignFactory(year=2024)

        assessment_2023_ddets = AssessmentFactory(
            campaign=campaign_2023,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
        )
        AssessmentInstitutionLink.objects.create(assessment=assessment_2023_ddets, institution=membership.institution)
        AssessmentInstitutionLink.objects.create(
            assessment=assessment_2023_ddets, institution=ddets, with_convention=True
        )

        assessment_2024_ddets_dreets = AssessmentFactory(
            campaign=campaign_2024,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            review_comment="Bravo !",
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=100_000,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment_2024_ddets_dreets, institution=membership.institution, with_convention=True
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment_2024_ddets_dreets, institution=ddets, with_convention=True
        )

        client.force_login(membership.user)

        with assertSnapshotQueries(snapshot(name="SQL queries")):
            # Select the DDETS only, the 2023 campaign and the SUBMITTED state
            response = client.get(
                self.URL,
                {"institutions": ddets.pk, "campaigns": campaign_2023.pk, "states": AssessmentState.SUBMITTED.value},
            )
        assertQuerySetEqual(response.context["assessments"], [assessment_2023_ddets], ordered=False)

        # One invalid data: all the filters are sadly ignored
        response = client.get(
            self.URL, {"institutions": ddets.pk, "campaigns": "invalid", "states": AssessmentState.SUBMITTED.value}
        )
        assertQuerySetEqual(
            response.context["assessments"], [assessment_2023_ddets, assessment_2024_ddets_dreets], ordered=False
        )

    @freeze_time("2025-05-21 12:00", tick=True)
    def test_filters_htmx(self, client):
        membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ,
            institution__name="Un DREETS GEIQ",
        )
        ddets = InstitutionFactory(kind=InstitutionKind.DDETS_GEIQ, name="Une DDETS GEIQ")
        campaign = AssessmentCampaignFactory()
        assessment_dreets_ddets = AssessmentFactory(campaign=campaign)
        # User selected both institutions in the creation form
        AssessmentInstitutionLink.objects.create(
            assessment=assessment_dreets_ddets, institution=membership.institution, with_convention=True
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment_dreets_ddets, institution=ddets, with_convention=True
        )

        assessment_ddets = AssessmentFactory(campaign=campaign)
        AssessmentInstitutionLink.objects.create(assessment=assessment_ddets, institution=membership.institution)
        AssessmentInstitutionLink.objects.create(assessment=assessment_ddets, institution=ddets, with_convention=True)

        client.force_login(membership.user)
        # No filter
        response = client.get(self.URL)
        page = parse_response_to_soup(response, selector="#main")

        # institutions filter
        ddets_checkbox = page.find("input", attrs={"type": "checkbox", "name": "institutions", "value": str(ddets.pk)})
        ddets_checkbox["checked"] = ""  # simulate select checkbox
        response = client.get(self.URL, {"institutions": ddets.pk}, headers={"HX-Request": "true"})
        update_page_with_htmx(page, f"form[hx-get='{self.URL}']", response)
        response = client.get(self.URL, {"institutions": ddets.pk})
        fresh_page = parse_response_to_soup(response, selector="#main")
        assertSoupEqual(page, fresh_page)
        ddets_checkbox["checked"] = ""  # simulate unselect checkbox
        response = client.get(self.URL, headers={"HX-Request": "true"})
        update_page_with_htmx(page, f"form[hx-get='{self.URL}']", response)
        response = client.get(self.URL)
        fresh_page = parse_response_to_soup(response, selector="#main")


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
            (PrescriberFactory(membership=True), 403),
            (EmployerFactory(membership=True), 403),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    @pytest.mark.parametrize(
        "institution_kind",
        set(INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_LIST).difference(set(INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_DETAILS)),
    )
    def test_unauthorized_access_by_national_geiq_institution(self, client, institution_kind):
        user = InstitutionMembershipFactory(institution__kind=institution_kind).user
        assessment = AssessmentFactory()
        client.force_login(user)
        url = reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "institution_kind",
        INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_DETAILS,
    )
    def test_unauthorized_access_by_unrelated_institution(self, client, institution_kind):
        user = InstitutionMembershipFactory(institution__kind=institution_kind).user
        assessment = AssessmentFactory()
        client.force_login(user)
        url = reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "institution_kind",
        INSTITUTION_KINDS_CAN_VIEW_ASSESSMENT_DETAILS,
    )
    def test_authorized_access_by_related_institution(self, client, institution_kind):
        membership = InstitutionMembershipFactory(institution__kind=institution_kind)
        assessment = AssessmentFactory()
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=membership.institution,
        )
        client.force_login(membership.user)
        url = reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assert response.status_code == 200

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
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "29000"}],
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
        with freeze_time(timezone.now() + datetime.timedelta(hours=3)):
            assessment.submit(user=geiq_membership.user)
        response = client.get(reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}))
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="assessment details title after submission"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details section after submission"
        )
        with freeze_time(timezone.now() + datetime.timedelta(hours=4)):
            assessment.ask_for_geiq_fix(
                user=ddets_membership.user, institution=ddets_membership.institution, comment="À revoir"
            )
        response = client.get(reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}))
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="assessment details title after geiq fix request"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details section after geiq fix request"
        )
        with freeze_time(timezone.now() + datetime.timedelta(hours=4.5)):
            assessment.submit(user=geiq_membership.user)

        assessment.grants_selection_validated_at = timezone.now() + datetime.timedelta(hours=5)
        assessment.save()
        response = client.get(reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}))
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="assessment details title"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details section with grants selection validated"
        )

        assessment.decision_validated_at = timezone.now() + datetime.timedelta(hours=6)
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

        assessment.review_comment = "Bravo !"
        with freeze_time(timezone.now() + datetime.timedelta(hours=7)):
            assessment.review(user=ddets_membership.user, institution=ddets_membership.institution)
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
        with freeze_time(timezone.now() + datetime.timedelta(hours=8)):
            assessment.final_review(user=dreets_membership.user, institution=dreets_membership.institution)
        response = client.get(reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}))
        assert pretty_indented(parse_response_to_soup(response, ".s-title-02")) == snapshot(
            name="final reviewed assessment details title"
        )
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessment details section with final review"
        )

    def test_ddets_review_and_dreets_final_review(self, client, mailoutbox, snapshot):
        ddets_membership = InstitutionMembershipFactory(
            institution__name="DDETS 29",
            institution__kind=InstitutionKind.DDETS_GEIQ,
            user__first_name="Julia",
            user__last_name="Martin",
        )
        other_ddets_membership = InstitutionMembershipFactory(
            institution=ddets_membership.institution,
        )
        # Inactive memberships
        InstitutionMembershipFactory(
            institution=ddets_membership.institution,
            is_active=False,
        )
        InstitutionMembershipFactory(
            institution=ddets_membership.institution,
            user__is_active=False,
        )
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
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "29000"}],
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
            transition = AssessmentTransitionLog.objects.filter(assessment=assessment).get()
            assert transition.assessment.reviewed_at == timezone.now()
            assert transition.assessment.reviewed_by == ddets_membership.user
            assert transition.assessment.reviewed_by_institution == ddets_membership.institution
            assert transition.transition == AssessmentTransition.REVIEW
            assert transition.user == ddets_membership.user
            assert transition.institution == ddets_membership.institution
            assert transition.timestamp == transition.assessment.reviewed_at

            assert len(mailoutbox) == 1
            email = mailoutbox[0]
            assert (
                f"[TEST] Validation du bilan d’exécution de la structure {assessment.label_geiq_name}" == email.subject
            )
            assert email.to[0] == dreets_membership.user.email
            assert email.body == snapshot(name="body of mail sent to DREETS members")
            mailoutbox.clear()

        with freeze_time(timezone.now() + datetime.timedelta(hours=7)):
            client.force_login(dreets_membership.user)
            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "review"},
            )
            assertRedirects(
                response, reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
            )
            transition = AssessmentTransitionLog.objects.filter(assessment=assessment).first()
            assert transition.assessment.final_reviewed_at == timezone.now()
            assert transition.assessment.final_reviewed_by == dreets_membership.user
            assert transition.assessment.final_reviewed_by_institution == dreets_membership.institution
            assert transition.transition == AssessmentTransition.FINAL_REVIEW
            assert transition.user == dreets_membership.user
            assert transition.institution == dreets_membership.institution
            assert transition.timestamp == transition.assessment.final_reviewed_at
            assert len(mailoutbox) == 1
            email = mailoutbox[0]
            assert (
                f"[TEST] Résultat du contrôle effectué sur votre bilan d’exécution {assessment.label_geiq_name}"
                == email.subject
            )
            assert email.to[0] == geiq_membership.user.email
            assert email.body == snapshot(name="body of mail sent to GEIQ members")
            assert email.cc == sorted([ddets_membership.user.email, other_ddets_membership.user.email])

    def test_ddets_review_dreets_ask_for_institution_fix_and_dreets_review(self, client, snapshot, mailoutbox):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        dreets_membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ, institution__name="DREETS Bretagne"
        )
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
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "29000"}],
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
            transition = AssessmentTransitionLog.objects.filter(assessment=assessment).get()
            assert transition.assessment.reviewed_at == timezone.now()
            assert transition.assessment.reviewed_by == ddets_membership.user
            assert transition.assessment.reviewed_by_institution == ddets_membership.institution
            assert transition.transition == AssessmentTransition.REVIEW
            assert transition.user == ddets_membership.user
            assert transition.institution == ddets_membership.institution
            assert transition.timestamp == transition.assessment.reviewed_at

        # DREETS ask for institution fix
        with freeze_time(timezone.now() + datetime.timedelta(hours=6)):
            client.force_login(dreets_membership.user)
            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "ask_for_institution_fix"},  # no comment
            )
            assertContains(response, "Ce champ est obligatoire")
            assessment.refresh_from_db()
            assert assessment.reviewed_at is not None
            assert not AssessmentTransitionLog.objects.filter(
                transition=AssessmentTransition.ASK_FOR_INSTITUTION_FIX
            ).exists()

            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "ask_for_institution_fix", "comment": " "},  # empty comment (space will be trimmed)
            )
            assertContains(response, "Ce champ est obligatoire")
            assessment.refresh_from_db()
            assert assessment.reviewed_at is not None
            assert not AssessmentTransitionLog.objects.filter(
                transition=AssessmentTransition.ASK_FOR_INSTITUTION_FIX
            ).exists()

            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "ask_for_institution_fix", "comment": "Revue à corriger."},
            )
            assertRedirects(
                response, reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
            )
            transition = AssessmentTransitionLog.objects.filter(
                assessment=assessment, transition=AssessmentTransition.ASK_FOR_INSTITUTION_FIX
            ).get()
            assert transition.assessment.reviewed_at is None
            assert transition.assessment.reviewed_by is None
            assert transition.assessment.reviewed_by_institution is None
            assert transition.transition == AssessmentTransition.ASK_FOR_INSTITUTION_FIX
            assert transition.user == dreets_membership.user
            assert transition.institution == dreets_membership.institution
            assert len(mailoutbox) == 2  # (review by DDETS, ask_for_institution_fix by DREETS)
            email = mailoutbox[1]
            assert f"[TEST] Bilan d’exécution à corriger - {assessment.label_geiq_name}" == email.subject
            assert email.to[0] == ddets_membership.user.email
            assert email.body == snapshot(name="body of mail sent to DDETS user")
            assert email.cc == []

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
            transition_review = AssessmentTransitionLog.objects.filter(
                assessment=assessment, transition=AssessmentTransition.REVIEW
            ).get()
            assert transition_review.assessment.reviewed_at == timezone.now()
            assert transition_review.assessment.reviewed_by == dreets_membership.user
            assert transition_review.assessment.reviewed_by_institution == dreets_membership.institution
            assert (
                transition_review.assessment.final_reviewed_at == transition_review.assessment.reviewed_at
            )  # useless assert because of freeze_time
            assert transition_review.assessment.final_reviewed_by == dreets_membership.user
            assert transition_review.assessment.final_reviewed_by_institution == dreets_membership.institution
            assert transition_review.user == ddets_membership.user  # The DRRETS directly final_reviewed
            assert transition_review.institution == ddets_membership.institution
            transition_final_review = AssessmentTransitionLog.objects.filter(
                assessment=assessment, transition=AssessmentTransition.FINAL_REVIEW
            ).get()
            assert transition_final_review.user == dreets_membership.user
            assert transition_final_review.institution == dreets_membership.institution

    def test_ddets_ask_for_geiq_fix(self, client, snapshot, mailoutbox):
        ddets_membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DDETS_GEIQ, institution__name="DDETS 29"
        )
        other_ddets_membership = InstitutionMembershipFactory(institution=ddets_membership.institution)
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
            company__for_snapshot=True,
            user__first_name="Paul",
            user__last_name="Martin",
            user__email="paul.martin@example.com",
        )
        is_reviewed = random.choice([True, False])  # a DDETS can request for fix even if an assessment is reviewed
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2024,
            companies=[geiq_membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            created_by__email="jean.dupont@example.com",
            label_geiq_name="Un Joli GEIQ",
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "29000"}],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=80_000,
            review_comment="Bravo !",
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=(timezone.now() + datetime.timedelta(hours=5)) if is_reviewed else None,
            reviewed_by=ddets_membership.user if is_reviewed else None,
            reviewed_by_institution=ddets_membership.institution if is_reviewed else None,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )

        with freeze_time(timezone.now() + datetime.timedelta(hours=6)):
            client.force_login(ddets_membership.user)
            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "ask_for_geiq_fix"},  # no comment
            )
            assertContains(response, "Ce champ est obligatoire.")
            assessment.refresh_from_db()
            assert assessment.submitted_at is not None
            assert AssessmentTransitionLog.objects.count() == 0

            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "ask_for_geiq_fix", "comment": " "},  # empty comment (space will be trimmed)
            )
            assertContains(response, "Ce champ est obligatoire.")
            assessment.refresh_from_db()
            assert assessment.submitted_at is not None
            assert AssessmentTransitionLog.objects.count() == 0

            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "ask_for_geiq_fix", "comment": "Revoyez votre copie."},
            )
            assertRedirects(
                response, reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
            )
            assessment.refresh_from_db()
            assert assessment.submitted_at is None
            assert assessment.submitted_by is None
            assert assessment.state == AssessmentState.NEW
            transition = AssessmentTransitionLog.objects.get()
            assert transition.user == ddets_membership.user
            assert transition.institution == ddets_membership.institution
            assert transition.transition == AssessmentTransition.ASK_FOR_GEIQ_FIX
            assert transition.comment == "Revoyez votre copie."
            assert len(mailoutbox) == 1
            email = mailoutbox[0]
            assert "[TEST] Demande de correction de votre bilan d’exécution GEIQ" == email.subject
            assert email.to[0] == geiq_membership.user.email
            assert email.body == snapshot(name="body of mail sent to GEIQ members")
            assert email.cc == sorted([ddets_membership.user.email, other_ddets_membership.user.email])

    def test_dreets_ask_for_geiq_fix(self, client, snapshot, mailoutbox):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        dreets_membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ, institution__name="DREETS 29"
        )
        other_dreets_membership = InstitutionMembershipFactory(institution=dreets_membership.institution)
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
            company__for_snapshot=True,
            user__first_name="Paul",
            user__last_name="Martin",
            user__email="paul.martin@example.com",
        )
        is_reviewed = random.choice([True, False])  # a DREETS can request for fix even if an assessment is reviewed
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2024,
            companies=[geiq_membership.company],
            created_by__first_name="Jean",
            created_by__last_name="Dupont",
            created_by__email="jean.dupont@example.com",
            label_geiq_name="Un Joli GEIQ",
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "29000"}],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(hours=4),
            convention_amount=100_000,
            advance_amount=50_000,
            granted_amount=80_000,
            review_comment="Bravo !",
            decision_validated_at=timezone.now() + datetime.timedelta(hours=5),
            reviewed_at=(timezone.now() + datetime.timedelta(hours=5)) if is_reviewed else None,
            reviewed_by=ddets_membership.user if is_reviewed else None,
            reviewed_by_institution=ddets_membership.institution if is_reviewed else None,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=dreets_membership.institution,
            with_convention=True,
        )

        with freeze_time(timezone.now() + datetime.timedelta(hours=6)):
            client.force_login(dreets_membership.user)
            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "ask_for_geiq_fix"},  # no comment
            )
            assertContains(response, "Ce champ est obligatoire.")
            assessment.refresh_from_db()
            assert assessment.submitted_at is not None
            assert AssessmentTransitionLog.objects.count() == 0

            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "ask_for_geiq_fix", "comment": " "},  # empty comment (space will be trimmed)
            )
            assertContains(response, "Ce champ est obligatoire.")
            assessment.refresh_from_db()
            assert assessment.submitted_at is not None
            assert AssessmentTransitionLog.objects.count() == 0

            response = client.post(
                reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
                data={"action": "ask_for_geiq_fix", "comment": "Revoyez votre copie."},
            )
            assertRedirects(
                response, reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk})
            )
            assessment.refresh_from_db()
            assert assessment.submitted_at is None
            assert assessment.submitted_by is None
            assert assessment.state == AssessmentState.NEW
            transition = AssessmentTransitionLog.objects.get()
            assert transition.user == dreets_membership.user
            assert transition.institution == dreets_membership.institution
            assert transition.transition == AssessmentTransition.ASK_FOR_GEIQ_FIX
            assert transition.comment == "Revoyez votre copie."
            assert len(mailoutbox) == 1
            email = mailoutbox[0]
            assert "[TEST] Demande de correction de votre bilan d’exécution GEIQ" == email.subject
            assert email.to[0] == geiq_membership.user.email
            assert email.body == snapshot(name="body of mail sent to GEIQ members")
            assert email.cc == sorted(
                [dreets_membership.user.email, other_dreets_membership.user.email, ddets_membership.user.email]
            )


class TestAssessmentContractsListForInstitutionView:
    @pytest.fixture
    def setup_data(self):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
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
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "12345"}],
            with_submission_requirements=True,
        )
        assessment.submitted_at = timezone.now()
        assessment.submitted_by = geiq_membership.user
        assessment.state = AssessmentState.SUBMITTED
        assessment.save()
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )

        contract_without_eligibility = EmployeeContractFactory(
            id=uuid.UUID("11111111-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__last_name="Dupont",
            employee__first_name="Jean",
            employee__allowance_amount=0,
            start_at=datetime.date(2024, 1, 1),
            end_at=datetime.date(2024, 4, 30),
            planned_end_at=datetime.date(2024, 5, 31),
            allowance_requested=True,
            allowance_granted=False,
        )
        contract_with_eligibility = EmployeeContractFactory(
            id=uuid.UUID("22222222-5555-5555-5555-555555555555"),
            employee__assessment=assessment,
            employee__last_name="Richard",
            employee__first_name="Jean",
            employee__allowance_amount=0,
            start_at=datetime.date(2024, 2, 1),
            end_at=datetime.date(2024, 3, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=True,
            allowance_granted=True,
        )

        return {
            "ddets_membership": ddets_membership,
            "assessment": assessment,
            "contract_with_eligibility": contract_with_eligibility,
            "contract_without_eligibility": contract_without_eligibility,
        }

    @pytest.mark.parametrize(
        "query_params, expected_in, expected_not_in",
        [
            ({"allowance_eligibility_on": "on"}, ["contract_with_eligibility"], ["contract_without_eligibility"]),
            ({"allowance_eligibility_off": "on"}, ["contract_without_eligibility"], ["contract_with_eligibility"]),
            (
                {"allowance_eligibility_on": "on", "allowance_eligibility_off": "on"},
                ["contract_with_eligibility", "contract_without_eligibility"],
                [],
            ),
        ],
    )
    def test_contract_list_filter_by_allowance_eligibility(
        self, client, setup_data, query_params, expected_in, expected_not_in
    ):
        url = reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": setup_data["assessment"].pk})
        client.force_login(setup_data["ddets_membership"].user)
        response = client.get(url, query_params)

        assert response.status_code == 200
        contracts_in_page = response.context["contracts_page"].object_list
        for key in expected_in:
            assert setup_data[key] in contracts_in_page
        for key in expected_not_in:
            assert setup_data[key] not in contracts_in_page


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
        # We also make accessible a printable version of the assessment after it has been finally reviewed (i.e. by a
        # DREETS). Here it must not be accessible either.
        url = reverse("geiq_assessments_views:assessment_print", kwargs={"pk": assessment.pk})
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
            (PrescriberFactory(membership=True), 403),
            (EmployerFactory(membership=True), 403),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status
        # Same checks for the printable version of the assessment.
        url = reverse("geiq_assessments_views:assessment_print", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(membership=True), 403),
            (EmployerFactory(membership=True), 403),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    @freeze_time("2025-05-21 12:00")
    def test_review_assessment(self, client, snapshot):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ, user__first_name="Paul", user__last_name="Martin"
        )
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            with_main_geiq=True,
            label_geiq_post_code="29000",
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "29000"}],
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

        # The printable version must not be accessible if the assessment has not been finally reviewed.
        url = reverse("geiq_assessments_views:assessment_print", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assert response.status_code == 404

        assessment.grants_selection_validated_at = timezone.now() + datetime.timedelta(hours=4)
        assessment.save()

        url = reverse("geiq_assessments_views:assessment_review", kwargs={"pk": assessment.pk})
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

        # The printable version must not be accessible at this stage as the assessment has not been finally reviewed.
        url = reverse("geiq_assessments_views:assessment_print", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assert response.status_code == 404

    @freeze_time("2025-05-21 12:00")
    def test_review_already_reviewed_assessment(self, client, snapshot):
        ddets_membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DDETS_GEIQ,
            institution__name="Un DDETS GEIQ",
            user__first_name="Jean",
            user__last_name="Dupont",
        )
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
            user__first_name="Paul",
            user__last_name="Martin",
        )
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(hours=3),
            submitted_by=geiq_membership.user,
            with_main_geiq=True,
            label_geiq_post_code="29000",
            label_antennas=[{"id": 1234, "name": "Une antenne", "post_code": "29000"}],
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

        # Check snapshot with a final review
        dreets_membership = InstitutionMembershipFactory(
            institution__kind=InstitutionKind.DREETS_GEIQ,
            institution__name="Un DREETS GEIQ",
            user__first_name="Julia",
            user__last_name="Thomas",
        )
        with freeze_time(timezone.now() + datetime.timedelta(hours=7)):
            assessment.final_review(user=dreets_membership.user, institution=dreets_membership.institution)
        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="disabled assessments review form with final review"
        )

        # Check also the printable version of the finally reviewed assessment.
        # Shall we check calculations as well?
        url = reverse("geiq_assessments_views:assessment_print", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assert response.status_code == 200
        assertContains(response, "Imprimer cette décision")
        assert pretty_indented(parse_response_to_soup(response, "main")) == snapshot(
            name="print assessment with final review"
        )
