import datetime
import random
import uuid

import pytest
from django.contrib import messages
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.companies.enums import CompanyKind
from itou.geiq_assessments.enums import (
    AllowanceJustificationReason,
    AllowanceRefusalReason,
    AssessmentContractDetailsTab,
    InstitutionAction,
)
from itou.geiq_assessments.models import AssessmentInstitutionLink
from itou.institutions.enums import InstitutionKind
from itou.users.enums import Title
from tests.companies.factories import CompanyMembershipFactory
from tests.geiq_assessments.factories import AssessmentFactory, EmployeeContractFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import (
    PAGINATION_PAGE_ONE_MARKUP,
    get_rows_from_streaming_response,
    parse_response_to_soup,
    pretty_indented,
)


class TestAssessmentContractsListAndToggle:
    EXPORT_BUTTON_LABELS_FOR_INSTITUTION = [
        "Exporter tous les contrats soumis par le GEIQ",
        "Exporter tous les contrats",
    ]

    def test_anonymous_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    def test_unauthorized_access(self, client):
        assessment = AssessmentFactory()
        url = reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(membership=True), 403),
            (EmployerFactory(membership=True, membership__company__not_geiq_kind=True), 403),
            (EmployerFactory(membership=True, membership__company__kind=CompanyKind.GEIQ), 404),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_access_as_geiq(self, client, snapshot):
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
            contracts_selection_validated_at=None,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contracts_list_url = reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        client.force_login(geiq_membership.user)
        response = client.get(contracts_list_url)
        for label in self.EXPORT_BUTTON_LABELS_FOR_INSTITUTION:
            assertNotContains(response, label)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments empty contracts list"
        )
        EmployeeContractFactory(
            id=uuid.UUID("11111111-4444-4444-4444-444444444444"),
            employee__id=uuid.UUID("11111111-eeee-4444-8888-111111111111"),
            employee__assessment=assessment,
            employee__last_name="Dupont",
            employee__first_name="Jean",
            employee__allowance_amount=0,
            start_at=datetime.date(2024, 1, 1),
            end_at=datetime.date(2024, 4, 30),
            planned_end_at=datetime.date(2024, 5, 31),
            allowance_requested=True,
        )
        short_contract = EmployeeContractFactory(
            id=uuid.UUID("22222222-4444-4444-4444-444444444444"),
            employee__id=uuid.UUID("22222222-eeee-4444-8888-222222222222"),
            employee__assessment=assessment,
            employee__last_name="Martin",
            employee__first_name="Cécile",
            employee__allowance_amount=814,
            start_at=datetime.date(2024, 2, 1),
            end_at=datetime.date(2024, 3, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=True,
        )
        EmployeeContractFactory(
            id=uuid.UUID("33333333-4444-4444-4444-444444444444"),
            employee__id=uuid.UUID("33333333-eeee-4444-8888-333333333333"),
            employee__assessment=assessment,
            employee__last_name="Dupond",
            employee__first_name="Jean-Pierre",
            employee__allowance_amount=1_400,
            employee__allowance_granted_previous_year=True,  # To test icon in list
            start_at=datetime.date(2024, 4, 1),
            end_at=datetime.date(2024, 6, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=False,
        )
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(contracts_list_url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments contracts list with request to justify"
        )
        # One contract is to justify, user cannot validate
        response = client.post(contracts_list_url, data={"action": "validate"})
        assert response.status_code == 403
        assessment.refresh_from_db()
        assert assessment.contracts_selection_validated_at is None

        # Fill request justification and try again
        short_contract.allowance_request_justification_reason = AllowanceJustificationReason.SUPPORT_CONSIDERATION
        short_contract.allowance_request_justification_details = "Détails."
        short_contract.save()
        response = client.post(contracts_list_url, data={"action": "validate"})
        assertRedirects(
            response,
            reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}),
            fetch_redirect_response=False,
        )
        assessment.refresh_from_db()
        assert assessment.contracts_selection_validated_at is not None

        response = client.get(contracts_list_url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments contracts list readonly"
        )
        response = client.post(contracts_list_url, data={"action": "invalidate"})
        assertRedirects(response, contracts_list_url, fetch_redirect_response=False)
        assessment.refresh_from_db()
        assert assessment.contracts_selection_validated_at is None
        response = client.get(contracts_list_url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments contracts list with justified request"
        )

    def test_allowance_granted_previous_year(self, client):
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
            contracts_selection_validated_at=None,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contract = EmployeeContractFactory(
            id=uuid.UUID("11111111-4444-4444-4444-444444444444"),
            employee__id=uuid.UUID("11111111-eeee-4444-8888-111111111111"),
            employee__assessment=assessment,
            employee__last_name="Dupont",
            employee__first_name="Jean",
            employee__allowance_amount=0,
            start_at=datetime.date(2024, 1, 1),
            end_at=datetime.date(2024, 4, 30),
            planned_end_at=datetime.date(2024, 5, 31),
            allowance_requested=True,
        )
        contracts_list_url = reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        client.force_login(geiq_membership.user)

        SINGULAR_PREVIOUS_YEAR_WARNING = (
            "Un contrat concerne un salarié déjà présent dans le bilan précédent. "
            "Nous vous invitons à vérifier la liste."
        )
        PLURAL_PREVIOUS_YEAR_WARNING = (
            "Des contrats concernent des salariés déjà présents dans le bilan précédent. "
            "Nous vous invitons à vérifier la liste."
        )

        response = client.get(contracts_list_url)
        assertNotContains(response, SINGULAR_PREVIOUS_YEAR_WARNING)
        assertNotContains(response, PLURAL_PREVIOUS_YEAR_WARNING)

        contract.employee.allowance_granted_previous_year = True
        contract.employee.save()
        response = client.get(contracts_list_url)
        assertContains(response, SINGULAR_PREVIOUS_YEAR_WARNING)
        assertNotContains(response, PLURAL_PREVIOUS_YEAR_WARNING)

        EmployeeContractFactory(
            id=uuid.UUID("22222222-4444-4444-4444-444444444444"),
            employee__id=uuid.UUID("22222222-eeee-4444-8888-222222222222"),
            employee__assessment=assessment,
            employee__last_name="Martin",
            employee__first_name="Cécile",
            employee__allowance_amount=814,
            employee__allowance_granted_previous_year=True,
            start_at=datetime.date(2024, 2, 1),
            end_at=datetime.date(2024, 3, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=False,
        )
        response = client.get(contracts_list_url)
        assertNotContains(response, SINGULAR_PREVIOUS_YEAR_WARNING)
        assertContains(response, PLURAL_PREVIOUS_YEAR_WARNING)

    @override_settings(PAGE_SIZE_LARGE=1)
    def test_pagination(self, client):
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
        )
        assessment = AssessmentFactory(
            campaign__year=2024,
            companies=[geiq_membership.company],
            with_submission_requirements=True,
            contracts_selection_validated_at=None,
        )
        EmployeeContractFactory.create_batch(2, employee__assessment=assessment)

        client.force_login(geiq_membership.user)
        contracts_list_url = reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        response = client.get(contracts_list_url)
        assertContains(response, PAGINATION_PAGE_ONE_MARKUP % (contracts_list_url + "?page=1"), html=True)

    def test_access_as_institution(self, client, snapshot):
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
        assessment.submit(user=geiq_membership.user)
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contracts_list_url = reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        client.force_login(ddets_membership.user)
        response = client.get(contracts_list_url)
        for label in self.EXPORT_BUTTON_LABELS_FOR_INSTITUTION:
            assertContains(response, label)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments empty contracts list"
        )
        EmployeeContractFactory(
            id=uuid.UUID("11111111-4444-4444-4444-444444444444"),
            employee__id=uuid.UUID("11111111-eeee-4444-8888-111111111111"),
            employee__assessment=assessment,
            employee__last_name="Dupont",
            employee__first_name="Jean",
            employee__allowance_amount=0,
            start_at=datetime.date(2024, 1, 1),
            end_at=datetime.date(2024, 4, 30),
            planned_end_at=datetime.date(2024, 5, 31),
            allowance_requested=True,
            allowance_granted=False,
            allowance_refusal_reason=AllowanceRefusalReason.UNCONFIRMED_ELIGIBILITY,
            allowance_refusal_details="Éligibilité non confirmée",
        )
        EmployeeContractFactory(
            id=uuid.UUID("22222222-4444-4444-4444-444444444444"),
            employee__id=uuid.UUID("22222222-eeee-4444-8888-222222222222"),
            employee__assessment=assessment,
            employee__last_name="Martin",
            employee__first_name="Cécile",
            employee__allowance_amount=814,
            start_at=datetime.date(2024, 2, 1),
            end_at=datetime.date(2024, 3, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=True,
            allowance_granted=True,
        )
        EmployeeContractFactory(
            id=uuid.UUID("33333333-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__last_name="Dupond",
            employee__first_name="Jean-Pierre",
            employee__allowance_amount=1_400,
            employee__allowance_granted_previous_year=True,  # To test icon in list
            start_at=datetime.date(2024, 4, 1),
            end_at=datetime.date(2024, 6, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=False,
            allowance_granted=False,
        )
        refused_contract = EmployeeContractFactory(
            id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
            employee__id=uuid.UUID("44444444-eeee-4444-8888-111111111111"),
            employee__assessment=assessment,
            employee__last_name="Dupons",
            employee__first_name="Pean-Jierre",
            employee__allowance_amount=1_400,
            start_at=datetime.date(2024, 6, 1),
            end_at=datetime.date(2024, 6, 30),  # so that duration <90 days and an icon is displayed
            planned_end_at=datetime.date(2024, 10, 30),
            allowance_requested=True,
            allowance_request_justification_reason=AllowanceJustificationReason.OTHER_REFERENCE_PERIOD,
            allowance_request_justification_details="Détails.",
            allowance_granted=False,
            allowance_refusal_reason="",
            allowance_refusal_details="",
        )
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(contracts_list_url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments contracts list with refusal to justify"
        )
        # One contract's allowance is refused, the user cannot validate
        response = client.post(contracts_list_url, data={"action": "validate"})
        assert response.status_code == 403
        assessment.refresh_from_db()
        assert assessment.grants_selection_validated_at is None

        # Fill allowance refusal reason and try again
        refused_contract.allowance_refusal_reason = AllowanceRefusalReason.ALLOWANCE_ALREADY_GRANTED
        refused_contract.allowance_refusal_details = "Aide déjà attribuée."
        refused_contract.save()
        response = client.post(contracts_list_url, data={"action": "validate"})
        assertRedirects(
            response,
            reverse("geiq_assessments_views:details_for_institution", kwargs={"pk": assessment.pk}),
            fetch_redirect_response=False,
        )
        assessment.refresh_from_db()
        assert assessment.grants_selection_validated_at is not None
        response = client.get(contracts_list_url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments contracts list readonly"
        )
        response = client.post(contracts_list_url, data={"action": "invalidate"})
        assertRedirects(response, contracts_list_url, fetch_redirect_response=False)
        assessment.refresh_from_db()
        assert assessment.grants_selection_validated_at is None
        response = client.get(contracts_list_url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments contracts list with justified refusal"
        )

    def test_htmx_toggle_as_geiq(self, client):
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
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contract_1 = EmployeeContractFactory(
            id=uuid.UUID("11111111-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__last_name="Dupont",
            employee__first_name="Jean",
            employee__allowance_amount=0,
            start_at=datetime.date(2024, 1, 1),
            end_at=datetime.date(2024, 4, 30),
            planned_end_at=datetime.date(2024, 5, 31),
            allowance_requested=True,
        )
        contract_2 = EmployeeContractFactory(
            id=uuid.UUID("22222222-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__last_name="Martin",
            employee__first_name="Cécile",
            employee__allowance_amount=814,
            start_at=datetime.date(2024, 2, 1),
            end_at=datetime.date(2024, 3, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=False,
        )
        EmployeeContractFactory(
            id=uuid.UUID("33333333-4444-4444-4444-444444444444"),
            employee__id=uuid.UUID("33333333-eeee-4444-8888-333333333333"),
            employee__assessment=assessment,
            employee__last_name="Dupond",
            employee__first_name="Jean-Pierre",
            employee__allowance_amount=1_400,
            start_at=datetime.date(2024, 4, 1),
            end_at=datetime.date(2024, 6, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=True,
        )
        url = reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        client.force_login(geiq_membership.user)
        response = client.get(url)
        simulated_page = parse_response_to_soup(response, ".s-section")
        # Unselect contract
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_exclude",
                kwargs={"contract_pk": str(contract_1.pk)},
            ),
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"#toggle_allowance_for_contract_{contract_1.pk} > form", response)
        assert response.status_code == 200
        contract_1.refresh_from_db()
        assert contract_1.allowance_requested is False
        response = client.get(url)
        assertSoupEqual(simulated_page, parse_response_to_soup(response, ".s-section"))
        # Select contract that will need justification
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_include",
                kwargs={"contract_pk": str(contract_2.pk)},
            ),
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"#toggle_allowance_for_contract_{contract_2.pk} > form", response)
        assert response.status_code == 200
        contract_2.refresh_from_db()
        assert contract_2.allowance_requested is True
        response = client.get(url)
        assertSoupEqual(simulated_page, parse_response_to_soup(response, ".s-section"))

    def test_htmx_toggle_as_institution(self, client):
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
            submitted_at=timezone.now() + datetime.timedelta(seconds=1),
            submitted_by=geiq_membership.user,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contract_1 = EmployeeContractFactory(
            id=uuid.UUID("11111111-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__last_name="Dupont",
            employee__first_name="Jean",
            employee__allowance_amount=0,
            start_at=datetime.date(2024, 1, 1),
            end_at=datetime.date(2024, 4, 30),
            planned_end_at=datetime.date(2024, 5, 31),
            allowance_requested=True,
            allowance_granted=True,
        )
        contract_2 = EmployeeContractFactory(
            id=uuid.UUID("22222222-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__last_name="Martin",
            employee__first_name="Cécile",
            employee__allowance_amount=814,
            start_at=datetime.date(2024, 2, 1),
            end_at=datetime.date(2024, 3, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=True,
            allowance_granted=False,
            allowance_refusal_reason=AllowanceRefusalReason.UNCONFIRMED_ELIGIBILITY,
            allowance_refusal_details="Détails",
        )
        EmployeeContractFactory(
            id=uuid.UUID("33333333-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__last_name="Dupond",
            employee__first_name="Jean-Pierre",
            employee__allowance_amount=1_400,
            start_at=datetime.date(2024, 4, 1),
            end_at=datetime.date(2024, 6, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=True,
            allowance_granted=True,
        )
        url = reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        client.force_login(ddets_membership.user)
        response = client.get(url)
        simulated_page = parse_response_to_soup(response, ".s-section")
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_exclude",
                kwargs={"contract_pk": str(contract_1.pk)},
            ),
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"#toggle_allowance_for_contract_{contract_1.pk} > form", response)
        assert response.status_code == 200
        contract_1.refresh_from_db()
        assert contract_1.allowance_granted is False
        response = client.get(url)
        assertSoupEqual(simulated_page, parse_response_to_soup(response, ".s-section"))
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_include",
                kwargs={"contract_pk": str(contract_2.pk)},
            ),
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"#toggle_allowance_for_contract_{contract_2.pk} > form", response)
        assert response.status_code == 200
        contract_2.refresh_from_db()
        assert contract_2.allowance_granted is True
        response = client.get(url)
        assertSoupEqual(simulated_page, parse_response_to_soup(response, ".s-section"))

    def test_contract_selection_after_ask_for_geiq_fix(self, client):
        """Simulate back and forth exchanges between institution and GEIQ."""
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
            submitted_at=timezone.now() + datetime.timedelta(seconds=1),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(seconds=2),
            review_comment="Bon bilan.",
            convention_amount=10_000,
            granted_amount=9_000,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contract_1 = EmployeeContractFactory(
            id=uuid.UUID("11111111-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__last_name="Dupont",
            employee__first_name="Jean",
            employee__allowance_amount=0,
            start_at=datetime.date(2024, 1, 1),
            end_at=datetime.date(2024, 4, 30),
            planned_end_at=datetime.date(2024, 5, 31),
            allowance_requested=True,
            allowance_granted=True,
        )
        contract_2 = EmployeeContractFactory(
            id=uuid.UUID("22222222-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__last_name="Dupont",
            employee__first_name="Jean",
            employee__allowance_amount=0,
            start_at=datetime.date(2024, 1, 1),
            end_at=datetime.date(2024, 4, 30),
            planned_end_at=datetime.date(2024, 5, 31),
            allowance_requested=True,
            allowance_granted=False,
            allowance_refusal_reason=AllowanceRefusalReason.ALLOWANCE_ALREADY_GRANTED,
            allowance_refusal_details="Ce contrat n’aura pas d’aide.",
        )
        assessment.ask_for_geiq_fix(
            user=ddets_membership.user, institution=ddets_membership.institution, comment="À revoir"
        )

        # Sending the assessment back to the GEIQ for correction unsets allowance_granted
        contract_1.refresh_from_db()
        contract_2.refresh_from_db()
        assert contract_1.allowance_requested is True
        assert contract_1.allowance_granted is False
        assert contract_2.allowance_requested is True
        assert contract_2.allowance_granted is False

        client.force_login(geiq_membership.user)

        # The GEIQ can unselect a contract
        assessment.contracts_selection_validated_at = None
        assessment.save()
        client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_exclude",
                kwargs={"contract_pk": str(contract_1.pk)},
            ),
            headers={"HX-Request": "true"},
        )
        contract_1.refresh_from_db()
        assert contract_1.allowance_requested is False
        assert contract_1.allowance_granted is False

        # The GEIQ submits a corrected assessment, the DDETS/DREETS preselection is updated
        client.post(reverse("geiq_assessments_views:details_for_geiq", kwargs={"pk": assessment.pk}))

        # The work done by the institution was not lost
        assessment.refresh_from_db()
        assert assessment.review_comment == "Bon bilan."
        assert assessment.convention_amount == 10_000
        assert assessment.granted_amount == 9_000
        assert assessment.advance_amount == 0

        # The contracts with allowance_refusal_reason are automatically unselected
        contract_1.refresh_from_db()
        contract_2.refresh_from_db()
        assert contract_1.allowance_requested is False  # Was unselected by GEIQ
        assert contract_1.allowance_granted is False
        assert contract_2.allowance_requested is True
        assert contract_2.allowance_granted is False  # Had non empty allowance_refusal_reason


class TestAssessmentContractsDetails:
    @pytest.mark.parametrize("tab", AssessmentContractDetailsTab)
    def test_anonymous_access(self, client, tab):
        contract = EmployeeContractFactory()
        url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={"contract_pk": str(contract.pk), "tab": tab.value},
        )
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    @pytest.mark.parametrize("tab", AssessmentContractDetailsTab)
    def test_unauthorized_access(self, client, tab):
        contract = EmployeeContractFactory()
        url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={"contract_pk": str(contract.pk), "tab": tab.value},
        )
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(membership=True), 403),
            (EmployerFactory(membership=True, membership__company__not_geiq_kind=True), 403),
            (EmployerFactory(membership=True, membership__company__kind=CompanyKind.GEIQ), 404),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_contract_details_access(self, client, snapshot):
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
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contract = EmployeeContractFactory(
            employee__assessment=assessment,
            employee__last_name="Dupont",
            employee__first_name="Jean",
            employee__birthdate="1990-01-01",
            allowance_requested=True,
            nb_days_in_campaign_year=90,
        )

        PREVIOUS_YEAR_WARNING = (
            "Ce salarié figurait déjà dans le bilan précédent, nous vous invitons à vérifier ce contrat."
        )

        def check_user_access_to_tabs(
            user, *, access, tabs=AssessmentContractDetailsTab.get_common_tabs(), with_previous_year_warning=False
        ):
            client.force_login(user)
            if user == geiq_membership.user:
                user_label = "GEIQ"
                viewable_tabs_for_user = AssessmentContractDetailsTab.get_employer_tabs()
            else:
                user_label = "DDETS"
                viewable_tabs_for_user = AssessmentContractDetailsTab.get_institution_tabs()
            for tab in tabs:
                tab_url = reverse(
                    "geiq_assessments_views:assessment_contracts_details",
                    kwargs={"contract_pk": str(contract.pk), "tab": tab.value},
                )
                if access and tab in viewable_tabs_for_user:
                    with assertSnapshotQueries(snapshot(name=f"SQL queries for {tab=} as {user_label}")):
                        response = client.get(tab_url)
                    assertContains(response, "DUPONT Jean")
                    if with_previous_year_warning:
                        assertContains(response, PREVIOUS_YEAR_WARNING)
                    else:
                        assertNotContains(response, PREVIOUS_YEAR_WARNING)
                else:
                    response = client.get(tab_url)
                    assert response.status_code == 404

        check_user_access_to_tabs(geiq_membership.user, access=True)

        # DDETS user should not access the contract details before submission
        check_user_access_to_tabs(ddets_membership.user, access=False)

        # Submit the assessment
        assessment.submit(user=geiq_membership.user)
        check_user_access_to_tabs(ddets_membership.user, access=True)

        # Now for contract without allowance requested
        contract.allowance_requested = False
        contract.save()
        check_user_access_to_tabs(geiq_membership.user, access=True)
        check_user_access_to_tabs(ddets_membership.user, access=False)

        # GEIQ only tabs
        # --------------------------------------------------------------------
        # Justification tab is not available for contracts >90 days with allowance_requested=True
        contract.allowance_requested = True
        contract.save()
        assert not contract.requires_justification
        check_user_access_to_tabs(
            geiq_membership.user, tabs=[AssessmentContractDetailsTab.ALLOWANCE_REQUEST_JUSTIFICATION], access=False
        )
        # Justification tab is available for contract <90 days with allowance_requested=True
        contract.nb_days_in_campaign_year = 1
        contract.save()
        assert contract.requires_justification
        check_user_access_to_tabs(
            geiq_membership.user, tabs=[AssessmentContractDetailsTab.ALLOWANCE_REQUEST_JUSTIFICATION], access=True
        )
        check_user_access_to_tabs(
            ddets_membership.user, tabs=[AssessmentContractDetailsTab.ALLOWANCE_REQUEST_JUSTIFICATION], access=False
        )  # institution users still do not have access

        # Institution only tabs
        # --------------------------------------------------------------------
        # Justification tab is available when allowance_granted=False
        assert contract.allowance_granted is False
        check_user_access_to_tabs(
            ddets_membership.user, tabs=[AssessmentContractDetailsTab.ALLOWANCE_REFUSAL_JUSTIFICATION], access=True
        )
        contract.allowance_granted = True
        contract.save()
        # Justification tab is not available when allowance_granted=True
        check_user_access_to_tabs(
            geiq_membership.user, tabs=[AssessmentContractDetailsTab.ALLOWANCE_REFUSAL_JUSTIFICATION], access=False
        )
        check_user_access_to_tabs(
            ddets_membership.user, tabs=[AssessmentContractDetailsTab.ALLOWANCE_REFUSAL_JUSTIFICATION], access=False
        )  # GEIQ users do not have access

        # Now for contract with previous year info
        contract.employee.allowance_granted_previous_year = True
        contract.employee.save()
        contract.allowance_requested = True
        contract.save()
        check_user_access_to_tabs(ddets_membership.user, access=True, with_previous_year_warning=True)
        check_user_access_to_tabs(geiq_membership.user, access=True, with_previous_year_warning=True)

    @pytest.mark.parametrize("short_contract", [True, False], ids=["contract < 90 days", "contract >= 90 days"])
    def test_contract_request_allowance_as_geiq(self, client, snapshot, short_contract):
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
        )
        assessment = AssessmentFactory(
            companies=[geiq_membership.company],
            campaign__year=2024,
            with_submission_requirements=True,
            contracts_selection_validated_at=None,
        )
        contract = EmployeeContractFactory(
            employee__assessment=assessment,
            allowance_requested=False,
            nb_days_in_campaign_year=89 if short_contract else 90,
        )
        details_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={
                "contract_pk": str(contract.pk),
                # all common tabs should behave the same
                "tab": random.choice(AssessmentContractDetailsTab.get_common_tabs()).value,
            },
        )
        details_contract_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={"contract_pk": str(contract.pk), "tab": AssessmentContractDetailsTab.CONTRACT},
        )
        details_justification_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={
                "contract_pk": str(contract.pk),
                "tab": AssessmentContractDetailsTab.ALLOWANCE_REQUEST_JUSTIFICATION.value,
            },
        )
        JUSTIFICATION_TAB_LI = f"""
        <li class="nav-item">
            <a class="nav-link" href="{details_justification_url}">
                <span>Justification</span>
            </a>
        </li>"""
        JUSTIFICATION_TAB_WITH_ICON_LI = f"""
        <li class="nav-item">
            <a class="nav-link" href="{details_justification_url}">
                <span>Justification</span>
                <i class="ri-error-warning-line text-warning ms-2"></i>
            </a>
        </li>"""

        client.force_login(geiq_membership.user)
        response = client.get(details_url)
        # Allowance is not requested, never display justification tab
        assertNotContains(response, JUSTIFICATION_TAB_LI, html=True)
        assertNotContains(response, JUSTIFICATION_TAB_WITH_ICON_LI, html=True)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                selector="div.s-section__row > div.s-section__col.order-1 > div.c-box",
                replace_in_attr=[("action", str(contract.pk), "[PK of EmployeeContract]")],
            )
        ) == snapshot(name="allowance request box with allowance not requested")

        # User requests the allowance
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_include",
                kwargs={"contract_pk": str(contract.pk)},
            ),
        )
        contract.refresh_from_db()
        assert contract.allowance_requested is True

        if not short_contract:
            assertRedirects(response, details_contract_url)
            response = client.get(details_url)
            assert pretty_indented(
                parse_response_to_soup(
                    response,
                    selector="div.s-section__row > div.s-section__col.order-1 > div.c-box",
                    replace_in_attr=[("action", str(contract.pk), "[PK of EmployeeContract]")],
                )
            ) == snapshot(name="allowance request box with allowance requested")
            assertNotContains(response, JUSTIFICATION_TAB_LI, html=True)
            assertNotContains(response, JUSTIFICATION_TAB_WITH_ICON_LI, html=True)

        else:
            # contract is <90 days, requesting the allowance requires justification
            assertRedirects(response, details_justification_url)

            response = client.get(details_url)
            assert pretty_indented(
                parse_response_to_soup(
                    response,
                    selector="div.s-section__row > div.s-section__col.order-1 > div.c-box",
                    replace_in_attr=[
                        ("action", str(contract.pk), "[PK of EmployeeContract]"),
                        ("href", str(contract.pk), "[PK of EmployeeContract]"),
                    ],
                )
            ) == snapshot(name="allowance request box with allowance requested, missing reason, common tab")
            assertNotContains(response, JUSTIFICATION_TAB_LI, html=True)
            assertContains(response, JUSTIFICATION_TAB_WITH_ICON_LI, html=True)

            # User fills the form with invalid values
            response = client.post(
                details_justification_url,
                data={
                    "allowance_request_reason": "inexistant",
                },
            )
            assertContains(
                response, "<li>Sélectionnez un choix valide. inexistant n’en fait pas partie.</li>", html=True, count=1
            )
            assertContains(response, "<li>Ce champ est obligatoire.</li>", html=True, count=1)
            response = client.post(
                details_justification_url,
                data={"allowance_request_details": " "},
            )
            assertContains(
                response, "<li>Ce champ est obligatoire.</li>", html=True, count=2
            )  # both reason and details are empty

            # User fills the form with valid values
            response = client.post(
                details_justification_url,
                data={
                    "allowance_request_reason": random.choice(AllowanceJustificationReason.choices)[0],
                    "allowance_request_details": "C’est un cas particulier…",
                },
            )
            assertRedirects(response, details_contract_url)
            contract.refresh_from_db()
            assert contract.allowance_requested is True
            assert contract.allowance_request_justification_reason is not None
            assert contract.allowance_request_justification_details == "C’est un cas particulier…"
            response = client.get(details_url)
            assert pretty_indented(
                parse_response_to_soup(
                    response,
                    selector="div.s-section__row > div.s-section__col.order-1 > div.c-box",
                    replace_in_attr=[
                        ("action", str(contract.pk), "[PK of EmployeeContract]"),
                        ("href", str(contract.pk), "[PK of EmployeeContract]"),
                    ],
                )
            ) == snapshot(name="allowance request box with allowance requested, filled reason, common tab")
            assertContains(response, JUSTIFICATION_TAB_LI, html=True)
            assertNotContains(response, JUSTIFICATION_TAB_WITH_ICON_LI, html=True)

        # User unrequests the allowance and gets redirected to contract tab
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_exclude",
                kwargs={"contract_pk": str(contract.pk)},
            ),
        )
        contract.refresh_from_db()
        assert contract.allowance_requested is False
        assertRedirects(
            response,
            reverse(
                "geiq_assessments_views:assessment_contracts_details",
                kwargs={"contract_pk": contract.pk, "tab": AssessmentContractDetailsTab.CONTRACT},
            ),
        )
        if short_contract:
            # The reason and details are not deleted
            assert contract.allowance_request_justification_reason is not None
            assert contract.allowance_request_justification_details == "C’est un cas particulier…"

    @pytest.mark.parametrize("short_contract", [True, False], ids=["contract < 90 days", "contract >= 90 days"])
    def test_contract_request_allowance_as_geiq_after_contract_selection(self, client, snapshot, short_contract):
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
        )
        assessment = AssessmentFactory(
            companies=[geiq_membership.company],
            campaign__year=2024,
            with_submission_requirements=True,  # sets contracts_selection_validated_at
        )
        contract = EmployeeContractFactory(
            employee__assessment=assessment,
            allowance_requested=False,
            nb_days_in_campaign_year=89 if short_contract else 90,
        )
        details_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={
                "contract_pk": str(contract.pk),
                # all common tabs should behave the same
                "tab": random.choice(AssessmentContractDetailsTab.get_common_tabs()).value,
            },
        )
        details_contract_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={"contract_pk": str(contract.pk), "tab": AssessmentContractDetailsTab.CONTRACT},
        )
        details_justification_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={
                "contract_pk": str(contract.pk),
                "tab": AssessmentContractDetailsTab.ALLOWANCE_REQUEST_JUSTIFICATION.value,
            },
        )

        client.force_login(geiq_membership.user)
        response = client.get(details_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                selector="div.s-section__row > div.s-section__col.order-1 > div.c-box",
                replace_in_attr=[("action", str(contract.pk), "[PK of EmployeeContract]")],
            )
        ) == snapshot(name="allowance request box with allowance not requested after contract selection")

        # User tries to request the allowance
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_include",
                kwargs={"contract_pk": str(contract.pk)},
            ),
        )
        contract.refresh_from_db()
        assert contract.allowance_requested is False
        assertRedirects(response, details_contract_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "La sélection des contrats a déjà été validée : "
                    "vous ne pouvez plus modifier le statut de sollicitation de l’aide pour ce contrat.",
                )
            ],
        )
        response = client.get(details_contract_url)
        # Box has not changed
        assert pretty_indented(
            parse_response_to_soup(
                response,
                selector="div.s-section__row > div.s-section__col.order-1 > div.c-box",
                replace_in_attr=[
                    ("action", str(contract.pk), "[PK of EmployeeContract]"),
                ],
            )
        ) == snapshot(name="allowance request box with allowance not requested after contract selection")

        # User tries to deselect contract
        contract.allowance_requested = True
        if short_contract:
            contract.allowance_request_justification_reason = AllowanceJustificationReason.OTHER_REFERENCE_PERIOD
            contract.allowance_request_justification_details = "Détails."
        contract.save()
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_exclude",
                kwargs={"contract_pk": str(contract.pk)},
            ),
        )
        contract.refresh_from_db()
        assert contract.allowance_requested is True
        assertRedirects(response, details_contract_url)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "La sélection des contrats a déjà été validée : "
                    "vous ne pouvez plus modifier le statut de sollicitation de l’aide pour ce contrat.",
                )
            ],
        )
        response = client.get(details_contract_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                selector="div.s-section__row > div.s-section__col.order-1 > div.c-box",
                replace_in_attr=[
                    ("action", str(contract.pk), "[PK of EmployeeContract]"),
                    ("href", str(contract.pk), "[PK of EmployeeContract]"),
                ],
            )
        ) == snapshot(name="allowance request box with allowance requested after contract selection")

        if short_contract:
            # User tries to update justification reason
            response = client.post(
                details_justification_url,
                data={
                    "allowance_request_reason": AllowanceJustificationReason.OTHER.value,
                    "allowance_request_details": "Nouveaux détails",
                },
            )
            assertRedirects(response, details_contract_url)
            assertMessages(
                response,
                [
                    messages.Message(
                        messages.ERROR,
                        "La sélection des contrats a déjà été validée : "
                        "vous ne pouvez plus modifier le motif de sollicitation de l’aide pour ce contrat.",
                    )
                ],
            )
            contract.refresh_from_db()
            assert (
                contract.allowance_request_justification_reason
                == AllowanceJustificationReason.OTHER_REFERENCE_PERIOD.value
            )
            assert contract.allowance_request_justification_details == "Détails."

    def test_contract_grant_or_refuse_allowance_as_institution(self, client, snapshot):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
        )
        assessment = AssessmentFactory(
            companies=[geiq_membership.company],
            campaign__year=2024,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(seconds=1),
            submitted_by=geiq_membership.user,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contract = EmployeeContractFactory(
            employee__assessment=assessment, allowance_requested=True, allowance_granted=True
        )
        details_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={
                "contract_pk": str(contract.pk),
                # all common tabs should behave the same
                "tab": random.choice(AssessmentContractDetailsTab.get_common_tabs()).value,
            },
        )
        details_justification_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={
                "contract_pk": str(contract.pk),
                "tab": AssessmentContractDetailsTab.ALLOWANCE_REFUSAL_JUSTIFICATION.value,
            },
        )
        JUSTIFICATION_TAB_LI = f"""
        <li class="nav-item">
            <a class="nav-link" href="{details_justification_url}">
                Motif de refus
            </a>
        </li>"""
        JUSTIFICATION_TAB_WITH_ICON_LI = f"""
        <li class="nav-item">
            <a class="nav-link" href="{details_justification_url}">
                Motif de refus <i class="ri-error-warning-line ri-xl text-warning ms-2"></i>
            </a>
        </li>"""

        client.force_login(ddets_membership.user)
        response = client.get(details_url)
        assertNotContains(response, JUSTIFICATION_TAB_LI, html=True)
        assertNotContains(response, JUSTIFICATION_TAB_WITH_ICON_LI, html=True)
        assert pretty_indented(
            parse_response_to_soup(response, selector="div.s-section__row > div.s-section__col.order-1 > div.c-box")
        ) == snapshot(name="contract detail side box with granted allowance")

        # User refuses the allowance and gets redirected to the justification form tab
        response = client.post(details_url, data={"action": InstitutionAction.REFUSE_ALLOWANCE})
        assertRedirects(response, details_justification_url)
        contract.refresh_from_db()
        assert contract.allowance_granted is False

        response = client.get(details_url)
        assertNotContains(response, JUSTIFICATION_TAB_LI, html=True)
        assertContains(response, JUSTIFICATION_TAB_WITH_ICON_LI, html=True)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                selector="div.s-section__row > div.s-section__col.order-1 > div.c-box",
                replace_in_attr=[("href", str(contract.pk), "[Pk of EmployeeContract]")],
            )
        ) == snapshot(name="contract detail side box with refused allowance, missing reason, common tab")

        response = client.get(details_justification_url)
        assert pretty_indented(
            parse_response_to_soup(response, selector="div.s-section__row > div.s-section__col.order-1 > div.c-box")
        ) == snapshot(name="contract detail side box with refused allowance, missing reason, justification tab")

        # User fills the form with invalid values
        response = client.post(details_justification_url, data={"allowance_refusal_reason": ""})
        assert response.status_code == 404  # no action given leads to 404
        response = client.post(
            details_justification_url,
            data={
                "action": InstitutionAction.ALLOWANCE_REFUSAL_JUSTIFICATION,
                "allowance_refusal_reason": "inexistant",
            },
        )
        assertContains(
            response, "<li>Sélectionnez un choix valide. inexistant n’en fait pas partie.</li>", html=True, count=1
        )
        assertContains(response, "<li>Ce champ est obligatoire.</li>", html=True, count=1)
        response = client.post(
            details_justification_url,
            data={"action": InstitutionAction.ALLOWANCE_REFUSAL_JUSTIFICATION, "allowance_refusal_details": " "},
        )
        assertContains(
            response, "<li>Ce champ est obligatoire.</li>", html=True, count=2
        )  # both reason and details are empty

        # User fills the form with valid values
        response = client.post(
            details_justification_url,
            data={
                "action": InstitutionAction.ALLOWANCE_REFUSAL_JUSTIFICATION,
                "allowance_refusal_reason": random.choice(AllowanceRefusalReason.choices)[0],
                "allowance_refusal_details": "C’est un refus.",
            },
        )
        assert response.status_code == 200
        contract.refresh_from_db()
        assert contract.allowance_granted is False
        assert contract.allowance_refusal_reason is not None
        assert contract.allowance_refusal_details == "C’est un refus."

        # Check content of the common tabs
        response = client.get(details_url)
        assertContains(response, JUSTIFICATION_TAB_LI, html=True)
        assertNotContains(response, JUSTIFICATION_TAB_WITH_ICON_LI, html=True)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                selector="div.s-section__row > div.s-section__col.order-1 > div.c-box",
                replace_in_attr=[("href", str(contract.pk), "[Pk of EmployeeContract]")],
            )
        ) == snapshot(name="contract detail side box with refused allowance, filled reason, common tab")

        # User grants the allowance and gets redirected to employee tab
        response = client.post(details_justification_url, data={"action": InstitutionAction.GRANT_ALLOWANCE})
        assertRedirects(
            response,
            reverse(
                "geiq_assessments_views:assessment_contracts_details",
                kwargs={"contract_pk": contract.pk, "tab": AssessmentContractDetailsTab.EMPLOYEE},
            ),
        )
        contract.refresh_from_db()
        assert contract.allowance_granted is True
        assert contract.allowance_refusal_reason == ""
        assert contract.allowance_refusal_details == ""

    def test_contract_grant_or_refuse_allowance_as_institution_after_selection_validation(self, client, snapshot):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
        )
        assessment = AssessmentFactory(
            companies=[geiq_membership.company],
            campaign__year=2024,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(seconds=1),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(seconds=2),
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contract = EmployeeContractFactory(
            employee__assessment=assessment,
            allowance_requested=True,
            allowance_granted=False,
            allowance_refusal_reason=AllowanceRefusalReason.UNCONFIRMED_ELIGIBILITY,
            allowance_refusal_details="Incorrect.",
        )
        details_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={
                "contract_pk": str(contract.pk),
                # all common tabs should behave the same
                "tab": random.choice(AssessmentContractDetailsTab.get_common_tabs()).value,
            },
        )
        details_justification_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={
                "contract_pk": str(contract.pk),
                "tab": AssessmentContractDetailsTab.ALLOWANCE_REFUSAL_JUSTIFICATION.value,
            },
        )

        client.force_login(ddets_membership.user)
        response = client.get(details_url)
        assert pretty_indented(
            parse_response_to_soup(
                response,
                selector="div.s-section__row > div.s-section__col.order-1 > div.c-box",
                replace_in_attr=[("href", str(contract.pk), "[Pk of EmployeeContract]")],
            )
        ) == snapshot(name="contract detail side box with refused allowance and validated selection")

        # User tries to grant the allowance
        response = client.post(details_url, data={"action": InstitutionAction.GRANT_ALLOWANCE})
        assertContains(
            response,
            "La sélection des contrats a déjà été validée : vous ne pouvez plus accorder ou "
            "refuser l’aide pour ce contrat.",
        )
        contract.refresh_from_db()
        assert contract.allowance_granted is False

        # User tries to update a refusal reason
        response = client.post(
            details_justification_url,
            data={
                "action": InstitutionAction.ALLOWANCE_REFUSAL_JUSTIFICATION,
                "allowance_refusal_reason": random.choice(AllowanceRefusalReason.choices)[0],
                "allowance_refusal_details": "C’est un refus.",
            },
        )
        assertContains(
            response, "La sélection des contrats a déjà été validée : vous ne pouvez plus modifier le motif de refus."
        )
        contract.refresh_from_db()
        assert contract.allowance_refusal_reason == AllowanceRefusalReason.UNCONFIRMED_ELIGIBILITY
        assert contract.allowance_refusal_details == "Incorrect."

    @pytest.mark.parametrize(
        "short_contract, allowance_request_justification_reason, assertion",
        [
            (True, AllowanceJustificationReason.OTHER_REFERENCE_PERIOD, assertContains),
            (False, AllowanceJustificationReason.OTHER_REFERENCE_PERIOD, assertNotContains),
            (False, "", assertNotContains),
        ],
    )
    def test_display_allowance_request_justification_to_institution(
        self, client, short_contract, allowance_request_justification_reason, assertion
    ):
        JUSTIFICATION_TITLE = "<h3>Demande d’aide motivée</h3>"
        JUSTIFICATION_LABEL = (
            f"{AllowanceJustificationReason(allowance_request_justification_reason).label}"
            if allowance_request_justification_reason
            else ""
        )
        JUSTIFICATION_DETAILS = "<i>Détails saisissants.</i>"

        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(
            company__kind=CompanyKind.GEIQ,
        )
        assessment = AssessmentFactory(
            companies=[geiq_membership.company],
            campaign__year=2024,
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(seconds=1),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(seconds=2),
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contract = EmployeeContractFactory(
            employee__assessment=assessment,
            allowance_requested=True,
            nb_days_in_campaign_year=89 if short_contract else 90,
            allowance_request_justification_reason=allowance_request_justification_reason,
            allowance_request_justification_details="Détails saisissants."
            if allowance_request_justification_reason
            else "",
        )
        common_tabs_except_contract = AssessmentContractDetailsTab.get_common_tabs()
        common_tabs_except_contract.remove(AssessmentContractDetailsTab.CONTRACT)
        details_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={"contract_pk": str(contract.pk), "tab": random.choice(common_tabs_except_contract)},
        )
        details_contract_url = reverse(
            "geiq_assessments_views:assessment_contracts_details",
            kwargs={"contract_pk": str(contract.pk), "tab": AssessmentContractDetailsTab.CONTRACT.value},
        )
        client.force_login(ddets_membership.user)

        # Never display justification on tabs other than CONTRACT
        response = client.get(details_url)
        assertNotContains(response, JUSTIFICATION_TITLE, html=True)
        if allowance_request_justification_reason:
            assertNotContains(response, JUSTIFICATION_LABEL, html=True)
            assertNotContains(response, JUSTIFICATION_DETAILS, html=True)

        response = client.get(details_contract_url)
        assertion(response, JUSTIFICATION_TITLE, html=True)
        if allowance_request_justification_reason:
            assertion(response, JUSTIFICATION_LABEL, html=True)
            assertion(response, JUSTIFICATION_DETAILS, html=True)


