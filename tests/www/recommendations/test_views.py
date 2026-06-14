import uuid
from functools import partial

import pytest
from django.templatetags.static import static
from django.test import override_settings
from django.urls import reverse
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertTemplateUsed

from itou.recommendations import _mock_data
from tests.recommendations.factories import BeneficiaryFactory
from tests.users.factories import JobSeekerFactory, PrescriberFactory, random_pro_user_factory
from tests.utils.testing import parse_response_to_soup, pretty_indented
from tests.www.recommendations.conftest import OTHER_SAFIR, SAFIR


class TestListView:
    @pytest.mark.parametrize(
        "factory,access",
        [
            [JobSeekerFactory, False],
            [partial(random_pro_user_factory, membership=True), False],
            [
                partial(
                    PrescriberFactory,
                    membership__organization__france_travail=True,
                    membership__organization__code_safir_pole_emploi=OTHER_SAFIR,
                ),
                False,
            ],
            [
                partial(
                    PrescriberFactory,
                    membership__organization__france_travail=True,
                    membership__organization__code_safir_pole_emploi=SAFIR,
                ),
                True,
            ],
        ],
        ids=["job_seeker", "professional", "any_ft_prescriber", "authorized_ft_prescriber"],
    )
    def test_permission(self, client, factory, access):
        user = factory()
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_list"))
        assert response.status_code == (200 if access else 403)

    def test_view(self, client, advisor, snapshot):
        user, _ = advisor
        client.force_login(user)

        displayed = BeneficiaryFactory(
            first_name="John",
            last_name="Doe",
            referent_email=user.email,
            organization_safir=SAFIR,
        )
        BeneficiaryFactory(referent_email=user.email, organization_safir=OTHER_SAFIR)
        BeneficiaryFactory(referent_email="other-referent@example.com", organization_safir=SAFIR)

        response = client.get(reverse("recommendations:beneficiary_list"))
        rows = response.context["beneficiaries_page"]
        assert [(b.first_name, b.last_name) for b in rows] == [("John", "Doe")]

        # Snapshot the rendered table to lock the row-scoping behavior,
        # The displayed beneficiary's PK varies between runs: normalize it
        soup = parse_response_to_soup(
            response,
            "table",
            replace_in_attr=[
                ("href", f"/recommendations/{displayed.public_id}/", "/recommendations/[PUBLIC_ID]/"),
            ],
        )
        assert pretty_indented(soup) == snapshot

    def test_view_num_queries(self, client, advisor, snapshot):
        user, _ = advisor
        for _ in range(3):
            BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        url = reverse("recommendations:beneficiary_list")
        with assertSnapshotQueries(snapshot(name="beneficiary list num queries")):
            response = client.get(url)
        assert response.status_code == 200

    def test_htmx_request_returns_results_partial_template(self, client, advisor):
        user, _ = advisor
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_list"), HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        rendered = [t.name for t in response.templates if t.name]
        assert "recommendations/includes/list_results.html" in rendered
        assert "recommendations/list.html" not in rendered

    def test_order_query_param_descending(self, client, advisor):
        user, _ = advisor
        common = {"referent_email": user.email, "organization_safir": SAFIR}
        first = BeneficiaryFactory(last_name="Alpha", first_name="A", **common)
        last = BeneficiaryFactory(last_name="Zulu", first_name="Z", **common)
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_list"), data={"order": "-full_name"})
        page = response.context["beneficiaries_page"]
        assert [b.pk for b in page.object_list] == [last.pk, first.pk]

    def test_order_query_param_invalid_falls_back_to_default(self, client, advisor):
        user, _ = advisor
        common = {"referent_email": user.email, "organization_safir": SAFIR}
        first = BeneficiaryFactory(last_name="Alpha", first_name="A", **common)
        last = BeneficiaryFactory(last_name="Zulu", first_name="Z", **common)
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_list"), data={"order": "garbage"})
        assert response.status_code == 200
        page = response.context["beneficiaries_page"]
        assert [b.pk for b in page.object_list] == [first.pk, last.pk]

    def test_filter_by_beneficiary_id_keeps_only_that_row(self, client, advisor):
        user, _ = advisor
        common = {"referent_email": user.email, "organization_safir": SAFIR}
        kept = BeneficiaryFactory(**common)
        BeneficiaryFactory(**common)
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_list"), data={"beneficiary": kept.pk})
        page = response.context["beneficiaries_page"]
        assert [b.pk for b in page.object_list] == [kept.pk]

    def test_filter_by_beneficiary_id_outside_scope_falls_back(self, client, advisor):
        user, _ = advisor
        BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        foreign = BeneficiaryFactory(  # not in this user's scope
            referent_email="someone-else@example.com",
            organization_safir=OTHER_SAFIR,
        )
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_list"), data={"beneficiary": foreign.pk})
        # Form rejects the choice, no filter applied, user still sees their own scope
        assert response.status_code == 200
        page = response.context["beneficiaries_page"]
        assert page.paginator.count == 2

    @override_settings(PAGE_SIZE_LARGE=1)
    def test_pagination(self, client, advisor):
        user, _ = advisor
        common = {"referent_email": user.email, "organization_safir": SAFIR}
        BeneficiaryFactory(last_name="Alpha", **common)
        second = BeneficiaryFactory(last_name="Bravo", **common)
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_list"), data={"page": 2})
        assert response.status_code == 200
        page = response.context["beneficiaries_page"]
        assert page.number == 2
        assert [b.pk for b in page.object_list] == [second.pk]

    def test_filters_counter(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)

        response = client.get(reverse("recommendations:beneficiary_list"))
        assert response.context["filters_counter"] == 0

        response = client.get(
            reverse("recommendations:beneficiary_list"),
            data={"profile_kinds": ["rsa"], "beneficiary": beneficiary.pk},
        )
        assert response.context["filters_counter"] == 2


