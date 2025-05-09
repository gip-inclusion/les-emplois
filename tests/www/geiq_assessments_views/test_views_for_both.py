import datetime
import random
import uuid

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertRedirects

from itou.companies.enums import CompanyKind
from itou.geiq_assessments.models import AssessmentInstitutionLink
from itou.institutions.enums import InstitutionKind
from itou.www.geiq_assessments_views.views import AssessmentContractDetailsTab
from tests.companies.factories import CompanyMembershipFactory
from tests.geiq_assessments.factories import (
    AssessmentFactory,
    EmployeeContractFactory,
)
from tests.institutions.factories import InstitutionMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup, pretty_indented


class TestAssessmentContractsListAndToggle:
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
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
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
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
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
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments empty contracts list"
        )
        EmployeeContractFactory(
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
        EmployeeContractFactory(
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
            employee__assessment=assessment,
            employee__last_name="Dupond",
            employee__first_name="Jean-Pierre",
            employee__allowance_amount=1_400,
            start_at=datetime.date(2024, 4, 1),
            end_at=datetime.date(2024, 6, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=False,
        )
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(contracts_list_url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments contracts list"
        )
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
            name="assessments contracts list"
        )

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
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
            with_submission_requirements=True,
        )
        assessment.submitted_at = timezone.now()
        assessment.submitted_by = geiq_membership.user
        assessment.save()
        AssessmentInstitutionLink.objects.create(
            assessment=assessment,
            institution=ddets_membership.institution,
            with_convention=True,
        )
        contracts_list_url = reverse("geiq_assessments_views:assessment_contracts_list", kwargs={"pk": assessment.pk})
        client.force_login(ddets_membership.user)
        response = client.get(contracts_list_url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments empty contracts list"
        )
        EmployeeContractFactory(
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
        EmployeeContractFactory(
            id=uuid.UUID("22222222-4444-4444-4444-444444444444"),
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
            start_at=datetime.date(2024, 4, 1),
            end_at=datetime.date(2024, 6, 30),
            planned_end_at=datetime.date(2024, 6, 30),
            allowance_requested=False,
            allowance_granted=False,
        )
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(contracts_list_url)
        assert pretty_indented(parse_response_to_soup(response, ".s-section")) == snapshot(
            name="assessments contracts list"
        )
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
            name="assessments contracts list"
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
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
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
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_exclude",
                kwargs={"contract_pk": str(contract_1.pk)},
            )
            + "?from_list=1",
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"#toggle_allowance_for_contract_{contract_1.pk}", response)
        assert response.status_code == 200
        contract_1.refresh_from_db()
        assert contract_1.allowance_requested is False
        response = client.get(url)
        assertSoupEqual(simulated_page, parse_response_to_soup(response, ".s-section"))
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_include",
                kwargs={"contract_pk": str(contract_2.pk)},
            )
            + "?from_list=1",
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"#toggle_allowance_for_contract_{contract_2.pk}", response)
        assert response.status_code == 200
        contract_2.refresh_from_db()
        assert contract_2.allowance_requested is True

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
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
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
            )
            + "?from_list=1",
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"#toggle_allowance_for_contract_{contract_1.pk}", response)
        assert response.status_code == 200
        contract_1.refresh_from_db()
        assert contract_1.allowance_granted is False
        response = client.get(url)
        assertSoupEqual(simulated_page, parse_response_to_soup(response, ".s-section"))
        response = client.post(
            reverse(
                "geiq_assessments_views:assessment_contracts_include",
                kwargs={"contract_pk": str(contract_2.pk)},
            )
            + "?from_list=1",
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"#toggle_allowance_for_contract_{contract_2.pk}", response)
        assert response.status_code == 200
        contract_2.refresh_from_db()
        assert contract_2.allowance_granted is True


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
            (PrescriberFactory(), 403),
            (EmployerFactory(with_company=True), 404),
            (LaborInspectorFactory(membership=True), 404),
        ]:
            client.force_login(user)
            response = client.get(url)
            assert response.status_code == expected_status

    def test_contract_details_access(self, client):
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
            label_antennas=[{"id": 1234, "name": "Une antenne"}],
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
        )

        def check_user_access_to_all_tabs(user, *, access):
            client.force_login(user)
            for tab in AssessmentContractDetailsTab:
                tab_url = reverse(
                    "geiq_assessments_views:assessment_contracts_details",
                    kwargs={"contract_pk": str(contract.pk), "tab": tab.value},
                )
                response = client.get(tab_url)
                if access:
                    assertContains(response, "Jean DUPONT")
                else:
                    assert response.status_code == 404

        check_user_access_to_all_tabs(geiq_membership.user, access=True)

        # DDETS user should not access the contract details before submission
        check_user_access_to_all_tabs(ddets_membership.user, access=False)

        # Submit the assessment
        assessment.submitted_at = timezone.now()
        assessment.submitted_by = geiq_membership.user
        assessment.save()
        check_user_access_to_all_tabs(ddets_membership.user, access=True)

        # Now for contract without allowance requested
        contract.allowance_requested = False
        contract.save()
        check_user_access_to_all_tabs(geiq_membership.user, access=True)
        check_user_access_to_all_tabs(ddets_membership.user, access=False)

    def test_contract_toggle_as_geiq(self, client):
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2024,
            companies=[geiq_membership.company],
            with_submission_requirements=True,
            contracts_selection_validated_at=None,
        )
        contract = EmployeeContractFactory(
            employee__assessment=assessment,
            allowance_requested=random.choice([True, False]),
        )
        client.force_login(geiq_membership.user)
        for tab in AssessmentContractDetailsTab:
            current_value = contract.allowance_requested
            tab_url = reverse(
                "geiq_assessments_views:assessment_contracts_details",
                kwargs={"contract_pk": str(contract.pk), "tab": tab.value},
            )
            response = client.get(tab_url)
            simulated_page = parse_response_to_soup(response, selector="#main")
            view_name = "assessment_contracts_include" if not current_value else "assessment_contracts_exclude"
            response = client.post(
                reverse(f"geiq_assessments_views:{view_name}", kwargs={"contract_pk": str(contract.pk)}),
                headers={"HX-Request": "true"},
            )
            contract.refresh_from_db()
            assert contract.allowance_requested != current_value
            update_page_with_htmx(simulated_page, f"#toggle_allowance_for_contract_{contract.pk}", response)
            response = client.get(tab_url)
            fresh_page = parse_response_to_soup(response, selector="#main")
            assertSoupEqual(simulated_page, fresh_page)

    def test_contract_toggle_as_institution(self, client):
        ddets_membership = InstitutionMembershipFactory(institution__kind=InstitutionKind.DDETS_GEIQ)
        geiq_membership = CompanyMembershipFactory(company__kind=CompanyKind.GEIQ)
        assessment = AssessmentFactory(
            id=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            campaign__year=2024,
            companies=[geiq_membership.company],
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
            employee__assessment=assessment,
            allowance_requested=True,
            allowance_granted=random.choice([True, False]),
        )
        client.force_login(ddets_membership.user)
        for tab in AssessmentContractDetailsTab:
            current_value = contract.allowance_granted
            tab_url = reverse(
                "geiq_assessments_views:assessment_contracts_details",
                kwargs={"contract_pk": str(contract.pk), "tab": tab.value},
            )
            response = client.get(tab_url)
            simulated_page = parse_response_to_soup(response, selector="#main")
            view_name = "assessment_contracts_include" if not current_value else "assessment_contracts_exclude"
            response = client.post(
                reverse(f"geiq_assessments_views:{view_name}", kwargs={"contract_pk": str(contract.pk)}),
                headers={"HX-Request": "true"},
            )
            contract.refresh_from_db()
            assert contract.allowance_granted != current_value
            update_page_with_htmx(simulated_page, f"#toggle_allowance_for_contract_{contract.pk}", response)
            response = client.get(tab_url)
            fresh_page = parse_response_to_soup(response, selector="#main")
            assertSoupEqual(simulated_page, fresh_page)


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
