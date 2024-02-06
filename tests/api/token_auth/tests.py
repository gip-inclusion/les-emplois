from django.urls import reverse
from rest_framework.authtoken.models import Token

from tests.users.factories import DEFAULT_PASSWORD, EmployerFactory


def test_token_auth_with_login_password(client):
    user = EmployerFactory()
    assert Token.objects.count() == 0

    url = reverse("v1:token-auth")
    response = client.post(url, data={"username": user.email, "password": DEFAULT_PASSWORD})

    token = Token.objects.get()
    assert response.json() == {"token": token.key}


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
