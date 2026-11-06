import random
import uuid

from django.contrib.gis.geos import Point
from django.core.cache import caches
from django.urls import reverse
from itoutils.urls import add_url_params
from pytest_django.asserts import assertContains, assertRedirects

from itou.cities.cache import CACHE_DIRECTORY_ACTIVE_CITY_IDS_KEY
from itou.cities.models import DirectoryActiveCity
from tests.cities.factories import create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.users.factories import EmployerFactory, LaborInspectorFactory
from tests.www.directory_views.helpers import get_target_person, setup_directory


def test_person_detail_preserves_back_url_and_hides_contact(client):
    _, _, target_organization, person = get_target_person(client)
    back_url = f"{reverse('directory:people_results')}?q={person.public_id}"

    response = client.get(
        reverse("directory:person_detail", kwargs={"public_id": person.public_id}),
        {"back_url": back_url},
    )

    assertContains(
        response,
        f"""
        <a href="{back_url}" class="btn btn-ico btn-link ps-0" aria-label="Retour à la page précédente">
            <i class="ri-arrow-drop-left-line ri-xl fw-medium" aria-hidden="true"></i>
            <span>Retour</span>
        </a>
        """,
        html=True,
        count=1,
    )
    assertContains(response, "Afficher l’adresse e-mail")
    assertContains(response, "Afficher le téléphone")
    assertContains(response, target_organization.get_card_url())
    assertContains(response, "https://mission-locale.example")


def test_person_detail_displays_missing_phone(client):
    _, _, _, person = get_target_person(client, target_phone="")

    response = client.get(reverse("directory:person_detail", kwargs={"public_id": person.public_id}))

    assertContains(
        response,
        """
        <li>
            <i class="ri-phone-line fw-normal me-2" aria-hidden="true"></i>
            <i class="text-disabled">Non renseigné</i>
        </li>""",
        html=True,
        count=1,
    )


def test_person_detail_unknown_key(client):
    setup_directory(client)

    response = client.get(
        reverse(
            "directory:person_detail",
            kwargs={
                "public_id": str(uuid.UUID("00000000-0000-0000-0000-000000000000")),
            },
        )
    )

    assert response.status_code == 404


def test_person_detail_rate_limit(client, mocker):
    _, _, _, person = get_target_person(client)
    mocker.patch("itou.www.directory_views.views.MessageThrottle.rate", "0/day")
    response = client.get(reverse("directory:person_detail", kwargs={"public_id": person.public_id}))
    assertContains(response, "Vous avez atteint la limite de messages envoyés : 0 par jour.")


def test_access(client):
    vannes = create_city_vannes()
    employer = EmployerFactory(membership=False)
    company = CompanyFactory(coords=vannes.coords, insee_city=vannes)
    CompanyMembershipFactory(user=employer, company=company)
    url = reverse("directory:person_detail", kwargs={"public_id": employer.public_id})

    user = EmployerFactory(membership=False)
    company = CompanyFactory()
    CompanyMembershipFactory(user=user, company=company)
    client.force_login(user)

    def set_coords_within_20kms():
        # https://stackoverflow.com/a/8477438
        # 0.01 degree is roughly 1.11 km
        km = 0.01
        x_dist = random.random() * 10 * km * random.choice([1, -1])
        y_dist = random.random() * 10 * km * random.choice([1, -1])
        company.coords = Point(vannes.coords.x + x_dist, vannes.coords.y + y_dist)
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
        response = client.get(url)
        assert response.status_code == 403
    last_cond()
    clean_cache()

    response = client.get(url)

    assertContains(response, f'<h2 class="h3">Envoyer un message à {employer.get_inverted_full_name()}</h2>')


def test_cannot_be_accessed_by_labor_inspectors(client):
    city = create_city_vannes()
    DirectoryActiveCity.objects.create(city=city)
    employer = EmployerFactory(membership=False)
    company = CompanyFactory(coords=city.coords, insee_city=city)
    CompanyMembershipFactory(user=employer, company=company)

    client.force_login(LaborInspectorFactory())
    url = reverse("directory:person_detail", kwargs={"public_id": employer.public_id})
    response = client.get(url)

    assert response.status_code == 403


def test_cannot_be_accessed_by_anonymous(client):
    city = create_city_vannes()
    DirectoryActiveCity.objects.create(city=city)
    employer = EmployerFactory(membership=False)
    company = CompanyFactory(coords=city.coords, insee_city=city)
    CompanyMembershipFactory(user=employer, company=company)

    url = reverse("directory:person_detail", kwargs={"public_id": employer.public_id})
    response = client.get(url)

    assertRedirects(response, add_url_params(reverse("account_login"), {"next": url}))
