import datetime
import itertools
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from itoutils.django.testing import assertSnapshotQueries
from pytest_django.asserts import assertContains, assertNotContains, assertQuerySetEqual

from itou.companies.enums import CompanyKind
from itou.eligibility.enums import AdministrativeCriteriaKind, AdministrativeCriteriaLevel, AuthorKind
from itou.eligibility.models import AdministrativeCriteria
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplicationWorkflow
from itou.jobs.models import Appellation
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.apply.views.list_views import JobApplicationOrder, JobApplicationsDisplayKind
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.cities.factories import create_city_saint_andre
from tests.companies.factories import CompanyFactory, CompanyMembershipFactory, JobDescriptionFactory
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.users.factories import JobSeekerFactory, LaborInspectorFactory, PrescriberFactory
from tests.utils.htmx.testing import assertSoupEqual, update_page_with_htmx
from tests.utils.testing import (
    assert_previous_step,
    get_rows_from_streaming_response,
    parse_response_to_soup,
    pretty_indented,
)


INVALID_VALUE_MESSAGE = "Sélectionnez un choix valide."


class TestProcessListSiae:
    SELECTED_JOBS = "selected_jobs"

    def test_list_for_siae(self, client, snapshot):
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
        employer = company.members.first()

        city = create_city_saint_andre()
        create_test_romes_and_appellations(["N4105"], appellations_per_rome=2)
        appellations = Appellation.objects.all()[:2]
        job1 = JobDescriptionFactory(company=company, appellation=appellations[0], location=city)
        job2 = JobDescriptionFactory(company=company, appellation=appellations[1], location=city)

        # A job application without eligibility diagnosis
        job_app = JobApplicationFactory(to_company=company, selected_jobs=[job1, job2])
        # Two with it (ensure there are no 1+N queries)
        JobApplicationFactory.create_batch(
            2, to_company=company, selected_jobs=[job1, job2], with_iae_eligibility_diagnosis=True
        )
        # A job application for another company
        JobApplicationFactory()

        client.force_login(employer)
        with assertSnapshotQueries(snapshot(name="SQL queries in list mode")):
            response = client.get(reverse("apply:list_for_siae"), {"display": JobApplicationsDisplayKind.LIST})

        total_applications = len(response.context["job_applications_page"].object_list)

        # Result page should contain all the company's job applications.
        assert total_applications == 3

        # Has link to export with back_url set
        export_url = unquote(
            reverse("apply:list_for_siae_exports", query={"back_url": reverse("apply:list_for_siae")})
        )
        assertContains(response, export_url)

        # Has job application card link with back_url set
        job_application_link = unquote(
            reverse(
                "apply:details_for_company",
                kwargs={"job_application_id": job_app.pk},
                query={"back_url": reverse("apply:list_for_siae")},
            )
        )
        assertContains(response, job_application_link)

        assertContains(
            response,
            # Appellations are ordered by name.
            f"""
            <div class="dropdown">
            <button type="button" class="btn btn-dropdown-filter dropdown-toggle" data-bs-toggle="dropdown"
                    data-bs-display="static" data-bs-auto-close="outside" aria-expanded="false">
                Fiches de poste
            </button>
            <ul class="dropdown-menu">
            <li class="dropdown-item">
            <div class="form-check">
            <input id="id_selected_jobs_0-top"
                   class="form-check-input"
                   data-emplois-sync-with="id_selected_jobs_0"
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
                       data-emplois-sync-with="id_selected_jobs_1"
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
        assertContains(response, job_app.job_seeker.get_inverted_full_name())
        assertNotContains(
            response, reverse("job_seekers_views:details", kwargs={"public_id": job_app.job_seeker.public_id})
        )

        with assertSnapshotQueries(snapshot(name="SQL queries in table mode")):
            response = client.get(reverse("apply:list_for_siae"), {"display": JobApplicationsDisplayKind.TABLE})
        assert len(response.context["job_applications_page"].object_list) == 3

    def test_list_for_siae_show_criteria(self, client):
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
        employer = company.members.first()

        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        criteria = AdministrativeCriteria.objects.filter(
            kind__in=[
                # Level 1 criteria
                AdministrativeCriteriaKind.AAH,
                AdministrativeCriteriaKind.ASS,
                AdministrativeCriteriaKind.RSA,
                # Level 2 criterion
                AdministrativeCriteriaKind.SENIOR,
            ]
        )
        assert len(criteria) == 4
        diagnosis.administrative_criteria.add(*criteria)
        JobApplicationFactory(
            job_seeker=diagnosis.job_seeker,
            to_company=company,
            # fallback on the jobseeker's iae eligibility diagnosis
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
        diagnosis.administrative_criteria.add(
            AdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.DETLD)
        )

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
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
        employer = company.members.first()

        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        # Level 1 criteria
        diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.AAH))
        JobApplicationFactory(
            job_seeker=diagnosis.job_seeker,
            to_company=company,
            # fallback on the jobseeker's iae eligibility diagnosis
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
                company.save(update_fields=("kind", "updated_at"))
                response = client.get(
                    reverse("apply:list_for_siae"), data={"display": JobApplicationsDisplayKind.LIST}
                )
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
        company = CompanyFactory(with_membership=True, not_geiq_kind=True)
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
        response = client.get(reverse("apply:list_for_siae", query={"start_date": "", "end_date": ""}))
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
        assertNotContains(response, INVALID_VALUE_MESSAGE)

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

        # Test with invalid value
        response = client.get(
            reverse("apply:list_for_siae"),
            {"sender_prescriber_organizations": [PrescriberOrganizationFactory().pk]},
        )
        assertContains(response, INVALID_VALUE_MESSAGE)

    def test_list_for_siae_filtered_by_sender_name(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        job_app = JobApplicationFactory(to_company=company)
        _another_job_app = JobApplicationFactory(to_company=company)

        client.force_login(employer)
        response = client.get(reverse("apply:list_for_siae"), {"senders": [job_app.sender.id]})
        assert response.context["job_applications_page"].object_list == [job_app]
        assertNotContains(response, INVALID_VALUE_MESSAGE)

        # Test with invalid value
        response = client.get(
            reverse("apply:list_for_siae"),
            {"senders": [PrescriberFactory().pk]},
        )
        assertContains(response, INVALID_VALUE_MESSAGE)

    def test_list_for_siae_filtered_by_job_seeker_cancels_other_filters(self, client):
        company = CompanyFactory(with_membership=True)
        employer = company.members.first()

        job_app = JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
        _another_job_app = JobApplicationFactory(
            to_company=company, job_seeker=job_app.job_seeker, state=JobApplicationState.NEW
        )
        _job_app_from_other_job_seeker = JobApplicationFactory(to_company=company)

        client.force_login(employer)
        response = client.get(reverse("apply:list_for_siae"), {"job_seeker": job_app.job_seeker.pk})
        assert set(response.context["job_applications_page"].object_list) == set([job_app, _another_job_app])
        assertNotContains(response, INVALID_VALUE_MESSAGE)

        response = client.get(
            reverse("apply:list_for_siae"),
            {"job_seeker": job_app.job_seeker.pk, "states": [JobApplicationState.ACCEPTED]},
        )
        assert set(response.context["job_applications_page"].object_list) == set([job_app, _another_job_app])

        # Test with invalid value
        response = client.get(
            reverse("apply:list_for_siae"),
            {"job_seeker": [JobSeekerFactory().id]},
        )
        assertContains(response, INVALID_VALUE_MESSAGE)

    def test_list_for_siae_filtered_by_pass_state(self, client):
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
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

        # So far no approval was expired
        response = client.get(reverse("apply:list_for_siae"), {"pass_iae_expired": True})
        assert response.context["job_applications_page"].object_list == []

        jobapp_with_expired_pass = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=yesterday - timezone.timedelta(days=365),
            approval__start_at=yesterday - timezone.timedelta(days=365),
            approval__end_at=yesterday,
            to_company=company,
        )

        # The pass_iae_expired filter works as expected
        response = client.get(reverse("apply:list_for_siae"), {"pass_iae_expired": True})
        assert response.context["job_applications_page"].object_list == [jobapp_with_expired_pass]

    def test_list_for_siae_filtered_by_eligibility_state(self, client):
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
        employer = company.members.first()

        job_app = JobApplicationFactory(to_company=company)
        _another_job_app = JobApplicationFactory(to_company=company)

        client.force_login(employer)
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == []
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_pending": True})
        assert set(response.context["job_applications_page"].object_list) == set([job_app, _another_job_app])

        # Authorized prescriber diagnosis
        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True, job_seeker=job_app.job_seeker)
        # Test all four possible combinations of the two filters.
        response = client.get(reverse("apply:list_for_siae"))
        assert set(response.context["job_applications_page"].object_list) == set([job_app, _another_job_app])
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == [job_app]
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_pending": True})
        assert response.context["job_applications_page"].object_list == [_another_job_app]
        response = client.get(
            reverse("apply:list_for_siae"), {"eligibility_validated": True, "eligibility_pending": True}
        )
        assert set(response.context["job_applications_page"].object_list) == set([job_app, _another_job_app])

        # Make sure the diagnostic expired - it should be ignored
        diagnosis.expires_at = timezone.localdate() - datetime.timedelta(
            days=diagnosis.EXPIRATION_DELAY_MONTHS * 31 + 1
        )
        diagnosis.save(update_fields=("expires_at", "updated_at"))
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == []
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_pending": True})
        assert set(response.context["job_applications_page"].object_list) == set([job_app, _another_job_app])

        # Diagnosis made by employer's SIAE
        diagnosis.delete()
        diagnosis = IAEEligibilityDiagnosisFactory(
            job_seeker=job_app.job_seeker, from_employer=True, author_siae=company
        )
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == [job_app]
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_pending": True})
        assert response.context["job_applications_page"].object_list == [_another_job_app]

        # Diagnosis made by an other SIAE - it should be ignored
        diagnosis.delete()
        diagnosis = IAEEligibilityDiagnosisFactory(job_seeker=job_app.job_seeker, from_employer=True)
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == []
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_pending": True})
        assert set(response.context["job_applications_page"].object_list) == set([job_app, _another_job_app])

        # With a valid approval
        approval = ApprovalFactory(
            user=job_app.job_seeker,
            with_origin_values=True,  # origin_values needed to delete it
        )
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == [job_app]
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_pending": True})
        assert response.context["job_applications_page"].object_list == [_another_job_app]

        # With an expired approval
        approval_diagnosis = approval.eligibility_diagnosis
        approval.delete()
        approval_diagnosis.delete()
        approval = ApprovalFactory(expired=True)
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_validated": True})
        assert response.context["job_applications_page"].object_list == []
        response = client.get(reverse("apply:list_for_siae"), {"eligibility_pending": True})
        assert set(response.context["job_applications_page"].object_list) == set([job_app, _another_job_app])

    def test_list_for_siae_filtered_by_administrative_criteria(self, client):
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
        employer = company.members.first()
        client.force_login(employer)

        job_app = JobApplicationFactory(to_company=company)
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

    @freeze_time("2025-03-13")
    def test_list_for_siae_filters_query(self, client, snapshot):
        company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
        employer = company.members.first()

        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        level1_criterion = AdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.AAH)
        diagnosis.administrative_criteria.add(level1_criterion)

        job_app = JobApplicationFactory(
            to_company=company,
            created_at=timezone.now() - timezone.timedelta(days=1),
            sent_by_authorized_prescriber_organisation=True,
            job_seeker__post_code="37000",
            with_approval=True,
            eligibility_diagnosis=diagnosis,
        )
        date_format = DuetDatePickerWidget.INPUT_DATE_FORMAT

        client.force_login(employer)
        with assertSnapshotQueries(snapshot(name="SQL queries with all filters but job_seeker")):
            response = client.get(
                reverse("apply:list_for_siae"),
                {
                    "states": [JobApplicationState.ACCEPTED],
                    "start_date": timezone.localdate(job_app.created_at).strftime(date_format),
                    "end_date": timezone.localdate(job_app.created_at).strftime(date_format),
                    "sender_prescriber_organizations": [job_app.sender_prescriber_organization.id],
                    "senders": [job_app.sender.id],
                    "pass_iae_active": True,
                    "eligibility_validated": True,
                    "criteria": [level1_criterion.pk],
                    "departments": ["37"],
                },
            )
        assert len(response.context["job_applications_page"].object_list) == 1

        with assertSnapshotQueries(snapshot(name="SQL queries with only job_seeker filter")):
            response = client.get(
                reverse("apply:list_for_siae"),
                {
                    "job_seeker": job_app.job_seeker.pk,
                },
            )
        assert len(response.context["job_applications_page"].object_list) == 1

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
    JobApplicationFactory(to_company=company)
    client.force_login(employer)
    url = reverse("apply:list_for_siae")

    TABLE_VIEW_MARKER = '<caption class="visually-hidden">Liste des candidatures'
    LIST_VIEW_MARKER = '<div class="c-box--results__header">'

    for display_param, expected_marker in [
        ({}, TABLE_VIEW_MARKER),
        ({"display": "invalid"}, TABLE_VIEW_MARKER),
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
    company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
    client.force_login(company.members.get())
    response = client.get(reverse("apply:list_for_siae"))
    assertContains(response, APPLY_TXT)
    for kind in [CompanyKind.EA, CompanyKind.EATT, CompanyKind.OPCS]:
        company.kind = kind
        company.save(update_fields=("kind", "updated_at"))
        response = client.get(reverse("apply:list_for_siae"))
        assertNotContains(response, APPLY_TXT)


def test_list_for_siae_filter_for_different_kind(client, snapshot):
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
        company = CompanyFactory(with_membership=True, kind=kind)
        client.force_login(company.members.get())
        response = client.get(reverse("apply:list_for_siae"), {"display": JobApplicationsDisplayKind.LIST})
        assert response.status_code == 200
        filter_form = parse_response_to_soup(response, "#offcanvasApplyFilters")
        # GEIQ and non IAE kind do not have a filter on approval and eligibility.
        # Non IAE kind do not have prior action.
        assert pretty_indented(filter_form) == snapshot(name=kind_snapshot[kind])


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
    response = client.get(url, {"display": JobApplicationsDisplayKind.LIST})
    assertContains(response, active.pk)
    assertNotContains(response, archived.pk)
    assertNotContains(response, archived_badge_html, html=True)
    response = client.get(url, data={"display": JobApplicationsDisplayKind.LIST, "archived": ""})
    assertContains(response, active.pk)
    assertNotContains(response, archived.pk)
    assertNotContains(response, archived_badge_html, html=True)
    response = client.get(url, data={"display": JobApplicationsDisplayKind.LIST, "archived": "archived"})
    assertNotContains(response, active.pk)
    assertContains(response, archived.pk)
    assertContains(response, archived_badge_html, html=True, count=1)
    response = client.get(url, data={"display": JobApplicationsDisplayKind.LIST, "archived": "all"})
    assertContains(response, active.pk)
    assertContains(response, archived.pk)
    assertContains(response, archived_badge_html, html=True, count=1)
    response = client.get(url, data={"display": JobApplicationsDisplayKind.LIST, "archived": "invalid"})
    assertContains(response, active.pk)
    assertContains(response, archived.pk)
    assertContains(response, archived_badge_html, html=True, count=1)
    assertContains(
        response,
        """
        <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
            <p>
                <strong>Votre formulaire contient une erreur</strong>
            </p>
            <ul class="mb-0">
                <li>Sélectionnez un choix valide. invalid n’en fait pas partie.</li>
            </ul>
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
    # Simulate the data-emplois-sync-with and check both checkboxes.
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
    company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
    employer = company.members.first()

    diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
    # Level 1 criteria
    diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.get(kind=AdministrativeCriteriaKind.AAH))
    JobApplicationFactory(
        job_seeker=diagnosis.job_seeker,
        to_company=company,
        # fallback on the jobseeker's iae eligibility diagnosis
    )

    TITLE = '<th scope="col" class="text-nowrap">Critères administratifs</th>'
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
            company.save(update_fields=("kind", "updated_at"))
            response = client.get(reverse("apply:list_for_siae"), {"display": JobApplicationsDisplayKind.TABLE})
            if expect_to_see_criteria[kind]:
                assertContains(response, TITLE, html=True)
                assertContains(response, CRITERION, html=True)
            else:
                assertNotContains(response, TITLE, html=True)
                assertNotContains(response, CRITERION, html=True)


