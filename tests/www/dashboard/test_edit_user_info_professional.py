import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertRedirects

from itou.companies.models import CompanyMembership
from itou.directory.models import DirectoryProfile
from itou.users.enums import IdentityProvider
from itou.users.models import User
from tests.companies.factories import CompanyMembershipFactory
from tests.institutions.factories import InstitutionMembershipFactory
from tests.prescribers.factories import PrescriberMembershipFactory
from tests.users.factories import EmployerFactory, LaborInspectorFactory, PrescriberFactory, ProfessionalFactory
from tests.www.dashboard.test_edit_user_info_job_seeker import (
    BIRTHDATE_FIELD_NAME,
    DIRECTORY_OPT_OUT_FIELD_ID,
    LACK_OF_NIR_FIELD_ID,
    LACK_OF_NIR_REASON_FIELD_ID,
    NIR_FIELD_ID,
)


def membership_formsets_management_data(company_memberships=(), prescriber_memberships=()):
    return {
        "company_memberships-TOTAL_FORMS": len(company_memberships),
        "company_memberships-INITIAL_FORMS": len(company_memberships),
        "prescriber_memberships-TOTAL_FORMS": len(prescriber_memberships),
        "prescriber_memberships-INITIAL_FORMS": len(prescriber_memberships),
    }


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
        assertContains(
            response, f"<small>Prénom</small> <strong>{original_user.first_name.title()}</strong>", html=True
        )
        assertContains(response, f"<small>Nom</small> <strong>{original_user.last_name.upper()}</strong>", html=True)
        assertContains(response, f"<small>Adresse e-mail</small> <strong>{original_user.email}</strong>", html=True)
        assertContains(response, "Vos informations d’identité viennent de ProConnect", count=1)

        post_data = {
            "email": "notbob@notsaintclair.com",
            "first_name": "Bob",
            "last_name": "Saint Clair",
            "phone": "0610203050",
            **membership_formsets_management_data(),
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 302

        updated_user = User.objects.get(pk=original_user.pk)
        assert updated_user.email == original_user.email
        assert updated_user.first_name == original_user.first_name
        assert updated_user.last_name == original_user.last_name
        assert updated_user.phone == post_data["phone"]

    @pytest.mark.parametrize(
        "professional_factory",
        [PrescriberFactory, EmployerFactory, LaborInspectorFactory],
    )
    def test_directory_opt_out_field_displayed_for_professional(self, client, professional_factory):
        user = professional_factory()
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")
        response = client.get(url)

        assertContains(response, DIRECTORY_OPT_OUT_FIELD_ID)

    def test_professional_can_opt_out_of_directory(self, client):
        user = PrescriberFactory()
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        response = client.post(
            url,
            {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": user.phone,
                "is_directory_opted_out": "on",
                **membership_formsets_management_data(),
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
                **membership_formsets_management_data(),
            },
        )

        assertRedirects(response, reverse("dashboard:index"))
        profile.refresh_from_db()
        assert profile.is_opted_out is False

    def test_function_field_displayed_for_each_organization(self, client):
        user = ProfessionalFactory()
        company_membership = CompanyMembershipFactory(user=user)
        prescriber_membership = PrescriberMembershipFactory(user=user)
        client.force_login(user)

        response = client.get(reverse("dashboard:edit_user_info"))

        assertContains(response, "Fonctions")
        assertContains(response, escape(f"Fonction chez {company_membership.company.display_name}"))
        assertContains(response, escape(f"Fonction chez {prescriber_membership.organization.display_name}"))
        assertContains(response, 'list="membership-function-suggestions"', count=2)
        assertContains(response, '<datalist id="membership-function-suggestions">', count=1)

    def test_function_field_not_displayed_for_institution_member(self, client):
        user = ProfessionalFactory()
        InstitutionMembershipFactory(user=user)
        client.force_login(user)

        response = client.get(reverse("dashboard:edit_user_info"))

        assertNotContains(response, "Fonctions")
        assertNotContains(response, "Fonction chez")

    def test_professional_can_set_function_for_each_organization(self, client):
        COMPANY_FUNCTION = "Directeur"
        PRESCRIBER_FUNCTION = "Conseiller à l'emploi"
        user = ProfessionalFactory()
        company_membership = CompanyMembershipFactory(user=user)
        prescriber_membership = PrescriberMembershipFactory(user=user)
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        with freeze_time():
            now = timezone.now()
            post_data = {
                **membership_formsets_management_data([company_membership], [prescriber_membership]),
                "company_memberships-0-id": company_membership.pk,
                "company_memberships-0-function": COMPANY_FUNCTION,
                "prescriber_memberships-0-id": prescriber_membership.pk,
                "prescriber_memberships-0-function": PRESCRIBER_FUNCTION,
            }
            response = client.post(url, post_data)

        assert response.status_code == 302
        company_membership.refresh_from_db()
        assert company_membership.function == COMPANY_FUNCTION
        assert company_membership.updated_by == user
        assert company_membership.updated_at == now

        prescriber_membership.refresh_from_db()
        assert prescriber_membership.function == PRESCRIBER_FUNCTION
        assert prescriber_membership.updated_by == user
        assert prescriber_membership.updated_at == now

    def test_unchanged_membership_is_not_updated(self, client):
        COMPANY_FUNCTION = "Directeur"
        user = ProfessionalFactory()
        unchanged_membership = CompanyMembershipFactory(user=user, function=COMPANY_FUNCTION)
        client.force_login(user)

        with freeze_time():
            now = timezone.now()
            post_data = {
                **membership_formsets_management_data([unchanged_membership]),
                "company_memberships-0-id": unchanged_membership.pk,
                "company_memberships-0-function": COMPANY_FUNCTION,
            }
            response = client.post(reverse("dashboard:edit_user_info"), post_data)

        assert response.status_code == 302
        unchanged_membership.refresh_from_db()
        assert unchanged_membership.function == COMPANY_FUNCTION
        assert not unchanged_membership.updated_by
        assert unchanged_membership.updated_at < now

    def test_professional_cannot_set_function_of_another_user_membership(self, client):
        user = ProfessionalFactory()
        company_membership = CompanyMembershipFactory(user=user)
        other_user_membership = CompanyMembershipFactory()
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        post_data = {
            **membership_formsets_management_data([company_membership]),
            "company_memberships-0-id": other_user_membership.pk,
            "company_memberships-0-function": "Directeur",
        }
        response = client.post(url, post_data)

        assert response.status_code == 302
        other_user_membership.refresh_from_db()
        company_membership.refresh_from_db()
        assert not other_user_membership.function
        assert not company_membership.function

    def test_professional_cannot_create_membership_with_extra_form(self, client):
        user = ProfessionalFactory()
        company_membership = CompanyMembershipFactory(user=user)
        client.force_login(user)
        url = reverse("dashboard:edit_user_info")

        post_data = {
            **membership_formsets_management_data([company_membership]),
            "company_memberships-TOTAL_FORMS": 2,
            "company_memberships-0-id": company_membership.pk,
            "company_memberships-0-function": "",
            "company_memberships-1-function": "Directeur",
        }
        response = client.post(url, post_data)

        assert response.status_code == 302
        assert CompanyMembership.include_inactive.count() == 1

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
