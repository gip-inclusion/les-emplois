from functools import partial

import pytest
from django.urls import reverse
from factory.fuzzy import FuzzyChoice
from pytest_django.asserts import assertContains, assertNotContains

from itou.prescribers.enums import PrescriberOrganizationKind
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, LaborInspectorFactory, PrescriberFactory


NO_INFO_MARKUP = "<strong>Oups ! Aucune information en vue !</strong>"
YOUR_ORGA_EMPTY_MARKUP = """<i>Vous n’avez pas encore renseigné d’informations
           <br class="d-none d-lg-inline">
           à propos de votre organisation.</i>"""
ADMIN_ORGA_EMPTY_MARKUP = "<i>L'administrateur n’a pas encore renseigné l’activité de l’organisation.</i>"

PUBLIC_PAGE_MARKUP = "<span>Voir la fiche publique</span>"


@pytest.mark.parametrize(
    "user_factory,status_code",
    [
        pytest.param(JobSeekerFactory, 403, id="JobSeeker"),
        pytest.param(partial(EmployerFactory, with_company=True), 403, id="Employer"),
        pytest.param(partial(LaborInspectorFactory, membership=True), 403, id="LaborInspector"),
        pytest.param(PrescriberFactory, 404, id="PrescriberWithoutOrganization"),
        pytest.param(
            partial(PrescriberFactory, membership__organization__authorized=False),
            404,
            id="PrescriberWithUnauthorizedOrganization",
        ),
        pytest.param(
            partial(
                PrescriberFactory,
                membership__organization__name="Orga courante",
                membership__organization__authorized=True,
                membership__is_admin=False,
            ),
            200,
            id="PrescriberWithOrganization",
        ),
        pytest.param(
            partial(
                PrescriberFactory,
                membership__organization__name="Orga courante",
                membership__organization__authorized=True,
                membership__is_admin=True,
            ),
            200,
            id="PrescriberIsAdminOfOrganization",
        ),
    ],
)
def test_access(client, user_factory, status_code):
    client.force_login(user_factory())
    response = client.get(reverse("prescribers_views:overview"))
    assert response.status_code == status_code
    if status_code == 200:
        assertContains(response, "<h3>Orga courante</h3>")


def test_access_prescriber_with_multiple_organizations(client):
    user = PrescriberFactory()
    current_org = PrescriberOrganizationWithMembershipFactory(
        name="Orga courante", membership__user=user, authorized=True
    )
    PrescriberOrganizationWithMembershipFactory(name="Une autre orga", membership__user=user, authorized=True)
    client.force_login(user)
    client.post(reverse("dashboard:switch_organization"), data={"organization_id": current_org.pk})
    response = client.get(reverse("prescribers_views:overview"))
    assertContains(response, "<h3>Orga courante</h3>")
    assertNotContains(response, "<h3>Une autre orga</h3>")


def test_content_ft(client):
    organization = PrescriberOrganizationWithMembershipFactory(
        description="Mon activité",
        kind=PrescriberOrganizationKind.FT,
        authorized=True,
    )
    url = reverse("prescribers_views:overview")

    client.force_login(organization.members.first())
    response = client.get(url)
    assertContains(response, "<h3>Son activité</h3><p>Mon activité</p>", html=True)
    assertNotContains(response, NO_INFO_MARKUP, html=True)
    assertNotContains(response, YOUR_ORGA_EMPTY_MARKUP, html=True)
    assertContains(response, PUBLIC_PAGE_MARKUP, html=True)


def test_content_ft_empty_description(client):
    organization = PrescriberOrganizationWithMembershipFactory(
        description="",
        kind=PrescriberOrganizationKind.FT,
        authorized=True,
    )
    url = reverse("prescribers_views:overview")

    client.force_login(organization.members.first())
    response = client.get(url)
    assertNotContains(response, "<h3>Son activité</h3><p>Mon activité</p>", html=True)
    assertContains(response, NO_INFO_MARKUP, html=True)
    assertNotContains(response, YOUR_ORGA_EMPTY_MARKUP, html=True)
    assertContains(response, PUBLIC_PAGE_MARKUP, html=True)


@pytest.mark.parametrize("description", ["", "Mon activité"])
def test_content(client, description):
    organization = PrescriberOrganizationWithMembershipFactory(
        description=description,
        kind=FuzzyChoice(
            set(PrescriberOrganizationKind) - {PrescriberOrganizationKind.FT, PrescriberOrganizationKind.OTHER}
        ),
        authorized=True,
    )
    url = reverse("prescribers_views:overview")

    client.force_login(organization.members.first())
    response = client.get(url)
    assertion = [assertContains, assertNotContains] if description else [assertNotContains, assertContains]
    assertion[0](response, "<h3>Son activité</h3><p>Mon activité</p>", html=True)
    assertion[1](response, NO_INFO_MARKUP, html=True)
    assertion[1](response, YOUR_ORGA_EMPTY_MARKUP, html=True)
    assertContains(response, PUBLIC_PAGE_MARKUP, html=True)


def test_content_non_admin(client):
    organization = PrescriberOrganizationWithMembershipFactory(
        membership__is_admin=False,
        description="",
        kind=FuzzyChoice(
            set(PrescriberOrganizationKind) - {PrescriberOrganizationKind.FT, PrescriberOrganizationKind.OTHER}
        ),
        authorized=True,
    )
    url = reverse("prescribers_views:overview")

    client.force_login(organization.members.first())
    response = client.get(url)
    assertContains(response, ADMIN_ORGA_EMPTY_MARKUP, html=True)


@pytest.mark.parametrize("is_admin,assertion", [(False, assertNotContains), (True, assertContains)])
def test_edit_button(client, is_admin, assertion):
    organization = PrescriberOrganizationWithMembershipFactory(membership__is_admin=is_admin, authorized=True)
    client.force_login(organization.members.first())
    response = client.get(reverse("prescribers_views:overview"))
    assertion(response, "<span>Modifier</span>", html=True)