class TestBeneficiaryProfile:
    def test_visible_when_referent_and_safir_match(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        response = client.get(
            reverse("recommendations:beneficiary_profile", kwargs={"public_id": beneficiary.public_id})
        )
        assert response.status_code == 200

    def test_not_found_on_safir_mismatch(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=OTHER_SAFIR)
        client.force_login(user)
        response = client.get(
            reverse("recommendations:beneficiary_profile", kwargs={"public_id": beneficiary.public_id})
        )
        assert response.status_code == 404

    def test_not_found_on_referent_mismatch(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(organization_safir=SAFIR, referent_email="someone-else@example.com")
        client.force_login(user)
        response = client.get(
            reverse("recommendations:beneficiary_profile", kwargs={"public_id": beneficiary.public_id})
        )
        assert response.status_code == 404

    def test_unknown_public_id_not_found(self, client, advisor):
        user, _ = advisor
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_profile", kwargs={"public_id": uuid.uuid4()}))
        assert response.status_code == 404

    def test_renders_beneficiary_fields(self, client, advisor, snapshot):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(
            first_name="John",
            last_name="Doe",
            france_travail_id="12345678901",
            referent_email=user.email,
            organization_safir=SAFIR,
        )
        client.force_login(user)
        response = client.get(
            reverse("recommendations:beneficiary_profile", kwargs={"public_id": beneficiary.public_id})
        )
        assert response.status_code == 200
        soup = parse_response_to_soup(
            response,
            "#profile-tab-pane",
            replace_in_attr=[
                ("href", f"/recommendations/{beneficiary.public_id}/", "/recommendations/[PUBLIC_ID]/"),
            ],
        )
        assert pretty_indented(soup) == snapshot


class TestBeneficiaryActions:
    def test_visible_when_referent_and_safir_match(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        response = client.get(
            reverse("recommendations:beneficiary_actions", kwargs={"public_id": beneficiary.public_id})
        )
        assert response.status_code == 200

    def test_not_found_when_out_of_scope(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email="someone-else@example.com", organization_safir=OTHER_SAFIR)
        client.force_login(user)
        response = client.get(
            reverse("recommendations:beneficiary_actions", kwargs={"public_id": beneficiary.public_id})
        )
        assert response.status_code == 404

    def test_htmx_request_returns_actions_partial(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        response = client.get(
            reverse("recommendations:beneficiary_actions", kwargs={"public_id": beneficiary.public_id}),
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        # HTMX path renders the inline partial `#actions-results` only
        body = response.content.decode()
        assert 'id="actions-section"' in body
        assert "<html" not in body
        assertTemplateUsed(response, "recommendations/includes/list_reset_filters.html")
        assertTemplateUsed(response, "offcanvas-reset")

    def test_recommendations_in_context(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        response = client.get(
            reverse("recommendations:beneficiary_actions", kwargs={"public_id": beneficiary.public_id})
        )
        assert response.context["recommendations"] == _mock_data.HARDCODED_RECOMMENDATIONS
        assert response.context["recommendations_count"] == sum(
            len(item["providers"]) for item in _mock_data.HARDCODED_RECOMMENDATIONS
        )

    def test_map_points_only_expose_show_map_true(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        response = client.get(
            reverse("recommendations:beneficiary_actions", kwargs={"public_id": beneficiary.public_id})
        )
        shown = [
            p["name"] for item in _mock_data.HARDCODED_RECOMMENDATIONS for p in item["providers"] if p["show_map"]
        ]
        hidden = sum(
            1 for item in _mock_data.HARDCODED_RECOMMENDATIONS for p in item["providers"] if not p["show_map"]
        )
        assert [point["name"] for point in response.context["map_points"]] == shown
        assert hidden > 0

    def test_map_assets_and_data_rendered(self, client, advisor, snapshot):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        response = client.get(
            reverse("recommendations:beneficiary_actions", kwargs={"public_id": beneficiary.public_id})
        )
        body = response.content.decode()
        # OpenLayers loaded from the vendored bundle, not a CDN. static() resolves the
        # ManifestStaticFilesStorage hash (CI) or the plain path (local) for us.
        assert static("vendor/ol/ol.js") in body
        assert static("vendor/ol/ol.css") in body
        assert static("js/recommendations_map.js") in body
        # Map container, its JSON data island, and the popup container
        soup = parse_response_to_soup(response, ".c-box--recommendations-map")
        assert pretty_indented(soup) == snapshot


class TestMobilise:
    def test_post_returns_redirect_and_does_not_persist(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        response = client.post(reverse("recommendations:mobilise", kwargs={"public_id": beneficiary.public_id}))
        assert response.status_code == 302
        # TODO llalba: to be completed

    def test_post_htmx_returns_success_fragment(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        response = client.post(
            reverse("recommendations:mobilise", kwargs={"public_id": beneficiary.public_id}),
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        assert "Recommandation enregistrée" in response.content.decode()

    def test_get_method_not_allowed(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        response = client.get(reverse("recommendations:mobilise", kwargs={"public_id": beneficiary.public_id}))
        assert response.status_code == 405

    def test_not_found_when_out_of_scope(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email="someone-else@example.com", organization_safir=OTHER_SAFIR)
        client.force_login(user)
        response = client.post(reverse("recommendations:mobilise", kwargs={"public_id": beneficiary.public_id}))
        assert response.status_code == 404

    def test_unknown_public_id_not_found(self, client, advisor):
        user, _ = advisor
        client.force_login(user)
        response = client.post(reverse("recommendations:mobilise", kwargs={"public_id": uuid.uuid4()}))
        assert response.status_code == 404

    def test_referent_email_match_is_case_insensitive(self, client, advisor):
        user, _ = advisor
        beneficiary = BeneficiaryFactory(referent_email=user.email.upper(), organization_safir=SAFIR)
        client.force_login(user)
        response = client.post(reverse("recommendations:mobilise", kwargs={"public_id": beneficiary.public_id}))
        assert response.status_code == 302


class TestBeneficiaryAutocomplete:
    def test_returns_only_own_scope(self, client, advisor):
        user, _ = advisor
        mine = BeneficiaryFactory(
            referent_email=user.email,
            organization_safir=SAFIR,
            first_name="Alice",
            last_name="Martin",
        )
        BeneficiaryFactory(  # different referent + safir
            first_name="Alice",
            last_name="Martin",
            referent_email="someone-else@example.com",
            organization_safir=OTHER_SAFIR,
        )
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_autocomplete"), data={"term": "Martin"})
        assert response.status_code == 200
        results = response.json()["results"]
        assert [r["id"] for r in results] == [mine.pk]

    def test_empty_term_returns_empty(self, client, advisor):
        user, _ = advisor
        BeneficiaryFactory(referent_email=user.email, organization_safir=SAFIR)
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_autocomplete"))
        assert response.status_code == 200
        assert response.json() == {"results": []}

    def test_multi_term_search(self, client, advisor):
        user, _ = advisor
        common = {"referent_email": user.email, "organization_safir": SAFIR}
        mine = BeneficiaryFactory(first_name="Alice", last_name="Martin", **common)
        BeneficiaryFactory(first_name="Alice", last_name="Dupont", **common)
        client.force_login(user)
        response = client.get(reverse("recommendations:beneficiary_autocomplete"), data={"term": "Alice Martin"})
        assert response.status_code == 200
        assert [r["id"] for r in response.json()["results"]] == [mine.pk]

    def test_forbidden_for_non_advisor(self, client):
        client.force_login(JobSeekerFactory())
        response = client.get(reverse("recommendations:beneficiary_autocomplete"), data={"term": "Martin"})
        assert response.status_code == 403


class TestUnauthenticated:
    def test_list_redirects_to_login(self, client):
        response = client.get(reverse("recommendations:beneficiary_list"))
        assert response.status_code == 302
