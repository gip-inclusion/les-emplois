import pytest
from django.contrib import messages
from django.contrib.gis.geos import Point
from django.core.exceptions import ObjectDoesNotExist
from django.template.defaultfilters import urlencode
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.cities.models import City
from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import JobDescription
from itou.jobs.models import Appellation
from itou.www.companies_views.views import ITOU_SESSION_JOB_DESCRIPTION_KEY
from tests.companies.factories import CompanyFactory, JobDescriptionFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.test import assert_previous_step, assertSnapshotQueries


class JobDescriptionAbstract:
    @pytest.fixture(autouse=True)
    def abstract_setup_method(self):
        city_slug = "paris-75"
        self.paris_city = City.objects.create(
            name="Paris", slug=city_slug, department="75", post_codes=["75001"], coords=Point(5, 23)
        )

        company = CompanyFactory(
            department="75",
            coords=self.paris_city.coords,
            post_code="75001",
            with_membership=True,
        )
        user = company.members.first()

        create_test_romes_and_appellations(["N1101", "N1105", "N1103", "N4105", "K2401"])
        self.appellations = Appellation.objects.filter(
            name__in=[
                "Agent / Agente cariste de livraison ferroviaire",
                "Agent / Agente de quai manutentionnaire",
                "Agent magasinier / Agente magasinière gestionnaire de stocks",
                "Chauffeur-livreur / Chauffeuse-livreuse",
            ]
        )
        company.jobs.add(*self.appellations)

        # Make sure at least two JobDescription have a location
        JobDescription.objects.filter(pk=company.job_description_through.last().pk).update(
            location=City.objects.create(
                name="Rennes",
                slug="rennes",
                department="35",
                post_codes=["35000"],
                code_insee="35000",
                coords=Point(-1.7, 45),
            )
        )
        JobDescription.objects.filter(pk=company.job_description_through.first().pk).update(
            location=City.objects.create(
                name="Lille",
                slug="lille",
                department="35",
                post_codes=["59000"],
                code_insee="59000",
                coords=Point(3, 50.5),
            )
        )

        self.company = company
        self.user = user

        self.list_url = reverse("companies_views:job_description_list")
        self.edit_url = reverse("companies_views:edit_job_description")
        self.edit_details_url = reverse("companies_views:edit_job_description_details")
        self.edit_preview_url = reverse("companies_views:edit_job_description_preview")

    def _login(self, client, user):
        client.force_login(user)

        response = client.get(self.url)

        return response


