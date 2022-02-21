from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase
from django.urls import reverse

from itou.cities.models import City
from itou.jobs.factories import create_test_romes_and_appellations
from itou.jobs.models import Appellation
from itou.siaes.factories import SiaeWithMembershipFactory
from itou.siaes.models import ContractType, SiaeJobDescription
from itou.users.factories import DEFAULT_PASSWORD


class JobDescriptionAbstractTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Set up data for the whole TestCase.
        city_slug = "paris-75"
        paris_city = City.objects.create(
            name="Paris", slug=city_slug, department="75", post_codes=["75001"], coords=Point(5, 23)
        )

        siae = SiaeWithMembershipFactory(department="75", coords=paris_city.coords, post_code="75001")
        user = siae.members.first()

        create_test_romes_and_appellations(["N1101", "N1105", "N1103", "N4105", "K2401"])
        appellations = Appellation.objects.filter(
            name__in=[
                "Agent / Agente cariste de livraison ferroviaire",
                "Agent / Agente de quai manutentionnaire",
                "Agent magasinier / Agente magasinière gestionnaire de stocks",
                "Chauffeur-livreur / Chauffeuse-livreuse",
            ]
        )
        siae.jobs.add(*appellations)
        siae.save()
        cls.siae = siae
        cls.user = user

        cls.list_url = reverse("siaes_views:job_description_list")
        cls.edit_url = reverse("siaes_views:edit_job_description")
        cls.edit_details_url = reverse("siaes_views:edit_job_description_details")
        cls.edit_preview_url = reverse("siaes_views:edit_job_description_preview")

    def _login(self):
        self.client.login(username=self.user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        return response


class JobDescriptionListViewTest(JobDescriptionAbstractTest):
    def setUp(self):
        self.url = self.list_url

    def test_job_application_list_response_content(self):
        response = self._login()

        self.assertEqual(self.siae.job_description_through.count(), 4)
        self.assertNotIn(settings.ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)
        self.assertIn(settings.ITOU_SESSION_CURRENT_PAGE_KEY, self.client.session)

        for job in self.siae.job_description_through.all():
            with self.subTest(job.pk):
                self.assertContains(response, f"{job.appellation.rome.code}")
                self.assertContains(response, f"/job_description/{job.pk}/card")
                self.assertContains(response, f"toggle_job_description_form_{job.pk}")
                self.assertContains(response, f"#_delete_modal_{job.pk}")

    def test_block_job_applications(self):
        self._login()
        response = self.client.post(self.url, data={"block_job_applications": "on"})

        self.assertRedirects(response, self.url)
        self.assertFalse(self.siae.block_job_applications)

        response = self.client.post(self.url, data={})
        self.siae.refresh_from_db()

        self.assertRedirects(response, self.url)
        self.assertTrue(self.siae.block_job_applications)

    def test_toggle_job_description_activity(self):
        self._login()

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
        self._login()

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
        self.url = self.edit_url

    def test_edit_job_description(self):
        self._login()

        # Step 1: edit job description
        response = self.client.get(self.edit_url)

        self.assertNotIn(settings.ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        post_data = {
            "job_appellation_code": "11076",  # Must be a non existing one for the SIAE
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
        self.assertIn(settings.ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        session_data = self.client.session.get(settings.ITOU_SESSION_JOB_DESCRIPTION_KEY)
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
        self.assertIn(settings.ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        session_data = self.client.session.get(settings.ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with self.subTest(k):
                self.assertEqual(v, session_data.get(k))

        # Step 3: preview and validation
        response = self.client.get(self.edit_preview_url)

        self.assertContains(response, "custom_name")
        self.assertContains(response, "description")
        self.assertContains(response, "profile_description")

        response = self.client.post(self.edit_preview_url)

        self.assertRedirects(response, self.list_url)
        self.assertNotIn(settings.ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)
        self.assertEqual(self.siae.job_description_through.count(), 5)


class UpdateJobDescriptionViewTest(JobDescriptionAbstractTest):
    def setUp(self):
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
        self._login()

        self.assertNotIn(settings.ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        response = self.client.get(self.update_url, follow=True)

        self.assertRedirects(response, self.edit_url)
        self.assertIn(settings.ITOU_SESSION_JOB_DESCRIPTION_KEY, self.client.session)

        session_data = self.client.session.get(settings.ITOU_SESSION_JOB_DESCRIPTION_KEY)

        self.assertEqual(session_data.get("pk"), self.job_description.pk)
        self.assertContains(response, self.job_description.appellation.name)

        # At this point, we're redirected to 'edit_job_description'
