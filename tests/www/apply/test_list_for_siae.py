import datetime
import itertools
from urllib.parse import unquote

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertNotContains, assertQuerySetEqual

from itou.companies.enums import CompanyKind
from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplicationWorkflow
from itou.jobs.models import Appellation
from itou.utils.urls import add_url_params
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.apply.views.list_views import JobApplicationsDisplayKind
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.cities.factories import create_city_saint_andre
from tests.companies.factories import CompanyFactory, JobDescriptionFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByJobSeekerFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import JobSeekerFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import (
    assert_previous_step,
    assertSnapshotQueries,
    get_rows_from_streaming_response,
    parse_response_to_soup,
)


class TestProcessListSiae:
    SELECTED_JOBS = "selected_jobs"

    def test_list_for_siae(self, client, snapshot):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        city = create_city_saint_andre()
        create_test_romes_and_appellations(["N4105"], appellations_per_rome=2)
        appellations = Appellation.objects.all()[:2]
        job1 = JobDescriptionFactory(company=company, appellation=appellations[0], location=city)
        job2 = JobDescriptionFactory(company=company, appellation=appellations[1], location=city)

        # A job application without eligibility diagnosis
        job_app = JobApplicationFactory(to_company=company, selected_jobs=[job1, job2], eligibility_diagnosis=None)
        # Two with it (ensure there are no 1+N queries)
        JobApplicationFactory.create_batch(2, to_company=company, selected_jobs=[job1, job2])
        # A job application for another company
        JobApplicationFactory()

        client.force_login(employer)
        with assertSnapshotQueries(snapshot(name="view queries")):
            response = client.get(reverse("apply:list_for_siae"))

        total_applications = len(response.context["job_applications_page"].object_list)

        # Result page should contain all the company's job applications.
        assert total_applications == 3

        # Has link to export with back_url set
        export_url = unquote(
            add_url_params(reverse("apply:list_for_siae_exports"), {"back_url": reverse("apply:list_for_siae")})
        )
        assertContains(response, export_url)

        # Has job application card link with back_url set
        job_application_link = unquote(
            add_url_params(
                reverse("apply:details_for_company", kwargs={"job_application_id": job_app.pk}),
                {"back_url": reverse("apply:list_for_siae")},
            )
        )
        assertContains(response, job_application_link)

        assertContains(
            response,
            # Appellations are ordered by name.
            f"""
            <div class="dropdown">
            <button type="button" class="btn btn-dropdown-filter dropdown-toggle" data-bs-toggle="dropdown"
                    data-bs-auto-close="outside" aria-expanded="false">
                Fiches de poste
            </button>
            <ul class="dropdown-menu">
            <li class="dropdown-item">
            <div class="form-check">
            <input id="id_selected_jobs_0-top"
                   class="form-check-input"
                   data-sync-with="id_selected_jobs_0"
                   name="{self.SELECTED_JOBS}"
                   type="checkbox"
                   value="{job1.appellation.code}">
            <label for="id_selected_jobs_0-top" class="form-check-label">{job1.appellation.name}</label>
            </div>
            </li>
            <li class="dropdown-item">
            <div class="form-check">
                <input id="id_selected_jobs_1-top"
                       class="form-check-input"
                       data-sync-with="id_selected_jobs_1"
                       name="{self.SELECTED_JOBS}"
                       type="checkbox"
                       value="{job2.appellation.code}">
                <label for="id_selected_jobs_1-top" class="form-check-label">{job2.appellation.name}</label>
            </div>
            </li>
            </ul>
            """,
            html=True,
            count=1,
        )
        assertContains(response, job_app.job_seeker.get_full_name())
        assertNotContains(
            response, reverse("job_seekers_views:details", kwargs={"public_id": job_app.job_seeker.public_id})
        )

    def test_list_for_siae_show_criteria(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        criteria = AdministrativeCriteria.objects.filter(
            name__in=[
                # Level 1 criteria
                "Allocataire AAH",
                "Allocataire ASS",
                "Bénéficiaire du RSA",
                # Level 2 criterion
                "Senior (+50 ans)",
            ]
        )
        assert len(criteria) == 4
        diagnosis.administrative_criteria.add(*criteria)
        JobApplicationFactory(
            job_seeker=diagnosis.job_seeker,
            to_company=company,
            eligibility_diagnosis=None,  # fallback on the jobseeker's
        )

        client.force_login(employer)
        response = client.get(reverse("apply:list_for_siae"))

        # 4 criteria: all are shown
        assertContains(response, "<li>Allocataire AAH</li>", html=True)
        assertContains(response, "<li>Allocataire ASS</li>", html=True)
        assertContains(response, "<li>Bénéficiaire du RSA</li>", html=True)
        SENIOR_CRITERION = "<li>Senior (+50 ans)</li>"
        assertContains(response, SENIOR_CRITERION, html=True)

        # Add a 5th criterion to the diagnosis
        diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.get(name="DETLD (+ 24 mois)"))

        response = client.get(reverse("apply:list_for_siae"))
        # Only the 3 first are shown (ordered by level & name)
        # The 4th line has been replaced by "+ 2 autres critères"
        assertContains(response, "<li>Allocataire AAH</li>", html=True)
        assertContains(response, "<li>Allocataire ASS</li>", html=True)
        assertContains(response, "<li>Bénéficiaire du RSA</li>", html=True)
        assertNotContains(response, SENIOR_CRITERION, html=True)
        # DETLD is also not shown
        assertContains(response, "+ 2 autres critères")

        # No selected jobs, the filter should not appear.
        assertNotContains(response, self.SELECTED_JOBS)

    def test_list_for_siae_hide_criteria_for_non_SIAE_employers(self, client, subtests):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        # Level 1 criteria
        diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.get(name="Allocataire AAH"))
        JobApplicationFactory(
            job_seeker=diagnosis.job_seeker,
            to_company=company,
            eligibility_diagnosis=None,  # fallback on the jobseeker's
        )

        TITLE = '<p class="h5">Critères administratifs IAE</p>'
        CRITERION = "<li>Allocataire AAH</li>"

        client.force_login(employer)

        expect_to_see_criteria = {
            CompanyKind.EA: False,
            CompanyKind.EATT: False,
            CompanyKind.EI: True,
            CompanyKind.GEIQ: False,
            CompanyKind.OPCS: False,
            CompanyKind.ACI: True,
            CompanyKind.AI: True,
            CompanyKind.EITI: True,
            CompanyKind.ETTI: True,
        }
        for kind in CompanyKind:
            with subtests.test(kind=kind.label):
                company.kind = kind
                company.save(update_fields=("kind",))
                response = client.get(reverse("apply:list_for_siae"))
                if expect_to_see_criteria[kind]:
                    assertContains(response, TITLE, html=True)
                    assertContains(response, CRITERION, html=True)
                else:
                    assertNotContains(response, TITLE, html=True)
                    assertNotContains(response, CRITERION, html=True)

    def test_list_for_siae_filtered_by_one_state(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        accepted_job_application = JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
        JobApplicationFactory(to_company=company, state=JobApplicationState.NEW)

        client.force_login(employer)
        response = client.get(reverse("apply:list_for_siae"), {"states": [JobApplicationState.ACCEPTED]})

        applications = response.context["job_applications_page"].object_list
        assert applications == [accepted_job_application]

    def test_list_for_siae_filtered_by_state_prior_to_hire(self, client):
        PRIOR_TO_HIRE_LABEL = "Action préalable à l’embauche</label>"
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
        prior_to_hire_job_app = JobApplicationFactory(to_company=company, state=JobApplicationState.PRIOR_TO_HIRE)

        # prior_to_hire filter doesn't exist for non-GEIQ companies and is ignored
        client.force_login(employer)
        params = {"states": [JobApplicationState.PRIOR_TO_HIRE]}
        response = client.get(reverse("apply:list_for_siae"), params)
        assertNotContains(response, PRIOR_TO_HIRE_LABEL)

        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 2

        # With a GEIQ user, the filter is present and works
        company.kind = CompanyKind.GEIQ
        company.save()
        response = client.get(reverse("apply:list_for_siae"), params)
        assertContains(response, PRIOR_TO_HIRE_LABEL)

        applications = response.context["job_applications_page"].object_list
        assert applications == [prior_to_hire_job_app]

    def test_list_for_siae_filtered_by_many_states(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
        new_job_app = JobApplicationFactory(to_company=company, state=JobApplicationState.NEW)
        processing_job_app = JobApplicationFactory(to_company=company, state=JobApplicationState.PROCESSING)

        client.force_login(employer)
        job_applications_states = [JobApplicationState.NEW, JobApplicationState.PROCESSING]
        response = client.get(reverse("apply:list_for_siae"), {"states": job_applications_states})

        applications = response.context["job_applications_page"].object_list
        assertQuerySetEqual(applications, [new_job_app, processing_job_app], ordered=False)

    def test_list_for_siae_filtered_by_dates(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        date_format = DuetDatePickerWidget.INPUT_DATE_FORMAT
        for i in range(4):
            JobApplicationFactory(to_company=company, created_at=timezone.now() - timezone.timedelta(days=i))
        job_applications = list(company.job_applications_received.order_by("created_at"))

        client.force_login(employer)
        start_date = job_applications[1].created_at
        end_date = job_applications[-2].created_at
        response = client.get(
            reverse("apply:list_for_siae"),
            {
                "start_date": timezone.localdate(start_date).strftime(date_format),
                "end_date": timezone.localdate(end_date).strftime(date_format),
            },
        )
        applications = response.context["job_applications_page"].object_list

        assert len(applications) == 2
        assert all(start_date <= job_app.created_at <= end_date for job_app in applications)

    def test_list_for_siae_empty_dates_in_params(self, client):
        """
        Our form uses a Datepicker that adds empty start and end dates
        in the HTTP query if they are not filled in by the user.
        Make sure the template loads all available job applications if fields are empty.
        """
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        job_app = JobApplicationFactory(to_company=company)

        client.force_login(employer)
        response = client.get(add_url_params(reverse("apply:list_for_siae"), {"start_date": "", "end_date": ""}))
        assert response.context["job_applications_page"].object_list == [job_app]

    def test_list_for_siae_filtered_by_sender_organization_name(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        job_app_1 = JobApplicationFactory(to_company=company, sent_by_authorized_prescriber_organisation=True)
        job_app_2 = JobApplicationFactory(to_company=company, sent_by_authorized_prescriber_organisation=True)
        _job_app_3 = JobApplicationFactory(to_company=company, sent_by_authorized_prescriber_organisation=True)

        client.force_login(employer)
        response = client.get(
            reverse("apply:list_for_siae"),
            {"sender_prescriber_organizations": [job_app_1.sender_prescriber_organization.id]},
        )
        assert response.context["job_applications_page"].object_list == [job_app_1]

        response = client.get(
            reverse("apply:list_for_siae"),
            {
                "sender_prescriber_organizations": [
                    job_app_1.sender_prescriber_organization.id,
                    job_app_2.sender_prescriber_organization.id,
                ]
            },
        )
        applications = response.context["job_applications_page"].object_list
        assertQuerySetEqual(applications, [job_app_1, job_app_2], ordered=False)

    def test_list_for_siae_filtered_by_sender_name(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        job_app = JobApplicationFactory(to_company=company)
        _another_job_app = JobApplicationFactory(to_company=company)

        client.force_login(employer)
        response = client.get(reverse("apply:list_for_siae"), {"senders": [job_app.sender.id]})
        assert response.context["job_applications_page"].object_list == [job_app]

    def test_list_for_siae_filtered_by_job_seeker_name(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        job_app = JobApplicationFactory(to_company=company)
        _another_job_app = JobApplicationFactory(to_company=company)

        client.force_login(employer)
        response = client.get(reverse("apply:list_for_siae"), {"job_seeker": job_app.job_seeker.pk})
        assert response.context["job_applications_page"].object_list == [job_app]

    def test_list_for_siae_filtered_by_pass_state(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        today = timezone.localdate()
        yesterday = today - timezone.timedelta(days=1)
        client.force_login(employer)

        JobApplicationFactory(to_company=company)

        # Without approval
        response = client.get(reverse("apply:list_for_siae"), {"pass_iae_active": True})
        assert len(response.context["job_applications_page"].object_list) == 0

        # With a job_application with an approval
        job_application = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=yesterday,
            approval__start_at=yesterday,
            to_company=company,
        )
        response = client.get(reverse("apply:list_for_siae"), {"pass_iae_active": True})
        assert response.context["job_applications_page"].object_list == [job_application]

        # Check that adding pass_iae_suspended does not hide the application
        response = client.get(reverse("apply:list_for_siae"), {"pass_iae_active": True, "pass_iae_suspended": True})
        assert response.context["job_applications_page"].object_list == [job_application]

        # But pass_iae_suspended alone does not show the application
        response = client.get(reverse("apply:list_for_siae"), {"pass_iae_suspended": True})
        assert response.context["job_applications_page"].object_list == []

        # Now with a suspension
        SuspensionFactory(
            approval=job_application.approval,
            start_at=yesterday,
            end_at=today + timezone.timedelta(days=2),
        )
        response = client.get(reverse("apply:list_for_siae"), {"pass_iae_suspended": True})
        assert response.context["job_applications_page"].object_list == [job_application]

        # Check that adding pass_iae_active does not hide the application
        response = client.get(reverse("apply:list_for_siae"), {"pass_iae_active": True, "pass_iae_suspended": True})
        assert response.context["job_applications_page"].object_list == [job_application]

    def test_list_for_siae_filtered_by_eligibility_validated(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        job_app = JobApplicationFactory(to_company=company, eligibility_diagnosis=None)
        _another_job_app = JobApplicationFactory(to_company=company, eligibility_diagnosis=None)

        client.force_login(employer)
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == []

        # Authorized prescriber diagnosis
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_app.job_seeker)
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == [job_app]

        # Make sure the diagnostic expired - it should be ignored
        diagnosis.expires_at = timezone.now() - datetime.timedelta(days=diagnosis.EXPIRATION_DELAY_MONTHS * 31 + 1)
        diagnosis.save(update_fields=("expires_at",))
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == []

        # Diagnosis made by employer's SIAE
        diagnosis.delete()
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=job_app.job_seeker, from_employer=True, author_siae=company
        )
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == [job_app]

        # Diagnosis made by an other SIAE - it should be ignored
        diagnosis.delete()
        diagnosis = IAEEligibilityDiagnosisFactory(job_seeker=job_app.job_seeker, from_employer=True)
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == []

        # With a valid approval
        approval = ApprovalFactory(
            user=job_app.job_seeker,
            with_origin_values=True,  # origin_values needed to delete it
        )
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == [job_app]

        # With an expired approval
        approval_diagnosis = approval.eligibility_diagnosis
        approval.delete()
        approval_diagnosis.delete()
        approval = ApprovalFactory(expired=True)
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == []

    def test_list_for_siae_filtered_by_administrative_criteria(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)

        job_app = JobApplicationFactory(to_company=company, eligibility_diagnosis=None)
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_app.job_seeker)

        level1_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
        level2_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()
        level1_other_criterion = AdministrativeCriteria.objects.filter(
            level=AdministrativeCriteriaLevel.LEVEL_1
        ).last()

        diagnosis.administrative_criteria.add(level1_criterion)
        diagnosis.administrative_criteria.add(level2_criterion)
        diagnosis.save()

        # Filter by level1 criterion
        response = client.get(reverse("apply:list_for_siae"), {"criteria": [level1_criterion.pk]})
        assert response.context["job_applications_page"].object_list == [job_app]

        # Filter by level2 criterion
        response = client.get(reverse("apply:list_for_siae"), {"criteria": [level2_criterion.pk]})
        assert response.context["job_applications_page"].object_list == [job_app]

        # Filter by two criteria
        response = client.get(reverse("apply:list_for_siae"), {"criteria": [level1_criterion.pk, level2_criterion.pk]})
        assert response.context["job_applications_page"].object_list == [job_app]

        # Filter by other criteria
        response = client.get(reverse("apply:list_for_siae"), {"criteria": [level1_other_criterion.pk]})
        assert response.context["job_applications_page"].object_list == []

    def test_list_for_siae_filtered_by_jobseeker_department(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        job_app = JobApplicationFactory(
            to_company=company,
            job_seeker__with_address=True,
            job_seeker__post_code="37000",
        )
        _another_job_app = JobApplicationFactory(
            to_company=company,
            job_seeker__with_address=True,
            job_seeker__post_code="75002",
        )

        client.force_login(employer)
        response = client.get(reverse("apply:list_for_siae"), {"departments": ["37"]})
        assert response.context["job_applications_page"].object_list == [job_app]

    def test_list_for_siae_filtered_by_selected_job(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        create_test_romes_and_appellations(["M1805", "N1101"], appellations_per_rome=2)
        (appellation1, appellation2) = Appellation.objects.all().order_by("?")[:2]
        job_app = JobApplicationSentByJobSeekerFactory(to_company=company, selected_jobs=[appellation1])
        _another_job_app = JobApplicationSentByJobSeekerFactory(to_company=company, selected_jobs=[appellation2])

        client.force_login(employer)
        response = client.get(reverse("apply:list_for_siae"), {"selected_jobs": [appellation1.pk]})
        assert response.context["job_applications_page"].object_list == [job_app]

    def test_prescriptions(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()
        client.force_login(employer)
        url = reverse("apply:list_prescriptions")
        response = client.get(url)
        assertContains(response, f'hx-get="{url}"')


def test_list_display_kind(client):
    company = CompanyFactory(with_membership=True)
    employer = company.members.first()
    JobApplicationFactory(to_company=company, eligibility_diagnosis=None)
    client.force_login(employer)
    url = reverse("apply:list_for_siae")

    TABLE_VIEW_MARKER = '<caption class="visually-hidden">Liste des candidatures</caption>'
    LIST_VIEW_MARKER = '<div class="c-box--results__header">'

    for display_param, expected_marker in [
        ({}, LIST_VIEW_MARKER),
        ({"display": "invalid"}, LIST_VIEW_MARKER),
        ({"display": JobApplicationsDisplayKind.LIST}, LIST_VIEW_MARKER),
        ({"display": JobApplicationsDisplayKind.TABLE}, TABLE_VIEW_MARKER),
    ]:
        response = client.get(url, display_param)
        for marker in (LIST_VIEW_MARKER, TABLE_VIEW_MARKER):
            if marker == expected_marker:
                assertContains(response, marker)
            else:
                assertNotContains(response, marker)


@pytest.mark.parametrize("filter_state", JobApplicationWorkflow.states)
def test_list_for_siae_message_when_company_got_no_new_nor_processing_nor_postponed_application(client, filter_state):
    company = CompanyFactory(with_membership=True)
    client.force_login(company.members.get())
    response = client.get(reverse("apply:list_for_siae"), {"states": [filter_state.name]})
    assertContains(response, "Aucune candidature pour le moment")


@pytest.mark.parametrize("state", JobApplicationWorkflow.PENDING_STATES)
@pytest.mark.parametrize("filter_state", JobApplicationWorkflow.states)
def test_list_for_siae_message_when_company_got_new_or_processing_or_postponed_application(
    client, state, filter_state
):
    company = CompanyFactory(with_membership=True, kind=CompanyKind.GEIQ)
    ja = JobApplicationFactory(to_company=company, state=state)
    client.force_login(company.members.get())

    response = client.get(reverse("apply:list_for_siae"), {"states": [filter_state.name]})
    if filter_state.name == state:
        assertContains(response, reverse("apply:details_for_company", kwargs={"job_application_id": ja.id}))
    else:
        assertContains(response, "Aucune candidature ne correspond aux filtres sélectionnés")


def test_list_for_siae_no_apply_button(client):
    APPLY_TXT = "Enregistrer une candidature"
    company = CompanyFactory(with_membership=True)
    client.force_login(company.members.get())
    response = client.get(reverse("apply:list_for_siae"))
    assertContains(response, APPLY_TXT)
    for kind in [CompanyKind.EA, CompanyKind.EATT, CompanyKind.OPCS]:
        company.kind = kind
        company.save(update_fields=("kind",))
        response = client.get(reverse("apply:list_for_siae"))
        assertNotContains(response, APPLY_TXT)


def test_list_for_siae_filter_for_different_kind(client, snapshot):
    company = CompanyFactory(with_membership=True)
    client.force_login(company.members.get())
    kind_snapshot = {
        CompanyKind.EA: "non_iae",
        CompanyKind.EATT: "non_iae",
        CompanyKind.EI: "iae",
        CompanyKind.GEIQ: "geiq",
        CompanyKind.OPCS: "non_iae",
        CompanyKind.ACI: "iae",
        CompanyKind.AI: "iae",
        CompanyKind.EITI: "iae",
        CompanyKind.ETTI: "iae",
    }
    for kind in CompanyKind:
        company.kind = kind
        company.save(update_fields=("kind",))
        response = client.get(reverse("apply:list_for_siae"))
        assert response.status_code == 200
        filter_form = parse_response_to_soup(response, "#offcanvasApplyFilters")
        # GEIQ and non IAE kind do not have a filter on approval and eligibility.
        # Non IAE kind do not have prior action.
        assert str(filter_form) == snapshot(name=kind_snapshot[kind])


def test_archived(client):
    company = CompanyFactory(with_membership=True)
    active = JobApplicationFactory(to_company=company)
    archived = JobApplicationFactory(to_company=company, archived_at=timezone.now())
    archived_badge_html = """\
    <span class="badge rounded-pill badge-sm mb-1 bg-light text-primary"
          aria-label="candidature archivée"
          data-bs-toggle="tooltip"
          data-bs-placement="top"
          data-bs-title="Candidature archivée">
      <i class="ri-archive-line mx-0"></i>
    </span>
    """

    client.force_login(company.members.get())
    url = reverse("apply:list_for_siae")
    response = client.get(url)
    assertContains(response, active.pk)
    assertNotContains(response, archived.pk)
    assertNotContains(response, archived_badge_html, html=True)
    response = client.get(url, data={"archived": ""})
    assertContains(response, active.pk)
    assertNotContains(response, archived.pk)
    assertNotContains(response, archived_badge_html, html=True)
    response = client.get(url, data={"archived": "archived"})
    assertNotContains(response, active.pk)
    assertContains(response, archived.pk)
    assertContains(response, archived_badge_html, html=True, count=1)
    response = client.get(url, data={"archived": "all"})
    assertContains(response, active.pk)
    assertContains(response, archived.pk)
    assertContains(response, archived_badge_html, html=True, count=1)
    response = client.get(url, data={"archived": "invalid"})
    assertContains(response, active.pk)
    assertContains(response, archived.pk)
    assertContains(response, archived_badge_html, html=True, count=1)
    assertContains(
        response,
        """
        <div class="alert alert-danger" role="alert">
            Sélectionnez un choix valide. invalid n’en fait pas partie.
        </div>
        """,
        html=True,
        count=1,
    )


def test_list_for_siae_htmx_filters(client):
    company = CompanyFactory(with_membership=True)
    JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
    client.force_login(company.members.get())
    url = reverse("apply:list_for_siae")
    response = client.get(url)
    page = parse_response_to_soup(response, selector="#main")
    # Simulate the data-sync-with and check both checkboxes.
    refused_checkboxes = page.find_all(
        "input",
        attrs={"name": "states", "value": "refused"},
    )
    assert len(refused_checkboxes) == 2
    for refused_checkbox in refused_checkboxes:
        refused_checkbox["checked"] = ""
    response = client.get(
        url,
        {"states": ["refused"]},
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(page, f"form[hx-get='{url}']", response)
    response = client.get(url, {"states": ["refused"]})
    fresh_page = parse_response_to_soup(response, selector="#main")
    assertSoupEqual(page, fresh_page)

    # Switch display kind
    [display_input] = page.find_all(id="display-kind")
    display_input["value"] = JobApplicationsDisplayKind.TABLE.value

    response = client.get(
        url,
        {"states": ["refused"], "display": JobApplicationsDisplayKind.TABLE},
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(page, f"form[hx-get='{url}']", response)

    response = client.get(url, {"states": ["refused"], "display": JobApplicationsDisplayKind.TABLE})
    fresh_page = parse_response_to_soup(response, selector="#main")
    assertSoupEqual(page, fresh_page)


def test_table_for_siae_hide_criteria_for_non_SIAE_employers(client, subtests):
    company = CompanyFactory(with_membership=True)
    employer = company.members.first()

    diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
    # Level 1 criteria
    diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.get(name="Allocataire AAH"))
    JobApplicationFactory(
        job_seeker=diagnosis.job_seeker,
        to_company=company,
        eligibility_diagnosis=None,  # fallback on the jobseeker's
    )

    TITLE = '<th scope="col" class="text-nowrap">Critères administratifs IAE</th>'
    CRITERION = "<li>Allocataire AAH</li>"

    client.force_login(employer)

    expect_to_see_criteria = {
        CompanyKind.EA: False,
        CompanyKind.EATT: False,
        CompanyKind.EI: True,
        CompanyKind.GEIQ: False,
        CompanyKind.OPCS: False,
        CompanyKind.ACI: True,
        CompanyKind.AI: True,
        CompanyKind.EITI: True,
        CompanyKind.ETTI: True,
    }
    for kind in CompanyKind:
        with subtests.test(kind=kind.label):
            company.kind = kind
            company.save(update_fields=("kind",))
            response = client.get(reverse("apply:list_for_siae"), {"display": JobApplicationsDisplayKind.TABLE})
            if expect_to_see_criteria[kind]:
                assertContains(response, TITLE, html=True)
                assertContains(response, CRITERION, html=True)
            else:
                assertNotContains(response, TITLE, html=True)
                assertNotContains(response, CRITERION, html=True)


@freeze_time("2024-11-27", tick=True)
def test_list_snapshot(client, snapshot):
    company = CompanyFactory(with_membership=True)
    client.force_login(company.members.get())
    url = reverse("apply:list_for_siae")

    for display_param in [
        {},
        {"display": JobApplicationsDisplayKind.LIST},
        {"display": JobApplicationsDisplayKind.TABLE},
    ]:
        response = client.get(url, display_param)
        page = parse_response_to_soup(response, selector="#job-applications-section")
        assert str(page) == snapshot(name="empty")

    job_seeker = JobSeekerFactory(for_snapshot=True)
    common_kwargs = {"job_seeker": job_seeker, "to_company": company}
    prescriber_org = PrescriberOrganizationWithMembershipFactory(for_snapshot=True)

    job_applications = [
        JobApplicationFactory(sender_kind=SenderKind.JOB_SEEKER, state=JobApplicationState.ACCEPTED, **common_kwargs),
        JobApplicationFactory(
            sender_kind=SenderKind.EMPLOYER,
            sender=company.members.first(),
            sender_company=company,
            state=JobApplicationState.NEW,
            **common_kwargs,
        ),
        JobApplicationFactory(
            sender_kind=SenderKind.PRESCRIBER,
            sender=prescriber_org.members.first(),
            sender_prescriber_organization=prescriber_org,
            state=JobApplicationState.REFUSED,
            **common_kwargs,
        ),
    ]

    # List display
    response = client.get(url, {"display": JobApplicationsDisplayKind.LIST})
    page = parse_response_to_soup(
        response,
        selector="#job-applications-section",
        replace_in_attr=itertools.chain(
            *(
                [
                    (
                        "href",
                        f"/apply/{job_application.pk}/siae/details",
                        "/apply/[PK of JobApplication]/siae/details",
                    ),
                    (
                        "id",
                        f"state_{job_application.pk}",
                        "state_[PK of JobApplication]",
                    ),
                ]
                for job_application in job_applications
            )
        ),
    )
    assert str(page) == snapshot(name="applications list")

    # Table display
    response = client.get(url, {"display": JobApplicationsDisplayKind.TABLE})
    page = parse_response_to_soup(
        response,
        selector="#job-applications-section",
        replace_in_attr=itertools.chain(
            *(
                [
                    (
                        "href",
                        f"/apply/{job_application.pk}/siae/details",
                        "/apply/[PK of JobApplication]/siae/details",
                    ),
                    (
                        "id",
                        f"state_{job_application.pk}",
                        "state_[PK of JobApplication]",
                    ),
                ]
                for job_application in job_applications
            )
        ),
    )
    assert str(page) == snapshot(name="applications table")


def test_list_for_siae_exports(client, snapshot):
    job_application = JobApplicationFactory()
    client.force_login(job_application.to_company.members.get())

    response = client.get(reverse("apply:list_for_siae_exports"))
    assertContains(response, "Toutes les candidatures")
    assert_previous_step(response, reverse("dashboard:index"))
    assert str(parse_response_to_soup(response, selector="#besoin-dun-chiffre")) == snapshot


def test_list_for_siae_exports_as_prescriber(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.sender)

    response = client.get(reverse("apply:list_for_siae_exports"))
    assert 404 == response.status_code


def test_list_for_siae_exports_back_to_list(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.to_company.members.get())

    response = client.get(reverse("apply:list_for_siae_exports"), {"back_url": reverse("apply:list_for_siae")})
    assert_previous_step(response, reverse("apply:list_for_siae"), back_to_list=True)


@pytest.mark.parametrize(
    "job_app_kwargs",
    [
        pytest.param({"for_snapshot": True}, id="for_snapshot"),
        pytest.param({"for_snapshot": True, "eligibility_diagnosis": None}, id="no_eligibility_diag"),
    ],
)
@freeze_time("2024-08-18")
def test_list_for_siae_exports_download(client, job_app_kwargs, snapshot):
    job_application = JobApplicationFactory(**job_app_kwargs)
    client.force_login(job_application.to_company.members.get())

    # Download all job applications
    response = client.get(reverse("apply:list_for_siae_exports_download"))
    assert 200 == response.status_code
    assert "spreadsheetml" in response.get("Content-Type")
    rows = get_rows_from_streaming_response(response)
    assert rows == snapshot


def test_list_for_siae_exports_download_as_prescriber(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.sender)

    response = client.get(
        reverse(
            "apply:list_for_siae_exports_download",
            kwargs={"month_identifier": job_application.created_at.strftime("%Y-%d")},
        )
    )
    assert 404 == response.status_code


def test_list_for_siae_exports_download_by_month(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.to_company.members.get())

    # When job applications exists
    response = client.get(
        reverse(
            "apply:list_for_siae_exports_download",
            kwargs={"month_identifier": job_application.created_at.strftime("%Y-%d")},
        )
    )
    assert 200 == response.status_code
    assert "spreadsheetml" in response.get("Content-Type")

    # When job applications doesn't exists
    response = client.get(
        reverse(
            "apply:list_for_siae_exports_download",
            kwargs={"month_identifier": "0000-00"},
        )
    )
    assert 200 == response.status_code
    assert "spreadsheetml" in response.get("Content-Type")


@pytest.mark.parametrize(
    "job_app_kwargs",
    [
        pytest.param({"with_approval": True}, id="with_approval"),
        pytest.param({}, id="with_eligibility_diag"),
        pytest.param({"eligibility_diagnosis": None}, id="no_eligibility_diag"),
    ],
)
def test_list_for_siae_badge(client, snapshot, job_app_kwargs):
    job_application = JobApplicationFactory(**job_app_kwargs)
    client.force_login(job_application.to_company.members.get())
    response = client.get(reverse("apply:list_for_siae"))
    badge = parse_response_to_soup(response, selector=".c-box--results__summary span.badge")
    assert str(badge) == snapshot