class TestJobDescriptionListView(JobDescriptionAbstract):
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.url = self.list_url + "?page=1"

    def test_job_application_list_response_content(self, client, snapshot, subtests):
        client.force_login(self.user)
        with assertSnapshotQueries(snapshot(name="job applications list")):
            response = client.get(self.url)

        assert self.company.job_description_through.count() == 4
        assertContains(
            response,
            '<p class="mb-0">4 métiers exercés</p>',
            html=True,
            count=1,
        )
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in client.session

        for job in self.company.job_description_through.all():
            with subtests.test(job.pk):
                job_description_link = f"{job.get_absolute_url()}?back_url={urlencode(self.url)}"
                assertContains(response, job_description_link)
                assertContains(response, f"toggle_job_description_form_{job.pk}")
                assertContains(response, f"#_delete_modal_{job.pk}")
                assertContains(
                    response,
                    f"""<input type="hidden" name="job_description_id" value="{job.pk}"/>""",
                    html=True,
                    count=2,
                )

        assert_previous_step(response, reverse("dashboard:index"))

    def test_block_job_applications(self, client):
        response = self._login(client, self.user)

        assert response.status_code == 200
        post_data = {"action": "block_job_applications", "block_job_applications": "on"}

        response = client.post(self.url, data=post_data)

        assertRedirects(response, self.url)
        assert not self.company.block_job_applications

        response = client.post(self.url, data={})
        self.company.refresh_from_db()

        assertRedirects(response, self.url)
        assert self.company.block_job_applications

    @freeze_time("2021-06-21 10:10:10.10")
    def test_toggle_job_description_activity(self, client):
        response = self._login(client, self.user)

        assert response.status_code == 200

        job_description = self.company.job_description_through.first()
        post_data = {"job_description_id": job_description.pk, "action": "toggle_active"}
        response = client.post(self.url, data=post_data)
        job_description.refresh_from_db()

        assertRedirects(response, self.url)
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
        response = client.post(self.url, data=post_data)
        job_description.refresh_from_db()

        assertRedirects(response, self.url)
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

        assertMessages(response, [messages.Message(messages.SUCCESS, "Le recrutement est maintenant ouvert.")])

        # Check that we do not crash on unexisting job description
        job_description.delete()
        response = client.post(self.url, data=post_data)
        assertRedirects(response, self.url)
        assertMessages(
            response,
            [messages.Message(messages.ERROR, "La fiche de poste que vous souhaitiez modifier n'existe plus.")],
        )

        # Trying to update job description from an other company does nothing
        other_company_job_description = JobDescriptionFactory(is_active=False)
        response = client.post(
            self.url,
            data={
                "job_description_id": other_company_job_description.pk,
                "job_description_is_active": "on",
                "action": "toggle_active",
            },
        )
        assertRedirects(response, self.url)
        assertMessages(
            response,
            [messages.Message(messages.ERROR, "La fiche de poste que vous souhaitiez modifier n'existe plus.")],
        )
        other_company_job_description.refresh_from_db()
        assert not other_company_job_description.is_active

    def test_delete_job_descriptions(self, client):
        response = self._login(client, self.user)

        assert response.status_code == 200

        job_description = self.company.job_description_through.first()
        post_data = {
            "job_description_id": job_description.pk,
            "action": "delete",
        }
        response = client.post(self.url, data=post_data)
        assertRedirects(response, self.url)
        assertMessages(response, [messages.Message(messages.SUCCESS, "La fiche de poste a été supprimée.")])

        with pytest.raises(ObjectDoesNotExist):
            JobDescription.objects.get(pk=job_description.id)

        # Second delete does not crash (and simply does nothing)
        response = client.post(self.url, data=post_data)
        assertRedirects(response, self.url)
        assertMessages(
            response,
            [messages.Message(messages.WARNING, "La fiche de poste que vous souhaitez supprimer n'existe plus.")],
        )

        # Trying to delete job description from an other company does nothing
        other_company_job_description = JobDescriptionFactory()
        response = client.post(
            self.url,
            data={
                "job_description_id": other_company_job_description.pk,
                "action": "delete",
            },
        )
        assertRedirects(response, self.url)
        assertMessages(
            response,
            [messages.Message(messages.WARNING, "La fiche de poste que vous souhaitez supprimer n'existe plus.")],
        )
        assert JobDescription.objects.filter(pk=other_company_job_description.pk).exists()


