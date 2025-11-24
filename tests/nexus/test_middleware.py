import pytest
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from itou.nexus.utils import generate_jwt
from itou.users.enums import IdentityProvider
from tests.users.factories import EmployerFactory


params_tuples = [
    ({}, ""),
    ({"filter": "76", "username": "123"}, "?filter=76&username=123"),
]


@pytest.mark.parametrize("params,expected_params", params_tuples)
def test_middleware_for_authenticated_user(client, params, expected_params, caplog):
    user = EmployerFactory(membership=True)
    client.force_login(user)
    params["auto_login"] = generate_jwt(user)

    response = client.get(reverse("home:hp", query=params))
    assertRedirects(response, f"/{expected_params}", fetch_redirect_response=False)
    assert caplog.messages == ["Nexus auto login: user is already logged in"]


@pytest.mark.parametrize("params,expected_params", params_tuples)
def test_middleware_for_wrong_authenticated_user(client, params, expected_params, caplog):
    user = EmployerFactory(membership=True)
    params["auto_login"] = generate_jwt(user)
    # Another user is logged in
    client.force_login(EmployerFactory(membership=True))

    response = client.get(reverse("home:hp", query=params))
    assertRedirects(
        response,
        reverse(
            "pro_connect:authorize",
            query={"user_kind": "employer", "next_url": f"/{expected_params}", "user_email": user.email},
        ),
        fetch_redirect_response=False,
    )
    assert caplog.messages == [
        "Nexus auto login: wrong user is logged in -> logging them out",
        f"Nexus auto login: {user} was found and forwarded to ProConnect",
    ]


def test_middleware_multiple_tokens(client, caplog):
    user = EmployerFactory(membership=True)
    params = [("auto_login", generate_jwt(user)), ("auto_login", generate_jwt(user))]
    response = client.get(reverse("home:hp", query=params))
    assertRedirects(response, reverse("home:hp"), fetch_redirect_response=False)
    assert caplog.messages == [
        "Nexus auto login: Multiple tokens found -> ignored",
    ]


def test_middleware_invalid_token(client, caplog):
    params = {"auto_login": "bad jwt"}
    response = client.get(reverse("home:hp", query=params))
    assertRedirects(response, reverse("home:hp"), fetch_redirect_response=False)
    assert caplog.messages == [
        "Could not decrypt jwt",
        "Invalid auto login token",
        "Nexus auto login: Missing email in token -> ignored",
    ]


@pytest.mark.parametrize("params,expected_params", params_tuples)
def test_middleware_with_no_existing_user(client, params, expected_params, caplog):
    jwt = generate_jwt(EmployerFactory.build())
    params["auto_login"] = jwt
    response = client.get(reverse("home:hp", query=params))
    assertRedirects(
        response,
        reverse("signup:choose_user_kind", query={"next_url": f"/{expected_params}"}),
        fetch_redirect_response=False,
    )
    assert caplog.messages == [f"Nexus auto login: no user found for jwt={jwt}"]


@pytest.mark.parametrize("params,expected_params", params_tuples)
def test_middleware_for_unlogged_user(client, params, expected_params, caplog):
    user = EmployerFactory(membership=True)
    params["auto_login"] = generate_jwt(user)

    response = client.get(reverse("home:hp", query=params))
    assertRedirects(
        response,
        reverse(
            "pro_connect:authorize",
            query={"user_kind": "employer", "next_url": f"/{expected_params}", "user_email": user.email},
        ),
        fetch_redirect_response=False,
    )
    assert caplog.messages == [f"Nexus auto login: {user} was found and forwarded to ProConnect"]

    # It also works if it's not a ProConnect user
    user.identity_provider = IdentityProvider.INCLUSION_CONNECT
    user.save()
    caplog.clear()

    response = client.get(reverse("home:hp", query=params))
    assertRedirects(
        response,
        reverse(
            "pro_connect:authorize",
            query={"user_kind": "employer", "next_url": f"/{expected_params}", "user_email": user.email},
        ),
        fetch_redirect_response=False,
    )
    assert caplog.messages == [f"Nexus auto login: {user} was found and forwarded to ProConnect"]