@freeze_time("2024-11-27", tick=True)
def test_list_snapshot(client, snapshot):
    company = CompanyFactory(with_membership=True, not_in_territorial_experimentation=True, subject_to_iae_rules=True)
    client.force_login(company.members.get())
    url = reverse("apply:list_for_siae")

    for display_param in [
        {},
        {"display": JobApplicationsDisplayKind.LIST},
        {"display": JobApplicationsDisplayKind.TABLE},
    ]:
        response = client.get(url, display_param)
        page = parse_response_to_soup(response, selector="#job-applications-section")
        assert pretty_indented(page) == snapshot(name="empty")

    job_seeker = JobSeekerFactory(for_snapshot=True)
    common_kwargs = {"job_seeker": job_seeker, "with_iae_eligibility_diagnosis": True, "to_company": company}
    prescriber_org = PrescriberOrganizationFactory(for_snapshot=True, with_membership=True)

    job_applications = [
        JobApplicationFactory(
            sender_kind=SenderKind.JOB_SEEKER, state=JobApplicationState.ACCEPTED, sender=job_seeker, **common_kwargs
        ),
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
    assert pretty_indented(page) == snapshot(name="applications list")

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
                    (
                        "value",
                        str(job_application.pk),
                        "[PK of JobApplication]",
                    ),
                    (
                        "id",
                        f"select-{job_application.pk}",
                        "select-[PK of JobApplication]",
                    ),
                    (
                        "for",
                        f"select-{job_application.pk}",
                        "select-[PK of JobApplication]",
                    ),
                ]
                for job_application in job_applications
            )
        ),
    )
    assert pretty_indented(page) == snapshot(name="applications table")


