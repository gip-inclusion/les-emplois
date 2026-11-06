import random

import pytest
from django.core.cache import caches
from django.urls import get_resolver, reverse
from itoutils.urls import add_url_params
from pytest_django.asserts import assertContains, assertRedirects

from itou.cities.cache import CACHE_DIRECTORY_ACTIVE_CITY_IDS_KEY
from itou.cities.models import DirectoryActiveCity
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory
from tests.www.directory_views.utils import coords_within_directory_radius


class Directory:
    urlname = "directory:people_results"

    @staticmethod
    def request(client, _recipient):
        return client.get(reverse(Directory.urlname))

    @staticmethod
    def assertion(response, _recipient):
        assertContains(
            response,
            """
            <h1>Annuaire des professionnels
                <span class="badge rounded-pill bg-important-lighter text-important badge-base">
                <i class="ri-flask-line" aria-hidden="true"></i>Beta</span>
            </h1>
            """,
            html=True,
            count=1,
        )


@pytest.mark.parametrize("view", [Directory])
class TestAccess:
    def test_access(self, client, view):
        vannes = create_city_vannes()
        employer = EmployerFactory(membership=False)
        company = CompanyFactory(coords=vannes.coords, insee_city=vannes)
        CompanyMembershipFactory(user=employer, company=company)

        user = EmployerFactory(membership=False)
        company = CompanyFactory()
        CompanyMembershipFactory(user=user, company=company)
        client.force_login(user)

        def set_coords_within_20kms():
            company.coords = coords_within_directory_radius(vannes.coords)
            company.save()

        def set_insee_city_id():
            company.insee_city = vannes
            company.save()

        def set_directory_active_city():
            DirectoryActiveCity.objects.create(city=vannes)

        def clean_cache():
            caches["failsafe"].delete(CACHE_DIRECTORY_ACTIVE_CITY_IDS_KEY)

        conditions = [set_coords_within_20kms, set_insee_city_id, set_directory_active_city]
        random.shuffle(conditions)
        *insufficient_cond, last_cond = conditions
        for condition in insufficient_cond:
            condition()
            clean_cache()
            response = view.request(client, employer)
            assert response.status_code == 403
        last_cond()
        clean_cache()

        response = view.request(client, employer)

        view.assertion(response, employer)

    @pytest.mark.parametrize(
        "user_factory",
        [
            lambda _city: JobSeekerFactory(),
            lambda city: (
                InstitutionMembershipFactory(
                    institution__coords=city.coords,
                    institution__insee_city=city,
                ).user
            ),
        ],
    )
    def test_detail_page_cannot_be_accessed(self, client, user_factory, view):
        city = create_city_vannes()
        DirectoryActiveCity.objects.create(city=city)
        employer = EmployerFactory(membership=False)
        company = CompanyFactory(coords=city.coords, insee_city=city)
        CompanyMembershipFactory(user=employer, company=company)

        client.force_login(user_factory(city))
        response = view.request(client, employer)

        assert response.status_code == 403

    def test_detail_page_cannot_be_accessed_by_anonymous(self, client, view):
        city = create_city_vannes()
        DirectoryActiveCity.objects.create(city=city)
        employer = EmployerFactory(membership=False)
        company = CompanyFactory(coords=city.coords, insee_city=city)
        CompanyMembershipFactory(user=employer, company=company)

        response = view.request(client, employer)

        assertRedirects(response, add_url_params(reverse("account_login"), {"next": response.request["PATH_INFO"]}))


def test_all_views_checked():
    root_resolver = get_resolver()
    namespace = "directory"
    _path, directory_resolver = root_resolver.namespace_dict[namespace]
    known_names = {Directory.urlname}
    for pattern in directory_resolver.url_patterns:
        known_names.remove(f"{namespace}:{pattern.name}")
    assert known_names == set()