class TestEmployeeContractToggleView:
    def test_contract_toggle_as_geiq_noop_after_selection_validated_at(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2024,
            companies=[geiq_membership.company],
            with_submission_requirements=True,
        )
        contract = EmployeeContractFactory(employee__assessment=assessment, allowance_requested=True)
        client.force_login(geiq_membership.user)
        response = client.post(
            reverse("geiq_assessments_views:assessment_contracts_exclude", kwargs={"contract_pk": str(contract.pk)}),
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        contract.refresh_from_db()
        assert contract.allowance_requested is True

        contract.allowance_requested = False
        contract.save()
        response = client.post(
            reverse("geiq_assessments_views:assessment_contracts_include", kwargs={"contract_pk": str(contract.pk)}),
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        contract.refresh_from_db()
        assert contract.allowance_requested is False

    def test_contract_toggle_as_institution_noop_after_selection_validated_at(self, client):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2024,
            companies=[geiq_membership.company],
            with_submission_requirements=True,
            submitted_at=timezone.now() + datetime.timedelta(seconds=1),
            submitted_by=geiq_membership.user,
            grants_selection_validated_at=timezone.now() + datetime.timedelta(seconds=1),
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contract = EmployeeContractFactory(
            employee__assessment=assessment, allowance_requested=True, allowance_granted=True
        )
        client.force_login(ddets_membership.user)
        response = client.post(
            reverse("geiq_assessments_views:assessment_contracts_exclude", kwargs={"contract_pk": str(contract.pk)}),
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        contract.refresh_from_db()
        assert contract.allowance_granted is True
        assert contract.allowance_requested is True

        contract.allowance_granted = False
        contract.save()
        response = client.post(
            reverse("geiq_assessments_views:assessment_contracts_include", kwargs={"contract_pk": str(contract.pk)}),
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        contract.refresh_from_db()
        assert contract.allowance_granted is False
        assert contract.allowance_requested is True

    def test_contract_toggle_as_institution_no_access_before_submission(self, client):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2024,
            companies=[geiq_membership.company],
            with_submission_requirements=True,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contract = EmployeeContractFactory(
            employee__assessment=assessment, allowance_requested=True, allowance_granted=False
        )
        client.force_login(ddets_membership.user)
        response = client.post(
            reverse("geiq_assessments_views:assessment_contracts_include", kwargs={"contract_pk": str(contract.pk)}),
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 404
        response = client.post(
            reverse("geiq_assessments_views:assessment_contracts_exclude", kwargs={"contract_pk": str(contract.pk)}),
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 404


class TestAssessmentContractsExportView:
    @pytest.mark.parametrize(
        "url_name",
        [
            "geiq_assessments_views:assessment_contracts_export",
            "geiq_assessments_views:assessment_contracts_export_all",
        ],
    )
    def test_anonymous_access(self, client, url_name):
        assessment = AssessmentFactory()
        url = reverse(url_name, kwargs={"pk": assessment.pk})
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

    @pytest.mark.parametrize(
        "url_name",
        [
            "geiq_assessments_views:assessment_contracts_export",
            "geiq_assessments_views:assessment_contracts_export_all",
        ],
    )
    def test_unauthorized_access(self, client, url_name):
        assessment = AssessmentFactory()
        url = reverse(url_name, kwargs={"pk": assessment.pk})
        for user, expected_status in [
            (JobSeekerFactory(), 403),
            (PrescriberFactory(membership=True), 403),
            (EmployerFactory(membership=True, membership__company__not_geiq_kind=True), 403),
            (EmployerFactory(membership=True, membership__company__kind=CompanyKind.GEIQ), 404),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    @freeze_time("2025-06-01 12:00:00")
    def test_export(self, client, snapshot):
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
            submitted_at=timezone.now() + datetime.timedelta(seconds=1),
            submitted_by=geiq_membership.user,
        )
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        EmployeeContractFactory(
            id=uuid.UUID("11111111-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__title=Title.M,
            employee__last_name="Dupont",
            employee__first_name="Jean",
            employee__birthdate="1990-01-01",
            employee__allowance_amount=0,
            start_at=datetime.date(2023, 12, 1),
            end_at=datetime.date(2024, 4, 30),
            planned_end_at=datetime.date(2024, 5, 31),
            allowance_requested=False,
            allowance_granted=False,
        )
        allowance_justification_reason = random.choice(
            AllowanceJustificationReason.choices
        )  # tuple: first value is value, second one is label
        allowance_refusal_reason = random.choice(
            AllowanceRefusalReason.choices
        )  # tuple: first value is value, second one is label
        EmployeeContractFactory(
            id=uuid.UUID("22222222-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__title=Title.MME,
            employee__last_name="Martin",
            employee__first_name="Cécile",
            employee__birthdate="1992-02-02",
            employee__allowance_amount=814,
            start_at=datetime.date(2024, 2, 1),
            end_at=datetime.date(2024, 3, 30),  # less than 90 days
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=True,
            allowance_request_justification_reason=allowance_justification_reason[0],
            allowance_request_justification_details="Détails de la dérogation.",
            allowance_granted=False,
            allowance_refusal_reason=allowance_refusal_reason[0],
            allowance_refusal_details="Détails de la justification",
        )
        EmployeeContractFactory(
            id=uuid.UUID("33333333-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__title=Title.M,
            employee__last_name="Dupond",
            employee__first_name="Jean-Pierre",
            employee__birthdate="1993-03-03",
            employee__allowance_amount=1_400,
            start_at=datetime.date(2024, 4, 1),
            end_at=datetime.date(2024, 6, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=True,
            allowance_granted=True,
        )
        # Justifications might have been filled, before the GEIQ corrected the assessment and unselected the contract.
        # Do not display the reasons in such cases.
        EmployeeContractFactory(
            id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
            employee__assessment=assessment,
            employee__title=Title.MME,
            employee__last_name="Nicolas",
            employee__first_name="Violette",
            employee__birthdate="1993-04-04",
            employee__allowance_amount=1_400,
            start_at=datetime.date(2024, 6, 1),
            end_at=datetime.date(2024, 6, 30),
            planned_end_at=datetime.date(2024, 9, 30),
            allowance_requested=False,
            allowance_request_justification_reason=allowance_justification_reason[0],
            allowance_request_justification_details="Détails de la dérogation.",
            allowance_granted=False,
            allowance_refusal_reason=allowance_refusal_reason[0],
            allowance_refusal_details="Détails de la justification",
        )
        url = reverse("geiq_assessments_views:assessment_contracts_export", kwargs={"pk": assessment.pk})
        all_contracts_url = reverse(
            "geiq_assessments_views:assessment_contracts_export_all", kwargs={"pk": assessment.pk}
        )
        client.force_login(geiq_membership.user)
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(url)
            excel_export = get_rows_from_streaming_response(response)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert response["Content-Disposition"] == 'attachment; filename="Contrats - Un Joli GEIQ - 2025-06-01.xlsx"'
        assert len(excel_export) == 5  # 4 contracts + header
        assert excel_export[0] == snapshot(name="excel export headers for the employer")
        rupture_anticipee_idx = excel_export[0].index("Date de rupture anticipée")
        allowance_requested_idx = excel_export[0].index("Demande d’aide")
        allowance_justification_reason_idx = excel_export[0].index("Motif de dérogation")
        assert excel_export[1][:4] == [
            "Dupond",
            "Jean-Pierre",
            "H",
            datetime.datetime(1993, 3, 3, 0, 0),
        ]
        assert excel_export[1][rupture_anticipee_idx] == ""
        assert excel_export[1][allowance_requested_idx] == "Oui"
        assert excel_export[2][:4] == [
            "Dupont",
            "Jean",
            "H",
            datetime.datetime(1990, 1, 1, 0, 0),
        ]
        assert excel_export[2][rupture_anticipee_idx] == datetime.datetime(2024, 4, 30)
        assert excel_export[2][allowance_requested_idx] == "Non"
        assert excel_export[2][allowance_justification_reason_idx] == ""
        assert excel_export[3][:4] == [
            "Martin",
            "Cécile",
            "F",
            datetime.datetime(1992, 2, 2, 0, 0),
        ]
        assert excel_export[3][allowance_justification_reason_idx] == allowance_justification_reason[1]
        assert excel_export[3][rupture_anticipee_idx] == datetime.datetime(2024, 3, 30)
        assert excel_export[3][allowance_requested_idx] == "Oui"
        assert excel_export[4][:4] == [
            "Nicolas",
            "Violette",
            "F",
            datetime.datetime(1993, 4, 4, 0, 0),
        ]
        assert excel_export[4][allowance_justification_reason_idx] == ""
        assert excel_export[4][rupture_anticipee_idx] == datetime.datetime(2024, 6, 30)
        assert excel_export[4][allowance_requested_idx] == "Non"

        response = client.get(all_contracts_url)
        assert response.status_code == 404

        client.force_login(ddets_membership.user)
        response = client.get(url)
        excel_export = get_rows_from_streaming_response(response)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert response["Content-Disposition"] == 'attachment; filename="Contrats - Un Joli GEIQ - 2025-06-01.xlsx"'
        assert len(excel_export) == 3  # 2 contracts + header
        assert excel_export[0] == snapshot(name="excel export headers for the DDETS")
        allowance_justification_reason_idx = excel_export[0].index("Motif de dérogation")
        allowance_granted_idx = excel_export[0].index("Éligible à l’aide")
        assert excel_export[1][:4] == [
            "Dupond",
            "Jean-Pierre",
            "H",
            datetime.datetime(1993, 3, 3, 0, 0),
        ]
        assert excel_export[1][allowance_justification_reason_idx] == ""
        assert excel_export[1][allowance_granted_idx] == "Oui"
        assert excel_export[1][-1] == ""  # allowance refusal reason
        assert excel_export[2][:4] == [
            "Martin",
            "Cécile",
            "F",
            datetime.datetime(1992, 2, 2, 0, 0),
        ]
        assert excel_export[2][allowance_justification_reason_idx] == allowance_justification_reason[1]
        assert excel_export[2][allowance_granted_idx] == "Non"
        assert excel_export[2][-1] == allowance_refusal_reason[1]  # allowance refusal reason

        response = client.get(all_contracts_url)
        excel_export = get_rows_from_streaming_response(response)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert response["Content-Disposition"] == 'attachment; filename="Contrats - Un Joli GEIQ - 2025-06-01.xlsx"'
        assert len(excel_export) == 5  # 4 contracts + header
        assert excel_export[0] == snapshot(name="excel export headers for the DDETS - all contracts version")
        allowance_justification_reason_idx = excel_export[0].index("Motif de dérogation")
        allowance_requested_idx = excel_export[0].index("Aide demandée par le GEIQ")
        allowance_granted_idx = excel_export[0].index("Éligible à l’aide")
        assert excel_export[1][:4] == [
            "Dupond",
            "Jean-Pierre",
            "H",
            datetime.datetime(1993, 3, 3, 0, 0),
        ]
        assert excel_export[1][allowance_justification_reason_idx] == ""
        assert excel_export[1][allowance_granted_idx] == "Oui"
        assert excel_export[1][-1] == ""  # allowance refusal reason
        assert excel_export[2][:4] == [
            "Dupont",
            "Jean",
            "H",
            datetime.datetime(1990, 1, 1, 0, 0),
        ]
        assert excel_export[2][allowance_requested_idx] == "Non"
        assert excel_export[2][allowance_justification_reason_idx] == ""
        assert excel_export[2][-1] == ""  # allowance refusal reason
        assert excel_export[3][:4] == [
            "Martin",
            "Cécile",
            "F",
            datetime.datetime(1992, 2, 2, 0, 0),
        ]
        assert excel_export[3][allowance_justification_reason_idx] == allowance_justification_reason[1]
        assert excel_export[3][allowance_granted_idx] == "Non"
        assert excel_export[3][-1] == allowance_refusal_reason[1]  # allowance refusal reason
        assert excel_export[4][:4] == [
            "Nicolas",
            "Violette",
            "F",
            datetime.datetime(1993, 4, 4, 0, 0),
        ]
        assert excel_export[4][allowance_justification_reason_idx] == ""
        assert excel_export[4][allowance_requested_idx] == "Non"
        assert excel_export[4][-1] == ""  # allowance refusal reason
