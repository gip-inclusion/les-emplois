import pytest
from django.contrib import messages
from django.contrib.gis.geos import Point
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from freezegun import freeze_time

from itou.cities.models import City
from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import SiaeJobDescription
from itou.jobs.models import Appellation
from itou.www.companies_views.views import ITOU_SESSION_JOB_DESCRIPTION_KEY
from tests.companies.factories import SiaeFactory, SiaeJobDescriptionFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import BASE_NUM_QUERIES, TestCase, assertMessages


pytestmark = pytest.mark.ignore_template_errors


class JobDescriptionAbstractTest(TestCase):
    def setUp(self):
        super().setUp()
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

        # Make sure at least two SiaeJobDescription have a location
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
        SiaeJobDescription.objects.filter(pk=siae.job_description_through.first().pk).update(
            location=City.objects.create(
                name="Lille",
                slug="lille",
                department="35",
                post_codes=["59000"],
                code_insee="59000",
                coords=Point(3, 50.5),
            )
        )

        self.siae = siae
        self.user = user

        self.list_url = reverse("companies_views:job_description_list")
        self.edit_url = reverse("companies_views:edit_job_description")
        self.edit_details_url = reverse("companies_views:edit_job_description_details")
        self.edit_preview_url = reverse("companies_views:edit_job_description_preview")

    def _login(self, user):
        self.client.force_login(user)

        response = self.client.get(self.url)

        return response


class JobDescriptionListViewTest(JobDescriptionAbstractTest):
    def setUp(self):
        super().setUp()

        self.url = self.list_url + "?page=1"

    def test_job_application_list_response_content(self):
        self.client.force_login(self.user)
        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 2  # fetch user memberships (and if siae is active/in grace period)
            + 1  # count job descriptions
            + 1  # fetch job descriptions
            + 3  # prefetch appelation, rome & siae
            + 3  # update session
        ):
            response = self.client.get(self.url)

        assert self.siae.job_description_through.count() == 4
        self.assertContains(
            response,
            '<h3 class="h4 mb-0">4 métiers exercés</h3>',
            html=True,
            count=1,
        )
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in self.client.session

        for job in self.siae.job_description_through.all():
            with self.subTest(job.pk):
                self.assertContains(response, f"/job_description/{job.pk}/card")
                self.assertContains(response, f"toggle_job_description_form_{job.pk}")
                self.assertContains(response, f"#_delete_modal_{job.pk}")
                self.assertContains(
                    response,
                    f"""<input type="hidden" name="job_description_id" value="{job.pk}"/>""",
                    html=True,
                    count=2,
                )

    def test_block_job_applications(self):
        response = self._login(self.user)

        assert response.status_code == 200
        post_data = {"action": "block_job_applications", "block_job_applications": "on"}

        response = self.client.post(self.url, data=post_data)

        self.assertRedirects(response, self.url)
        assert not self.siae.block_job_applications

        response = self.client.post(self.url, data={})
        self.siae.refresh_from_db()

        self.assertRedirects(response, self.url)
        assert self.siae.block_job_applications

    @freeze_time("2021-06-21 10:10:10.10")
    def test_toggle_job_description_activity(self):
        response = self._login(self.user)

        assert response.status_code == 200

        job_description = self.siae.job_description_through.first()
        post_data = {"job_description_id": job_description.pk, "action": "toggle_active"}
        response = self.client.post(self.url, data=post_data)
        job_description.refresh_from_db()

        self.assertRedirects(response, self.url)
        assert not job_description.is_active
        assert job_description.field_history == [
            {
                "at": "2021-06-21T10:10:10.100Z",
                "field": "is_active",
                "from": True,
                "to": False,
            },
        ]

        post_data = {
            "job_description_id": job_description.pk,
            "job_description_is_active": "on",
            "action": "toggle_active",
        }
        response = self.client.post(self.url, data=post_data)
        job_description.refresh_from_db()

        self.assertRedirects(response, self.url)
        assert job_description.is_active
        assert job_description.field_history == [
            {
                "at": "2021-06-21T10:10:10.100Z",
                "field": "is_active",
                "from": True,
                "to": False,
            },
            {
                "at": "2021-06-21T10:10:10.100Z",
                "field": "is_active",
                "from": False,
                "to": True,
            },
        ]

        assertMessages(response, [(messages.SUCCESS, "Le recrutement est maintenant ouvert.")])

        # Check that we do not crash on unexisting job description
        job_description.delete()
        response = self.client.post(self.url, data=post_data)
        self.assertRedirects(response, self.url)
        assertMessages(response, [(messages.ERROR, "La fiche de poste que vous souhaitiez modifier n'existe plus.")])

        # Trying to update job description from an other SIAE does nothing
        other_siae_job_description = SiaeJobDescriptionFactory(is_active=False)
        response = self.client.post(
            self.url,
            data={
                "job_description_id": other_siae_job_description.pk,
                "job_description_is_active": "on",
                "action": "toggle_active",
            },
        )
        self.assertRedirects(response, self.url)
        assertMessages(response, [(messages.ERROR, "La fiche de poste que vous souhaitiez modifier n'existe plus.")])
        other_siae_job_description.refresh_from_db()
        assert not other_siae_job_description.is_active

    def test_delete_job_descriptions(self):
        response = self._login(self.user)

        assert response.status_code == 200

        job_description = self.siae.job_description_through.first()
        post_data = {
            "job_description_id": job_description.pk,
            "action": "delete",
        }
        response = self.client.post(self.url, data=post_data)
        self.assertRedirects(response, self.url)
        assertMessages(response, [(messages.SUCCESS, "La fiche de poste a été supprimée.")])

        with pytest.raises(ObjectDoesNotExist):
            SiaeJobDescription.objects.get(pk=job_description.id)

        # Second delete does not crash (and simply does nothing)
        response = self.client.post(self.url, data=post_data)
        self.assertRedirects(response, self.url)
        assertMessages(response, [(messages.WARNING, "La fiche de poste que vous souhaitez supprimer n'existe plus.")])

        # Trying to delete job description from an other SIAE does nothing
        other_siae_job_description = SiaeJobDescriptionFactory()
        response = self.client.post(
            self.url,
            data={
                "job_description_id": other_siae_job_description.pk,
                "action": "delete",
            },
        )
        self.assertRedirects(response, self.url)
        assertMessages(response, [(messages.WARNING, "La fiche de poste que vous souhaitez supprimer n'existe plus.")])
        assert SiaeJobDescription.objects.filter(pk=other_siae_job_description.pk).exists()


