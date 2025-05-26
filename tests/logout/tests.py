from django.urls import reverse
from pytest_django.asserts import assertRedirects

from itou.prescribers.enums import PrescriberOrganizationKind
from tests.companies.factories import CompanyMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.test import parse_response_to_soup, pretty_indented


def tests_employers_without_company(client, snapshot):
    user = EmployerFactory()
    client.force_login(user)
    response = client.get("dashboard:index", follow=True)

    assertRedirects(response, reverse("logout:warning", kwargs={"kind": "employer_no_company"}))
    assert pretty_indented(parse_response_to_soup(response, ".s-section__container")) == snapshot()


def tests_employers_with_inactive_company(client, snapshot):
    user = CompanyMembershipFactory(company__subject_to_eligibility=True, company__convention=None).user
    client.force_login(user)
    response = client.get("dashboard:index", follow=True)

    assertRedirects(response, reverse("logout:warning", kwargs={"kind": "employer_inactive_company"}))
    assert pretty_indented(parse_response_to_soup(response, ".s-section__container")) == snapshot()


def test_labor_inspector_with_no_institution(client, snapshot):
    user = LaborInspectorFactory()
    client.force_login(user)
    response = client.get("dashboard:index", follow=True)

    assertRedirects(response, reverse("logout:warning", kwargs={"kind": "labor_inspector_no_institution"}))
    assert pretty_indented(parse_response_to_soup(response, ".s-section__container")) == snapshot()


def test_ft_prescriber_with_no_ft_organization(client, snapshot):
    user = PrescriberFactory(email="prenom.nom@francetravail.fr")
    # A FT user requires a FT organization, anoher kind of organization is not enough
    PrescriberMembershipFactory(organization__kind=PrescriberOrganizationKind.AFPA, user=user)
    client.force_login(user)
    response = client.get("dashboard:index", follow=True)

    assertRedirects(response, reverse("logout:warning", kwargs={"kind": "ft_no_ft_organization"}))
    assert pretty_indented(parse_response_to_soup(response, ".s-section__container")) == snapshot()
