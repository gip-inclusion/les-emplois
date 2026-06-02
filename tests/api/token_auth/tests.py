import pytest
from django.urls import reverse
from rest_framework.authtoken.models import Token

from itou.users.enums import IdentityProvider
from tests.users.factories import DEFAULT_PASSWORD, EmployerFactory


@pytest.mark.parametrize(
    "identity_provider,expects_creation",
    [
        (IdentityProvider.DJANGO, True),
        (IdentityProvider.PRO_CONNECT, False),
    ],
    ids=["django", "pro_connect"],
)
def test_token_auth_with_login_password(client, identity_provider, expects_creation):
    user = EmployerFactory(with_password=True, identity_provider=identity_provider)
    assert not Token.objects.exists()
    response = client.post(reverse("v1:token-auth"), data={"username": user.email, "password": DEFAULT_PASSWORD})
    if expects_creation:
        token = Token.objects.get()
        assert response.json() == {"token": token.key}
    else:
        assert response.status_code == 400
        assert not Token.objects.exists()


def test_token_auth_with_token(client):
    user = EmployerFactory()
    token = Token(user=user)
    assert Token.objects.count() == 0

    url = reverse("v1:token-auth")
    response = client.post(url, data={"username": "__token__", "password": token.key})
    assert response.status_code == 400

    token.save()
    response = client.post(url, data={"username": "__token__", "password": token.key})
    assert response.json() == {"token": token.key}

    # Don't crash on missing field
    response = client.post(url, data={"username": "__token__"})
    assert response.status_code == 400
