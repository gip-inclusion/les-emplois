import pytest
from django.urls import reverse
from pytest_django.asserts import assertRedirects

from itou.users.enums import IdentityProvider
from tests.users.factories import EmployerFactory


params_tuples = [
    ("?proconnect_login=true", ""),
    ("?proconnect_login=true&filter=76", "?filter=76"),
    ("?proconnect_login=true&filter=76&kind=EI", "?filter=76&kind=EI"),
]


@pytest.mark.parametrize(
    "params,user,redirection",
    [
        ("", lambda: EmployerFactory(with_company=True), "dashboard:index"),
        ("?param=1", lambda: EmployerFactory(with_company=True), "dashboard:index"),
        ("?param=1&username=2", lambda: EmployerFactory(with_company=True), "dashboard:index"),
        ("", None, "search:employers_home"),
        ("?param=1", None, "search:employers_home"),
        ("?param=1&username=2", None, "search:employers_home"),
    ],
)
def test_middleware_wo_proconnect_login_param(client, db, params, user, redirection):
    if user:
        client.force_login(user())
    response = client.get(f"{reverse('home:hp')}/{params}")
    assertRedirects(response, reverse(redirection), fetch_redirect_response=False)


@pytest.mark.parametrize("params,expected_params", params_tuples)
def test_middleware_for_authenticated_user(client, db, params, expected_params):
    user = EmployerFactory(with_company=True)
    client.force_login(user)

    for username_param in ["", "&username=123-abc"]:
        response = client.get(f"/{params}{username_param}")
        assertRedirects(response, f"/{expected_params}", fetch_redirect_response=False)


@pytest.mark.parametrize("params,expected_params", params_tuples)
def test_middlware_for_non_proconnect_user(client, db, params, expected_params):
    user = EmployerFactory(with_company=True)
    for username_param in ["", "&username=123-abc", f"&username={user.username}"]:
        response = client.get(f"/{params}{username_param}")
        assertRedirects(
            response,
            f"{reverse('signup:choose_user_kind')}?previous_url=/{expected_params}",
            fetch_redirect_response=False,
        )


@pytest.mark.parametrize("params,expected_params", params_tuples)
def test_middleware_for_unlogged_proconnect_user(client, db, params, expected_params):
    user = EmployerFactory(with_company=True, identity_provider=IdentityProvider.PRO_CONNECT)
    response = client.get(f"/{params}&username={user.username}")
    assertRedirects(
        response,
        f"{reverse("pro_connect:authorize")}?user_kind={user.kind}&previous_url=/{expected_params}",
        fetch_redirect_response=False,
    )
