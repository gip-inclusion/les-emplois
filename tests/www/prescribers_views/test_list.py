import random

from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains

from itou.common_apps.address.departments import DEPARTMENTS
from itou.prescribers.enums import PrescriberOrganizationKind
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationFactory,
)


def test_list_accredited_organizations(client):
    organization = PrescriberOrganizationFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.DEPT,
    )
    user = PrescriberMembershipFactory(organization=organization, is_admin=True).user
    client.force_login(user)

    other_departments = set(DEPARTMENTS) - {organization.department}

    # Create accredited org
    accredited_org = PrescriberOrganizationFactory(
        authorized=True,
        department=organization.department,
        kind=PrescriberOrganizationKind.OTHER,
        is_brsa=True,
    )
    accredited_org_from_other_department = PrescriberOrganizationFactory(
        authorized=True,
        department=random.choice(tuple(other_departments)),
        kind=PrescriberOrganizationKind.OTHER,
        is_brsa=True,
    )
    non_authorized_org = PrescriberOrganizationFactory(
        department=organization.department,
        kind=PrescriberOrganizationKind.OTHER,
        is_brsa=True,
    )
    authorized_but_not_brsa_org = PrescriberOrganizationFactory(
        authorized=True,
        department=organization.department,
        kind=PrescriberOrganizationKind.OTHER,
        is_brsa=False,
    )

    response = client.get(reverse("prescribers_views:list_accredited_organizations"))
    assertContains(response, accredited_org.display_name)
    assertNotContains(response, accredited_org_from_other_department.display_name)
    assertNotContains(response, non_authorized_org.display_name)
    assertNotContains(response, authorized_but_not_brsa_org.display_name)


def test_list_accredited_organizations_denied_for_non_admin(client):
    organization = PrescriberOrganizationFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.DEPT,
    )
    user = PrescriberMembershipFactory(organization=organization, is_admin=False).user
    client.force_login(user)
    response = client.get(reverse("prescribers_views:list_accredited_organizations"))
    assert response.status_code == 403


def test_list_accredited_organizations_denied_for_unauthorized(client):
    organization = PrescriberOrganizationFactory(kind=PrescriberOrganizationKind.DEPT)
    user = PrescriberMembershipFactory(organization=organization, is_admin=True).user
    client.force_login(user)
    response = client.get(reverse("prescribers_views:list_accredited_organizations"))
    assert response.status_code == 403


def test_list_accredited_organizations_denied_for_non_DEPT(client):
    organization = PrescriberOrganizationFactory(
        authorized=True,
        kind=PrescriberOrganizationKind.AFPA,
    )
    user = PrescriberMembershipFactory(organization=organization, is_admin=True).user
    client.force_login(user)
    response = client.get(reverse("prescribers_views:list_accredited_organizations"))
    assert response.status_code == 403