def test_list_for_siae_exports(client, snapshot):
    job_application = JobApplicationFactory()
    client.force_login(job_application.to_company.members.get())

    response = client.get(reverse("apply:list_for_siae_exports"))
    assertContains(response, "Toutes les candidatures")
    assert_previous_step(response, reverse("dashboard:index"))
    assert pretty_indented(parse_response_to_soup(response, selector="#besoin-dun-chiffre")) == snapshot


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
        pytest.param({"for_snapshot": True, "with_iae_eligibility_diagnosis": True}, id="for_snapshot"),
        pytest.param({"for_snapshot": True}, id="no_eligibility_diag"),
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
        pytest.param({"with_iae_eligibility_diagnosis": True}, id="with_eligibility_diag"),
        pytest.param({"to_company__subject_to_iae_rules": True}, id="no_eligibility_diag"),
    ],
)
def test_list_for_siae_badge(client, snapshot, job_app_kwargs):
    job_application = JobApplicationFactory(**job_app_kwargs)
    client.force_login(job_application.to_company.members.get())
    response = client.get(reverse("apply:list_for_siae"), {"display": JobApplicationsDisplayKind.LIST})
    badge = parse_response_to_soup(response, selector=".c-box--results__summary span.badge")
    assert pretty_indented(badge) == snapshot


def test_reset_filter_button_snapshot(client, snapshot):
    job_application = JobApplicationFactory()
    client.force_login(job_application.to_company.members.get())

    filter_params = {"states": [job_application.state], "display": JobApplicationsDisplayKind.LIST}
    response = client.get(reverse("apply:list_for_siae"), filter_params)

    assert pretty_indented(parse_response_to_soup(response, selector="#apply-list-filter-counter")) == snapshot(
        name="reset-filter button in list view"
    )
    assert pretty_indented(parse_response_to_soup(response, selector="#offcanvasApplyFiltersButtons")) == snapshot(
        name="off-canvas buttons in list view"
    )

    filter_params["display"] = JobApplicationsDisplayKind.TABLE
    filter_params["order"] = JobApplicationOrder.CREATED_AT_ASC
    response = client.get(reverse("apply:list_for_siae"), filter_params)

    assert pretty_indented(parse_response_to_soup(response, selector="#apply-list-filter-counter")) == snapshot(
        name="reset-filter button in table view & created_at ascending order"
    )
    assert pretty_indented(parse_response_to_soup(response, selector="#offcanvasApplyFiltersButtons")) == snapshot(
        name="off-canvas buttons in table view & created_at ascending order"
    )


def test_list_for_siae_actions_forced_refresh(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.to_company.members.get())
    response = client.get(reverse("apply:list_for_siae_actions"), {"selected-application": []})
    assert not response.headers.get("HX-Refresh")
    response = client.get(reverse("apply:list_for_siae_actions"), {"selected-application": [job_application.pk]})
    assert not response.headers.get("HX-Refresh")
    # If the user checks an application, that either doesn't exist anymore or was transferred to another company
    # a forced refresh should occur
    response = client.get(reverse("apply:list_for_siae_actions"), {"selected-application": [str(uuid.uuid4())]})
    assert response.headers.get("HX-Refresh") == "true"


