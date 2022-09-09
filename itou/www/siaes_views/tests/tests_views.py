# pylint: disable=too-many-lines
from unittest import mock

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.utils.html import escape

from itou.siaes.enums import SiaeKind
from itou.siaes.factories import (
    SiaeConventionFactory,
    SiaeFactory,
    SiaeWith2MembershipsFactory,
    SiaeWithMembershipAndJobsFactory,
)
from itou.siaes.models import Siae
from itou.utils import constants as global_constants
from itou.utils.mocks.geocoding import BAN_GEOCODING_API_NO_RESULT_MOCK, BAN_GEOCODING_API_RESULT_MOCK


class CardViewTest(TestCase):
    def test_card(self):
        siae = SiaeFactory(with_membership=True)
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


class ShowAndSelectFinancialAnnexTest(TestCase):
    def test_asp_source_siae_admin_can_see_but_cannot_select_af(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        self.assertTrue(siae.has_admin(user))
        self.assertTrue(siae.should_have_convention)
        self.assertTrue(siae.source == Siae.SOURCE_ASP)

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        url = reverse("siaes_views:show_financial_annexes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        url = reverse("siaes_views:select_financial_annex")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_user_created_siae_admin_can_see_and_select_af(self):
        siae = SiaeFactory(
            source=Siae.SOURCE_USER_CREATED,
            with_membership=True,
        )
        user = siae.members.first()
        old_convention = siae.convention
        # Only conventions of the same SIREN can be selected.
        new_convention = SiaeConventionFactory(siret_signature=f"{siae.siren}12345")

        self.assertTrue(siae.has_admin(user))
        self.assertTrue(siae.should_have_convention)
        self.assertTrue(siae.source == Siae.SOURCE_USER_CREATED)

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        url = reverse("siaes_views:show_financial_annexes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        url = reverse("siaes_views:select_financial_annex")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        self.assertEqual(siae.convention, old_convention)
        self.assertNotEqual(siae.convention, new_convention)

        post_data = {
            "financial_annexes": new_convention.financial_annexes.get().id,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        siae.refresh_from_db()
        self.assertNotEqual(siae.convention, old_convention)
        self.assertEqual(siae.convention, new_convention)

    def test_staff_created_siae_admin_cannot_see_nor_select_af(self):
        siae = SiaeFactory(source=Siae.SOURCE_STAFF_CREATED, with_membership=True)
        user = siae.members.first()
        self.assertTrue(siae.has_admin(user))
        self.assertTrue(siae.should_have_convention)
        self.assertTrue(siae.source == Siae.SOURCE_STAFF_CREATED)

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        url = reverse("siaes_views:show_financial_annexes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        url = reverse("siaes_views:select_financial_annex")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_asp_source_siae_non_admin_cannot_see_nor_select_af(self):
        siae = SiaeFactory(membership__is_admin=False, with_membership=True)
        user = siae.members.first()
        self.assertFalse(siae.has_admin(user))
        self.assertTrue(siae.should_have_convention)
        self.assertTrue(siae.source == Siae.SOURCE_ASP)

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        url = reverse("siaes_views:show_financial_annexes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        url = reverse("siaes_views:select_financial_annex")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_import_created_geiq_admin_cannot_see_nor_select_af(self):
        siae = SiaeFactory(kind=SiaeKind.GEIQ, source=Siae.SOURCE_GEIQ, with_membership=True)
        user = siae.members.first()
        self.assertTrue(siae.has_admin(user))
        self.assertFalse(siae.should_have_convention)
        self.assertTrue(siae.source == Siae.SOURCE_GEIQ)

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        url = reverse("siaes_views:show_financial_annexes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        url = reverse("siaes_views:select_financial_annex")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_user_created_geiq_admin_cannot_see_nor_select_af(self):
        siae = SiaeFactory(kind=SiaeKind.GEIQ, source=Siae.SOURCE_USER_CREATED, with_membership=True)
        user = siae.members.first()
        self.assertTrue(siae.has_admin(user))
        self.assertFalse(siae.should_have_convention)
        self.assertTrue(siae.source == Siae.SOURCE_USER_CREATED)

        self.client.force_login(user)
        url = reverse("dashboard:index")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        url = reverse("siaes_views:show_financial_annexes")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        url = reverse("siaes_views:select_financial_annex")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


class CreateSiaeViewTest(TestCase):
    def test_create_non_preexisting_siae_outside_of_siren_fails(self):

        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        self.client.force_login(user)

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

        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        self.client.force_login(user)

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

        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        self.client.force_login(user)

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
        self.assertContains(response, escape(global_constants.ITOU_ASSISTANCE_URL))

        self.assertEqual(Siae.objects.filter(siret=post_data["siret"]).count(), 1)

    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_RESULT_MOCK)
    def test_cannot_create_siae_with_same_siret_and_different_kind(self, _mock_call_ban_geocoding_api):
        siae = SiaeFactory(with_membership=True)
        siae.kind = SiaeKind.ETTI
        siae.save()
        user = siae.members.first()

        self.client.force_login(user)

        url = reverse("siaes_views:create_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "siret": siae.siret,
            "kind": SiaeKind.ACI,
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
    def test_cannot_create_siae_with_same_siren_and_different_kind(self, _mock_call_ban_geocoding_api):
        siae = SiaeFactory(with_membership=True)
        siae.kind = SiaeKind.ETTI
        siae.save()
        user = siae.members.first()

        new_siret = siae.siren + "12345"
        self.assertNotEqual(siae.siret, new_siret)

        self.client.force_login(user)

        url = reverse("siaes_views:create_siae")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "siret": new_siret,
            "kind": SiaeKind.ACI,
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
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        self.client.force_login(user)

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
    def test_edit(self, _unused_mock):

        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        self.client.force_login(user)

        url = reverse("siaes_views:edit_siae_step_contact_infos")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informations générales")

        post_data = {
            "brand": "NEW FAMOUS SIAE BRAND NAME",
            "phone": "0610203050",
            "email": "",
            "website": "https://famous-siae.com",
            "address_line_1": "1 Rue Jeanne d'Arc",
            "address_line_2": "",
            "post_code": "62000",
            "city": "Arras",
        }
        response = self.client.post(url, data=post_data)

        # Ensure form validation is done
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ce champ est obligatoire")

        # Go to next step: description
        post_data["email"] = "toto@titi.fr"
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, reverse("siaes_views:edit_siae_step_description"))

        response = self.client.post(url, data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Présentation de l'activité")

        # Go to next step: summary
        url = response.redirect_chain[-1][0]
        post_data = {
            "description": "Le meilleur des SIAEs !",
            "provided_support": "On est très très forts pour tout",
        }
        response = self.client.post(url, data=post_data)
        self.assertRedirects(response, reverse("siaes_views:edit_siae_step_preview"))

        response = self.client.post(url, data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aperçu de la fiche")

        # Go back, should not be an issue
        step_2_url = reverse("siaes_views:edit_siae_step_description")
        response = self.client.get(step_2_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Présentation de l'activité")
        self.assertEqual(
            self.client.session["edit_siae_session_key"],
            {
                "address_line_1": "1 Rue Jeanne d'Arc",
                "address_line_2": "",
                "brand": "NEW FAMOUS SIAE BRAND NAME",
                "city": "Arras",
                "department": "62",
                "description": "Le meilleur des SIAEs !",
                "email": "toto@titi.fr",
                "phone": "0610203050",
                "post_code": "62000",
                "provided_support": "On est très très forts pour tout",
                "website": "https://famous-siae.com",
            },
        )

        # Go forward again
        response = self.client.post(step_2_url, data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aperçu de la fiche")
        self.assertContains(response, "On est très très forts pour tout")

        # Save the object for real
        response = self.client.post(response.redirect_chain[-1][0])
        self.assertRedirects(response, reverse("dashboard:index"))

        # refresh Siae, but using the siret to be sure we didn't mess with the PK
        siae = Siae.objects.get(siret=siae.siret)

        self.assertEqual(siae.brand, "NEW FAMOUS SIAE BRAND NAME")
        self.assertEqual(siae.description, "Le meilleur des SIAEs !")
        self.assertEqual(siae.email, "toto@titi.fr")
        self.assertEqual(siae.phone, "0610203050")
        self.assertEqual(siae.website, "https://famous-siae.com")

        self.assertEqual(siae.address_line_1, "1 Rue Jeanne d'Arc")
        self.assertEqual(siae.address_line_2, "")
        self.assertEqual(siae.post_code, "62000")
        self.assertEqual(siae.city, "Arras")
        self.assertEqual(siae.department, "62")

        # This data comes from BAN_GEOCODING_API_RESULT_MOCK.
        self.assertEqual(siae.coords, "SRID=4326;POINT (2.316754 48.838411)")
        self.assertEqual(siae.latitude, 48.838411)
        self.assertEqual(siae.longitude, 2.316754)
        self.assertEqual(siae.geocoding_score, 0.587663373207207)

    def test_permission(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        self.client.force_login(user)

        # Only admin members should be allowed to edit SIAE's details
        membership = user.siaemembership_set.first()
        membership.is_admin = False
        membership.save()
        url = reverse("siaes_views:edit_siae_step_contact_infos")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


class EditSiaeViewWithWrongAddressTest(TestCase):
    @mock.patch("itou.utils.apis.geocoding.call_ban_geocoding_api", return_value=BAN_GEOCODING_API_NO_RESULT_MOCK)
    def test_edit(self, _unused_mock):

        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()

        self.client.force_login(user)

        url = reverse("siaes_views:edit_siae_step_contact_infos")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informations générales")

        post_data = {
            "brand": "NEW FAMOUS SIAE BRAND NAME",
            "phone": "0610203050",
            "email": "toto@titi.fr",
            "website": "https://famous-siae.com",
            "address_line_1": "1 Rue Jeanne d'Arc",
            "address_line_2": "",
            "post_code": "62000",
            "city": "Arras",
        }
        response = self.client.post(url, data=post_data, follow=True)

        self.assertRedirects(response, reverse("siaes_views:edit_siae_step_description"))

        # Go to next step: summary
        url = response.redirect_chain[-1][0]
        post_data = {
            "description": "Le meilleur des SIAEs !",
            "provided_support": "On est très très forts pour tout",
        }
        response = self.client.post(url, data=post_data, follow=True)
        self.assertRedirects(response, reverse("siaes_views:edit_siae_step_preview"))

        # Save the object for real
        response = self.client.post(response.redirect_chain[-1][0])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "L'adresse semble erronée")


class MembersTest(TestCase):
    def test_members(self):
        siae = SiaeFactory(with_membership=True)
        user = siae.members.first()
        self.client.force_login(user)
        url = reverse("siaes_views:members")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)


class UserMembershipDeactivationTest(TestCase):
    def test_self_deactivation(self):
        """
        A user, even if admin, can't self-deactivate
        (must be done by another admin)
        """
        siae = SiaeFactory(with_membership=True)
        admin = siae.members.filter(siaemembership__is_admin=True).first()
        memberships = admin.siaemembership_set.all()
        membership = memberships.first()

        self.client.force_login(admin)
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
        admin = siae.members.filter(siaemembership__is_admin=True).first()
        guest = siae.members.filter(siaemembership__is_admin=False).first()

        membership = guest.siaemembership_set.first()
        self.assertFalse(guest in siae.active_admin_members)
        self.assertTrue(admin in siae.active_admin_members)

        self.client.force_login(admin)
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
        self.assertEqual(f"[Désactivation] Vous n'êtes plus membre de {siae.display_name}", email.subject)
        self.assertIn("Un administrateur vous a retiré d'une structure sur les emplois de l'inclusion", email.body)
        self.assertEqual(email.to[0], guest.email)

    def test_deactivate_with_no_perms(self):
        """
        Non-admin user can't change memberships
        """
        siae = SiaeWith2MembershipsFactory()
        guest = siae.members.filter(siaemembership__is_admin=False).first()
        self.client.force_login(guest)
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
        admin = siae.members.filter(siaemembership__is_admin=True).first()
        guest = siae.members.filter(siaemembership__is_admin=False).first()

        self.client.force_login(admin)
        url = reverse("siaes_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.client.logout()

        self.client.force_login(guest)
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
        siae2 = SiaeFactory(with_membership=True)
        guest = siae2.members.first()

        siae = SiaeWith2MembershipsFactory()
        admin = siae.members.first()
        siae.members.add(guest)

        memberships = guest.siaemembership_set.all()
        self.assertEqual(len(memberships), 2)

        # Admin remove guest from structure
        self.client.force_login(admin)
        url = reverse("siaes_views:deactivate_member", kwargs={"user_id": guest.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.client.logout()

        # guest must be able to login
        self.client.force_login(guest)
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
        admin = siae.members.filter(siaemembership__is_admin=True).first()
        guest = siae.members.filter(siaemembership__is_admin=False).first()

        self.client.force_login(admin)
        url = reverse("siaes_views:update_admin_role", kwargs={"action": "add", "user_id": guest.id})

        # Redirection to confirm page
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Confirm action
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        siae.refresh_from_db()
        self.assertTrue(guest in siae.active_admin_members)

        # The admin should receive a valid email
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(f"[Activation] Vous êtes désormais administrateur de {siae.display_name}", email.subject)
        self.assertIn("Vous êtes administrateur d'une structure sur les emplois de l'inclusion", email.body)
        self.assertEqual(email.to[0], guest.email)

    def test_remove_admin(self):
        """
        Check the ability for an admin to remove another admin
        """
        siae = SiaeWith2MembershipsFactory()
        admin = siae.members.filter(siaemembership__is_admin=True).first()
        guest = siae.members.filter(siaemembership__is_admin=False).first()

        membership = guest.siaemembership_set.first()
        membership.is_admin = True
        membership.save()
        self.assertTrue(guest in siae.active_admin_members)

        self.client.force_login(admin)
        url = reverse("siaes_views:update_admin_role", kwargs={"action": "remove", "user_id": guest.id})

        # Redirection to confirm page
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Confirm action
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        siae.refresh_from_db()
        self.assertFalse(guest in siae.active_admin_members)

        # The admin should receive a valid email
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(f"[Désactivation] Vous n'êtes plus administrateur de {siae.display_name}", email.subject)
        self.assertIn(
            "Un administrateur vous a retiré les droits d'administrateur d'une structure",
            email.body,
        )
        self.assertEqual(email.to[0], guest.email)

    def test_admin_management_permissions(self):
        """
        Non-admin users can't update admin members
        """
        siae = SiaeWith2MembershipsFactory()
        admin = siae.members.filter(siaemembership__is_admin=True).first()
        guest = siae.members.filter(siaemembership__is_admin=False).first()

        self.client.force_login(guest)
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
        admin = siae.members.filter(siaemembership__is_admin=True).first()
        guest = siae.members.filter(siaemembership__is_admin=False).first()

        self.client.force_login(guest)
        # update: less test with RE_PATH
        with self.assertRaises(NoReverseMatch):
            reverse("siaes_views:update_admin_role", kwargs={"action": suspicious_action, "user_id": admin.id})
