import uuid

from django.shortcuts import reverse


class TestNewUser:
    def test_new_user(self, client):
        response = client.get(
            reverse(
                "invitations_views:new_user",
                kwargs={"invitation_type": "invalid", "invitation_id": uuid.uuid4()},
            )
        )
        assert response.status_code == 404
