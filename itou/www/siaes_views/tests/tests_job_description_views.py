from django.contrib.gis.geos import Point
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

from itou.cities.models import City
from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.enums import ContractType, SiaeKind
from itou.siaes.factories import SiaeFactory
from itou.siaes.models import SiaeJobDescription
from itou.utils.test import TestCase
from itou.www.siaes_views.views import ITOU_SESSION_CURRENT_PAGE_KEY, ITOU_SESSION_JOB_DESCRIPTION_KEY


class JobDescriptionAbstractTest(TestCase):
    def setUp(self):
        city_slug = "paris-75"
        self.paris_city = City.objects.create(
            name="Paris", slug=city_slug, department="75", post_codes=["75001"], coords=Point(5, 23)
        )

        siae = SiaeFactory(
            department="75",
            coords=self.paris_city.coords,
            post_code="75001",
            with_membership=True,
        )
        user = siae.members.first()

        create_test_romes_and_appellations(["N1101", "N1105", "N1103", "N4105", "K2401"])
        self.appellations = Appellation.objects.filter(
            name__in=[
                "Agent / Agente cariste de livraison ferroviaire",
                "Agent / Agente de quai manutentionnaire",
                "Agent magasinier / Agente magasinière gestionnaire de stocks",
                "Chauffeur-livreur / Chauffeuse-livreuse",
            ]
        )
        siae.jobs.add(*self.appellations)

        # Make sure at least one SiaeJobDescription has a location
        SiaeJobDescription.objects.filter(pk=siae.job_description_through.last().pk).update(
            location=City.objects.create(
                name="Rennes",
                slug="rennes",
                department="35",
                post_codes=["35000"],
                code_insee="35000",
                coords=Point(-1.7, 45),
            )
        )

        self.siae = siae
        self.user = user

        self.list_url = reverse("siaes_views:job_description_list")
        self.edit_url = reverse("siaes_views:edit_job_description")
        self.edit_details_url = reverse("siaes_views:edit_job_description_details")
        self.edit_preview_url = reverse("siaes_views:edit_job_description_preview")

    def _login(self, user):
        self.client.force_login(user)

        response = self.client.get(self.url)

        return response


class JobDescriptionListViewTest(JobDescriptionAbstractTest):
    def setUp(self):
        super().setUp()

        self.url = self.list_url

    def test_job_application_list_response_content(self):
        response = self._login(self.user)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.siae.job_description_through.count(), 4)
        self.assertNotIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)
        self.assertIn(ITOU_SESSION_CURRENT_PAGE_KEY, self.client.session)

        for job in self.siae.job_description_through.all():
            with self.subTest(job.pk):
                self.assertContains(response, f"{job.appellation.rome.code}")
                self.assertContains(response, f"/job_description/{job.pk}/card")
                self.assertContains(response, f"toggle_job_description_form_{job.pk}")
                self.assertContains(response, f"#_delete_modal_{job.pk}")

    def test_block_job_applications(self):
        response = self._login(self.user)

        self.assertEqual(response.status_code, 200)

        response = self.client.post(self.url, data={"block_job_applications": "on"})

        self.assertRedirects(response, self.url)
        self.assertFalse(self.siae.block_job_applications)

        response = self.client.post(self.url, data={})
        self.siae.refresh_from_db()

        self.assertRedirects(response, self.url)
        self.assertTrue(self.siae.block_job_applications)

    def test_toggle_job_description_activity(self):
        response = self._login(self.user)

        self.assertEqual(response.status_code, 200)

        job_description = self.siae.job_description_through.first()
        post_data = {
            "job_description_id": job_description.pk,
        }
        response = self.client.post(self.url + "?action=toggle_active", data=post_data)
        job_description.refresh_from_db()

        self.assertRedirects(response, self.url)
        self.assertFalse(job_description.is_active)

        post_data = {
            "job_description_id": job_description.pk,
            "job_description_is_active": "on",
        }
        response = self.client.post(self.url + "?action=toggle_active", data=post_data)
        job_description.refresh_from_db()

        self.assertRedirects(response, self.url)
        self.assertTrue(job_description.is_active)

    def test_delete_job_descriptions(self):
        response = self._login(self.user)

        self.assertEqual(response.status_code, 200)

        job_description = self.siae.job_description_through.first()
        post_data = {
            "job_description_id": job_description.pk,
        }
        response = self.client.post(self.url + "?action=delete", data=post_data)
        self.assertRedirects(response, self.url)

        with self.assertRaises(ObjectDoesNotExist):
            SiaeJobDescription.objects.get(pk=job_description.id)


