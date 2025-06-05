import datetime

import pytest
from django.contrib import messages
from django.contrib.gis.geos import Point
from django.core.exceptions import ObjectDoesNotExist
from django.template.defaultfilters import urlencode
from django.urls import resolve, reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNotContains, assertRedirects

from itou.cities.models import City
from itou.companies.enums import CompanyKind, ContractType
from itou.companies.models import JobDescription
from itou.jobs.models import Appellation, Rome
from itou.utils.session import SessionNamespace
from itou.www.companies_views.views import JOB_DESCRIPTION_EDIT_SESSION_KIND
from tests.companies.factories import (
    CompanyFactory,
    CompanyWith2MembershipsFactory,
    JobDescriptionFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import EmployerFactory, JobSeekerFactory, PrescriberFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import assertSnapshotQueries, parse_response_to_soup, pretty_indented


POSTULER = "Postuler"
REMINDER_BANNER = (
    '<p class="mb-0"><strong>Attention</strong> : Très prochainement, vos fiches de poste qui n’ont pas été '
    "actualisées depuis plus de 3 mois seront automatiquement dépubliées. "
    f'<a href="{reverse("companies_views:job_description_list")}">Pensez à les mettre à jour pour maintenir '
    "leur visibilité</a>.</p>"
)


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


class TestJobDescriptionListView(JobDescriptionAbstract):
    BLOCK_JOB_APPS_BTN = "Bloquer l'envoi de candidatures"
    UNBLOCK_JOB_APPS_BTN = "Débloquer l'envoi de candidatures"

    @pytest.fixture(autouse=True)
    def setup_method(self):
        self.url = self.list_url + "?page=1"

    def test_response_content(self, client, snapshot, subtests):
        client.force_login(self.user)
        with assertSnapshotQueries(snapshot(name="job descriptions list")):
            response = client.get(self.url)

        assert self.company.job_description_through.count() == 4
        assertContains(
            response,
            '<p class="mb-0">4 métiers exercés</p>',
            html=True,
            count=1,
        )

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

    def test_ordering(self, client, subtests):
        self.company.job_description_through.all().delete()
        first = JobDescriptionFactory(company=self.company, last_employer_update_at=None)
        second = JobDescriptionFactory(company=self.company, last_employer_update_at=None)
        third = JobDescriptionFactory(company=self.company, last_employer_update_at=None)

        client.force_login(self.user)

        with subtests.test(order="default"):
            response = client.get(self.list_url)
            assert response.context["job_pager"].object_list == [third, second, first]

        with subtests.test(order="with-inactive"):
            second.is_active = False
            second.save(update_fields=["is_active", "updated_at"])
            response = client.get(self.list_url)
            assert response.context["job_pager"].object_list == [third, first, second]

        with subtests.test(order="with-recent-updated-at"):
            first.save(update_fields=["updated_at"])
            response = client.get(self.list_url)
            assert response.context["job_pager"].object_list == [first, third, second]

        with subtests.test(order="with-inactive-last-employer-update-at"):
            second.last_employer_update_at = timezone.now()
            second.save(update_fields=["updated_at", "last_employer_update_at"])
            response = client.get(self.list_url)
            assert response.context["job_pager"].object_list == [first, third, second]

        with subtests.test(order="with-active-last-employer-update-at"):
            first.last_employer_update_at = timezone.now()
            first.save(update_fields=["updated_at", "last_employer_update_at"])
            third.save(update_fields=["updated_at"])
            response = client.get(self.list_url)
            assert response.context["job_pager"].object_list == [third, first, second]

            # Refresh updated_at, last_employer_update_at takes precedence
            first.save(update_fields=["updated_at"])
            assert response.context["job_pager"].object_list == [third, first, second]

    @pytest.mark.parametrize("no_job_descriptions", [True, False])
    def test_block_job_applications(self, client, no_job_descriptions):
        if no_job_descriptions:
            self.company.job_description_through.all().delete()
            assert self.company.jobs.count() == 0

        client.force_login(self.user)
        response = client.get(self.url)
        assertContains(response, self.BLOCK_JOB_APPS_BTN)
        assertNotContains(response, self.UNBLOCK_JOB_APPS_BTN)

        post_data = {"action": "block_job_applications", "block_job_applications": "true"}
        response = client.post(self.url, data=post_data, follow=True)
        assertNotContains(response, self.BLOCK_JOB_APPS_BTN)
        assertContains(response, self.UNBLOCK_JOB_APPS_BTN)
        self.company.refresh_from_db()
        assert self.company.block_job_applications

        post_data = {"action": "block_job_applications", "block_job_applications": "false"}
        response = client.post(self.url, data=post_data, follow=True)
        assertContains(response, self.BLOCK_JOB_APPS_BTN)
        assertNotContains(response, self.UNBLOCK_JOB_APPS_BTN)
        self.company.refresh_from_db()
        assert not self.company.block_job_applications

        # Test indempotency
        post_data = {"action": "block_job_applications", "block_job_applications": "false"}
        response = client.post(self.url, data=post_data, follow=True)
        assertContains(response, self.BLOCK_JOB_APPS_BTN)
        assertNotContains(response, self.UNBLOCK_JOB_APPS_BTN)
        self.company.refresh_from_db()
        assert not self.company.block_job_applications

    @freeze_time("2025-01-01")
    def test_toggle_spontaneous_applications(self, client, snapshot):
        client.force_login(self.user)
        response = client.get(self.url)
        assert (
            pretty_indented(parse_response_to_soup(response, "#toggle_job_description_form_spontaneous_applications"))
            == snapshot
        )

        post_data = {"action": "toggle_spontaneous_applications"}
        client.post(self.url, data=post_data)
        self.company.refresh_from_db()
        assert self.company.spontaneous_applications_open_since is None

        post_data = {"action": "toggle_spontaneous_applications"}
        client.post(self.url, data=post_data)
        self.company.refresh_from_db()
        assert self.company.spontaneous_applications_open_since == timezone.now()

    @freeze_time("2021-06-21 10:10:10.10")
    def test_toggle_job_description_activity(self, client):
        client.force_login(self.user)
        response = client.get(self.url)

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

    def test_toggle_job_description_active_updates_last_employer_update_at(self, client):
        with freeze_time("2025-04-09 15:16:17.18") as frozen_time:
            client.force_login(self.user)

            job_description = JobDescriptionFactory(company=self.company, is_active=True)
            initial_last_employer_update_at = job_description.last_employer_update_at

            frozen_time.tick()

            # Setting inactive should not postpone last_employer_update_at
            post_data = {"job_description_id": job_description.pk, "action": "toggle_active"}
            client.post(self.url, data=post_data)
            job_description.refresh_from_db()
            assert not job_description.is_active
            assert job_description.updated_at == timezone.now()
            assert job_description.last_employer_update_at == initial_last_employer_update_at

            # Setting active should postpone last_employer_update_at
            post_data = {
                "job_description_id": job_description.pk,
                "job_description_is_active": "on",
                "action": "toggle_active",
            }
            client.post(self.url, data=post_data)
            job_description.refresh_from_db()
            assert job_description.is_active is True
            assert job_description.updated_at == timezone.now()
            assert job_description.last_employer_update_at == timezone.now()

    @pytest.mark.parametrize(
        "is_closed,expected",
        [
            (True, lambda: None),
            (False, lambda: timezone.now()),
        ],
        ids=["closed", "open"],
    )
    def test_spontaneous_applications_refresh_updates_spontaneous_applications_open_since(
        self, is_closed, expected, client
    ):
        with freeze_time("2025-04-09 15:16:17.18") as frozen_time:
            self.company.spontaneous_applications_open_since = timezone.now()
            self.company.save(update_fields=["spontaneous_applications_open_since", "updated_at"])

            frozen_time.move_to("2025-04-11 15:16:17.18")

            client.force_login(self.user)

            list_url = reverse("companies_views:job_description_list")
            refresh_url = reverse("companies_views:spontaneous_applications_refresh")
            response = client.get(list_url)
            page = parse_response_to_soup(response, selector="div.table-responsive > table")

            if is_closed:
                # Close spontaneous applications
                self.company.spontaneous_applications_open_since = None
                self.company.save(update_fields=["spontaneous_applications_open_since", "updated_at"])

            response = client.post(
                refresh_url, headers={"hx-request": "true", "hx-target": "refresh_spontaneous_applications_opening"}
            )
            update_page_with_htmx(page, f"form[hx-post='{refresh_url}']", response)

            self.company.refresh_from_db()
            assert self.company.spontaneous_applications_open_since == expected()

            response = client.get(list_url)
            fresh_page = parse_response_to_soup(response, selector="div.table-responsive > table")
            assertSoupEqual(page, fresh_page)

    @pytest.mark.parametrize("is_active", [True, False])
    def test_job_description_refresh_updates_last_employer_update_at(self, is_active, client):
        with freeze_time("2025-04-09 15:16:17.18") as frozen_time:
            client.force_login(self.user)

            job_description = JobDescriptionFactory(
                company=self.company, is_active=is_active, last_employer_update_at=timezone.now()
            )

            frozen_time.move_to("2025-04-11 15:16:17.18")

            list_url = reverse("companies_views:job_description_list")
            refresh_url = reverse("companies_views:job_description_refresh", args=(job_description.pk,))
            response = client.get(list_url)
            page = parse_response_to_soup(response, selector="div.table-responsive > table")

            response = client.post(refresh_url, headers={"hx-request": "true"})
            update_page_with_htmx(page, f"form[hx-post='{refresh_url}']", response)

            job_description.refresh_from_db()
            assert job_description.last_employer_update_at == timezone.now()

            response = client.get(list_url)
            fresh_page = parse_response_to_soup(response, selector="div.table-responsive > table")
            assertSoupEqual(page, fresh_page)

    def test_delete_job_descriptions(self, client):
        client.force_login(self.user)
        response = client.get(self.url)

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
    @freeze_time("2025-04-09 15:16:17.18")
    def test_edit_job_description_company(self, client):
        client.force_login(self.user)
        url = reverse("companies_views:edit_job_description")

        response = client.get(url)
        assert response.status_code == 200
        post_data = {
            "appellation": "11076",  # Must be a non existing one for the company
            "location": self.paris_city.pk,
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": 5,
        }
        response = client.post(url, data=post_data)
        resolver_match = resolve(response.url)
        assert resolver_match.view_name == "companies_views:edit_job_description_details"
        session_key = str(resolver_match.kwargs["edit_session_id"])  # It’s a UUID.
        expected_session_data = post_data
        expected_session_data["custom_name"] = ""
        assert client.session[session_key] == expected_session_data
        details_url = response.url

        # Step 2: edit job description details
        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": True,
        }
        response = client.post(details_url, data=post_data)
        resolver_match = resolve(response.url)
        assert resolver_match.view_name == "companies_views:edit_job_description_preview"
        assert str(resolver_match.kwargs["edit_session_id"]) == session_key
        expected_session_data.update(post_data)
        assert client.session[session_key] == expected_session_data
        preview_url = response.url

        # Step 3: preview and validation
        response = client.get(preview_url)

        assertContains(response, "description")
        assertContains(response, "profile_description")
        assertContains(response, "Curriculum Vitae")

        response = client.post(preview_url)
        assertRedirects(response, self.list_url)
        assert session_key not in client.session
        assert self.company.job_description_through.count() == 5

        # Creation immediately activates job description
        # Hence its last activation date should be automatically defined
        assert self.company.job_description_through.order_by("-pk").first().last_employer_update_at == timezone.now()

    @freeze_time("2025-04-09 15:16:17.18")
    def test_edit_job_description_opcs(self, client):
        opcs = CompanyFactory(
            department="75",
            coords=self.paris_city.coords,
            post_code="75001",
            kind=CompanyKind.OPCS,
            with_membership=True,
        )
        user_opcs = opcs.members.first()
        opcs.jobs.add(*self.appellations)

        client.force_login(user_opcs)
        response = client.get(self.edit_url)

        assert response.status_code == 200

        # Step 1: edit job description
        response = client.get(self.edit_url)
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
        resolver_match = resolve(response.url)
        assert resolver_match.view_name == "companies_views:edit_job_description_details"
        session_key = str(resolver_match.kwargs["edit_session_id"])  # It’s a UUID.
        expected_session_data = post_data
        expected_session_data["custom_name"] = ""
        assert client.session[session_key] == expected_session_data
        details_url = response.url

        # Step 2: edit job description details and check the rendered markdown
        post_data = {
            "description": "**Lorem ipsum**\n<span>Span</span>",  # HTML tags should be ignored
            "profile_description": "profile_*description*",
            "is_resume_mandatory": True,
            "is_qpv_mandatory": True,
        }

        response = client.post(details_url, data=post_data)
        resolver_match = resolve(response.url)
        assert resolver_match.view_name == "companies_views:edit_job_description_preview"
        assert str(resolver_match.kwargs["edit_session_id"]) == session_key
        expected_session_data.update(post_data)
        assert client.session[session_key] == expected_session_data
        preview_url = response.url

        # Step 3: preview and validation
        response = client.get(preview_url)
        assertContains(response, "<strong>Lorem ipsum</strong><br>\nSpan")
        assertContains(response, "profile_<em>description</em>")
        assertContains(response, "Whatever market description")
        assertContains(response, "Curriculum Vitae")
        # Rendering of `is_qpv_mandatory`
        assertContains(response, "typologies de public particulières")

        response = client.post(preview_url)

        assertRedirects(response, self.list_url)
        assert session_key not in client.session
        assert opcs.job_description_through.count() == 5

        # Creation immediately activates job description
        # Hence its last activation date should be automatically defined
        assert opcs.job_description_through.order_by("-pk").first().last_employer_update_at == timezone.now()

    def test_remove_location(self, client):
        job_description = self.company.job_description_through.filter(location__isnull=False).first()
        initial_location_name = job_description.location.name
        client.force_login(self.user)

        edit_url = reverse(
            "companies_views:edit_job_description",
            kwargs={"job_description_id": job_description.pk},
        )
        # Step 1: edit job description
        response = client.get(edit_url)
        assertContains(response, initial_location_name)

        post_data = {
            "appellation": job_description.appellation.code,
            "custom_name": "custom_name",
            "location": "",  # Remove location
            "hours_per_week": 35,
            "contract_type": ContractType.OTHER.value,
            "other_contract_type": "other_contract_type",
            "open_positions": job_description.open_positions,
        }
        response = client.post(edit_url, data=post_data)
        resolver_match = resolve(response.url)
        assert resolver_match.view_name == "companies_views:edit_job_description_details"
        assert resolver_match.kwargs["job_description_id"] == job_description.pk
        session_key = str(resolver_match.kwargs["edit_session_id"])  # It’s a UUID.
        expected_session_data = post_data
        expected_session_data["location"] = None
        assert client.session[session_key] == expected_session_data
        details_url = response.url

        # Step 2: edit job description details
        post_data = {
            "description": "description",
            "profile_description": "profile_description",
            "is_resume_mandatory": True,
        }
        response = client.post(details_url, data=post_data)
        resolver_match = resolve(response.url)
        assert resolver_match.view_name == "companies_views:edit_job_description_preview"
        assert resolver_match.kwargs["job_description_id"] == job_description.pk
        assert str(resolver_match.kwargs["edit_session_id"]) == session_key
        expected_session_data.update(post_data)
        assert client.session[session_key] == expected_session_data
        preview_url = response.url

        # Step 3: preview
        response = client.get(preview_url)
        assertNotContains(response, initial_location_name)

        # Step 4: validation
        response = client.post(preview_url)
        assertRedirects(response, self.list_url)
        assert session_key not in client.session

        job_description.refresh_from_db()
        assert job_description.location is None

    def test_edit_job_description_of_other_company(self, client):
        job_description = JobDescriptionFactory()
        client.force_login(self.user)
        response = client.get(
            reverse(
                "companies_views:edit_job_description",
                kwargs={"job_description_id": job_description.pk},
            )
        )
        assert response.status_code == 404

    def test_edit_job_description_details_of_other_company(self, client):
        my_job_description = self.company.job_description_through.first()
        other_job_description = JobDescriptionFactory()
        client.force_login(self.user)
        post_data = {
            "appellation": my_job_description.appellation.code,
            "custom_name": my_job_description.custom_name,
            "location": my_job_description.location_id,
            "contract_type": ContractType.FIXED_TERM_I,
            "open_positions": my_job_description.open_positions,
        }
        response = client.post(
            reverse(
                "companies_views:edit_job_description",
                kwargs={"job_description_id": my_job_description.pk},
            ),
            data=post_data,
        )
        resolver_match = resolve(response.url)
        assert resolver_match.view_name == "companies_views:edit_job_description_details"
        assert resolver_match.kwargs["job_description_id"] == my_job_description.pk
        session_key = str(resolver_match.kwargs["edit_session_id"])  # It’s a UUID.

        response = client.get(
            reverse(
                "companies_views:edit_job_description_details",
                kwargs={
                    # Try updating a job description from another company by changing the URL.
                    "job_description_id": other_job_description.pk,
                    "edit_session_id": session_key,
                },
            ),
            data=post_data,
        )
        assert response.status_code == 404
        response = client.get(
            reverse(
                "companies_views:edit_job_description_preview",
                kwargs={
                    # Try updating a job description from another company by changing the URL.
                    "job_description_id": other_job_description.pk,
                    "edit_session_id": session_key,
                },
            ),
            data=post_data,
        )
        assert response.status_code == 404

    @pytest.mark.parametrize("is_active", [True, False])
    def test_last_employer_update_at_updates(self, is_active, client):
        client.force_login(self.user)

        with freeze_time() as frozen_time:
            job_description = JobDescriptionFactory(
                company=self.company,
                is_active=is_active,
                last_employer_update_at=frozen_time().replace(tzinfo=datetime.UTC),
            )
            session_namespace = SessionNamespace.create_uuid_namespace(
                client.session,
                JOB_DESCRIPTION_EDIT_SESSION_KIND,
                {
                    "appellation": job_description.appellation.code,
                    "custom_name": job_description.custom_name,
                    "location": job_description.location,
                    "hours_per_week": job_description.hours_per_week,
                    "contract_type": job_description.contract_type,
                    "other_contract_type": job_description.other_contract_type,
                    "open_positions": job_description.open_positions,
                    "description": job_description.description,
                    "profile_description": job_description.profile_description,
                    "is_resume_mandatory": job_description.is_resume_mandatory,
                },
            )
            session_namespace.save()

            frozen_time.tick()

            response = client.post(
                reverse(
                    "companies_views:edit_job_description_preview",
                    kwargs={
                        "edit_session_id": str(session_namespace.name),
                        "job_description_id": job_description.pk,
                    },
                )
            )
            assertRedirects(response, self.list_url)

            job_description.refresh_from_db()
            assert job_description.is_active == is_active
            assert job_description.updated_at == timezone.now()
            assert job_description.last_employer_update_at == timezone.now()


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
            "companies_views:edit_job_description",
            kwargs={"job_description_id": job_description.pk},
        )

    def test_employer_card_actions(self, client):
        # Checks if company can update their job descriptions
        client.force_login(self.user)
        response = client.get(self.url)

        assertContains(response, "Modifier la fiche de poste")
        assertContains(response, self.update_job_description_url(self.job_description))
        assertContains(response, reverse("companies_views:job_description_list"))
        assertNotContains(response, self.apply_start_url(self.company))

    def test_prescriber_card_actions(self, client, snapshot):
        # Checks if non-employers can apply to opened job descriptions
        client.force_login(PrescriberOrganizationWithMembershipFactory().members.first())

        with assertSnapshotQueries(snapshot):
            response = client.get(self.url)

        assertContains(response, f"{POSTULER} auprès de l'employeur inclusif")
        assertContains(response, self.apply_start_url(self.company))
        assertNotContains(
            response,
            self.update_job_description_url(self.job_description),
        )

    def test_job_seeker_card_actions(self, client, snapshot):
        client.force_login(JobSeekerFactory())

        with assertSnapshotQueries(snapshot):
            response = client.get(self.url)

        assertContains(response, f"{POSTULER} auprès de l'employeur inclusif")
        assertContains(response, self.apply_start_url(self.company))
        assertNotContains(response, self.update_job_description_url(self.job_description))

    def test_anonymous_card_actions(self, client):
        response = client.get(self.url)

        assertContains(response, f"{POSTULER} auprès de l'employeur inclusif")
        assertContains(response, self.apply_start_url(self.company))
        assertNotContains(response, self.update_job_description_url(self.job_description))

    def test_display_placeholder_for_empty_fields(self, client):
        PLACE_HOLDER = "La structure n'a pas encore renseigné cette rubrique"

        client.force_login(self.user)
        response = client.get(self.url)

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

    @pytest.mark.parametrize("is_active", [True, False])
    @freeze_time("2025-05-07")
    def test_job_description_refresh_updates_last_employer_update_at(self, is_active, client):
        refresh_url = reverse("companies_views:job_description_refresh_for_detail", args=(self.job_description.pk,))
        client.force_login(self.user)

        self.job_description.is_active = is_active
        self.job_description.last_employer_update_at = None
        self.job_description.save()

        response = client.get(self.url)
        page = parse_response_to_soup(response, selector=".c-navinfo__info")
        assertContains(
            response, '<span class="fs-sm text-muted fw-normal">Actualiser la date de mise à jour</span>', html=True
        )

        response = client.post(refresh_url, headers={"hx-request": "true"})
        update_page_with_htmx(page, f"form[hx-post='{refresh_url}']", response)
        assertContains(
            response, '<span class="fs-sm text-muted fw-normal">Mise à jour le 07/05/2025</span>', html=True
        )

        self.job_description.refresh_from_db()
        assert self.job_description.last_employer_update_at == timezone.now()

        response = client.get(self.url)
        fresh_page = parse_response_to_soup(response, selector=".c-navinfo__info")
        assertSoupEqual(page, fresh_page)


