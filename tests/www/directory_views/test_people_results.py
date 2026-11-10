import random
from collections import Counter

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains

from itou.cities.models import City, DirectoryActiveCity
from itou.companies.enums import CompanyKind
from itou.directory.models import DirectoryProfile
from itou.prescribers.enums import PrescriberOrganizationKind
from tests.cities.factories import create_city_geispolsheim, create_city_vannes
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import ProfessionalFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import parse_response_to_soup
from tests.www.directory_views.utils import KM


def add_km(count: float, coords: Point):
    return Point(coords.x + count * KM, coords.y + count * KM)


def test_list_company_and_prescriber_memberships(client, snapshot):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    company_membership_a = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
        user__last_name="Employeur",
        user__first_name="A",
    )
    company_membership_b = CompanyMembershipFactory(
        company__coords=vannes.coords,
        user__last_name="Employeur",
        user__first_name="B",
    )
    authorized_prescriber_memberships = []
    orienteur_memberships = []
    for first_name in ["A", "B"]:
        authorized_prescriber_memberships.append(
            PrescriberMembershipFactory(
                organization__coords=vannes.coords,
                organization__authorized=True,
                user__last_name="Prescripteur habilité",
                user__first_name=first_name,
            )
        )
        orienteur_memberships.append(
            PrescriberMembershipFactory(
                organization__coords=vannes.coords,
                user__last_name="Orienteur",
                user__first_name=first_name,
            )
        )
    InstitutionMembershipFactory(
        institution__coords=vannes.coords,
        user__last_name="Inspecteur",
        user__first_name="A",
    )

    user = company_membership_a.user
    client.force_login(user)
    with assertSnapshotQueries(snapshot):
        response = client.get(reverse("directory:people_results"))

    assert response.context["results"].object_list == [
        company_membership_a,
        company_membership_b,
        *orienteur_memberships,
        *authorized_prescriber_memberships,
    ]


def test_card_display(client, snapshot):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    company_membership = CompanyMembershipFactory(
        user__for_snapshot=True,
        company__kind=CompanyKind.EI,
        company__name="Envie",
        company__address_line_1="1 avenue Léon Blum",
        company__post_code="56056",
        company__city="Vannes",
        company__coords=vannes.coords,
        company__insee_city=vannes,
    )
    authorized_prescriber_membership = PrescriberMembershipFactory(
        user__for_snapshot=True,
        organization__authorized=True,
        organization__name="France Travail Vannes",
        organization__address_line_1="24 rue de Lorient",
        organization__kind=PrescriberOrganizationKind.FT,
        organization__post_code="56000",
        organization__city="Vannes",
        organization__coords=vannes.coords,
        organization__insee_city=vannes,
    )
    orienteur_membership = PrescriberMembershipFactory(
        user__first_name="Clément",
        user__last_name="Renard",
        organization__name="La bande des orienteurs",
        organization__address_line_1="12 rue de Rennes",
        organization__kind=PrescriberOrganizationKind.CAP_EMPLOI,
        organization__post_code="56000",
        organization__city="Vannes",
        organization__coords=vannes.coords,
        organization__insee_city=vannes,
    )

    client.force_login(company_membership.user)
    response = client.get(reverse("directory:people_results"))

    assert response.context["results"].object_list == [
        authorized_prescriber_membership,
        company_membership,
        orienteur_membership,
    ]

    page = parse_response_to_soup(response, "#people-search-results")
    assert page.prettify() == snapshot


