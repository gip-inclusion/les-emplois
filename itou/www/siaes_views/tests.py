from unittest import mock

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.utils.html import escape

from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.siaes.factories import (
    SiaeFactory,
    SiaeWith2MembershipsFactory,
    SiaeWithMembershipAndJobsFactory,
    SiaeWithMembershipFactory,
)
from itou.siaes.models import Siae
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_RESULT_MOCK


class CardViewTest(TestCase):
    def test_card(self):
        siae = SiaeWithMembershipFactory()
        url = reverse("siaes_views:card", kwargs={"siae_id": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["siae"], siae)
        self.assertContains(response, escape(siae.display_name))
        self.assertContains(response, siae.email)
        self.assertContains(response, siae.phone)


class JobDescriptionCardViewTest(TestCase):
    def test_job_description_card(self):
        siae = SiaeWithMembershipAndJobsFactory()
        job_description = siae.job_description_through.first()
        job_description.description = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
        job_description.save()
        url = reverse("siaes_views:job_description_card", kwargs={"job_description_id": job_description.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["job"], job_description)
        self.assertEqual(response.context["siae"], siae)
        self.assertContains(response, job_description.description)
        self.assertContains(response, escape(job_description.display_name))
        self.assertContains(response, escape(siae.display_name))


class ConfigureJobsViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.

        siae = SiaeWithMembershipFactory()
        user = siae.members.first()

        create_test_romes_and_appellations(["N1101", "N1105", "N1103", "N4105"])
        appellations = Appellation.objects.filter(
            name__in=[
                "Agent / Agente cariste de livraison ferroviaire",
                "Agent / Agente de quai manutentionnaire",
                "Agent magasinier / Agente magasinière gestionnaire de stocks",
                "Chauffeur-livreur / Chauffeuse-livreuse",
            ]
        )
        siae.jobs.add(*appellations)

        cls.siae = siae
        cls.user = user

        cls.url = reverse("siaes_views:configure_jobs")

    def test_access(self):

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_content(self):

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(self.siae.jobs.count(), 4)
        response_content = str(response.content)
        for appellation in self.siae.jobs.all():
            self.assertIn(f'value="{appellation.code}"', response_content)
            self.assertIn(f'name="is_active-{appellation.code}"', response_content)

    def test_update(self):

        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            # List of appellations codes that we will operate on.
            "code": ["10357", "10579", "10750", "10877", "16361"],
            # Do nothing for "Agent / Agente cariste de livraison ferroviaire"
            "is_active-10357": "on",  # "on" is set when the checkbox is checked.
            # Update "Agent / Agente de quai manutentionnaire"
            "custom-name-10579": "Agent de quai",
            "description-10579": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "is_active-10579": "",
            # Update "Agent magasinier / Agente magasinière gestionnaire de stocks"
            "is_active-10750": "",
            "custom-name-10750": "",
            "description-10750": "",
            # Delete for "Chauffeur-livreur / Chauffeuse-livreuse"
            # Exclude code `11999` from POST payload.
            # Add "Aide-livreur / Aide-livreuse"
            "is_active-10877": "on",
            "custom-name-10877": "Aide-livreur hebdomadaire",
            "description-10877": "Pellentesque ex ex, elementum sed sollicitudin sit amet, dictum vel elit.",
            # Add "Manutentionnaire"
            "is_active-16361": "",
        }

        response = self.client.post(self.url, data=post_data)
        self.assertEqual(response.status_code, 302)

        self.assertEqual(self.siae.jobs.count(), 5)
        self.assertEqual(self.siae.job_description_through.count(), 5)

        self.assertTrue(self.siae.job_description_through.get(appellation_id=10357, is_active=True))
        self.assertTrue(
            self.siae.job_description_through.get(
                appellation_id=10579,
                is_active=False,
                custom_name=post_data["custom-name-10579"],
                description=post_data["description-10579"],
            )
        )
        self.assertTrue(
            self.siae.job_description_through.get(
                appellation_id=10750,
                is_active=False,
                custom_name=post_data["custom-name-10750"],
                description=post_data["description-10750"],
            )
        )
        self.assertTrue(
            self.siae.job_description_through.get(
                appellation_id=10877,
                is_active=True,
                custom_name=post_data["custom-name-10877"],
                description=post_data["description-10877"],
            )
        )
        self.assertTrue(self.siae.job_description_through.get(appellation_id=16361, is_active=False))


class CreateSiaeViewTest(TestCase):
    def test_create_non_preexisting_siae_outside_of_siren_fails(self):

        siae = SiaeWithMembershipFactory()
        user = siae.members.first()

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("siaes_views:create_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        new_siren = "9876543210"
        new_siret = f"{new_siren}1234"
        self.assertNotEqual(siae.siren, new_siren)
        self.assertFalse(Siae.objects.filter(siret=new_siret).exists())

        post_data = {
            "siret": new_siret,
            "kind": siae.kind,
            "name": "FAMOUS SIAE SUB STRUCTURE",
            "source": Siae.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-siae.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

        expected_message = f"Le SIRET doit commencer par le SIREN {siae.siren}"
        self.assertContains(response, escape(expected_message))
        expected_message = "La structure à laquelle vous souhaitez vous rattacher est déjà"
        self.assertNotContains(response, escape(expected_message))

        self.assertFalse(Siae.objects.filter(siret=post_data["siret"]).exists())

    def test_create_preexisting_siae_outside_of_siren_fails(self):

        siae = SiaeWithMembershipFactory()
        user = siae.members.first()

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("siaes_views:create_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        preexisting_siae = SiaeFactory()
        new_siret = preexisting_siae.siret
        self.assertNotEqual(siae.siren, preexisting_siae.siren)
        self.assertTrue(Siae.objects.filter(siret=new_siret).exists())

        post_data = {
            "siret": new_siret,
            "kind": preexisting_siae.kind,
            "name": "FAMOUS SIAE SUB STRUCTURE",
            "source": Siae.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-siae.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

        expected_message = "Le SIRET doit commencer par le SIREN"
        self.assertNotContains(response, escape(expected_message))
        expected_message = "La structure à laquelle vous souhaitez vous rattacher est déjà"
        self.assertContains(response, escape(expected_message))

        self.assertEqual(Siae.objects.filter(siret=post_data["siret"]).count(), 1)

    def test_cannot_create_siae_with_same_siret_and_same_kind(self):

        siae = SiaeWithMembershipFactory()
        user = siae.members.first()

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("siaes_views:create_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "siret": siae.siret,
            "kind": siae.kind,
            "name": "FAMOUS SIAE SUB STRUCTURE",
            "source": Siae.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-siae.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

        expected_message = "Le SIRET doit commencer par le SIREN"
        self.assertNotContains(response, escape(expected_message))
        expected_message = "La structure à laquelle vous souhaitez vous rattacher est déjà"
        self.assertContains(response, escape(expected_message))

        self.assertEqual(Siae.objects.filter(siret=post_data["siret"]).count(), 1)

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_cannot_create_siae_with_same_siret_and_different_kind(self, mock_call_ban_geocoding_api):
        siae = SiaeWithMembershipFactory()
        siae.kind = Siae.KIND_ETTI
        siae.save()
        user = siae.members.first()

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("siaes_views:create_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "siret": siae.siret,
            "kind": Siae.KIND_ACI,
            "name": "FAMOUS SIAE SUB STRUCTURE",
            "source": Siae.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-siae.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(Siae.objects.filter(siret=post_data["siret"]).count(), 1)

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_cannot_create_siae_with_same_siren_and_different_kind(self, mock_call_ban_geocoding_api):
        siae = SiaeWithMembershipFactory()
        siae.kind = Siae.KIND_ETTI
        siae.save()
        user = siae.members.first()

        new_siret = siae.siren + "12345"
        self.assertNotEqual(siae.siret, new_siret)

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("siaes_views:create_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "siret": new_siret,
            "kind": Siae.KIND_ACI,
            "name": "FAMOUS SIAE SUB STRUCTURE",
            "source": Siae.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-siae.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(Siae.objects.filter(siret=siae.siret).count(), 1)
        self.assertEqual(Siae.objects.filter(siret=new_siret).count(), 0)

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_create_siae_with_same_siren_and_same_kind(self, mock_call_ban_geocoding_api):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("siaes_views:create_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        new_siret = siae.siren + "12345"
        self.assertNotEqual(siae.siret, new_siret)

        post_data = {
            "siret": new_siret,
            "kind": siae.kind,
            "name": "FAMOUS SIAE SUB STRUCTURE",
            "source": Siae.SOURCE_USER_CREATED,
            "address_line_1": "2 Rue de Soufflenheim",
            "city": "Betschdorf",
            "post_code": "67660",
            "department": "67",
            "email": "",
            "phone": "0610203050",
            "website": "https://famous-siae.com",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        mock_call_ban_geocoding_api.assert_called_once()

        new_siae = Siae.objects.get(siret=new_siret)
        self.assertTrue(new_siae.has_admin(user))
        self.assertEqual(siae.source, Siae.SOURCE_ASP)
        self.assertEqual(new_siae.source, Siae.SOURCE_USER_CREATED)
        self.assertEqual(new_siae.siret, post_data["siret"])
        self.assertEqual(new_siae.kind, post_data["kind"])
        self.assertEqual(new_siae.name, post_data["name"])
        self.assertEqual(new_siae.address_line_1, post_data["address_line_1"])
        self.assertEqual(new_siae.city, post_data["city"])
        self.assertEqual(new_siae.post_code, post_data["post_code"])
        self.assertEqual(new_siae.department, post_data["department"])
        self.assertEqual(new_siae.email, post_data["email"])
        self.assertEqual(new_siae.phone, post_data["phone"])
        self.assertEqual(new_siae.website, post_data["website"])
        self.assertEqual(new_siae.description, post_data["description"])
        self.assertEqual(new_siae.created_by, user)
        self.assertEqual(new_siae.source, Siae.SOURCE_USER_CREATED)
        self.assertTrue(new_siae.is_active)
        self.assertTrue(new_siae.convention is not None)
        self.assertEqual(siae.convention, new_siae.convention)

        # This data comes from BAN_GEOCODING_API_RESULT_MOCK.
        self.assertEqual(new_siae.coords, "SRID=4326;POINT (2.316754 48.838411)")
        self.assertEqual(new_siae.latitude, 48.838411)
        self.assertEqual(new_siae.longitude, 2.316754)
        self.assertEqual(new_siae.geocoding_score, 0.587663373207207)


class EditSiaeViewTest(TestCase):
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_edit(self, mock_call_ban_geocoding_api):

        siae = SiaeWithMembershipFactory()
        user = siae.members.first()

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("siaes_views:edit_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "brand": "NEW FAMOUS SIAE BRAND NAME",
            "description": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "phone": "0610203050",
            "email": "",
            "website": "https://famous-siae.com",
            "address_line_1": "1 Rue Jeanne d'Arc",
            "address_line_2": "",
            "post_code": "62000",
            "city": "Arras",
            "department": "62",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        siae = Siae.objects.get(siret=siae.siret)

        self.assertEqual(siae.brand, post_data["brand"])
        self.assertEqual(siae.description, post_data["description"])
        self.assertEqual(siae.email, post_data["email"])
        self.assertEqual(siae.phone, post_data["phone"])
        self.assertEqual(siae.website, post_data["website"])

        self.assertEqual(siae.address_line_1, post_data["address_line_1"])
        self.assertEqual(siae.address_line_2, post_data["address_line_2"])
        self.assertEqual(siae.post_code, post_data["post_code"])
        self.assertEqual(siae.city, post_data["city"])
        self.assertEqual(siae.department, post_data["department"])

        # This data comes from BAN_GEOCODING_API_RESULT_MOCK.
        self.assertEqual(siae.coords, "SRID=4326;POINT (2.316754 48.838411)")
        self.assertEqual(siae.latitude, 48.838411)
        self.assertEqual(siae.longitude, 2.316754)
        self.assertEqual(siae.geocoding_score, 0.587663373207207)


class MembersTest(TestCase):
    def test_members(self):
        siae = SiaeWithMembershipFactory()
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("siaes_views:members")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class BlockJobApplicationsTest(TestCase):
    def test_block_direct_job_application(self):
        """
        Check if user is trying to get to job application directly via URL
        """
        siae = SiaeWithMembershipAndJobsFactory(block_job_applications=True)

        user = JobSeekerFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

        # Check for member of the SIAE: should pass
        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_toggle_blocking(self):
        """Testing enabling / disabling job applications blocking and checking results"""

        # Avoid errors in validation of the SIAE
        siae = SiaeWithMembershipFactory(department="67", post_code="67020")

        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("siaes_views:block_job_applications")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["current_siae"], siae)

        post_data = {"block_job_applications": "on"}

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        siae = Siae.objects.get(siret=siae.siret)
        self.assertTrue(siae.block_job_applications)
        self.assertIsNotNone(siae.job_applications_blocked_at)

        block_date = siae.job_applications_blocked_at

        post_data = {"block_job_applications": ""}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        siae = Siae.objects.get(siret=siae.siret)
        self.assertFalse(siae.block_job_applications)
        self.assertEqual(siae.job_applications_blocked_at, block_date)

        post_data = {"block_job_applications": "on"}

        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        siae = Siae.objects.get(siret=siae.siret)
        self.assertTrue(siae.block_job_applications)
        self.assertNotEqual(block_date, siae.job_applications_blocked_at)


class UserMembershipDeactivationTest(TestCase):
    def test_self_deactivation(self):
        """
        A user, even if admin, can't self-deactivate
        (must be done by another admin)
        """
        siae = SiaeWithMembershipFactory()
        admin = siae.members.first()
        memberships = admin.siaemembership_set.all()
        membership = memberships.first()

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("siaes_views:deactivate_member", kwargs={"user_id": admin.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

        # Trying to change self membership is not allowed
        # but does not raise an error (does nothing)
        membership.refresh_from_db()
        self.assertTrue(membership.is_active)

    def test_deactivate_user(self):
        """
        Standard use case of user deactivation.
        Everything should be fine ...
        """
        siae = SiaeWith2MembershipsFactory()
        admin = siae.members.first()
        guest = siae.members.all()[1]

        membership = guest.siaemembership_set.first()
        self.assertFalse(guest in siae.active_admin_members)
        self.assertTrue(admin in siae.active_admin_members)

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("siaes_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # User should be deactivated now
        membership.refresh_from_db()
        self.assertFalse(membership.is_active)
        self.assertEqual(admin, membership.updated_by)
        self.assertIsNotNone(membership.updated_at)

        # Check mailbox
        # User must have been notified of deactivation (we're human after all)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("[Désactivation] Vous n'êtes plus membre de", email.subject)
        self.assertIn("Un administrateur vous a retiré d'une structure sur la Plateforme de l'inclusion", email.body)
        self.assertEqual(email.to[0], guest.email)

    def test_deactivate_with_no_perms(self):
        """
        Non-admin user can't change memberships
        """
        siae = SiaeWith2MembershipsFactory()
        guest = siae.members.all()[1]
        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        url = reverse("siaes_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_user_with_no_siae_left(self):
        """
        Former SIAE members with no SIAE membership left must not
        be able to log in.
        They are still "active" technically speaking, so if they
        are activated/invited again, they will be able to log in.
        """
        siae = SiaeWith2MembershipsFactory()
        admin, guest = siae.members.all()

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("siaes_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.client.logout()

        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:index")
        response = self.client.get(url)

        # should be redirected to logout
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("account_logout"))

    def test_structure_selector(self):
        """
        Check that a deactivated member can't access the structure
        from the dashboard selector
        """
        siae2 = SiaeWithMembershipFactory()
        guest = siae2.members.first()

        siae = SiaeWith2MembershipsFactory()
        admin = siae.members.first()
        siae.members.add(guest)

        memberships = guest.siaemembership_set.all()
        self.assertEqual(len(memberships), 2)

        # Admin remove guest from structure
        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("siaes_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.client.logout()

        # guest must be able to login
        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        url = reverse("dashboard:index")
        response = self.client.get(url)

        # Wherever guest lands should give a 200 OK
        self.assertEqual(response.status_code, 200)

        # Check response context, only one SIAE should remain
        self.assertEqual(len(response.context["user_siaes"]), 1)


class SIAEAdminMembersManagementTest(TestCase):
    def test_add_admin(self):
        """
        Check the ability for an admin to add another admin to the siae
        """
        siae = SiaeWith2MembershipsFactory()
        admin, guest = siae.members.all()

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("siaes_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        # Redirection to confirm page
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Confirm action
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        siae.refresh_from_db()
        self.assertTrue(guest in siae.active_admin_members)

    def test_remove_admin(self):
        """
        Check the ability for an admin to remove another admin
        """
        siae = SiaeWith2MembershipsFactory()
        admin, guest = siae.members.all()

        membership = guest.siaemembership_set.first()
        membership.is_siae_admin = True
        membership.save()
        self.assertTrue(guest in siae.active_admin_members)

        self.client.login(username=admin.email, password=DEFAULT_PASSWORD)
        url = reverse("siaes_views:update_admin_role", kwargs={"action": "remove", "user_id": guest.id})

        # Redirection to confirm page
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Confirm action
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        siae.refresh_from_db()
        self.assertFalse(guest in siae.active_admin_members)

    def test_admin_management_permissions(self):
        """
        Non-admin users can't update admin members
        """
        siae = SiaeWith2MembershipsFactory()
        admin, guest = siae.members.all()

        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        url = reverse("siaes_views:update_admin_role", kwargs={"action": "remove", "user_id": admin.id})

        # Redirection to confirm page
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        # Confirm action
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

        # Add self as admin with no privilege
        url = reverse("siaes_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_suspicious_action(self):
        """
        Test "suspicious" actions: action code not registered for use (even if admin)
        """
        suspicious_action = "h4ckm3"
        siae = SiaeWith2MembershipsFactory()
        admin, guest = siae.members.all()

        self.client.login(username=guest.email, password=DEFAULT_PASSWORD)
        # update: less test with RE_PATH
        with self.assertRaises(NoReverseMatch):
            reverse("siaes_views:update_admin_role", kwargs={"action": suspicious_action, "user_id": admin.id})
