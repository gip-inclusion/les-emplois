import pytest
from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.companies.enums import CompanyKind
from itou.search.models import SavedSearch
from tests.cities.factories import create_city_lyon
from tests.search.factories import SavedSearchFactory
from tests.users.factories import PrescriberFactory, random_user_kind_factory


class TestSavedSearches:
    ADD_BUTTON_MARKUP = """
        <button class="btn btn-lg btn-secondary btn-ico" type="button" data-bs-toggle="modal"
                data-bs-target="#newSavedSearchModal">
            <i class="ri-star-line fw-medium" aria-hidden="true"></i>
            <span>Enregistrer cette recherche</span>
        </button>
        """

    EMPLOYERS_SEARCH_URL = reverse("search:employers_results")
    JOB_DESCRIPTIONS_SEARCH_URL = reverse("search:job_descriptions_results")
    ADD_SAVED_SEARCH_URL = reverse("search:add_saved_search")

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

    def test_add_saved_search(self, client):
        user = PrescriberFactory()
        client.force_login(user)

        data = {"saved_search-name": "Lyon 2", "saved_search-query_params": "city=lyon-69"}
        client.post(self.ADD_SAVED_SEARCH_URL, data)
        qs = SavedSearch.objects.all()
        assert qs.count() == 1

        saved_search = qs.first()
        assert saved_search.name == "Lyon 2"
        assert saved_search.user == user
        assert saved_search.query_params == "city=lyon-69"

    def test_cannot_add_saved_search_same_name(self, client):
        user = PrescriberFactory()
        client.force_login(user)
        SavedSearchFactory(name="Lyon", user=user)

        data = {"saved_search-name": "Lyon", "saved_search-query_params": "city=lyon-69"}
        response = client.post(self.ADD_SAVED_SEARCH_URL, data)
        assertContains(response, "Une recherche existe déjà avec ce nom.")
        assert SavedSearch.objects.count() == 1

    def test_cannot_add_saved_search_too_many(self, mocker, client):
        mocker.patch("itou.www.search_views.forms.NewSavedSearchForm.MAX_SAVED_SEARCHES_COUNT", 1)
        user = PrescriberFactory()
        client.force_login(user)
        SavedSearchFactory(name="Brest", user=user)

        data = {"saved_search-name": "Lyon", "saved_search-query_params": "city=lyon-69"}
        response = client.post(self.ADD_SAVED_SEARCH_URL, data)
        assertContains(response, "Vous ne pouvez pas enregistrer plus de 1 recherches. Veuillez en supprimer.")
        assert SavedSearch.objects.count() == 1
