from django.contrib import messages
from django.contrib.auth import get_user
from django.urls import reverse
from pytest_django.asserts import assertMessages, assertRedirects

from tests.users.factories import JobSeekerFactory
from tests.utils.test import parse_response_to_soup


class TestLogoutView:
    def test_logout(self, client, snapshot):
        client.force_login(user=JobSeekerFactory())

        url = reverse("accounts:account_logout")
        response = client.get(url)
        assert str(parse_response_to_soup(response, "#main")) == snapshot
        user = get_user(client)
        assert user.is_authenticated

        response = client.post(url)
        assertRedirects(response, reverse("search:employers_home"))
        assert get_user(client).is_authenticated is False
        assertMessages(response, [messages.Message(messages.SUCCESS, "Vous êtes déconnecté(e).")])
