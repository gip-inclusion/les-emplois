from django.urls import reverse
from django.utils.html import escape
from django.utils.http import urlencode
from pytest_django.asserts import assertContains, assertRedirects

from itou.users.enums import KIND_PRESCRIBER
from tests.users.factories import PrescriberFactory


class TestProfessionalSignup:
    # FIXME: Add a test_choose_user_kind when it's connected to the new signup flow

    def test_user_creation_with_proconnect(self, client, pro_connect):
        start_url = reverse("signup:professional_user")
        response = client.get(start_url)

        # Check ProConnect will redirect to the correct url
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": start_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=start_url,
        )

        response = client.get(response.url)
        assertRedirects(response, reverse("logout:warning", kwargs={"kind": "no_organization"}))

    def test_user_already_exists(self, client, pro_connect):
        # FIXME(alaurent) Allow LaborInspector to use ProConnect
        PrescriberFactory(email=pro_connect.oidc_userinfo["email"], username=pro_connect.oidc_userinfo["sub"])
        start_url = reverse("signup:professional_user")
        response = client.get(start_url)

        # Check ProConnect will redirect to the correct url
        params = {
            "user_kind": KIND_PRESCRIBER,
            "previous_url": start_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            KIND_PRESCRIBER,
            previous_url=start_url,
        )

        response = client.get(response.url)
        assertRedirects(response, reverse("logout:warning", kwargs={"kind": "no_organization"}))