class TestEditJobDescriptionView(JobDescriptionAbstract):
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.url = self.edit_url

    def test_edit_job_description_company(self, client, subtests):
        response = self._login(client, self.user)

        assert response.status_code == 200

        # Step 1: edit job description
        response = client.get(self.edit_url)

        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in client.session

        post_data = {
            "appellation": "11076",  # Must be a non existing one for the company
            "location": self.paris_city.pk,
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
        }
        response = client.post(self.edit_url, data=post_data)

        assertRedirects(response, self.edit_details_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in client.session

        session_data = client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with subtests.test(k):
                assert v == session_data.get(k)

        # Step 2: edit job description details
        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": True,
        }

        response = client.post(self.edit_details_url, data=post_data)

        assertRedirects(response, self.edit_preview_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in client.session

        session_data = client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with subtests.test(k):
                assert v == session_data.get(k)

        # Step 3: preview and validation
        response = client.get(self.edit_preview_url)

        assertContains(response, "description")
        assertContains(response, "profile_description")
        assertContains(response, "Curriculum Vitae")

        response = client.post(self.edit_preview_url)

        assertRedirects(response, self.list_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in client.session
        assert self.company.job_description_through.count() == 5

    def test_edit_job_description_opcs(self, client, subtests):
        opcs = CompanyFactory(
            department="75",
            coords=self.paris_city.coords,
            post_code="75001",
            kind=CompanyKind.OPCS,
            with_membership=True,
        )
        user_opcs = opcs.members.first()
        opcs.jobs.add(*self.appellations)

        response = self._login(client, user_opcs)

        assert response.status_code == 200

        # Step 1: edit job description
        response = client.get(self.edit_url)

        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in client.session

        post_data = {
            "appellation": "11076",  # Must be a non existing one for the company
            "market_context_description": "Whatever market description",
            "location": self.paris_city.pk,
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
        }
        response = client.post(self.edit_url, data=post_data)

        assertRedirects(response, self.edit_details_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in client.session

        session_data = client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with subtests.test(k):
                assert v == session_data.get(k)

        # Step 2: edit job description details and check the rendered markdown
        post_data = {
            "description": "**Lorem ipsum**\n<span>Span</span>",  # HTML tags should be ignored
            "profile_description": "profile_*description*",
            "is_resume_mandatory": True,
            "is_qpv_mandatory": True,
        }

        response = client.post(self.edit_details_url, data=post_data)

        assertRedirects(response, self.edit_preview_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in client.session

        session_data = client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with subtests.test(k):
                assert v == session_data.get(k)

        # Step 3: preview and validation
        response = client.get(self.edit_preview_url)
        assertContains(response, "<strong>Lorem ipsum</strong><br>\nSpan")
        assertContains(response, "profile_<em>description</em>")
        assertContains(response, "Whatever market description")
        assertContains(response, "Curriculum Vitae")
        # Rendering of `is_qpv_mandatory`
        assertContains(response, "typologies de public particulières")

        response = client.post(self.edit_preview_url)

        assertRedirects(response, self.list_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in client.session
        assert opcs.job_description_through.count() == 5

    def test_empty_session_during_edit(self, client):
        # If the session data have been erased during one of the job description
        # crestion / update tunnel (browser navigation for instance),
        # then redirect to the first step.

        response = self._login(client, self.user)

        assert response.status_code == 200

        # Step 1: edit job description
        response = client.get(self.edit_url)

        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in client.session

        post_data = {
            "appellation": "11076",  # Must be a non existing one for the company
            "custom_name": "custom_name",
            "location": self.paris_city.pk,
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
        }
        response = client.post(self.edit_url, data=post_data)

        assertRedirects(response, self.edit_details_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in client.session

        # Remove session data
        # - do not remove directly from client (i.e client.session.pop(...) )
        # - don't forget to call session.save()
        session = client.session
        session.pop(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        session.save()

        assert session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY) is None

        response = client.get(self.edit_details_url)
        assertRedirects(response, self.edit_url)

        # Step 1 + 2
        response = client.post(self.edit_url, data=post_data)
        response = client.post(self.edit_details_url, data=post_data)
        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": True,
            "is_qpv_mandatory": True,
        }

        response = client.post(self.edit_details_url, data=post_data)

        assertRedirects(response, self.edit_preview_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in client.session

        # Remove session data
        session = client.session
        session.pop(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        session.save()

        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in client.session

        response = client.get(self.edit_preview_url)
        assertRedirects(response, self.edit_url)


class TestUpdateJobDescriptionView(JobDescriptionAbstract):
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.job_description = self.company.job_description_through.filter(location__isnull=False).first()
        self.update_url = reverse(
            "companies_views:update_job_description",
            kwargs={
                "job_description_id": self.job_description.pk,
            },
        )
        # Start from here as update is a redirect
        self.url = self.list_url

    @staticmethod
    def initial_location_name(location):
        return location.name

    def test_update_job_description(self, client):
        response = self._login(client, self.user)

        assert response.status_code == 200
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in client.session

        response = client.get(self.update_url, follow=True)

        assertRedirects(response, self.edit_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in client.session

        session_data = client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)

        assert session_data.get("pk") == self.job_description.pk
        assertContains(response, self.job_description.appellation.name)

        # At this point, we're redirected to 'edit_job_description'

    def test_update_job_description_remove_location(self, client, subtests):
        assert self.job_description.location is not None
        initial_location = self.job_description.location

        response = self._login(client, self.user)
        assert response.status_code == 200
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in client.session

        response = client.get(self.update_url, follow=True)
        assertRedirects(response, self.edit_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in client.session

        # Step 1: edit job description
        response = client.get(self.edit_url)
        assertContains(response, self.initial_location_name(initial_location))

        post_data = {
            "appellation": self.job_description.appellation.code,
            "custom_name": "custom_name",
            "location": "",  # Remove location
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": self.job_description.open_positions,
        }
        response = client.post(self.edit_url, data=post_data)

        assertRedirects(response, self.edit_details_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in client.session
        session_data = client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with subtests.test(k):
                if k == "location":
                    # We cannot send None in post_data
                    assert session_data.get(k) is None
                else:
                    assert v == session_data.get(k)

        # Step 2: edit job description details
        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": True,
        }
        response = client.post(self.edit_details_url, data=post_data)
        assertRedirects(response, self.edit_preview_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY in client.session
        session_data = client.session.get(ITOU_SESSION_JOB_DESCRIPTION_KEY)
        for k, v in post_data.items():
            with subtests.test(k):
                assert v == session_data.get(k)

        # Step 3: preview
        response = client.get(self.edit_preview_url)
        assertNotContains(response, self.initial_location_name(initial_location))

        # Step 4: validation
        response = client.post(self.edit_preview_url)
        assertRedirects(response, self.list_url)
        assert ITOU_SESSION_JOB_DESCRIPTION_KEY not in client.session

        self.job_description.refresh_from_db()
        assert self.job_description.location is None


class TestJobDescriptionCard(JobDescriptionAbstract):
    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.job_description = self.company.job_description_through.first()
        self.url = reverse(
            "companies_views:job_description_card",
            kwargs={
                "job_description_id": self.job_description.pk,
            },
        )

    @staticmethod
    def apply_start_url(company):
        return reverse("apply:start", kwargs={"company_pk": company.pk})

    @staticmethod
    def update_job_description_url(job_description):
        return reverse(
            "companies_views:update_job_description",
            kwargs={"job_description_id": job_description.pk},
        )

    def test_employer_card_actions(self, client):
        # Checks if company can update their job descriptions
        response = self._login(client, self.user)

        assertContains(response, "Modifier la fiche de poste")
        assertContains(response, self.update_job_description_url(self.job_description))
        assertContains(response, reverse("companies_views:job_description_list"))
        assertNotContains(response, self.apply_start_url(self.company))

    def test_prescriber_card_actions(self, client, snapshot):
        # Checks if non-employers can apply to opened job descriptions
        client.force_login(PrescriberOrganizationWithMembershipFactory().members.first())

        with assertSnapshotQueries(snapshot):
            response = client.get(self.url)

        assertContains(response, "Postuler auprès de l'employeur inclusif")
        assertContains(response, self.apply_start_url(self.company))
        assertNotContains(
            response,
            self.update_job_description_url(self.job_description),
        )

    def test_job_seeker_card_actions(self, client, snapshot):
        client.force_login(JobSeekerFactory())

        with assertSnapshotQueries(snapshot):
            response = client.get(self.url)

        assertContains(response, "Postuler auprès de l'employeur inclusif")
        assertContains(response, self.apply_start_url(self.company))
        assertNotContains(response, self.update_job_description_url(self.job_description))

    def test_anonymous_card_actions(self, client):
        response = client.get(self.url)

        assertContains(response, "Postuler auprès de l'employeur inclusif")
        assertContains(response, self.apply_start_url(self.company))
        assertNotContains(response, self.update_job_description_url(self.job_description))

    def test_display_placeholder_for_empty_fields(self, client):
        PLACE_HOLDER = "La structure n'a pas encore renseigné cette rubrique"

        response = self._login(client, self.user)

        # Job description created in setup has empty description fields
        assertContains(response, PLACE_HOLDER, count=2)

        self.job_description.description = "a job description"
        self.job_description.save()
        response = client.get(self.url)

        assertContains(response, "a job description")
        assertContains(response, PLACE_HOLDER)

        self.job_description.profile_description = "a profile description"
        self.job_description.save()
        response = client.get(self.url)

        assertContains(response, "a job description")
        assertContains(response, "a profile description")
        assertNotContains(response, PLACE_HOLDER)
