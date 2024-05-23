import uuid

from django.shortcuts import reverse
from pytest_django.asserts import assertRedirects


class TestNewUser:
    def test_new_user(self, client):
        response = client.get(
            reverse(
                "invitations_views:new_user",
                kwargs={"invitation_type": "invalid", "invitation_id": uuid.uuid4()},
            )
        )
        assertRedirects(response, reverse("search:employers_home"))