def test_alphabetical_ordering_and_pagination(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    factory = random.choice([CompanyMembershipFactory, PrescriberMembershipFactory])
    org_key = "company" if factory is CompanyMembershipFactory else "organization"

    def membership(name, km_from_search_origin):
        kwargs = {
            f"{org_key}__insee_city": vannes,
            f"{org_key}__coords": add_km(km_from_search_origin, vannes.coords),
        }
        return factory(user__last_name=name, user__first_name=name, **kwargs)

    # Ordering by PK/date_joined should not pass the test.
    c = membership("C", random.uniform(0, 10))
    m = membership("M", random.uniform(0, 10))
    q = membership("Q", random.uniform(0, 10))
    n = membership("N", random.uniform(0, 10))
    p = membership("P", random.uniform(0, 10))
    a = membership("A", random.uniform(0, 10))
    d = membership("D", random.uniform(0, 10))
    b = membership("B", random.uniform(0, 10))
    e = membership("E", random.uniform(0, 10))
    o = membership("O", random.uniform(0, 10))

    user = ProfessionalFactory(first_name="Z second page", last_name="Z second page")
    company_membership = CompanyMembershipFactory(
        user=user,
        # Search point is farthest from Vannes.
        # Ordering by distance should not pass the test.
        company__coords=add_km(11, vannes.coords),
        company__insee_city=vannes,
    )

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assert response.context["results"].object_list == [a, b, c, d, e, m, n, o, p, q]

    response = client.get(reverse("directory:people_results"), {"page": 2})
    assert response.context["results"].object_list == [company_membership]


def test_order_user_memberships_by_distance_to_current_organization(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = ProfessionalFactory(first_name="Alice", last_name="Martin")
    # The organization from the oldest membership is active.
    active_membership = CompanyMembershipFactory(
        user=user,
        company__coords=vannes.coords,
        company__insee_city=vannes,
    )
    farther_membership = CompanyMembershipFactory(
        user=user,
        company__coords=add_km(3, vannes.coords),
        company__insee_city=vannes,
    )
    middle_membership = CompanyMembershipFactory(
        user=user,
        company__coords=add_km(2, vannes.coords),
        company__insee_city=vannes,
    )
    closest_membership = PrescriberMembershipFactory(
        user=user,
        organization__coords=add_km(1, vannes.coords),
        organization__insee_city=vannes,
    )

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assert response.context["results"].object_list == [
        active_membership,
        closest_membership,
        middle_membership,
        farther_membership,
    ]


def test_only_organizations_within_radius(client):
    geispolsheim = create_city_geispolsheim()
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = ProfessionalFactory(first_name="Alice", last_name="Martin")
    near_name = "Near company"
    far_name = "Far company"
    near_membership = CompanyMembershipFactory(
        user=user,
        company__coords=vannes.coords,
        company__insee_city=vannes,
        company__brand=near_name,
    )
    CompanyMembershipFactory(
        user=user,
        company__coords=geispolsheim.coords,
        company__insee_city=geispolsheim,
        company__brand=far_name,
    )

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assert response.context["results"].object_list == [near_membership]


def test_exclude_opted_out_email(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
    ).user
    DirectoryProfile.objects.create(user=user, is_opted_out=True)

    client.force_login(user)
    response = client.get(reverse("directory:people_results"))

    assert response.context["results"].object_list == []
    assertContains(response, '<p class="mb-0">Annuaire vide.</p>', html=True, count=1)


def test_ignores_inactive_companies(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    CompanyFactory(
        subject_to_iae_rules=True,
        # Inactive, thus not listed on the page.
        convention__is_active=False,
        coords=vannes.coords,
        insee_city=vannes,
        with_membership=True,
    )
    membership = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
    )

    client.force_login(membership.user)
    response = client.get(reverse("directory:people_results"))

    assert response.context["results"].object_list == [membership]


def test_includes_nearby_other_city(client):
    vannes = create_city_vannes()
    arradon = City.objects.create(
        name="Arradon",
        slug="arradon-56",
        department="56",
        coords=Point(-2.823008, 47.627922),
        post_codes=["56610"],
        code_insee="56003",
    )
    DirectoryActiveCity.objects.create(city=vannes)
    company_membership = CompanyMembershipFactory(
        user__first_name="Jean",
        user__last_name="Némar",
        company__coords=vannes.coords,
        company__insee_city=vannes,
    )
    prescriber_membership = PrescriberMembershipFactory(
        user__first_name="Claire",
        user__last_name="Dupont",
        organization__coords=arradon.coords,
        organization__insee_city=arradon,
    )

    client.force_login(company_membership.user)
    response = client.get(reverse("directory:people_results"))

    assert response.context["results"].object_list == [prescriber_membership, company_membership]


def test_search_htmx(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
        user__first_name="Manuel",
        user__last_name="Calavera",
    ).user
    membership_julie = CompanyMembershipFactory(
        user__first_name="Julie",
        user__last_name="Durand",
        company__coords=vannes.coords,
        company__insee_city=vannes,
    )

    search_string = "julie"
    client.force_login(user)
    response = client.get(reverse("directory:people_results"))
    page = parse_response_to_soup(response)

    response = client.get(
        reverse("directory:people_results"),
        {"q": search_string},
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(page, "#people-search-form", response)
    assert response.context["results"].object_list == [membership_julie]

    # Simulate page state after user interactions.
    [q_input] = page.select("#id_q")
    q_input["value"] = search_string
    assertSoupEqual(
        page,
        parse_response_to_soup(client.get(reverse("directory:people_results"), {"q": search_string})),
    )


@pytest.mark.parametrize(
    "q,found",
    [
        pytest.param("Loic", False, id="other-name"),
        pytest.param("ierre", False, id="contains"),
        pytest.param("lEO", True, id="case-sensitivity-partial"),
        pytest.param("lÈoN", True, id="case-sensitivity-accent-full"),
        pytest.param("Léon", True, id="full"),
        pytest.param("pierre leon", True, id="no-dash"),
        pytest.param("de la joie", True, id="spaces"),
        pytest.param("joufflue", True, id="spaces"),
    ],
)
def test_search_q(client, q, found):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    membership = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
        user__first_name="Pierre-Léon",
        user__last_name="De la joie Joufflue",
    )

    client.force_login(membership.user)
    response = client.get(reverse("directory:people_results"), {"q": q})

    expected = [membership] if found else []
    assert response.context["results"].object_list == expected


def test_search_kind(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    ai = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
        company__kind=CompanyKind.AI,
    )
    ei = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
        company__kind=CompanyKind.EI,
    )
    cada = PrescriberMembershipFactory(
        organization__coords=vannes.coords,
        organization__insee_city=vannes,
        organization__kind=PrescriberOrganizationKind.CADA,
    )

    client.force_login(ai.user)
    response = client.get(reverse("directory:people_results"), {"kind": CompanyKind.AI})
    assert response.context["results"].object_list == [ai]
    response = client.get(reverse("directory:people_results"), {"kind": CompanyKind.EI})
    assert response.context["results"].object_list == [ei]
    response = client.get(reverse("directory:people_results"), {"kind": PrescriberOrganizationKind.CADA})
    assert response.context["results"].object_list == [cada]
    response = client.get(
        reverse("directory:people_results"), {"kind": [PrescriberOrganizationKind.CADA, CompanyKind.EI]}
    )
    assert Counter(response.context["results"].object_list) == Counter([cada, ei])


def test_search_filters_combined_with_and(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    ai = CompanyMembershipFactory(
        user__first_name="Jules",
        user__last_name="Després",
        company__coords=vannes.coords,
        company__insee_city=vannes,
        company__kind=CompanyKind.AI,
    )
    CompanyMembershipFactory(
        user__first_name="Kévin",
        user__last_name="Taillefer",
        company__coords=vannes.coords,
        company__insee_city=vannes,
        company__kind=CompanyKind.EI,
    )

    client.force_login(ai.user)

    response = client.get(reverse("directory:people_results"), {"kind": CompanyKind.AI, "q": "Kevin"})
    assert response.context["results"].object_list == []


def test_empty_results_message(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
        company__kind=CompanyKind.AI,
    ).user

    client.force_login(user)
    response = client.get(reverse("directory:people_results"), {"kind": CompanyKind.EI})

    assertContains(response, '<p class="mb-0">Aucun résultat avec les filtres actuels.</p>', html=True, count=1)


def test_invalid_form_data(client):
    vannes = create_city_vannes()
    DirectoryActiveCity.objects.create(city=vannes)
    user = CompanyMembershipFactory(
        company__coords=vannes.coords,
        company__insee_city=vannes,
        company__kind=CompanyKind.AI,
        user__first_name="Manuel",
        user__last_name="Calavera",
    ).user

    client.force_login(user)
    response = client.get(reverse("directory:people_results"), {"kind": "INVALID"})

    assertContains(
        response,
        "Sélectionnez un choix valide. INVALID n’en fait pas partie.",
        html=True,
        count=1,
    )
    assertContains(response, '<p class="mb-0">Aucun résultat avec les filtres actuels.</p>', html=True, count=1)
