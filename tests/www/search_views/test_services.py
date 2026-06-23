import pytest
from data_inclusion.schema import v1 as data_inclusion_v1
from django.test import override_settings
from django.urls import reverse, reverse_lazy
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

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


class TestSearchServices:
    URL = reverse_lazy("search:services_results")
    FIRST_RESULT_LINK = "#services-search-results > .c-box--results:first-child a"

    def test_home_anonymous(self, client):
        response = client.get(reverse("search:services_home"))
        assertContains(response, "Rechercher un service d'insertion")

    def test_home_connected(self, client):
        client.force_login(EmployerFactory(membership=True))
        with pytest.warns(RuntimeWarning, match="Access to 'search_services_home' while authenticated"):
            response = client.get(reverse("search:services_home"))
        assertRedirects(response, reverse("search:services_results"))

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
        expected_title = f"Services d'insertion « {CATEGORY.label} » autour de {vannes} - Les emplois de l'inclusion"
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
        client.force_login(PrescriberFactory(membership=True, membership__organization__authorized=True))

        response = client.get(
            self.URL, {"city": vannes.slug, "category": CATEGORY, "job_seeker_public_id": job_seeker.public_id}
        )
        href = parse_response_to_soup(response, selector=self.FIRST_RESULT_LINK)["href"]
        assert f"job_seeker_public_id={job_seeker.public_id}" in href
        assertContains(response, "Vous recherchez un service pour")

    def test_category_error_suppression(self, client):
        vannes = create_city_vannes()

        response = client.get(self.URL, {"city": vannes.slug})
        assertContains(response, "Veuillez sélectionner une thématique pour voir les résultats.")
        assertNotContains(response, "Votre formulaire contient une erreur")

        response = client.get(self.URL, {"city": vannes.slug, "category": "invalid"})
        assertContains(response, "Votre formulaire contient une erreur")

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