class EditJobDescriptionViewTest(JobDescriptionAbstractTest):
    def setUp(self):
        super().setUp()

        self.url = self.edit_url

    def test_edit_job_description_siae(self):
        response = self._login(self.user)

        assert response.status_code == 200

        # Step 1: edit job description
        response = self.client.get(self.edit_url)

        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in self.client.session

        post_data = {
            "appellation": "11076",  # Must be a non existing one for the SIAE
            "custom_name": "custom_name",
            "location_code": "paris-75",
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
        }
        response = self.client.post(self.edit_url, data=post_data)

        self.assertRedirects(response, self.edit_details_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in self.client.session

        session_data = self.client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with self.subTest(k):
                assert v == session_data.get(k)

        # Step 2: edit job description details
        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": True,
        }

        response = self.client.post(self.edit_details_url, data=post_data)

        self.assertRedirects(response, self.edit_preview_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in self.client.session

        session_data = self.client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with self.subTest(k):
                assert v == session_data.get(k)

        # Step 3: preview and validation
        response = self.client.get(self.edit_preview_url)

        self.assertContains(response, "custom_name")
        self.assertContains(response, "description")
        self.assertContains(response, "profile_description")
        self.assertContains(response, "Curriculum Vitae")

        response = self.client.post(self.edit_preview_url)

        self.assertRedirects(response, self.list_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in self.client.session
        assert self.siae.job_description_through.count() == 5

    def test_edit_job_description_opcs(self):
        opcs = SiaeFactory(
            department="75",
            coords=self.paris_city.coords,
            post_code="75001",
            kind=CompanyKind.OPCS,
            with_membership=True,
        )
        user_opcs = opcs.members.first()
        opcs.jobs.add(*self.appellations)

        response = self._login(user_opcs)

        assert response.status_code == 200

        # Step 1: edit job description
        response = self.client.get(self.edit_url)

        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in self.client.session

        post_data = {
            "appellation": "11076",  # Must be a non existing one for the SIAE
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
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in self.client.session

        session_data = self.client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with self.subTest(k):
                assert v == session_data.get(k)

        # Step 2: edit job description details
        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": True,
            "is_qpv_mandatory": True,
        }

        response = self.client.post(self.edit_details_url, data=post_data)

        self.assertRedirects(response, self.edit_preview_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in self.client.session

        session_data = self.client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with self.subTest(k):
                assert v == session_data.get(k)

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
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in self.client.session
        assert opcs.job_description_through.count() == 5

    def test_empty_session_during_edit(self):
        # If the session data have been erased during one of the job description
        # crestion / update tunnel (browser navigation for instance),
        # then redirect to the first step.

        response = self._login(self.user)

        assert response.status_code == 200

        # Step 1: edit job description
        response = self.client.get(self.edit_url)

        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in self.client.session

        post_data = {
            "appellation": "11076",  # Must be a non existing one for the SIAE
            "custom_name": "custom_name",
            "location_code": "paris-75",
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
        }
        response = self.client.post(self.edit_url, data=post_data)

        self.assertRedirects(response, self.edit_details_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in self.client.session

        # Remove session data
        # - do not remove directly from client (i.e self.client.session.pop(...) )
        # - don't forget to call session.save()
        session = self.client.session
        session.pop(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        session.save()

        assert session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY) is None

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
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in self.client.session

        # Remove session data
        session = self.client.session
        session.pop(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        session.save()

        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in self.client.session

        response = self.client.get(self.edit_preview_url)
        self.assertRedirects(response, self.edit_url)


class UpdateJobDescriptionViewTest(JobDescriptionAbstractTest):
    def setUp(self):
        super().setUp()

        self.job_description = self.siae.job_description_through.first()
        self.update_url = reverse(
            "companies_views:update_job_description",
            kwargs={
                "job_description_id": self.job_description.pk,
            },
        )
        # Start from here as update is a redirect
        self.url = self.list_url

    def test_update_job_description(self):
        response = self._login(self.user)

        assert response.status_code == 200
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in self.client.session

        response = self.client.get(self.update_url, follow=True)

        self.assertRedirects(response, self.edit_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in self.client.session

        session_data = self.client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)

        assert session_data.get("pk") == self.job_description.pk
        self.assertContains(response, self.job_description.appellation.name)

        # At this point, we're redirected to 'edit_job_description'


class JobDescriptionCardTest(JobDescriptionAbstractTest):
    def setUp(self):
        super().setUp()
        self.job_description = self.siae.job_description_through.first()
        self.url = reverse(
            "companies_views:job_description_card",
            kwargs={
                "job_description_id": self.job_description.pk,
            },
        )

    def test_employer_card_actions(self):
        # Checks if SIAE can update their job descriptions
        response = self._login(self.user)

        self.assertContains(response, "Modifier la fiche de poste")
        self.assertContains(
            response,
            reverse(
                "companies_views:update_job_description",
                kwargs={"job_description_id": self.job_description.pk},
            ),
        )
        self.assertContains(response, "Retour vers la liste des postes")
        self.assertContains(response, reverse("companies_views:job_description_list"))
        self.assertNotContains(response, reverse("apply:start", kwargs={"siae_pk": self.siae.pk}))

    def test_prescriber_card_actions(self):
        # Checks if non-SIAE can apply to opened job descriptions
        self.client.force_login(PrescriberOrganizationWithMembershipFactory().members.first())

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 1  # fetch user memberships
            + 1  # fetch siaes_siaejobdescription
            + 1  # fetch siaes infos
            + 1  # fetch jobappelation
            + 1  # fetch other job infos
            + 3  # update session
        ):
            response = self.client.get(self.url)

        self.assertContains(response, "Postuler auprès de l'employeur solidaire")
        self.assertContains(response, reverse("apply:start", kwargs={"siae_pk": self.siae.pk}))
        self.assertNotContains(
            response,
            reverse(
                "companies_views:update_job_description",
                kwargs={"job_description_id": self.job_description.pk},
            ),
        )

    def test_job_seeker_card_actions(self):
        self.client.force_login(JobSeekerFactory())

        with self.assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 1  # fetch siaes_siaejobdescription
            + 1  # fetch siaes infos
            + 1  # fetch jobappelation
            + 1  # fetch other job infos
            + 3  # update session
        ):
            response = self.client.get(self.url)

        self.assertContains(response, "Postuler auprès de l'employeur solidaire")
        self.assertContains(response, reverse("apply:start", kwargs={"siae_pk": self.siae.pk}))
        self.assertNotContains(
            response,
            reverse(
                "companies_views:update_job_description",
                kwargs={"job_description_id": self.job_description.pk},
            ),
        )

    def test_anonymous_card_actions(self):
        response = self.client.get(self.url)

        self.assertContains(response, "Postuler auprès de l'employeur solidaire")
        self.assertContains(response, reverse("apply:start", kwargs={"siae_pk": self.siae.pk}))
        self.assertNotContains(
            response,
            reverse(
                "companies_views:update_job_description",
                kwargs={"job_description_id": self.job_description.pk},
            ),
        )

    def test_display_placeholder_for_empty_fields(self):
        response = self._login(self.user)

        # Job description created in setup has empty description fields
        self.assertContains(response, "La structure n'a pas encore renseigné cette rubrique", count=2)

        self.job_description.description = "a job description"
        self.job_description.save()
        response = self.client.get(self.url)

        self.assertContains(response, "a job description")
        self.assertContains(response, "La structure n'a pas encore renseigné cette rubrique")

        self.job_description.profile_description = "a profile description"
        self.job_description.save()
        response = self.client.get(self.url)

        self.assertContains(response, "a job description")
        self.assertContains(response, "a profile description")
        self.assertNotContains(response, "La structure n'a pas encore renseigné cette rubrique")
