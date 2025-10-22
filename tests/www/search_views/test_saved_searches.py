from unittest.mock import patch

import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.companies.enums import CompanyKind
from itou.search.models import SavedSearch
from itou.www.search_views import forms, views
from tests.cities.factories import create_city_lyon
from tests.search.factories import SavedSearchFactory
from tests.users.factories import PrescriberFactory, random_user_kind_factory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import assertSnapshotQueries, parse_response_to_soup, pretty_indented


class TestSavedSearches:
    ADD_BUTTON_MARKUP = """
        <button class="btn btn-lg btn-secondary btn-ico" type="button" data-bs-toggle="modal"
                data-bs-target="#newSavedSearchModal">
            <i class="ri-star-line fw-medium" aria-hidden="true"></i>
            <span>Enregistrer cette recherche</span>
        </button>
        """
    DISABLED_ADD_BUTTON_MARKUP = """
        <button class="btn btn-lg btn-secondary btn-ico" type="button" data-bs-toggle="modal"
                data-bs-target="#newSavedSearchModal" disabled="">
            <i class="ri-star-line fw-medium" aria-hidden="true"></i>
            <span>Enregistrer cette recherche</span>
        </button>
        <button type="button" data-bs-toggle="tooltip" data-bs-placement="top"
                data-bs-title="Le nombre maximum de recherches enregistrées a été atteint.">
            <i class="ri-information-line ri-xl text-info ms-1"
               aria-label="Le nombre maximum de recherches enregistrées a été atteint."></i>
        </button>
        """

    EMPLOYERS_SEARCH_URL = reverse("search:employers_results")
    JOB_DESCRIPTIONS_SEARCH_URL = reverse("search:job_descriptions_results")
    DASHBOARD_URL = reverse("dashboard:index")
    ADD_SAVED_SEARCH_URL = reverse("search:add_saved_search")
    DELETE_SAVED_SEARCH_VIEW_NAME = "search:delete_saved_search"

    def setup_method(self):
        self.lyon = create_city_lyon()

    @pytest.mark.parametrize(
        "user_factory, assertion", [(None, assertNotContains), (random_user_kind_factory, assertContains)]
    )
    @pytest.mark.parametrize("url", [EMPLOYERS_SEARCH_URL, JOB_DESCRIPTIONS_SEARCH_URL])
    def test_add_button_users(self, client, user_factory, url, assertion):
        if user_factory:
            client.force_login(user_factory())
        response = client.get(url, {"city": self.lyon.slug})
        assertion(response, self.ADD_BUTTON_MARKUP, html=True)

    @pytest.mark.parametrize(
        "params, assertion",
        [
            ({"city": "foo-69"}, assertNotContains),
            ({"city": "lyon-69"}, assertContains),
            ({"city": "lyon-69", "kinds": ["AE"]}, assertNotContains),
            ({"city": "lyon-69", "kinds": ["EA"]}, assertContains),
        ],
    )
    @pytest.mark.parametrize("url", [EMPLOYERS_SEARCH_URL, JOB_DESCRIPTIONS_SEARCH_URL])
    def test_add_button_valid_or_invalid_data(self, client, url, params, assertion):
        """When a search is invalid, do not show the Save search button."""
        client.force_login(PrescriberFactory())
        response = client.get(url, params)
        assertion(response, self.ADD_BUTTON_MARKUP, html=True)

    def test_query_params_field_is_set(self, client):
        client.force_login(PrescriberFactory())
        params = {
            "city": self.lyon.slug,
            "distance": "50",
            "kinds": [CompanyKind.ACI, CompanyKind.EI, CompanyKind.OPCS],
            "departments": ["69"],
            "district_69": ["69001", "69003"],
        }
        response = client.get(self.EMPLOYERS_SEARCH_URL, params)
        assertContains(
            response,
            (
                '<input type="hidden" name="saved_search-query_params" '
                'value="city=lyon-69&amp;distance=50&amp;kinds=ACI&amp;kinds=EI&amp;kinds=OPCS&amp;'
                'departments=69&amp;district_69=69001&amp;district_69=69003" id="id_saved_search-query_params">'
            ),
            html=True,
        )

    @patch.object(views, "MAX_SAVED_SEARCHES_COUNT", 1)
    def test_disabled_add_button(self, client):
        user = PrescriberFactory()
        client.force_login(user)
        response = client.get(self.EMPLOYERS_SEARCH_URL, {"city": self.lyon.slug})
        assertNotContains(response, self.DISABLED_ADD_BUTTON_MARKUP, html=True)

        SavedSearchFactory(user=user)
        response = client.get(self.EMPLOYERS_SEARCH_URL, {"city": self.lyon.slug})
        assertContains(response, self.DISABLED_ADD_BUTTON_MARKUP, html=True)

    @pytest.mark.parametrize("url", [DASHBOARD_URL, EMPLOYERS_SEARCH_URL, JOB_DESCRIPTIONS_SEARCH_URL])
    def test_display_saved_searches_and_delete_modal(self, client, url, snapshot):
        SEARCH_LIST_MARKUP = """<div class="c-search__list__title">Recherches enregistrées :</div>"""
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(url)
        assertNotContains(response, SEARCH_LIST_MARKUP, html=True)

        [saved_search1, saved_search2] = [SavedSearchFactory(user=user), SavedSearchFactory(user=user)]
        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(url)
        # Most recent first
        assertContains(
            response,
            f"""
            {SEARCH_LIST_MARKUP}
            <div class="c-search__list__slider">
                <div data-it-sliding-search="true">
                        <div>
                            <a href="{saved_search2.url}" class="btn-link btn-ico" data-matomo-event="true"
                            data-matomo-category="recherche" data-matomo-action="clic"
                            data-matomo-option="clic-sur-recherche-enregistree">
                                <i class="ri-star-line" aria-hidden="true"></i>
                                <span>{saved_search2.name}</span>
                            </a>
                        </div>
                        <div>
                            <a href="{saved_search1.url}" class="btn-link btn-ico" data-matomo-event="true"
                            data-matomo-category="recherche" data-matomo-action="clic"
                            data-matomo-option="clic-sur-recherche-enregistree">
                                <i class="ri-star-line" aria-hidden="true"></i>
                                <span>{saved_search1.name}</span>
                            </a>
                        </div>
                </div>
            </div>
            """,
            html=True,
        )
        # Only check that the delete modal is present on the 3 pages, the content is checked in a later test
        assertContains(
            response,
            """<h3 class="modal-title" id="savedSearchesSettingsModalLabel">Recherches enregistrées</h3>""",
            html=True,
        )

    @patch.object(views, "MAX_SAVED_SEARCHES_COUNT", 1)
    def test_add_saved_search(self, client, caplog):
        user = PrescriberFactory()
        client.force_login(user)

        data = {"saved_search-name": "Grand Lyon", "saved_search-query_params": "city=lyon-69"}
        response = client.post(self.ADD_SAVED_SEARCH_URL, headers={"HX-Request": "true"}, data=data)
        qs = SavedSearch.objects.all()
        assert qs.count() == 1

        saved_search = qs.first()
        assert saved_search.name == "Grand Lyon"
        assert saved_search.user == user
        assert saved_search.query_params == "city=lyon-69"
        # The max count is reached, disable the add button
        assertContains(response, self.DISABLED_ADD_BUTTON_MARKUP, html=True)
        # The new saved searches list was in the response
        assertContains(
            response,
            f"""
            <a href="{saved_search.url}" class="btn-link btn-ico" data-matomo-event="true"
            data-matomo-category="recherche" data-matomo-action="clic"
            data-matomo-option="clic-sur-recherche-enregistree">
                <i class="ri-star-line" aria-hidden="true"></i>
                <span>{saved_search.name}</span>
            </a>
           """,
            html=True,
        )
        assert f"user={user.pk} created a saved search" in caplog.messages

    @patch.object(views, "MAX_SAVED_SEARCHES_COUNT", 1)
    def test_add_saved_search_htmx_reload(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        response = client.get(self.EMPLOYERS_SEARCH_URL, {"city": self.lyon.slug})
        simulated_page = parse_response_to_soup(response, selector="body")

        data = {"saved_search-name": "Lyon", "saved_search-query_params": "city=lyon-69"}
        response = client.post(self.ADD_SAVED_SEARCH_URL, headers={"HX-Request": "true"}, data=data)
        assert response.status_code == 200
        update_page_with_htmx(simulated_page, f"form[hx-post='{self.ADD_SAVED_SEARCH_URL}']", response)

        # Check that a fresh reload gets us in the same state
        response = client.get(self.EMPLOYERS_SEARCH_URL, {"city": self.lyon.slug})
        fresh_page = parse_response_to_soup(response, selector="body")

        assertSoupEqual(fresh_page, simulated_page)

    def test_cannot_add_saved_search_same_name(self, client):
        user = PrescriberFactory()
        client.force_login(user)
        SavedSearchFactory(name="Lyon", user=user)

        data = {"saved_search-name": "Lyon", "saved_search-query_params": "city=lyon-69"}
        response = client.post(self.ADD_SAVED_SEARCH_URL, data)
        assertContains(response, "Une recherche existe déjà avec ce nom.")
        assert SavedSearch.objects.count() == 1

    @patch.object(forms, "MAX_SAVED_SEARCHES_COUNT", 1)
    def test_cannot_add_saved_search_too_many(self, client):
        user = PrescriberFactory()
        client.force_login(user)
        SavedSearchFactory(name="Brest", user=user)

        data = {"saved_search-name": "Lyon", "saved_search-query_params": "city=lyon-69"}
        response = client.post(self.ADD_SAVED_SEARCH_URL, data)
        assertContains(response, "Le nombre maximum de recherches enregistrées (1) a été atteint.")
        assert SavedSearch.objects.count() == 1

    def test_add_saved_search_strip_unwanted_params(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        data = {
            "saved_search-name": "Argenteuil",
            "saved_search-query_params": "job_seeker_public_id=558071c0-af88-4a14-8bc6-fb3c8343dc4&distance=25"
            "&domains=M&city=argenteuil-95&page=5",  # Real case from production
        }
        client.post(self.ADD_SAVED_SEARCH_URL, data)
        assert SavedSearch.objects.first().query_params == "distance=25&domains=M&city=argenteuil-95"

    def test_details_delete_modal_content(self, client, snapshot):
        user = PrescriberFactory()
        client.force_login(user)

        saved_search = SavedSearchFactory(user=user, for_snapshot=True)
        response = client.get(self.EMPLOYERS_SEARCH_URL)
        modal = parse_response_to_soup(
            response,
            selector="#savedSearchesSettingsModal",
            replace_in_attr=[("value", str(saved_search.pk), "[Pk of SavedSearch]")],
        )
        assert pretty_indented(modal) == snapshot

    def test_details_delete_modal_content_with_bad_data(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        SavedSearchFactory(user=user, name="", query_params="distance=50&kinds=ACI")
        SavedSearchFactory(user=user, name="No city", query_params="kinds=ACI")
        SavedSearchFactory(user=user, name="Not existing", query_params="city=foo-350&distance=50")

        response = client.get(self.EMPLOYERS_SEARCH_URL)
        assertContains(response, '<i class="ri-star-line" aria-hidden="true"></i><span></span>', html=True)
        assertContains(response, '<i class="ri-star-line" aria-hidden="true"></i><span>No city</span>', html=True)
        assertContains(response, '<i class="ri-star-line" aria-hidden="true"></i><span>Not existing</span>', html=True)

    def test_delete_saved_search(self, client, caplog):
        user = PrescriberFactory()
        client.force_login(user)

        saved_search = SavedSearchFactory(user=user)
        response = client.post(
            reverse(self.DELETE_SAVED_SEARCH_VIEW_NAME),
            data={"saved_search_id": saved_search.id},
            headers={"HX-Request": "true"},
        )

        assert SavedSearch.objects.count() == 0
        assert f"user={user.pk} deleted 1 saved search" in caplog.messages
        assertContains(
            response,
            """
            <div class="c-search__list" id="savedSearchesList" hx-swap-oob="true"></div>
           """,
            html=True,
        )
        assertContains(
            response,
            self.ADD_BUTTON_MARKUP,
            html=True,
        )

    @patch.object(views, "MAX_SAVED_SEARCHES_COUNT", 1)
    def test_delete_saved_search_htmx_reload(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        saved_search = SavedSearchFactory(user=user)
        response = client.get(self.EMPLOYERS_SEARCH_URL, {"city": self.lyon.slug})
        simulated_page = parse_response_to_soup(response, selector="body")

        response = client.post(
            reverse(self.DELETE_SAVED_SEARCH_VIEW_NAME),
            data={"saved_search_id": saved_search.id},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        update_page_with_htmx(
            simulated_page,
            (f"form[hx-post='{reverse(self.DELETE_SAVED_SEARCH_VIEW_NAME)}']"),
            response,
        )

        # Check that a fresh reload gets us in the same state
        response = client.get(self.EMPLOYERS_SEARCH_URL, {"city": self.lyon.slug})
        fresh_page = parse_response_to_soup(response, selector="body")

        assertSoupEqual(fresh_page, simulated_page)
