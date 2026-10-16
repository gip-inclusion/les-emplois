from django.urls import reverse
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.directory.models import DirectoryProfile
from itou.users.enums import IdentityProvider
from itou.users.models import User
from tests.users.factories import PrescriberFactory
from tests.www.dashboard.test_edit_user_info_job_seeker import (
    BIRTHDATE_FIELD_NAME,
    LACK_OF_NIR_FIELD_ID,
    LACK_OF_NIR_REASON_FIELD_ID,
    NIR_FIELD_ID,
)


class TestEditUserInfoView:
    def test_edit_as_prescriber_PC(self, client):
        original_user = PrescriberFactory(
            email="bob@saintclair.tld",
            first_name="Not Bob",
            last_name="Not Saint Clair",
            phone="0600000000",
        )
        client.force_login(original_user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)
        assertNotContains(response, NIR_FIELD_ID)
        assertNotContains(response, LACK_OF_NIR_FIELD_ID)
        assertNotContains(response, LACK_OF_NIR_REASON_FIELD_ID)
        assertNotContains(response, BIRTHDATE_FIELD_NAME)
        assertContains(response, f"Prénom : <strong>{original_user.first_name.title()}</strong>")
        assertContains(response, f"Nom : <strong>{original_user.last_name.upper()}</strong>")
        assertContains(response, f"Adresse e-mail : <strong>{original_user.email}</strong>")
        assertContains(response, "Vos informations d’identité viennent de ProConnect", count=1)

        post_data = {
            "email": "notbob@notsaintclair.com",
            "first_name": "Bob",
            "last_name": "Saint Clair",
            "phone": "0610203050",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 302

        updated_user = User.objects.get(pk=original_user.pk)
        assert updated_user.email == original_user.email
        assert updated_user.first_name == original_user.first_name
        assert updated_user.last_name == original_user.last_name
        assert updated_user.phone == post_data["phone"]

    def test_professional_can_opt_out_of_directory(self, client):
        user = PrescriberFactory()
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        response = client.get(url)

        assertContains(response, "Annuaire des professionnels")
        assertContains(response, "Ne pas apparaître dans l&#x27;annuaire des professionnels")

        response = client.post(
            url,
            {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": user.phone,
                "is_directory_opted_out": "on",
            },
        )

        assertRedirects(response, reverse("dashboard:index"))
        profile = DirectoryProfile.objects.get(user=user)
        assert profile.is_opted_out is True

        response = client.get(url)
        assert response.context["form"]["is_directory_opted_out"].value() is True

        response = client.post(
            url,
            {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": user.phone,
            },
        )

        assertRedirects(response, reverse("dashboard:index"))
        profile.refresh_from_db()
        assert profile.is_opted_out is False

    def test_edit_user_sso_alert(self, client):
        ALERT_COMPONENT = (
            "Pour les modifier, rendez-vous directement sur votre compte "
            '<a href="https://identite.proconnect.gouv.fr/personal-information" target="_blank" '
            'class="has-external-link" rel="noopener" '
            'aria-label="Votre compte ProConnect (ouverture dans un nouvel onglet)"> ProConnect</a> . '
            "Les changements seront automatiquement répercutés ici lors de votre prochaine connexion. "
            "En cas de difficultés, rapprochez-vous de "
            '<a href="https://proconnect.crisp.help/fr/" target="_blank" class="has-external-link" rel="noopener" '
            'aria-label="Service d’aide de ProConnect (ouverture dans un nouvel onglet)">leur service d’aide</a>. '
            "Une fois modifiées, vos informations seront mises à jour à votre prochaine connexion."
        )

        user = PrescriberFactory(identity_provider=IdentityProvider.PRO_CONNECT)

        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)

        assertContains(response, f"Vos informations d’identité viennent de {IdentityProvider.PRO_CONNECT.label}")
        # djlint wraps long tags over several lines
        normalized_content = " ".join(response.content.decode().split())
        assert ALERT_COMPONENT in normalized_content
