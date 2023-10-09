from django.urls import reverse
from pytest_django.asserts import assertContains

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

    # Create accredited org
    accredited_org = PrescriberOrganizationFactory(
        authorized=True,
        department=organization.department,
        kind=PrescriberOrganizationKind.OTHER,
        is_brsa=True,
    )

    response = client.get(reverse("prescribers_views:list_accredited_organizations"))
    assertContains(response, accredited_org.display_name)


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
