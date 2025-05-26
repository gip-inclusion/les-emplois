from functools import partial
from unittest import mock

import pytest
from django.urls import reverse
from factory.fuzzy import FuzzyChoice
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK
from itou.utils.urls import add_url_params
from tests.prescribers.factories import PrescriberOrganizationFactory, PrescriberOrganizationWithMembershipFactory
from tests.utils.test import assert_previous_step, parse_response_to_soup, pretty_indented


class TestCardView:
    def test_card(self, client):
        prescriber_org = PrescriberOrganizationFactory(authorized=True)
        url = reverse("prescribers_views:card", kwargs={"org_id": prescriber_org.pk})
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["prescriber_org"] == prescriber_org

        # When coming from prescribers search results page
        url = add_url_params(
            reverse("prescribers_views:card", kwargs={"org_id": prescriber_org.pk}),
            {"back_url": reverse("search:prescribers_results")},
        )
        response = client.get(url)
        assert_previous_step(response, reverse("search:prescribers_results"), back_to_list=True)

        # When coming from dashboard
        url = add_url_params(
            reverse("prescribers_views:card", kwargs={"org_id": prescriber_org.pk}),
            {"back_url": reverse("dashboard:index")},
        )
        response = client.get(url)
        assert_previous_step(response, reverse("dashboard:index"))

    def test_card_subtitle_ft(self, client):
        prescriber_org = PrescriberOrganizationFactory(authorized=True, kind=PrescriberOrganizationKind.FT)
        url = reverse("prescribers_views:card", kwargs={"org_id": prescriber_org.pk})
        response = client.get(url)
        assertContains(response, f"<p>{prescriber_org.name}</p>", html=True)

    def test_card_subtitle(self, client):
        prescriber_org = PrescriberOrganizationFactory(
            authorized=True,
            kind=FuzzyChoice(
                set(PrescriberOrganizationKind.values)
                - {PrescriberOrganizationKind.FT, PrescriberOrganizationKind.OTHER}
            ),
        )
        url = reverse("prescribers_views:card", kwargs={"org_id": prescriber_org.pk})
        response = client.get(url)
        assertContains(response, f"<p>{prescriber_org.get_kind_display()} - {prescriber_org.name}</p>", html=True)

    def test_card_render_markdown(self, client):
        prescriber_org = PrescriberOrganizationFactory(
            authorized=True,
            description="*Lorem ipsum*, **bold** and [link](https://beta.gouv.fr).",
        )
        url = reverse("prescribers_views:card", kwargs={"org_id": prescriber_org.pk})
        response = client.get(url)
        attrs = 'target="_blank" rel="noopener" aria-label="Ouverture dans un nouvel onglet"'

        assertContains(
            response,
            f'<p><em>Lorem ipsum</em>, <strong>bold</strong> and <a href="https://beta.gouv.fr" {attrs}>link</a>.</p>',
        )

    def test_card_render_markdown_forbidden_tags(self, client):
        prescriber_org = PrescriberOrganizationFactory(
            authorized=True,
            description='# Gros titre\n<script></script>\n<span class="font-size:200px;">Gros texte</span>',
        )
        url = reverse("prescribers_views:card", kwargs={"org_id": prescriber_org.pk})
        response = client.get(url)

        assertContains(response, "Gros titre\n\n<p>Gros texte</p>")