def test_list_for_siae_select_applications_htmx(client):
    company = CompanyFactory(with_membership=True)
    employer = company.members.first()

    job_apps = JobApplicationFactory.create_batch(3, to_company=company, state=JobApplicationState.NEW)
    client.force_login(employer)
    table_url = reverse("apply:list_for_siae", query={"display": "table"})

    response = client.get(table_url)
    simulated_page = parse_response_to_soup(response, selector="#main")
    [action_form] = simulated_page.find_all(
        "form", attrs={"hx-get": lambda attr: attr.startswith(reverse("apply:list_for_siae_actions"))}
    )
    action_url = action_form["hx-get"]
    assert simulated_page.find(id="selected-nb-display").contents == []
    assert simulated_page.find(id="batch-action-box").contents == []

    def simulate_applications_selection(application_list):
        response = client.get(
            action_url, {"selected-application": [app.pk for app in application_list]}, headers={"HX-Request": "true"}
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{action_url}']", response)

    # Select 1 application
    simulate_applications_selection([job_apps[0]])
    # Check selected nb info
    assert simulated_page.find(id="selected-nb-display").find("p").contents == ["1 résultat sélectionné"]
    # Check reset selection button
    reset_button = simulated_page.find(id="selected-nb-display").find("button")
    assert reset_button.find("span").contents == ["annuler la sélection"]
    assert reset_button["data-emplois-setter-checked"] == "false"
    assert simulated_page.select(reset_button["data-emplois-setter-target"])
    # Check batch action box display
    assert simulated_page.find(id="batch-action-box").find("h2")

    # Select 3 applications
    simulate_applications_selection(job_apps)
    assert simulated_page.find(id="selected-nb-display").find("p").contents == ["3 résultats sélectionnés"]
    # Check batch action box display
    assert simulated_page.find(id="batch-action-box").find("h2")

    # Unselect all
    simulate_applications_selection([])
    assert simulated_page.find(id="selected-nb-display").contents == []
    # Check batch action box display
    assert simulated_page.find(id="batch-action-box").contents == []

    # Reload page
    response = client.get(table_url)
    new_page = parse_response_to_soup(response, selector="#main")
    assertSoupEqual(new_page, simulated_page)


def test_list_for_siae_select_applications_batch_archive(client, snapshot):
    MODAL_ID = "archive_confirmation_modal"

    company = CompanyFactory(with_membership=True)
    employer = company.members.first()

    archivable_app_1 = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"), to_company=company, state=JobApplicationState.REFUSED
    )
    assert archivable_app_1.can_be_archived
    archivable_app_2 = JobApplicationFactory(
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"), to_company=company, state=JobApplicationState.REFUSED
    )
    assert archivable_app_2.can_be_archived
    archived_app = JobApplicationFactory(
        to_company=company, state=JobApplicationState.REFUSED, archived_at=timezone.now()
    )
    assert not archived_app.can_be_archived
    unarchivable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.NEW)
    assert not unarchivable_app.can_be_archived

    client.force_login(employer)
    table_url = reverse("apply:list_for_siae", query={"display": "table", "start_date": "2015-01-01"})

    response = client.get(table_url)
    simulated_page = parse_response_to_soup(
        response,
        # We need the whole body to be able to check modals
        selector="body",
    )
    [action_form] = simulated_page.find_all(
        "form", attrs={"hx-get": lambda attr: attr and attr.startswith(reverse("apply:list_for_siae_actions"))}
    )
    action_url = action_form["hx-get"]
    assert parse_qs(urlsplit(action_url).query) == {"list_url": [table_url]}
    assert simulated_page.find(id="batch-action-box").contents == []

    def simulate_applications_selection(application_list):
        response = client.get(
            action_url,
            # Explicitly redefine list_url since Django test client swallows it otherwise
            query_params={"list_url": table_url, "selected-application": application_list},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{action_url}']", response)

    def get_archive_modal():
        return simulated_page.find(id=MODAL_ID)

    def get_archive_button():
        archive_buttons = [
            span.parent
            for span in simulated_page.find(id="batch-action-box").select("button > span")
            if span.contents == ["Archiver"]
        ]
        if not archive_buttons:
            return None
        [archive_button] = archive_buttons
        return archive_button

    assert get_archive_modal() is None
    assert get_archive_button() is None

    # Select 1 archivable application
    simulate_applications_selection([archivable_app_1.pk])
    archive_button = get_archive_button()
    assert archive_button is not None
    assert archive_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(archive_button) == snapshot(name="active archive button")

    modal = get_archive_modal()
    assert pretty_indented(modal) == snapshot(name="modal with 1 archivable application")
    # Check that the next_url is correctly transmitted
    modal_form_action = urlsplit(modal.find("form")["action"])
    assert modal_form_action.path == reverse("apply:batch_archive")
    assert parse_qs(modal_form_action.query) == {"next_url": [table_url]}

    # Select 2 archivable applications
    simulate_applications_selection([archivable_app_1.pk, archivable_app_2.pk])
    archive_button = get_archive_button()
    assert archive_button is not None
    assert archive_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(archive_button) == snapshot(name="active archive button")
    assert pretty_indented(get_archive_modal()) == snapshot(name="modal with 2 archivable applications")

    # mishmash job applications
    # -------------------------

    # At least one archivable job application
    for app_list in [
        [archived_app.pk, archivable_app_1.pk],
        [unarchivable_app.pk, archivable_app_2.pk],
    ]:
        simulate_applications_selection(app_list)
    assert archive_button is not None
    assert archive_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(archive_button) == snapshot(name="active archive button")

    # No archivable job app
    for app_list in [
        [unarchivable_app.pk],
        [archived_app.pk],
        [archived_app.pk, unarchivable_app.pk],
    ]:
        simulate_applications_selection(app_list)
        # No modal & linked button
        assert get_archive_modal() is None
        archive_button = get_archive_button()
        assert pretty_indented(archive_button) == snapshot(name="inactive archive button")


def test_list_for_siae_select_applications_batch_unarchive(client, snapshot):
    MODAL_ID = "unarchive_confirmation_modal"

    company = CompanyFactory(with_membership=True)
    employer = company.members.first()

    archived_app_1 = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        to_company=company,
        state=JobApplicationState.REFUSED,
        archived_at=timezone.now(),
        archived_by=employer,
    )
    archived_app_2 = JobApplicationFactory(
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        to_company=company,
        state=JobApplicationState.REFUSED,
        archived_at=timezone.now(),
        archived_by=employer,
    )
    not_archived_app = JobApplicationFactory(to_company=company, state=JobApplicationState.REFUSED)

    client.force_login(employer)
    table_url = reverse(
        "apply:list_for_siae", query={"display": "table", "start_date": "2015-01-01", "archived": "archived"}
    )

    response = client.get(table_url)
    simulated_page = parse_response_to_soup(
        response,
        # We need the whole body to be able to check modals
        selector="body",
    )
    [action_form] = simulated_page.find_all(
        "form", attrs={"hx-get": lambda attr: attr and attr.startswith(reverse("apply:list_for_siae_actions"))}
    )
    action_url = action_form["hx-get"]
    assert parse_qs(urlsplit(action_url).query) == {"list_url": [table_url]}
    assert simulated_page.find(id="batch-action-box").contents == []

    def simulate_applications_selection(application_list):
        response = client.get(
            action_url,
            # Explicitly redefine list_url since Django test client swallows it otherwise
            query_params={"list_url": table_url, "selected-application": application_list},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{action_url}']", response)

    def get_unarchive_modal():
        return simulated_page.find(id=MODAL_ID)

    def get_unarchive_button():
        unarchive_buttons = [
            span.parent
            for span in simulated_page.find(id="batch-action-box").select("button > span")
            if span.contents == ["Désarchiver"]
        ]
        if not unarchive_buttons:
            return None
        [unarchive_button] = unarchive_buttons
        return unarchive_button

    assert get_unarchive_modal() is None
    assert get_unarchive_button() is None

    # Select 1 archived application
    simulate_applications_selection([archived_app_1.pk])
    archive_button = get_unarchive_button()
    assert archive_button is not None
    assert archive_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(archive_button) == snapshot(name="active unarchive button")

    modal = get_unarchive_modal()
    assert pretty_indented(modal) == snapshot(name="modal with 1 archived application")
    # Check that the next_url is correctly transmitted
    modal_form_action = urlsplit(modal.find("form")["action"])
    assert modal_form_action.path == reverse("apply:batch_unarchive")
    assert parse_qs(modal_form_action.query) == {"next_url": [table_url]}

    # Select 2 archived applications
    simulate_applications_selection([archived_app_1.pk, archived_app_2.pk])
    archive_button = get_unarchive_button()
    assert archive_button is not None
    assert archive_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(archive_button) == snapshot(name="active unarchive button")
    assert pretty_indented(get_unarchive_modal()) == snapshot(name="modal with 2 archived applications")

    # with at least one archived job app, the button is available
    simulate_applications_selection([not_archived_app.pk, archived_app_1])
    archive_button = get_unarchive_button()
    assert archive_button is not None
    assert archive_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(archive_button) == snapshot(name="active unarchive button")

    # But with only not archived job app, the button is disabled
    simulate_applications_selection([not_archived_app.pk])
    # No modal & linked button
    assert get_unarchive_modal() is None
    archive_button = get_unarchive_button()
    assert pretty_indented(archive_button) == snapshot(name="inactive unarchive button")


def test_list_for_siae_select_applications_batch_transfer(client, snapshot):
    MODAL_ID = "transfer_confirmation_modal"

    company = CompanyFactory(pk=1111, with_membership=True)
    employer = company.members.first()

    internal_transferable_app = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"), to_company=company, state=JobApplicationState.NEW
    )
    assert internal_transferable_app.transfer.is_available()
    both_transferable_app_1 = JobApplicationFactory(
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"), to_company=company, state=JobApplicationState.REFUSED
    )
    assert both_transferable_app_1.transfer.is_available()
    both_transferable_app_2 = JobApplicationFactory(
        pk=uuid.UUID("33333333-3333-3333-3333-333333333333"), to_company=company, state=JobApplicationState.REFUSED
    )
    assert both_transferable_app_2.transfer.is_available()

    untransferable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
    assert not untransferable_app.transfer.is_available()

    client.force_login(employer)
    table_url = reverse("apply:list_for_siae", query={"display": "table", "start_date": "2015-01-01"})

    response = client.get(table_url)
    simulated_page = parse_response_to_soup(
        response,
        # We need the whole body to be able to check modals
        selector="body",
    )
    [action_form] = simulated_page.find_all(
        "form", attrs={"hx-get": lambda attr: attr and attr.startswith(reverse("apply:list_for_siae_actions"))}
    )
    action_url = action_form["hx-get"]
    assert parse_qs(urlsplit(action_url).query) == {"list_url": [table_url]}
    assert simulated_page.find(id="batch-action-box").contents == []

    def simulate_applications_selection(application_list):
        response = client.get(
            action_url,
            # Explicitly redefine list_url since Django test client swallows it otherwise
            query_params={"list_url": table_url, "selected-application": application_list},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{action_url}']", response)

    def get_transfer_button():
        transfer_buttons = [
            button
            for button in simulated_page.find(id="batch-action-box").find_all("button")
            if button.text.strip() == "Transférer vers"
        ]
        if not transfer_buttons:
            return None
        [transfer_button] = transfer_buttons
        return transfer_button

    def get_transfer_modal():
        modal = simulated_page.find(id=MODAL_ID)
        if modal:
            modal_form_action = urlsplit(modal.find("form")["action"])
            assert modal_form_action.path == reverse("apply:batch_transfer")
            assert parse_qs(modal_form_action.query) == {"next_url": [table_url]}
        return modal

    assert get_transfer_button() is None

    # Mono organization cases : internal transfer is disabled
    # -------------------------------------------------------

    # Select 1 external transferable application and user is not member of multiple companies
    simulate_applications_selection([both_transferable_app_1.pk])
    transfer_button = get_transfer_button()
    assert transfer_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(transfer_button) == snapshot(name="active transfer button")
    assert pretty_indented(get_transfer_modal()) == snapshot(name="modal with only external transfer")

    for app_list in [
        [untransferable_app.pk],
        [internal_transferable_app.pk],
        [untransferable_app.pk, both_transferable_app_1.pk],
        [both_transferable_app_1.pk, both_transferable_app_2.pk],  # only one job app can be transfered externally
    ]:
        simulate_applications_selection(app_list)
        assert pretty_indented(get_transfer_button()) == snapshot(name="inactive transfer button mono org")
        assert get_transfer_modal() is None

    # Multi organization cases : internal transfer is allowed
    # ------------------------------------------------------
    CompanyMembershipFactory(company__pk=2222, company__for_snapshot=True, user=employer).company
    CompanyMembershipFactory(
        company__pk=3333, company__kind=CompanyKind.EITI, company__name="Superbe snapshot", user=employer
    ).company

    # Select 1 internal transferable application (only internal transfer is available)
    simulate_applications_selection([internal_transferable_app.pk])
    assert pretty_indented(get_transfer_button()) == snapshot(name="active transfer button")
    assert pretty_indented(get_transfer_modal()) == snapshot(name="modal with only internal transfer")

    # Select 1 external transferable application (both transfers available)
    simulate_applications_selection([both_transferable_app_1.pk])
    assert pretty_indented(get_transfer_button()) == snapshot(name="active transfer button")
    assert pretty_indented(get_transfer_modal()) == snapshot(name="both transfer modal")

    # Select 2 external transferable applications (only internal transfer is available)
    simulate_applications_selection([both_transferable_app_1.pk, both_transferable_app_2.pk])
    assert pretty_indented(get_transfer_button()) == snapshot(name="active transfer button")
    assert pretty_indented(get_transfer_modal()) == snapshot(name="modal with 2 internal transferable application")

    # Test with untransferable batches
    for app_list in [
        [untransferable_app.pk],
        [untransferable_app.pk, internal_transferable_app.pk],
    ]:
        simulate_applications_selection(app_list)
        assert pretty_indented(get_transfer_button()) == snapshot(name="inactive transfer button multi org")
        assert get_transfer_modal() is None


def test_list_for_siae_select_applications_batch_add_to_pool(client, snapshot):
    MODAL_ID = "add_to_pool_confirmation_modal"

    company = CompanyFactory(with_membership=True)
    employer = company.members.first()

    addable_app_1 = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"), to_company=company, state=JobApplicationState.PROCESSING
    )
    assert addable_app_1.add_to_pool.is_available()
    addable_app_2 = JobApplicationFactory(
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        to_company=company,
        state=JobApplicationState.POSTPONED,
    )
    assert addable_app_2.add_to_pool.is_available()
    added_app = JobApplicationFactory(to_company=company, state=JobApplicationState.POOL, archived_at=timezone.now())
    assert not added_app.add_to_pool.is_available()

    unaddable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.REFUSED)
    assert not unaddable_app.add_to_pool.is_available()

    client.force_login(employer)
    table_url = reverse("apply:list_for_siae", query={"display": "table", "start_date": "2015-01-01"})

    response = client.get(table_url)
    simulated_page = parse_response_to_soup(
        response,
        # We need the whole body to be able to check modals
        selector="body",
    )
    [action_form] = simulated_page.find_all(
        "form", attrs={"hx-get": lambda attr: attr and attr.startswith(reverse("apply:list_for_siae_actions"))}
    )
    action_url = action_form["hx-get"]
    assert parse_qs(urlsplit(action_url).query) == {"list_url": [table_url]}
    assert simulated_page.find(id="batch-action-box").contents == []

    def simulate_applications_selection(application_list):
        response = client.get(
            action_url,
            # Explicitly redefine list_url since Django test client swallows it otherwise
            query_params={"list_url": table_url, "selected-application": application_list},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{action_url}']", response)

    def get_add_to_pool_modal():
        return simulated_page.find(id=MODAL_ID)

    def get_add_to_pool_button():
        addable_buttons = [
            button
            for button in simulated_page.find(id="batch-action-box").find_all("button")
            if button.text.strip() == "Ajouter au vivier"
        ]
        if not addable_buttons:
            return None
        [addable_button] = addable_buttons
        return addable_button

    assert get_add_to_pool_modal() is None
    assert get_add_to_pool_button() is None

    # Select 1 addable application
    simulate_applications_selection([addable_app_1.pk])
    add_to_pool_button = get_add_to_pool_button()
    assert add_to_pool_button is not None
    assert add_to_pool_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(add_to_pool_button) == snapshot(name="active add to pool button")

    modal = get_add_to_pool_modal()
    assert pretty_indented(modal) == snapshot(name="modal with 1 addable application")
    # Check that the next_url is correctly transmitted
    modal_form_action = urlsplit(modal.find("form")["action"])
    assert modal_form_action.path == reverse("apply:batch_add_to_pool")
    assert parse_qs(modal_form_action.query) == {"next_url": [table_url]}

    # Select 2 addable applications
    simulate_applications_selection([addable_app_1.pk, addable_app_2.pk])
    add_to_pool_button = get_add_to_pool_button()
    assert add_to_pool_button is not None
    assert add_to_pool_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(add_to_pool_button) == snapshot(name="active add to pool button")
    assert pretty_indented(get_add_to_pool_modal()) == snapshot(name="modal with 2 addable applications")

    # Test with unaddable batches
    for app_list in [
        [added_app.pk],
        [unaddable_app.pk],
        [added_app.pk, addable_app_1.pk],
        [unaddable_app.pk, addable_app_2.pk],
    ]:
        simulate_applications_selection(app_list)
        # No modal & linked button
        assert get_add_to_pool_modal() is None
        add_to_pool_button = get_add_to_pool_button()
        assert pretty_indented(add_to_pool_button) == snapshot(name="inactive add to pool button")


def test_list_for_siae_select_applications_batch_postpone(client, snapshot):
    MODAL_ID = "postpone_confirmation_modal"

    company = CompanyFactory(
        with_membership=True,
        not_geiq_kind=True,  # GEIQ has more statuses in tooltip
    )
    employer = company.members.first()

    postponable_app_1 = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"), to_company=company, state=JobApplicationState.PROCESSING
    )
    assert postponable_app_1.postpone.is_available()
    postponable_app_2 = JobApplicationFactory(
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        to_company=company,
        state=JobApplicationState.PRIOR_TO_HIRE,
    )
    assert postponable_app_2.postpone.is_available()
    postponed_app = JobApplicationFactory(
        to_company=company, state=JobApplicationState.POSTPONED, archived_at=timezone.now()
    )
    assert not postponed_app.postpone.is_available()

    unpostponable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.REFUSED)
    assert not unpostponable_app.postpone.is_available()

    client.force_login(employer)
    table_url = reverse("apply:list_for_siae", query={"display": "table", "start_date": "2015-01-01"})

    response = client.get(table_url)
    simulated_page = parse_response_to_soup(
        response,
        # We need the whole body to be able to check modals
        selector="body",
    )
    [action_form] = simulated_page.find_all(
        "form", attrs={"hx-get": lambda attr: attr and attr.startswith(reverse("apply:list_for_siae_actions"))}
    )
    action_url = action_form["hx-get"]
    assert parse_qs(urlsplit(action_url).query) == {"list_url": [table_url]}
    assert simulated_page.find(id="batch-action-box").contents == []

    def simulate_applications_selection(application_list):
        response = client.get(
            action_url,
            # Explicitly redefine list_url since Django test client swallows it otherwise
            query_params={"list_url": table_url, "selected-application": application_list},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{action_url}']", response)

    def get_postpone_modal():
        return simulated_page.find(id=MODAL_ID)

    def get_postpone_button():
        postponable_buttons = [
            button
            for button in simulated_page.find(id="batch-action-box").find_all("button")
            if button.text.strip() == "Mettre en attente"
        ]
        if not postponable_buttons:
            return None
        [postponable_button] = postponable_buttons
        return postponable_button

    assert get_postpone_modal() is None
    assert get_postpone_button() is None

    # Select 1 postponable application
    simulate_applications_selection([postponable_app_1.pk])
    postpone_button = get_postpone_button()
    assert postpone_button is not None
    assert postpone_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(postpone_button) == snapshot(name="active postpone button")

    modal = get_postpone_modal()
    assert pretty_indented(modal) == snapshot(name="modal with 1 postponable application")
    # Check that the next_url is correctly transmitted
    modal_form_action = urlsplit(modal.find("form")["action"])
    assert modal_form_action.path == reverse("apply:batch_postpone")
    assert parse_qs(modal_form_action.query) == {"next_url": [table_url]}

    # Select 2 postponable applications
    simulate_applications_selection([postponable_app_1.pk, postponable_app_2.pk])
    postpone_button = get_postpone_button()
    assert postpone_button is not None
    assert postpone_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(postpone_button) == snapshot(name="active postpone button")
    assert pretty_indented(get_postpone_modal()) == snapshot(name="modal with 2 postponable applications")

    # Test with unpostponable batches
    for app_list in [
        [postponed_app.pk],
        [unpostponable_app.pk],
        [postponed_app.pk, postponable_app_1.pk],
        [unpostponable_app.pk, postponable_app_2.pk],
    ]:
        simulate_applications_selection(app_list)
        # No modal & linked button
        assert get_postpone_modal() is None
        postpone_button = get_postpone_button()
        assert pretty_indented(postpone_button) == snapshot(name="inactive postpone button")

    # Check as GEIQ
    company.kind = CompanyKind.GEIQ
    company.save(update_fields={"kind", "updated_at"})
    simulate_applications_selection([postponed_app.pk, postponable_app_1.pk])
    # No modal & linked button
    assert get_postpone_modal() is None
    postpone_button = get_postpone_button()
    assert pretty_indented(postpone_button) == snapshot(name="inactive postpone button as GEIQ")


def test_list_for_siae_select_applications_batch_process(client, snapshot):
    MODAL_ID = "process_confirmation_modal"

    company = CompanyFactory(with_membership=True)
    employer = company.members.first()

    processable_app_1 = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"), to_company=company, state=JobApplicationState.NEW
    )
    assert processable_app_1.process.is_available()
    processable_app_2 = JobApplicationFactory(
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"), to_company=company, state=JobApplicationState.NEW
    )
    assert processable_app_2.process.is_available()
    processed_app = JobApplicationFactory(
        to_company=company, state=JobApplicationState.PROCESSING, archived_at=timezone.now()
    )
    assert not processed_app.process.is_available()

    unprocessable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
    assert not unprocessable_app.process.is_available()

    client.force_login(employer)
    table_url = reverse("apply:list_for_siae", query={"display": "table", "start_date": "2015-01-01"})

    response = client.get(table_url)
    simulated_page = parse_response_to_soup(
        response,
        # We need the whole body to be able to check modals
        selector="body",
    )
    [action_form] = simulated_page.find_all(
        "form", attrs={"hx-get": lambda attr: attr and attr.startswith(reverse("apply:list_for_siae_actions"))}
    )
    action_url = action_form["hx-get"]
    assert parse_qs(urlsplit(action_url).query) == {"list_url": [table_url]}
    assert simulated_page.find(id="batch-action-box").contents == []

    def simulate_applications_selection(application_list):
        response = client.get(
            action_url,
            # Explicitly redefine list_url since Django test client swallows it otherwise
            query_params={"list_url": table_url, "selected-application": application_list},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{action_url}']", response)

    def get_process_modal():
        return simulated_page.find(id=MODAL_ID)

    def get_process_button():
        processable_buttons = [
            button
            for button in simulated_page.find(id="batch-action-box").find_all("button")
            if button.text.strip() == "Étudier"
        ]
        if not processable_buttons:
            return None
        [processable_button] = processable_buttons
        return processable_button

    assert get_process_modal() is None
    assert get_process_button() is None

    # Select 1 processable application
    simulate_applications_selection([processable_app_1.pk])
    postpone_button = get_process_button()
    assert postpone_button is not None
    assert postpone_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(postpone_button) == snapshot(name="active process button")

    modal = get_process_modal()
    assert pretty_indented(modal) == snapshot(name="modal with 1 processable application")
    # Check that the next_url is correctly transmitted
    modal_form_action = urlsplit(modal.find("form")["action"])
    assert modal_form_action.path == reverse("apply:batch_process")
    assert parse_qs(modal_form_action.query) == {"next_url": [table_url]}

    # Select 2 processable applications
    simulate_applications_selection([processable_app_1.pk, processable_app_2.pk])
    postpone_button = get_process_button()
    assert postpone_button is not None
    assert postpone_button["data-bs-target"] == f"#{MODAL_ID}"
    assert pretty_indented(postpone_button) == snapshot(name="active process button")
    assert pretty_indented(get_process_modal()) == snapshot(name="modal with 2 processable applications")

    # Test with unprocessable batches
    for app_list in [
        [processed_app.pk],
        [unprocessable_app.pk],
        [processed_app.pk, processable_app_1.pk],
        [unprocessable_app.pk, processable_app_2.pk],
    ]:
        simulate_applications_selection(app_list)
        # No modal & linked button
        assert get_process_modal() is None
        postpone_button = get_process_button()
        assert pretty_indented(postpone_button) == snapshot(name="inactive process button")


def test_list_for_siae_select_applications_batch_refuse(client, snapshot):
    company = CompanyFactory(
        with_membership=True,
        not_geiq_kind=True,  # GEIQ has more statuses in tooltip
    )
    employer = company.members.first()

    refusable_app_1 = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"), to_company=company, state=JobApplicationState.NEW
    )
    assert refusable_app_1.refuse.is_available()
    refusable_app_2 = JobApplicationFactory(
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        to_company=company,
        state=JobApplicationState.PRIOR_TO_HIRE,
    )
    assert refusable_app_2.refuse.is_available()
    refused_app = JobApplicationFactory(
        to_company=company, state=JobApplicationState.REFUSED, archived_at=timezone.now()
    )
    assert not refused_app.refuse.is_available()

    unrefusable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
    assert not unrefusable_app.refuse.is_available()

    client.force_login(employer)
    table_url = reverse("apply:list_for_siae", query={"display": "table", "start_date": "2015-01-01"})

    response = client.get(table_url)
    simulated_page = parse_response_to_soup(
        response,
        # We need the whole body to be able to check modals
        selector="body",
    )
    [action_form] = simulated_page.find_all(
        "form", attrs={"hx-get": lambda attr: attr and attr.startswith(reverse("apply:list_for_siae_actions"))}
    )
    action_url = action_form["hx-get"]
    assert parse_qs(urlsplit(action_url).query) == {"list_url": [table_url]}
    assert simulated_page.find(id="batch-action-box").contents == []

    def simulate_applications_selection(application_list):
        response = client.get(
            action_url,
            # Explicitly redefine list_url since Django test client swallows it otherwise
            query_params={"list_url": table_url, "selected-application": application_list},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{action_url}']", response)

    def get_refuse_button():
        refuse_buttons = [
            span.parent
            for span in simulated_page.find(id="batch-action-box").select("button > span")
            if span.contents == ["Décliner"]
        ]
        if not refuse_buttons:
            return None
        [refuse_button] = refuse_buttons
        return refuse_button

    assert get_refuse_button() is None

    # Select 1 refusable application
    simulate_applications_selection([refusable_app_1.pk])
    refuse_button = get_refuse_button()
    assert refuse_button is not None
    assert pretty_indented(refuse_button) == snapshot(name="active refuse button")

    # Check that the next_url is correctly transmitted
    refuse_form_action = urlsplit(refuse_button.parent["action"])
    assert refuse_form_action.path == reverse("apply:batch_refuse")
    assert parse_qs(refuse_form_action.query) == {"next_url": [table_url]}

    # Select 2 refusable applications
    simulate_applications_selection([refusable_app_1.pk, refusable_app_2.pk])
    refuse_button = get_refuse_button()
    assert refuse_button is not None
    assert pretty_indented(refuse_button) == snapshot(name="active refuse button")

    # Test with unrefusable batches
    for app_list in [
        [unrefusable_app.pk],
        [refused_app.pk, refusable_app_1.pk],
        [unrefusable_app.pk, refusable_app_2.pk],
    ]:
        simulate_applications_selection(app_list)
        refuse_button = get_refuse_button()
        assert pretty_indented(refuse_button) == snapshot(name="inactive refuse button")

    # Check as GEIQ
    company.kind = CompanyKind.GEIQ
    company.save(update_fields={"kind", "updated_at"})
    simulate_applications_selection([refused_app.pk, refusable_app_1.pk])
    refuse_button = get_refuse_button()
    assert pretty_indented(refuse_button) == snapshot(name="inactive refuse button as GEIQ")


def test_list_for_siae_select_applications_batch_accept(client, snapshot):
    company = CompanyFactory(with_membership=True, subject_to_iae_rules=True)
    employer = company.members.first()

    acceptable_app_1 = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        to_company=company,
        state=JobApplicationState.PROCESSING,
        with_iae_eligibility_diagnosis=True,
    )
    assert acceptable_app_1.accept.is_available()
    acceptable_app_2 = JobApplicationFactory(
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        to_company=company,
        state=JobApplicationState.PRIOR_TO_HIRE,
        with_iae_eligibility_diagnosis=True,
    )
    assert acceptable_app_2.accept.is_available()
    acceptable_app_3 = JobApplicationFactory(
        pk=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        to_company=company,
        state=JobApplicationState.NEW,
        with_iae_eligibility_diagnosis=True,
    )
    assert acceptable_app_3.accept.is_available()

    unacceptable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
    assert not unacceptable_app.accept.is_available()

    client.force_login(employer)
    table_url = reverse("apply:list_for_siae", query={"display": "table", "start_date": "2015-01-01"})

    response = client.get(table_url)
    simulated_page = parse_response_to_soup(
        response,
        # We need the whole body to be able to check modals
        selector="body",
    )
    [action_form] = simulated_page.find_all(
        "form", attrs={"hx-get": lambda attr: attr and attr.startswith(reverse("apply:list_for_siae_actions"))}
    )
    action_url = action_form["hx-get"]
    assert parse_qs(urlsplit(action_url).query) == {"list_url": [table_url]}
    assert simulated_page.find(id="batch-action-box").contents == []

    def simulate_applications_selection(application_list):
        response = client.get(
            action_url,
            # Explicitly redefine list_url since Django test client swallows it otherwise
            query_params={"list_url": table_url, "selected-application": application_list},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{action_url}']", response)

    def get_accept_button():
        accept_buttons = [
            span.parent
            for span in simulated_page.find(id="batch-action-box").select("span")
            if span.contents == ["Accepter"]
        ]
        if not accept_buttons:
            return None
        [accept_button] = accept_buttons
        return accept_button

    assert get_accept_button() is None
    # Select 1 acceptable application
    for acceptable_app in [acceptable_app_1, acceptable_app_2, acceptable_app_3]:
        simulate_applications_selection([acceptable_app.pk])
        accept_button = get_accept_button()
        assert accept_button is not None
        assert pretty_indented(accept_button).replace(str(acceptable_app.pk), "[PK of JobApplication]") == snapshot(
            name="active accept button"
        )
        # Check that the next_url is correctly transmitted
        assert accept_button["href"] == reverse(
            "apply:start-accept", kwargs={"job_application_id": acceptable_app.pk}, query={"next_url": table_url}
        )

    # Test with unacceptable batches
    simulate_applications_selection([acceptable_app_1.pk, acceptable_app_2.pk, acceptable_app_3.pk])
    accept_button = get_accept_button()
    assert pretty_indented(accept_button) == snapshot(name="inactive accept button multiple job applications")

    # the "unnacceptable" job application tooltip only works if the only unnaceptable state is accepted.
    # update the tooltip if this assert breaks
    assert set(JobApplicationState) - set(JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES) == {
        JobApplicationState.ACCEPTED
    }
    simulate_applications_selection([unacceptable_app.pk])
    accept_button = get_accept_button()
    assert pretty_indented(accept_button) == snapshot(name="inactive accept button already accepted")


def test_list_for_siae_select_applications_batch_accept_geiq(client, snapshot):
    company = CompanyFactory(with_membership=True, kind=CompanyKind.GEIQ)
    employer = company.members.first()

    acceptable_app_1 = JobApplicationFactory(
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        to_company=company,
        state=JobApplicationState.PROCESSING,
    )
    assert acceptable_app_1.accept.is_available()
    acceptable_app_2 = JobApplicationFactory(
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        to_company=company,
        state=JobApplicationState.PRIOR_TO_HIRE,
    )
    assert acceptable_app_2.accept.is_available()
    acceptable_app_3 = JobApplicationFactory(
        pk=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        to_company=company,
        state=JobApplicationState.NEW,
    )
    assert acceptable_app_3.accept.is_available()

    unacceptable_app = JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
    assert not unacceptable_app.accept.is_available()

    client.force_login(employer)
    table_url = reverse("apply:list_for_siae", query={"display": "table", "start_date": "2015-01-01"})

    response = client.get(table_url)
    simulated_page = parse_response_to_soup(
        response,
        # We need the whole body to be able to check modals
        selector="body",
    )
    [action_form] = simulated_page.find_all(
        "form", attrs={"hx-get": lambda attr: attr and attr.startswith(reverse("apply:list_for_siae_actions"))}
    )
    action_url = action_form["hx-get"]
    assert parse_qs(urlsplit(action_url).query) == {"list_url": [table_url]}
    assert simulated_page.find(id="batch-action-box").contents == []

    def simulate_applications_selection(application_list):
        response = client.get(
            action_url,
            # Explicitly redefine list_url since Django test client swallows it otherwise
            query_params={"list_url": table_url, "selected-application": application_list},
            headers={"HX-Request": "true"},
        )
        update_page_with_htmx(simulated_page, f"form[hx-get='{action_url}']", response)

    def get_accept_button():
        accept_buttons = [
            span.parent
            for span in simulated_page.find(id="batch-action-box").select("span")
            if span.contents == ["Accepter"]
        ]
        if not accept_buttons:
            return None
        [accept_button] = accept_buttons
        return accept_button

    def get_confirm_button():
        return simulated_page.find(id="confirm_no_allowance_modal").find("a")

    assert get_accept_button() is None
    # Select 1 acceptable application
    for acceptable_app in [acceptable_app_1, acceptable_app_2, acceptable_app_3]:
        simulate_applications_selection([acceptable_app.pk])
        accept_button = get_accept_button()
        assert accept_button is not None
        assert pretty_indented(accept_button).replace(str(acceptable_app.pk), "[PK of JobApplication]") == snapshot(
            name="active accept button"
        )
        # button opens a model
        assert accept_button["data-bs-target"] == "#confirm_no_allowance_modal"

        # Check that the next_url is correctly transmitted
        confirm_button = get_confirm_button()
        assert confirm_button["href"] == reverse(
            "apply:start-accept", kwargs={"job_application_id": acceptable_app.pk}
        )

    # Test with unacceptable batches
    simulate_applications_selection([acceptable_app_1.pk, acceptable_app_2.pk, acceptable_app_3.pk])
    accept_button = get_accept_button()
    assert pretty_indented(accept_button) == snapshot(name="inactive accept button multiple job applications")

    # the "unnacceptable" job application tooltip only works if the only unnaceptable state is accepted.
    # update the tooltip if this assert breaks
    assert set(JobApplicationState) - set(JobApplicationWorkflow.CAN_BE_ACCEPTED_STATES) == {
        JobApplicationState.ACCEPTED
    }
    simulate_applications_selection([unacceptable_app.pk])
    accept_button = get_accept_button()
    assert pretty_indented(accept_button) == snapshot(name="inactive accept button already accepted")


def test_order(client, subtests):
    company = CompanyFactory(with_membership=True)
    employer = company.members.first()
    zorro_application = JobApplicationFactory(
        job_seeker__first_name="Zorro",
        job_seeker__last_name="Don Diego",
        to_company=company,
    )
    alice_first_application = JobApplicationFactory(
        job_seeker__first_name="Alice",
        job_seeker__last_name="Lewis",
        to_company=company,
        pk=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    )
    alice_second_application = JobApplicationFactory(
        job_seeker__first_name="Alice",
        job_seeker__last_name="Lewis",
        to_company=company,
        pk=uuid.UUID("22222222-2222-2222-2222-222222222222"),
    )

    client.force_login(employer)
    url = reverse("apply:list_for_siae")
    query_params = {"display": JobApplicationsDisplayKind.TABLE}

    expected_order = {
        "created_at": [zorro_application, alice_first_application, alice_second_application],
        "job_seeker_full_name": [zorro_application, alice_first_application, alice_second_application],
    }

    with subtests.test(order="<missing_value>"):
        response = client.get(url, query_params)
        assert response.context["job_applications_page"].object_list == list(reversed(expected_order["created_at"]))

    with subtests.test(order="<invalid_value>"):
        response = client.get(url, query_params | {"order": "invalid_value"})
        assert response.context["job_applications_page"].object_list == list(reversed(expected_order["created_at"]))

    for order, applications in expected_order.items():
        with subtests.test(order=order):
            response = client.get(url, query_params | {"order": order})
            assert response.context["job_applications_page"].object_list == applications

            response = client.get(url, query_params | {"order": f"-{order}"})
            assert response.context["job_applications_page"].object_list == list(reversed(applications))


def test_htmx_order(client):
    url = reverse("apply:list_for_siae")
    company = CompanyFactory(with_membership=True)
    employer = company.members.first()

    JobApplicationFactory.create_batch(2, to_company=company)
    client.force_login(employer)
    query_params = {"display": JobApplicationsDisplayKind.TABLE}
    response = client.get(url, query_params)

    assertContains(response, "2 résultats")
    simulated_page = parse_response_to_soup(response)

    ORDER_ID = "id_order"
    CREATED_AT_ASC = "created_at"
    assert response.context["order"] != CREATED_AT_ASC

    [sort_by_created_at_button] = simulated_page.find_all("button", {"data-emplois-setter-value": CREATED_AT_ASC})
    assert sort_by_created_at_button["data-emplois-setter-target"] == f"#{ORDER_ID}"
    [order_input] = simulated_page.find_all(id=ORDER_ID)
    # Simulate click on button
    order_input["value"] = CREATED_AT_ASC
    response = client.get(url, query_params | {"order": CREATED_AT_ASC}, headers={"HX-Request": "true"})
    update_page_with_htmx(simulated_page, f"form[hx-get='{url}']", response)
    response = client.get(url, query_params | {"order": CREATED_AT_ASC})
    assertContains(response, "2 résultats")
    fresh_page = parse_response_to_soup(response)
    assertSoupEqual(simulated_page, fresh_page)


@freeze_time("2024-11-27", tick=True)
def test_table_iae_state_and_criteria(client, snapshot):
    company = CompanyFactory(with_membership=True, not_in_territorial_experimentation=True, subject_to_iae_rules=True)
    employer = company.members.first()
    client.force_login(employer)
    url = reverse("apply:list_for_siae")

    prescriber_org = PrescriberOrganizationFactory(authorized=True, for_snapshot=True, with_membership=True)
    prescriber = prescriber_org.members.get()
    job_seeker = JobSeekerFactory(for_snapshot=True)
    common_kwargs = {
        "to_company": company,
        "sender_kind": SenderKind.EMPLOYER,
        "sender": employer,
        "sender_company": company,
    }
    company_diag = IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        author_kind=AuthorKind.EMPLOYER,
        author_siae=company,
        author=company.members.first(),
        criteria_kinds=[AdministrativeCriteriaKind.ASS, AdministrativeCriteriaKind.RSA],
    )
    no_criteria_prescriber_diag = IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        author_kind=AuthorKind.PRESCRIBER,
        author_prescriber_organization=prescriber_org,
        author=prescriber,
    )
    prescriber_diag = IAEEligibilityDiagnosisFactory(
        job_seeker=job_seeker,
        author_kind=AuthorKind.PRESCRIBER,
        author_prescriber_organization=prescriber_org,
        author=prescriber,
        criteria_kinds=[AdministrativeCriteriaKind.AAH, AdministrativeCriteriaKind.QPV],
    )

    prescriber_approval = ApprovalFactory(
        user__first_name="Martine",
        user__last_name="Martin",
    )
    employer_approval = ApprovalFactory(
        user__first_name="Aline",
        user__last_name="Bato",
        with_diagnosis_from_employer=True,
    )
    company_approval_diag = IAEEligibilityDiagnosisFactory(
        job_seeker__first_name="Béatrice",
        job_seeker__last_name="Voiture",
        author_kind=AuthorKind.EMPLOYER,
        author_siae=company,
        author=company.members.first(),
        criteria_kinds=[AdministrativeCriteriaKind.ASS, AdministrativeCriteriaKind.RSA],
    )
    ApprovalFactory(
        user=company_approval_diag.job_seeker,
        eligibility_diagnosis=company_approval_diag,
    )

    job_applications = [
        JobApplicationFactory(
            state=JobApplicationState.NEW,
            job_seeker__first_name="Pas de",
            job_seeker__last_name="Diagnostique",
            **common_kwargs,
        ),
        JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
            eligibility_diagnosis=company_diag,
            job_seeker=job_seeker,
            **common_kwargs,
        ),
        JobApplicationFactory(
            state=JobApplicationState.REFUSED,
            eligibility_diagnosis=no_criteria_prescriber_diag,
            job_seeker=job_seeker,
            **common_kwargs,
        ),
        JobApplicationFactory(
            state=JobApplicationState.POSTPONED,
            eligibility_diagnosis=prescriber_diag,
            job_seeker=job_seeker,
            **common_kwargs,
        ),
        JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            eligibility_diagnosis=employer_approval.eligibility_diagnosis,
            job_seeker=employer_approval.user,
            **common_kwargs,
        ),
        JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            eligibility_diagnosis=prescriber_approval.eligibility_diagnosis,
            job_seeker=prescriber_approval.user,
            **common_kwargs,
        ),
        JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            eligibility_diagnosis=company_approval_diag,
            job_seeker=company_approval_diag.job_seeker,
            **common_kwargs,
        ),
    ]

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
                    (
                        "value",
                        str(job_application.pk),
                        "[PK of JobApplication]",
                    ),
                    (
                        "id",
                        f"select-{job_application.pk}",
                        "select-[PK of JobApplication]",
                    ),
                    (
                        "for",
                        f"select-{job_application.pk}",
                        "select-[PK of JobApplication]",
                    ),
                ]
                for job_application in job_applications
            )
        ),
    )
    assert pretty_indented(page) == snapshot(name="applications table")