class EditJobDescriptionViewTest(JobDescriptionAbstractTest):
    def setUp(self):
        super().setUp()

        self.url = self.edit_url

    def test_edit_job_description_siae(self):
        response = self._login(self.user)

        self.assertEqual(response.status_code, 200)

        # Step 1: edit job description
        response = self.client.get(self.edit_url)

        self.assertNotIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        post_data = {
            "job_appellation_code": 11076,  # Must be a non existing one for the SIAE
            "job_appellation": "Whatever",
            "custom_name": "custom_name",
            "location_code": "paris-75",
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
        }
        response = self.client.post(self.edit_url, data=post_data)

        self.assertRedirects(response, self.edit_details_url)
        self.assertIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        session_data = self.client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with self.subTest(k):
                self.assertEqual(v, session_data.get(k))

        # Step 2: edit job description details
        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": True,
        }

        response = self.client.post(self.edit_details_url, data=post_data)

        self.assertRedirects(response, self.edit_preview_url)
        self.assertIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        session_data = self.client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with self.subTest(k):
                self.assertEqual(v, session_data.get(k))

        # Step 3: preview and validation
        response = self.client.get(self.edit_preview_url)

        self.assertContains(response, "custom_name")
        self.assertContains(response, "description")
        self.assertContains(response, "profile_description")
        self.assertContains(response, "Curriculum Vitae")

        response = self.client.post(self.edit_preview_url)

        self.assertRedirects(response, self.list_url)
        self.assertNotIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)
        self.assertEqual(self.siae.job_description_through.count(), 5)

    def test_edit_job_description_opcs(self):
        opcs = SiaeFactory(
            department="75",
            coords=self.paris_city.coords,
            post_code="75001",
            kind=SiaeKind.OPCS,
            with_membership=True,
        )
        user_opcs = opcs.members.first()
        opcs.jobs.add(*self.appellations)

        response = self._login(user_opcs)

        self.assertEqual(response.status_code, 200)

        # Step 1: edit job description
        response = self.client.get(self.edit_url)

        self.assertNotIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        post_data = {
            "job_appellation_code": 11076,  # Must be a non existing one for the SIAE
            "job_appellation": "Whatever",
            "market_context_description": "Whatever market description",
            "custom_name": "custom_name",
            "location_code": "paris-75",
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
        }
        response = self.client.post(self.edit_url, data=post_data)

        self.assertRedirects(response, self.edit_details_url)
        self.assertIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        session_data = self.client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with self.subTest(k):
                self.assertEqual(v, session_data.get(k))

        # Step 2: edit job description details
        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": True,
            "is_qpv_mandatory": True,
        }

        response = self.client.post(self.edit_details_url, data=post_data)

        self.assertRedirects(response, self.edit_preview_url)
        self.assertIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        session_data = self.client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with self.subTest(k):
                self.assertEqual(v, session_data.get(k))

        # Step 3: preview and validation
        response = self.client.get(self.edit_preview_url)

        self.assertContains(response, "custom_name")
        self.assertContains(response, "description")
        self.assertContains(response, "profile_description")
        self.assertContains(response, "Whatever market description")
        self.assertContains(response, "Curriculum Vitae")
        # Rendering of `is_qpv_mandatory`
        self.assertContains(response, "typologies de public particulières")

        response = self.client.post(self.edit_preview_url)

        self.assertRedirects(response, self.list_url)
        self.assertNotIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)
        self.assertEqual(opcs.job_description_through.count(), 5)

    def test_empty_session_during_edit(self):
        # If the session data have been erased during one of the job description
        # crestion / update tunnel (browser navigation for instance),
        # then redirect to the first step.

        response = self._login(self.user)

        self.assertEqual(response.status_code, 200)

        # Step 1: edit job description
        response = self.client.get(self.edit_url)

        self.assertNotIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        post_data = {
            "job_appellation_code": 11076,  # Must be a non existing one for the SIAE
            "job_appellation": "Whatever",
            "custom_name": "custom_name",
            "location_code": "paris-75",
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
        }
        response = self.client.post(self.edit_url, data=post_data)

        self.assertRedirects(response, self.edit_details_url)
        self.assertIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        # Remove session data
        # - do not remove directly from client (i.e self.client.session.pop(...) )
        # - don't forget to call session.save()
        session = self.client.session
        session.pop(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        session.save()

        self.assertIsNone(session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY))

        response = self.client.get(self.edit_details_url)
        self.assertRedirects(response, self.edit_url)

        # Step 1 + 2
        response = self.client.post(self.edit_url, data=post_data)
        response = self.client.post(self.edit_details_url, data=post_data)
        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": True,
            "is_qpv_mandatory": True,
        }

        response = self.client.post(self.edit_details_url, data=post_data)

        self.assertRedirects(response, self.edit_preview_url)
        self.assertIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        # Remove session data
        session = self.client.session
        session.pop(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        session.save()

        self.assertNotIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        response = self.client.get(self.edit_preview_url)
        self.assertRedirects(response, self.edit_url)


class UpdateJobDescriptionViewTest(JobDescriptionAbstractTest):
    def setUp(self):

        super().setUp()

        self.job_description = self.siae.job_description_through.first()
        self.update_url = reverse(
            "siaes_views:update_job_description",
            kwargs={
                "job_description_id": self.job_description.pk,
            },
        )
        # Start from here as update is a redirect
        self.url = self.list_url

    def test_update_job_description(self):
        response = self._login(self.user)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        response = self.client.get(self.update_url, follow=True)

        self.assertRedirects(response, self.edit_url)
        self.assertIn(ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        session_data = self.client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)

        self.assertEqual(session_data.get("pk"), self.job_description.pk)
        self.assertContains(response, self.job_description.appellation.name)

        # At this point, we're redirected to 'edit_job_description'


class JobDescriptionCardTest(JobDescriptionAbstractTest):
    def setUp(self):
        super().setUp()
        self.job_description = self.siae.job_description_through.first()
        self.url = reverse(
            "siaes_views:job_description_card",
            kwargs={
                "job_description_id": self.job_description.pk,
            },
        )

    def test_siae_card_actions(self):
        # Checks if SIAE can update their job descriptions
        response = self._login(self.user)

        self.assertEqual(response.status_code, 200)

        response = self.client.get(self.url)

        self.assertContains(response, "Modifier")

    def test_non_siae_card_actions(self):
        # Checks if non-SIAE can apply to opened job descriptions
        user = PrescriberOrganizationWithMembershipFactory().members.first()
        response = self._login(user)

        self.assertEqual(response.status_code, 200)

        with self.assertNumQueries(
            1  # fetch django session
            + 1  # fetch user
            + 1  # check user is active
            + 1  # fetch siaes_siaejobdescription
            + 1  # fetch siaes infos
            + 1  # fetch prescribers_prescribermembership/organization
            + 1  # fetch jobappelation
            + 1  # weird fetch social account
            + 1  # fetch other job infos
        ):
            response = self.client.get(self.url)

        self.assertContains(response, "Postuler")
