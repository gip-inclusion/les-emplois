from django.urls import reverse
from itoutils.django.nexus.token import generate_auto_login_token
from pytest_django.asserts import assertRedirects

from itou.users.enums import IdentityProvider
from tests.users.factories import EmployerFactory


def test_middleware_for_authenticated_user(client, caplog):
    user = EmployerFactory(membership=True)
    client.force_login(user)
    params = {"auto_login": generate_auto_login_token(user)}
    response = client.get(reverse("home:hp", query=params))
    assertRedirects(response, "/", fetch_redirect_response=False)
    assert caplog.messages == ["Nexus auto login: user is already logged in"]


def test_middleware_for_wrong_authenticated_user(client, caplog):
    user = EmployerFactory(membership=True)
    params = {"auto_login": generate_auto_login_token(user)}
    # Another user is logged in
    client.force_login(EmployerFactory(membership=True))

    response = client.get(reverse("home:hp", query=params))
    assertRedirects(
        response,
        reverse(
            "pro_connect:authorize",
            query={"user_kind": "employer", "next_url": "/", "user_email": user.email},
        ),
        fetch_redirect_response=False,
    )
    assert caplog.messages == [
        "Nexus auto login: wrong user is logged in -> logging them out",
        f"Nexus auto login: {user} was found and forwarded to ProConnect",
    ]


def test_middleware_with_no_existing_user(client, caplog):
    jwt = generate_auto_login_token(EmployerFactory.build())
    response = client.get(reverse("home:hp", query={"auto_login": jwt}))
    assertRedirects(
        response,
        reverse("signup:choose_user_kind", query={"next_url": "/"}),
        fetch_redirect_response=False,
    )
    assert caplog.messages == [f"Nexus auto login: no user found for jwt={jwt}"]


def test_middleware_for_unlogged_user(client, caplog):
    user = EmployerFactory(membership=True)
    params = {"auto_login": generate_auto_login_token(user)}

    response = client.get(reverse("home:hp", query=params))
    assertRedirects(
        response,
        reverse(
            "pro_connect:authorize",
            query={"user_kind": "employer", "next_url": "/", "user_email": user.email},
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
            query={"user_kind": "employer", "next_url": "/", "user_email": user.email},
        ),
        fetch_redirect_response=False,
    )
    assert caplog.messages == [f"Nexus auto login: {user} was found and forwarded to ProConnect"]
