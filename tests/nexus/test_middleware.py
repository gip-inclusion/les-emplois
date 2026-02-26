import random
from functools import partial

import pytest
from django.conf import settings
from django.urls import reverse
from itoutils.django.nexus.token import generate_auto_login_token
from pytest_django.asserts import assertRedirects

from itou.nexus.enums import Service
from itou.users.enums import IdentityProvider
from tests.companies.factories import CompanyMembershipFactory
from tests.users.factories import (
    EmployerFactory,
    ItouStaffFactory,
    JobSeekerFactory,
    LaborInspectorFactory,
    PrescriberFactory,
)


class TestAutoLoginMiddleware:
    def test_middleware_for_authenticated_user(self, client, caplog):
        user = EmployerFactory(membership=True)
        client.force_login(user)
        params = {"auto_login": generate_auto_login_token(user)}
        response = client.get(reverse("home:hp", query=params))
        assertRedirects(response, "/", fetch_redirect_response=False)
        assert caplog.messages == ["Nexus auto login: user is already logged in"]

    def test_middleware_for_wrong_authenticated_user(self, client, caplog):
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

    def test_middleware_with_no_existing_user(self, client, caplog):
        jwt = generate_auto_login_token(EmployerFactory.build())
        response = client.get(reverse("home:hp", query={"auto_login": jwt}))
        assertRedirects(
            response,
            reverse("signup:choose_user_kind", query={"next_url": "/"}),
            fetch_redirect_response=False,
        )
        assert caplog.messages == [f"Nexus auto login: no user found for jwt={jwt}"]

    def test_middleware_for_unlogged_user(self, client, caplog):
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


class TestDropDownMiddleware:
    def test_context(self, client):
        user = EmployerFactory()
        CompanyMembershipFactory(user=user, company__post_code=random.choice(settings.NEXUS_MVP_DEPARTMENTS))
        client.force_login(user)
        response = client.get(reverse("dashboard:index"))
        assert response.wsgi_request.nexus_dropdown == {
            "proconnect": True,
            "activated_services": [Service.EMPLOIS],
            "mvp_enabled": True,
        }

    def test_nexus_page(self, client):
        user = EmployerFactory()
        CompanyMembershipFactory(user=user, company__post_code=random.choice(settings.NEXUS_MVP_DEPARTMENTS))
        client.force_login(user)
        response = client.get(reverse("nexus:homepage"))
        assert response.wsgi_request.nexus_dropdown == {}

    @pytest.mark.parametrize(
        "factory", [JobSeekerFactory, partial(LaborInspectorFactory, membership=True), ItouStaffFactory]
    )
    def test_wrong_user_kind(self, client, factory):
        user = factory()
        client.force_login(user)
        response = client.get(reverse("dashboard:index"))
        assert response.wsgi_request.nexus_dropdown == {}

    def test_inactive_user(self, client):
        user = PrescriberFactory(is_active=False)
        client.force_login(user)
        response = client.get(reverse("dashboard:index"))
        assert response.wsgi_request.nexus_dropdown == {}

    def test_unauthenticated_user(self, client):
        response = client.get(reverse("dashboard:index"))
        assert response.wsgi_request.nexus_dropdown == {}
