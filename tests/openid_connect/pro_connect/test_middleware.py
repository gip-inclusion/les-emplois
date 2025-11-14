import pytest
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from itou.users.enums import IdentityProvider
from itou.utils.templatetags.url_add_query import generate_proconnect_login_jwt
from tests.users.factories import EmployerFactory


old_params_tuples = [
    # FIXME: Old values
    ("?proconnect_login=true", ""),
    ("?proconnect_login=true&filter=76&kind=EI", "?filter=76&kind=EI"),
]


params_tuples = [
    ({}, ""),
    ({"filter": "76", "username": "123"}, "?filter=76&username=123"),
]


def test_middleware_wo_proconnect_login_param(client):
    url = reverse("home:hp", query={"param": "1", "username": "2"})

    response = client.get(url)
    assertRedirects(response, reverse("search:employers_home"), fetch_redirect_response=False)

    client.force_login(EmployerFactory(membership=True))
    response = client.get(url)
    assertRedirects(response, reverse("dashboard:index"), fetch_redirect_response=False)


@pytest.mark.parametrize("params,expected_params", params_tuples)
def test_middleware_for_authenticated_user(client, params, expected_params):
    user = EmployerFactory(membership=True)
    client.force_login(user)
    params["proconnect_login"] = generate_proconnect_login_jwt(user)

    response = client.get(reverse("home:hp", query=params))
    assertRedirects(response, f"/{expected_params}", fetch_redirect_response=False)

    # Same with if the authenticated user has the wrong email
    user.email = "not_jean_dupond@mailinator.net"
    user.save()

    response = client.get(reverse("home:hp", query=params))
    assertRedirects(response, f"/{expected_params}", fetch_redirect_response=False)


def test_middleware_invalid_token(client, caplog):
    params = {"proconnect_login": "bad jwt"}
    response = client.get(reverse("home:hp", query=params))
    assertRedirects(
        response,
        reverse("signup:choose_user_kind", query={"next_url": "/"}),
        fetch_redirect_response=False,
    )
    assert caplog.messages == ["Invalid proconnect_login token"]


@pytest.mark.parametrize("params,expected_params", params_tuples)
def test_middlware_with_no_existing_user(client, params, expected_params):
    params["proconnect_login"] = generate_proconnect_login_jwt(EmployerFactory.build())
    response = client.get(reverse("home:hp", query=params))
    assertRedirects(
        response,
        reverse("signup:choose_user_kind", query={"next_url": f"/{expected_params}"}),
        fetch_redirect_response=False,
    )


@pytest.mark.parametrize("params,expected_params", params_tuples)
def test_middleware_for_unlogged_user(client, params, expected_params):
    user = EmployerFactory(membership=True)
    params["proconnect_login"] = generate_proconnect_login_jwt(user)

    response = client.get(reverse("home:hp", query=params))
    assertRedirects(
        response,
        reverse(
            "pro_connect:authorize",
            query={"user_kind": "employer", "next_url": f"/{expected_params}", "user_email": user.email},
        ),
        fetch_redirect_response=False,
    )

    # It also works if it's not a ProConect user
    user.identity_provider = IdentityProvider.INCLUSION_CONNECT
    user.save()

    response = client.get(reverse("home:hp", query=params))
    assertRedirects(
        response,
        reverse(
            "pro_connect:authorize",
            query={"user_kind": "employer", "next_url": f"/{expected_params}", "user_email": user.email},
        ),
        fetch_redirect_response=False,
    )


@pytest.mark.parametrize("params,expected_params", old_params_tuples)
def test_middleware_for_authenticated_user_old(client, db, params, expected_params):
    user = EmployerFactory(membership=True)
    client.force_login(user)

    for username_param in ["", "&username=123-abc"]:
        response = client.get(f"/{params}{username_param}")
        assertRedirects(response, f"/{expected_params}", fetch_redirect_response=False)


@pytest.mark.parametrize("params,expected_params", old_params_tuples)
def test_middlware_for_non_proconnect_user_old(client, db, params, expected_params):
    user = EmployerFactory(membership=True, identity_provider=IdentityProvider.INCLUSION_CONNECT)
    for username_param in ["", "&username=123-abc", f"&username={user.username}"]:
        response = client.get(f"/{params}{username_param}")
        assertRedirects(
            response,
            reverse("signup:choose_user_kind", query={"next_url": f"/{expected_params}"}),
            fetch_redirect_response=False,
        )


@pytest.mark.parametrize("params,expected_params", old_params_tuples)
def test_middleware_for_unlogged_proconnect_user_old(client, db, params, expected_params):
    user = EmployerFactory(membership=True, identity_provider=IdentityProvider.PRO_CONNECT)
    response = client.get(f"/{params}&username={user.username}")
    assertRedirects(
        response,
        reverse(
            "pro_connect:authorize",
            query={"user_kind": "employer", "next_url": f"/{expected_params}", "user_email": user.email},
        ),
        fetch_redirect_response=False,
    )