class TestAutocomplete:
    ALLOWED_FIELDS = [
        "job_seeker",
        "sender",
        "sender_company",
        "sender_prescriber_organization",
    ]

    FORBIDDEN_FIELDS = [
        "to_company",
        "unknown_field",
    ]

    def test_invalid_access(self, client):
        for user in [JobSeekerFactory(), LaborInspectorFactory(membership=True)]:
            client.force_login(user)
            for field_name in self.ALLOWED_FIELDS + self.FORBIDDEN_FIELDS:
                response = client.post(reverse("apply:list_for_siae_autocomplete", kwargs={"field_name": field_name}))
                assert response.status_code == 403

    def test_as_prescriber(self, client):
        job_application = JobApplicationFactory()
        client.force_login(job_application.sender)
        for field_name in self.ALLOWED_FIELDS + self.FORBIDDEN_FIELDS:
            response = client.get(reverse("apply:list_for_siae_autocomplete", kwargs={"field_name": field_name}))
            assert response.status_code == 404

    def test_as_employer(self, client, snapshot):
        company = CompanyFactory()
        employer = CompanyMembershipFactory(company=company).user
        job_application = JobApplicationFactory(
            to_company=company,
            sender__first_name="Alice",
            sender__last_name="Lewis",
            job_seeker__first_name="Calvin",
            job_seeker__last_name="Coolidge",
        )
        other_job_application = JobApplicationFactory(
            to_company=company,
            sender__first_name="Bob",
            sender__last_name="Alice",
            job_seeker__first_name="Robert",
            job_seeker__last_name="Cooledge",
        )
        prescriber_org_application = JobApplicationFactory(
            to_company=company,
            sender_prescriber_organization__name="Association de Prescripteurs",
            sent_by_authorized_prescriber_organisation=True,
            job_seeker__first_name="Roger",
            job_seeker__last_name="Smith",
        )
        sent_by_employer_application = JobApplicationFactory(
            to_company=company,
            sent_by_another_employer=True,
            sender_company__brand="L'entreprise envoyeuse",
            job_seeker__first_name="Samantha",
            job_seeker__last_name="Brown",
        )
        JobApplicationFactory(to_company=company, sender__first_name="John", sender__last_name="Smith")
        client.force_login(employer)

        for field_name in self.FORBIDDEN_FIELDS:
            response = client.get(reverse("apply:list_for_siae_autocomplete", kwargs={"field_name": field_name}))
            assert response.status_code == 404

        matching_terms_and_results = {
            "job_seeker": ("Calvin", {"id": job_application.job_seeker.pk, "text": "COOLIDGE Calvin"}),
            "sender": ("alIce lew", {"id": job_application.sender.pk, "text": "LEWIS Alice"}),
            "sender_company": (
                "envoy",
                {"id": sent_by_employer_application.sender_company.pk, "text": "L'entreprise envoyeuse"},
            ),
            "sender_prescriber_organization": (
                "tion de prescripteurs",
                {
                    "id": prescriber_org_application.sender_prescriber_organization.pk,
                    "text": "Association de Prescripteurs",
                },
            ),
        }

        for field_name in self.ALLOWED_FIELDS:
            autocomplete_url = reverse("apply:list_for_siae_autocomplete", kwargs={"field_name": field_name})

            # A term is needed to search
            response = client.get(autocomplete_url)
            assert response.status_code == 200
            assert response.json() == {"results": []}

            # A non empty term is needed to search
            with assertSnapshotQueries(snapshot(name="SQL queries when no actual search is performed ")):
                response = client.get(autocomplete_url, {"term": "  "})
            assert response.status_code == 200
            assert response.json() == {"results": []}

            # No results for unrelated term
            response = client.get(autocomplete_url, {"term": "Nom sans aucun rapport"})
            assert response.status_code == 200
            assert response.json() == {"results": []}

            term, expected_result = matching_terms_and_results[field_name]
            with assertSnapshotQueries(snapshot(name=f"SQL queries for {field_name} autocomplete")):
                response = client.get(autocomplete_url, {"term": term})
            assert response.status_code == 200
            assert response.json() == {"results": [expected_result]}

        # Test multiple results
        response = client.get(
            reverse("apply:list_for_siae_autocomplete", kwargs={"field_name": "sender"}), {"term": "aLice"}
        )
        assert response.status_code == 200
        assert len(response.json()["results"]) == 2
        assert {"id": job_application.sender.pk, "text": "LEWIS Alice"} in response.json()["results"]
        assert {"id": other_job_application.sender.pk, "text": "ALICE Bob"} in response.json()["results"]
