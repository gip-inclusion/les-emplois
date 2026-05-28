from django.urls import reverse
from django.utils.html import escape
from django.utils.http import urlencode
from pytest_django.asserts import assertContains, assertRedirects

from itou.users.enums import KIND_EMPLOYER, KIND_PRESCRIBER, KIND_PROFESSIONAL
from tests.users.factories import PrescriberFactory
from tests.utils.testing import accept_legal_terms, parse_response_to_soup, pretty_indented


class TestProfessionalSignup:
    def test_choose_user_kind(self, client, snapshot):
        url = reverse("signup:choose_user_kind")
        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

        response = client.post(url, data={"kind": KIND_PROFESSIONAL})
        assertRedirects(response, reverse("signup:professional_user"))

    def test_user_creation_with_proconnect(self, client, pro_connect):
        start_url = reverse("signup:professional_user")
        response = client.get(start_url)

        # Check ProConnect will redirect to the correct url
        next_url = reverse("signup:choose_pro_membership_kind")
        params = {
            "previous_url": start_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        response = pro_connect.mock_oauth_dance(
            client,
            previous_url=start_url,
            next_url=next_url,
        )

        response = accept_legal_terms(client, response)
        assertRedirects(response, next_url)

    def test_user_already_exists(self, client, pro_connect):
        # FIXME(alaurent) Allow LaborInspector to use ProConnect
        PrescriberFactory(email=pro_connect.oidc_userinfo["email"], username=pro_connect.oidc_userinfo["sub"])
        start_url = reverse("signup:professional_user")
        response = client.get(start_url)

        # Check ProConnect will redirect to the correct url
        next_url = reverse("signup:choose_pro_membership_kind")
        params = {
            "previous_url": start_url,
            "next_url": next_url,
        }
        url = escape(f"{pro_connect.authorize_url}?{urlencode(params)}")
        assertContains(response, url + '"')

        # mock_oauth_dance check the response redirects to mock_oauth_dance
        pro_connect.mock_oauth_dance(
            client,
            previous_url=start_url,
            next_url=next_url,
        )

    def test_choose_membership_kind(self, client, snapshot):
        url = reverse("signup:choose_pro_membership_kind")
        response = client.get(url)
        assertRedirects(response, reverse("account_login") + f"?next={url}")

        user = PrescriberFactory()
        client.force_login(user)
        response = client.get(url)
        assert pretty_indented(parse_response_to_soup(response, "#main")) == snapshot

        response = client.post(url, data={"kind": KIND_PRESCRIBER})
        assertRedirects(response, reverse("signup:prescriber_check_already_exists"))
        # The next steps are in tests/www/signup/test_prescriber.py

        response = client.post(url, data={"kind": KIND_EMPLOYER})
        assertRedirects(response, reverse("signup:company_select"))
        # The next steps are in tests/www/signup/test_employer.py
