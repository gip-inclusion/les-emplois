import pytest
from django.shortcuts import reverse
from pytest_django.asserts import (
    assertRedirects,
)

from itou.utils import constants as global_constants
from tests.prescribers.factories import (
    PrescriberPoleEmploiFactory,
)
from tests.users.factories import (
    PrescriberFactory,
)


INVITATION_URL = reverse("invitations_views:invite_prescriber_with_org")


class TestPEOrganizationInvitation:
    @pytest.mark.parametrize(
        "suffix",
        [
            global_constants.POLE_EMPLOI_EMAIL_SUFFIX,
            global_constants.FRANCE_TRAVAIL_EMAIL_SUFFIX,
        ],
    )
    def test_successful(self, client, suffix):
        organization = PrescriberPoleEmploiFactory()
        organization.members.add(PrescriberFactory())
        sender = organization.members.first()
        guest = PrescriberFactory.build(email=f"sabine.lagrange{suffix}")
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": guest.first_name,
            "form-0-last_name": guest.last_name,
            "form-0-email": guest.email,
        }
        client.force_login(sender)
        response = client.post(INVITATION_URL, data=post_data, follow=True)
        assertRedirects(response, reverse("prescribers_views:members"))

    def test_unsuccessful(self, client):
        organization = PrescriberPoleEmploiFactory()
        organization.members.add(PrescriberFactory())
        sender = organization.members.first()
        client.force_login(sender)
        post_data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "",
            "form-MAX_NUM_FORMS": "",
            "form-0-first_name": "René",
            "form-0-last_name": "Boucher",
            "form-0-email": "rene@example.com",
        }

        response = client.post(INVITATION_URL, data=post_data)
        # Make sure form is invalid
        assert not response.context["formset"].is_valid()
        assert (
            response.context["formset"].errors[0]["email"][0]
            == "L'adresse e-mail doit être une adresse Pôle emploi ou France Travail."
        )
