import uuid

from django.urls import reverse
from pytest_django.asserts import assertContains

from tests.users.factories import random_user_kind_factory


def test_non_superuser(client):
    user = random_user_kind_factory()
    client.force_login(user)
    assert client.get(reverse("selftest:headers")).status_code == 403


def test_superuser(admin_client):
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
