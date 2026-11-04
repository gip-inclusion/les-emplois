import uuid

from django.urls import reverse
from pytest_django.asserts import assertContains

from tests.users.factories import random_user_kind_factory


class TestHeaders:
    def test_non_superuser(self, client):
        user = random_user_kind_factory()
        client.force_login(user)
        assert client.get(reverse("selftest:headers")).status_code == 403

    def test_superuser(self, admin_client):
        random_string = str(uuid.uuid4())
        assertContains(
            admin_client.get(reverse("selftest:headers"), headers={"FooBar": random_string}),
            f"""
            <tr>
                <td>Foobar</td>
                <td>{random_string}</td>
            </tr>
            """,
            html=True,
        )


class TestSettings:
    def test_non_superuser(self, client):
        user = random_user_kind_factory()
        client.force_login(user)
        response = reverse("selftest:settings")
        assert client.get(response).status_code == 403

    def test_superuser(self, admin_client):
        response = admin_client.get(reverse("selftest:settings"))
        assertContains(
            response,
            """
            <tbody>
            <tr>
                <td>WEB_SERVER_MODE</td>
                <td>False</td>
            </tr>
            <tr>
                <td>REQUIRE_MFA_ON_COMPANY_IDS</td>
                <td>set()</td>
            </tr>
            <tr>
                <td>REQUIRE_MFA_ON_ORGANIZATION_IDS</td>
                <td>set()</td>
            </tr>
            </tbody>
            """,
            html=True,
        )