class TestEditOrganization:
    def test_edit(self, client):
        """Edit a prescriber organization."""

        organization = PrescriberOrganizationWithMembershipFactory(
            authorized=True, kind=PrescriberOrganizationKind.CAP_EMPLOI
        )
        user = organization.members.first()

        client.force_login(user)

        url = reverse("prescribers_views:edit_organization")
        response = client.get(url)
        assert response.status_code == 200

        assert_previous_step(response, reverse("dashboard:index"))

        post_data = {
            "name": "foo",
            "siret": organization.siret,
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "address_line_1": "2 Rue de Soufflenheim",
            "address_line_2": "",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
        }
        with mock.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api",
            return_value=BAN_GEOCODING_API_RESULT_MOCK,
        ) as mock_call_ban_geocoding_api:
            response = client.post(url, data=post_data)
        assert response.status_code == 302

        mock_call_ban_geocoding_api.assert_called_once()

        organization = PrescriberOrganization.objects.get(siret=organization.siret)

        assert organization.name == post_data["name"]
        assert organization.description == post_data["description"]
        assert organization.address_line_1 == post_data["address_line_1"]
        assert organization.address_line_2 == post_data["address_line_2"]
        assert organization.city == post_data["city"]
        assert organization.post_code == post_data["post_code"]
        assert organization.department == post_data["department"]
        assert organization.email == post_data["email"]
        assert organization.phone == post_data["phone"]
        assert organization.website == post_data["website"]

        # This data comes from BAN_GEOCODING_API_RESULT_MOCK.
        assert organization.coords == "SRID=4326;POINT (2.316754 48.838411)"
        assert organization.latitude == 48.838411
        assert organization.longitude == 2.316754
        assert organization.geocoding_score == 0.5197687103594081

        # Only admins should be able to edit organization details
        membership = organization.prescribermembership_set.first()
        membership.is_admin = False
        membership.save()
        url = reverse("prescribers_views:edit_organization")
        response = client.get(url)
        assert response.status_code == 403

    def test_edit_with_multiple_memberships_and_same_siret(self, client):
        """
        Updating information of the prescriber organization must be possible
        when user is member of multiple orgs with the same SIRET (and different types)
        (was a regression)
        """
        organization = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganizationKind.ML)
        siret = organization.siret
        user = organization.members.first()

        org2 = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganizationKind.PLIE, siret=siret)
        org2.members.add(user)
        org2.save()

        client.force_login(user)

        url = reverse("prescribers_views:edit_organization")
        response = client.get(url)
        assert response.status_code == 200

        assert_previous_step(response, reverse("dashboard:index"))

        post_data = {
            "siret": siret,
            "name": "foo",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "address_line_1": "2 Rue de Soufflenheim",
            "address_line_2": "",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
        }
        with mock.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api",
            return_value=BAN_GEOCODING_API_RESULT_MOCK,
        ):
            response = client.post(url, data=post_data)
        assert response.status_code == 302

        url = reverse("dashboard:index")
        assert url == response.url

    def test_ft_cannot_edit(self, client, snapshot):
        organization = PrescriberOrganizationWithMembershipFactory(
            authorized=True,
            kind=PrescriberOrganizationKind.FT,
            name="Pôle emploi",
            siret="12345678901234",
            phone="0600000000",
            email="pe@mailinator.com",
            department="53",
            post_code="53480",
        )
        user = organization.members.first()
        url = reverse("prescribers_views:edit_organization")

        client.force_login(user)
        response = client.get(url)
        form = parse_response_to_soup(response, selector="form.js-prevent-multiple-submit")
        assert pretty_indented(form) == snapshot(name="Fields are disabled")
        assertContains(response, "Affichage des informations en lecture seule", count=1)

        post_data = {
            "name": "foo",
            "siret": organization.siret,
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "address_line_1": "2 Rue de Soufflenheim",
            "address_line_2": "",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-company.com",
        }
        with mock.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api",
            return_value=BAN_GEOCODING_API_RESULT_MOCK,
        ) as mock_call_ban_geocoding_api:
            response = client.post(url, data=post_data)
        assert response.status_code == 200
        mock_call_ban_geocoding_api.assert_not_called()

        # Data was not modified.
        organization_refreshed = PrescriberOrganization.objects.get(pk=organization.pk)
        for field in [f for f in PrescriberOrganization._meta.get_fields() if not f.is_relation]:
            assert getattr(organization, field.name) == getattr(organization_refreshed, field.name)

    @pytest.mark.parametrize(
        "factory,assertion",
        [
            (partial(PrescriberOrganizationWithMembershipFactory, authorized=True), assertContains),
            (partial(PrescriberOrganizationWithMembershipFactory, authorized=False), assertNotContains),
        ],
    )
    def test_mask_description(self, client, factory, assertion):
        organization = factory()
        client.force_login(organization.members.first())
        response = client.get(reverse("prescribers_views:edit_organization"))
        assertion(response, '<label class="form-label" for="id_description">Description</label>', html=True)

    @pytest.mark.parametrize(
        "factory,assertion",
        [
            (partial(PrescriberOrganizationWithMembershipFactory, authorized=True), assertContains),
            (partial(PrescriberOrganizationWithMembershipFactory, authorized=False), assertNotContains),
        ],
    )
    def test_display_banner(self, client, factory, assertion):
        organization = factory(
            kind=FuzzyChoice(
                set(PrescriberOrganizationKind.values)
                - {PrescriberOrganizationKind.FT, PrescriberOrganizationKind.OTHER}
            )
        )
        client.force_login(organization.members.first())
        response = client.get(reverse("prescribers_views:edit_organization"))
        assertion(
            response,
            """<p class="mb-0">Les coordonnées de contact de votre organisation sont visibles
                par tous les utilisateurs connectés.</p>""",
            html=True,
        )

    @pytest.mark.parametrize(
        "back_url,expected_redirect",
        [
            (reverse("dashboard:index"), reverse("dashboard:index")),
            (reverse("prescribers_views:overview"), reverse("prescribers_views:overview")),
            ("", reverse("dashboard:index")),
            ("https://evil.org", reverse("dashboard:index")),
        ],
    )
    def test_redirect_after_edit(self, client, back_url, expected_redirect):
        organization = PrescriberOrganizationWithMembershipFactory(kind=PrescriberOrganizationKind.ML, authorized=True)
        user = organization.members.first()

        client.force_login(user)

        url = reverse("prescribers_views:edit_organization") + f"?back_url={back_url}"
        response = client.get(url)
        assert_previous_step(response, expected_redirect)

        post_data = {
            "siret": organization.siret,
            "name": "foo",
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
        }
        with mock.patch(
            "itou.utils.apis.geocoding.call_ban_geocoding_api",
            return_value=BAN_GEOCODING_API_RESULT_MOCK,
        ):
            response = client.post(url, data=post_data)
        assertRedirects(response, expected_redirect)
