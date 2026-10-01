from urllib.parse import urlencode

import pytest
from data_inclusion.schema import v1 as data_inclusion_v1
from django.test import override_settings
from django.urls import reverse, reverse_lazy
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains

from itou.www.search_views.forms import ServiceSearchForm
from tests.cities.factories import create_city_vannes
from tests.insertion.factories import (
    IN_PERSON_RECEPTION_VALUE,
    REMOTE_RECEPTION_VALUE,
    InPersonReceptionFactory,
    RemoteReceptionFactory,
    ServiceFactory,
)
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import PAGINATION_PAGE_ONE_MARKUP, parse_response_to_soup, pretty_indented


CATEGORY = data_inclusion_v1.Categorie.MOBILITE


SAVOIE = "Conseil départemental de la Savoie"
ESSONNE = "Conseil départemental de l'Essonne"
VIENNE = "Conseil départemental de la Vienne"


class TestSearchServices:
    URL = reverse_lazy("search:services_results")
    FIRST_RESULT_LINK = "#services-search-results > .c-box--results:first-child a"

    def test_home_anonymous(self, client, settings):
        settings.PLATEFORME_ACCUEIL_BASE_URL = "https://plateforme.accueil.fr"
        response = client.get(reverse("search:services_home"))
        assertContains(
            response,
            'data-plateforme-accueil="https://plateforme.accueil.fr?host=localhost%3A8000&amp;type=insertion"',
        )

    def test_home_connected(self, client):
        client.force_login(EmployerFactory())
        with pytest.warns(RuntimeWarning, match="Access to 'search_home' while authenticated"):
            client.get(reverse("search:services_home"))

    def test_invalid_query_parameters(self, client):
        response = client.get(self.URL, {"city": "foo-44", "category": "foobar"})
        assertContains(response, "Rechercher un service d'insertion")
        assertContains(response, "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.")

    def test_results_html(self, snapshot, client):
        vannes = create_city_vannes()
        mixed = ServiceFactory(
            uid="dora-presentiel",
            name="dora-presentiel",
            structure__name="Une structure",
            source__value="dora",
            coordinates=vannes.coords,
            post_code="56000",
            city="Vannes",
            eligibility_zones=[],
        )
        mixed.receptions.set([InPersonReceptionFactory(), RemoteReceptionFactory()])
        remote_only = ServiceFactory(
            uid="autre-distanciel",
            name="autre-distanciel",
            structure__name="Une structure",
            source__value="autre",
            coordinates=vannes.coords,
            post_code="56000",
            city="Vannes",
            eligibility_zones=["france"],
        )
        remote_only.receptions.set([RemoteReceptionFactory()])

        response = client.get(
            self.URL, {"city": vannes.slug, "category": CATEGORY, "reception": ServiceSearchForm.RECEPTION_ALL_VALUE}
        )
        assertContains(response, "2 résultats")
        expected_title = f"Services d'insertion « {CATEGORY.label} » autour de {vannes} - La plateforme de l’inclusion"
        assertContains(response, f"<title>{expected_title}</title>", html=True, count=1)
        assert pretty_indented(parse_response_to_soup(response, selector="#services-search-results")) == snapshot()

    def test_link_to_local_detail_page(self, client):
        vannes = create_city_vannes()
        service = ServiceFactory(coordinates=vannes.coords, city="Vannes")

        response = client.get(self.URL, {"city": vannes.slug, "category": CATEGORY})
        href = parse_response_to_soup(response, selector=self.FIRST_RESULT_LINK)["href"]
        assert href.startswith(reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid}))
        assert "back_url=" in href
        assert "job_seeker_public_id" not in href

    def test_link_carries_job_seeker_for_authorized_prescriber(self, client):
        vannes = create_city_vannes()
        ServiceFactory(coordinates=vannes.coords, city="Vannes")
        job_seeker = JobSeekerFactory()
        client.force_login(PrescriberFactory(membership__organization__authorized=True))

        response = client.get(
            self.URL, {"city": vannes.slug, "category": CATEGORY, "job_seeker_public_id": job_seeker.public_id}
        )
        href = parse_response_to_soup(response, selector=self.FIRST_RESULT_LINK)["href"]
        assert f"job_seeker_public_id={job_seeker.public_id}" in href
        assertContains(response, "Vous orientez actuellement")
        assertContains(response, "vers un service")

    def test_category_error_suppression(self, client):
        vannes = create_city_vannes()

        # Choosing to "orienter" a job seeker from the job seekers list
        # pre-fills the form with a job seeker city, but the category field
        # isn’t yet populated.
        response = client.get(self.URL, {"city": vannes.slug})
        error_message = "Votre formulaire contient une erreur"
        assertContains(response, "Veuillez sélectionner une thématique pour voir les résultats.")
        assertNotContains(response, error_message)

        response = client.get(self.URL, {"city": vannes.slug, "category": "invalid"})
        assertContains(response, error_message)

    def test_no_results(self, client):
        vannes = create_city_vannes()
        response = client.get(self.URL, {"city": vannes.slug, "category": CATEGORY})
        assertContains(response, "Aucun résultat avec les filtres actuels.")

    @override_settings(PAGE_SIZE_SMALL=1)
    def test_pagination(self, client):
        vannes = create_city_vannes()
        ServiceFactory.create_batch(2, coordinates=vannes.coords, city="Vannes")

        url = reverse("search:services_results", query={"city": vannes.slug, "category": CATEGORY})
        assertContains(client.get(url), PAGINATION_PAGE_ONE_MARKUP % (url + "&page=1"), html=True)

    def test_htmx_reload_for_filters(self, client, htmx_client):
        vannes = create_city_vannes()
        ServiceFactory(coordinates=vannes.coords, city="Vannes")
        remote = ServiceFactory(coordinates=vannes.coords, city="Vannes", eligibility_zones=["france"])
        remote.receptions.set([RemoteReceptionFactory()])

        simulated_page = parse_response_to_soup(
            client.get(self.URL, {"city": vannes.slug, "category": CATEGORY, "reception": IN_PERSON_RECEPTION_VALUE})
        )
        [radio_input] = simulated_page.find_all(
            "input", attrs={"type": "radio", "name": "reception", "value": REMOTE_RECEPTION_VALUE}
        )
        radio_input["checked"] = ""
        [radio_input] = simulated_page.find_all(
            "input", attrs={"type": "radio", "name": "reception", "value": IN_PERSON_RECEPTION_VALUE}
        )
        del radio_input.attrs["checked"]
        update_page_with_htmx(
            simulated_page,
            f"form[hx-get='{self.URL}']",
            htmx_client.get(
                self.URL, {"city": vannes.slug, "category": CATEGORY, "reception": REMOTE_RECEPTION_VALUE}
            ),
        )

        fresh_page = parse_response_to_soup(
            client.get(self.URL, {"city": vannes.slug, "category": CATEGORY, "reception": REMOTE_RECEPTION_VALUE})
        )
        assertSoupEqual(simulated_page, fresh_page)

    def test_no_error_when_special_chars_in_uid(self, client):
        vannes = create_city_vannes()
        service = ServiceFactory(
            coordinates=vannes.coords, city="Vannes", uid="fredo--97416_13643-activités / ateliers"
        )  # real case

        response = client.get(self.URL, {"city": vannes.slug, "category": CATEGORY})
        assertContains(response, reverse("insertion_views:service_detail", kwargs={"service_uid": service.uid}))

    def test_funding_labels_filter(self, client, snapshot):
        FUNDING_LABEL_FILTER = "#services-funding-labels-filter"
        vannes = create_city_vannes()

        unfunded = ServiceFactory(coordinates=vannes.coords, city="Vannes", extra={"funding_labels": None})
        params = {"city": vannes.slug, "category": CATEGORY}
        response = client.get(self.URL, params)
        assertContains(response, "1 résultat")
        assertNotContains(response, "Financé par")

        savoie_service = ServiceFactory(coordinates=vannes.coords, city="Vannes", extra={"funding_labels": [SAVOIE]})
        savoie_essonne_service = ServiceFactory(
            coordinates=vannes.coords, city="Vannes", extra={"funding_labels": [SAVOIE, ESSONNE]}
        )
        # Must not be part of the results (remote only).
        remote = ServiceFactory(
            coordinates=vannes.coords,
            city="Vannes",
            eligibility_zones=["france"],
            extra={"funding_labels": [VIENNE]},
        )
        remote.receptions.set([RemoteReceptionFactory()])

        def available_choices(response):
            soup = parse_response_to_soup(response, selector=FUNDING_LABEL_FILTER)
            return {
                checkbox["value"]: "checked" in checkbox.attrs
                for checkbox in soup.find_all("input", attrs={"type": "checkbox", "name": "funding_labels"})
            }

        response = client.get(self.URL, params)
        assertContains(response, "3 résultats")
        assertContains(response, "Financé par")
        assert available_choices(response) == {ESSONNE: False, SAVOIE: False}

        with assertSnapshotQueries(snapshot(name="SQL queries")):
            response = client.get(self.URL, params | {"funding_labels": [ESSONNE]})
        assertContains(response, "1 résultat")
        assertContains(response, savoie_essonne_service.name)
        assertNotContains(response, unfunded.name)
        # Other labels remain available.
        assert available_choices(response) == {ESSONNE: True, SAVOIE: False}

        response = client.get(self.URL, params | {"funding_labels": [ESSONNE, SAVOIE]})
        assertContains(response, "2 résultats")
        assertContains(response, savoie_service.name)
        assertContains(response, savoie_essonne_service.name)

        response = client.get(
            self.URL, params | {"reception": ServiceSearchForm.RECEPTION_ALL_VALUE, "funding_labels": [VIENNE]}
        )
        assertContains(response, "1 résultat")
        assertContains(response, remote.name)
        assert available_choices(response) == {ESSONNE: False, SAVOIE: False, VIENNE: True}

        response = client.get(self.URL, params | {"funding_labels": ["unknown"]})
        assertContains(response, "3 résultats")
        assert available_choices(response) == {ESSONNE: False, SAVOIE: False}

    def test_htmx_reload_funding_labels_filter(self, client, htmx_client):
        vannes = create_city_vannes()
        ServiceFactory(coordinates=vannes.coords, city="Vannes")
        remote = ServiceFactory(
            coordinates=vannes.coords,
            city="Vannes",
            eligibility_zones=["france"],
            extra={"funding_labels": [VIENNE]},
        )
        remote.receptions.set([RemoteReceptionFactory()])

        params = {"city": vannes.slug, "category": CATEGORY}
        simulated_page = parse_response_to_soup(
            client.get(self.URL, params | {"reception": IN_PERSON_RECEPTION_VALUE})
        )
        assert simulated_page.find("input", attrs={"name": "funding_labels"}) is None
        [radio_input] = simulated_page.find_all(
            "input", attrs={"type": "radio", "name": "reception", "value": REMOTE_RECEPTION_VALUE}
        )
        radio_input["checked"] = ""
        [radio_input] = simulated_page.find_all(
            "input", attrs={"type": "radio", "name": "reception", "value": IN_PERSON_RECEPTION_VALUE}
        )
        del radio_input.attrs["checked"]
        update_page_with_htmx(
            simulated_page,
            f"form[hx-get='{self.URL}']",
            htmx_client.get(self.URL, params | {"reception": REMOTE_RECEPTION_VALUE}),
        )

        fresh_page = parse_response_to_soup(client.get(self.URL, params | {"reception": REMOTE_RECEPTION_VALUE}))
        assert fresh_page.find("input", attrs={"name": "funding_labels"}) is not None
        assertSoupEqual(simulated_page, fresh_page)

    def test_selected_funding_labels_absent_from_results_are_ignored(self, client):
        vannes = create_city_vannes()
        unfunded = ServiceFactory(coordinates=vannes.coords, city="Vannes")
        remote = ServiceFactory(
            coordinates=vannes.coords,
            city="Vannes",
            eligibility_zones=["france"],
            extra={"funding_labels": [VIENNE]},
        )
        remote.receptions.set([RemoteReceptionFactory()])
        params = {"city": vannes.slug, "category": CATEGORY, "reception": IN_PERSON_RECEPTION_VALUE}

        # The remote service is not part of (in person) results so the funding
        # label selected beforehand must not hide all the results.
        response = client.get(self.URL, params | {"funding_labels": [VIENNE]})
        assertContains(response, "1 résultat")
        assertContains(response, unfunded.name)
        assertNotContains(response, "Financé par")

        # Selected labels still appearing in the results remain applied.
        savoie_service = ServiceFactory(coordinates=vannes.coords, city="Vannes", extra={"funding_labels": [SAVOIE]})
        response = client.get(self.URL, params | {"funding_labels": [SAVOIE, VIENNE]})
        assertContains(response, "1 résultat")
        assertContains(response, savoie_service.name)
        assertNotContains(response, unfunded.name)
        soup = parse_response_to_soup(response, selector="#services-funding-labels-filter")
        [checkbox] = soup.find_all("input", attrs={"type": "checkbox", "name": "funding_labels"})
        assert checkbox["value"] == SAVOIE
        assert "checked" in checkbox.attrs

    def test_htmx_funding_labels_filter_not_swapped_when_only_funding_labels_change(self, client, htmx_client):
        FUNDING_LABEL_FILTER = "#services-funding-labels-filter"
        vannes = create_city_vannes()
        ServiceFactory(coordinates=vannes.coords, city="Vannes", extra={"funding_labels": [VIENNE]})
        params = {"city": vannes.slug, "category": CATEGORY, "reception": IN_PERSON_RECEPTION_VALUE}

        def get(current_params, params):
            current_url = f"http://testserver{self.URL}?{urlencode(current_params, doseq=True)}"
            return htmx_client.get(self.URL, params, headers={"HX-Current-URL": current_url})

        # Otherwise, the dropdown would be closed everytime the user (un)selects something.
        response = get(params, params | {"funding_labels": [VIENNE]})
        assertContains(response, "1 résultat")
        assertNotContains(response, FUNDING_LABEL_FILTER[1:])
        response = get(params | {"funding_labels": [VIENNE]}, params | {"page": "1"})
        assertNotContains(response, FUNDING_LABEL_FILTER[1:])

        response = get(params, params | {"reception": REMOTE_RECEPTION_VALUE})
        assertContains(response, FUNDING_LABEL_FILTER[1:])
        response = get({"city": vannes.slug}, params)
        assertContains(response, FUNDING_LABEL_FILTER[1:])
        response = htmx_client.get(self.URL, params)  # No HX-Current-URL header.
        assertContains(response, FUNDING_LABEL_FILTER[1:])