@pytest.mark.parametrize(
    "user_factory",
    [
        pytest.param(lambda: JobSeekerFactory(for_snapshot=True), id="job_seeker"),
        pytest.param(lambda: PrescriberFactory(), id="prescriber"),
        pytest.param(
            lambda: EmployerFactory(
                with_company=True, with_company__company__spontaneous_applications_open_since=None
            ),
            id="employer_without_jobs",
        ),
    ],
)
def test_dont_display_reminder_banner_not_updated_jobs(client, user_factory):
    user = user_factory()
    client.force_login(user)

    response = client.get(reverse("dashboard:index"))
    assertNotContains(
        response,
        REMINDER_BANNER,
        html=True,
    )


@freeze_time("2025-06-06")
def test_display_reminder_banner_not_updated_jobs_for_employer(client):
    OLD_DATE = timezone.now() - datetime.timedelta(days=61)
    RECENT_DATE = timezone.now() - datetime.timedelta(days=59)

    rome = Rome.objects.create(code="I1304", name="Rome 1304")
    Appellation.objects.create(code="I13042", name="Doer", rome=rome)

    # Spontaneous application recently updated
    company = CompanyWith2MembershipsFactory(spontaneous_applications_open_since=RECENT_DATE)
    client.force_login(company.members.first())
    response = client.get(reverse("dashboard:index"))
    assertNotContains(
        response,
        REMINDER_BANNER,
        html=True,
    )

    # Spontaneous application updated a long time ago (>= 60 days)
    company.spontaneous_applications_open_since = OLD_DATE
    company.save()
    response = client.get(reverse("dashboard:index"))
    assertContains(
        response,
        REMINDER_BANNER,
        html=True,
    )

    # Recently updated job application
    company = CompanyWith2MembershipsFactory(spontaneous_applications_open_since=None)
    job_description = JobDescriptionFactory(
        company=company, created_at=RECENT_DATE, last_employer_update_at=RECENT_DATE
    )
    client.force_login(company.members.first())
    response = client.get(reverse("dashboard:index"))
    assertNotContains(
        response,
        REMINDER_BANNER,
        html=True,
    )

    # Job application updated a long time ago (>= 60 days)
    job_description.last_employer_update_at = OLD_DATE
    job_description.save()
    response = client.get(reverse("dashboard:index"))
    assertContains(
        response,
        REMINDER_BANNER,
        html=True,
    )
