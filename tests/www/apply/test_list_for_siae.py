import datetime
from urllib.parse import unquote

import pytest
from django.urls import reverse
from django.utils import timezone
from pytest_django.asserts import assertContains, assertNotContains, assertNumQueries

from itou.companies.enums import CompanyKind
from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.jobs.models import Appellation
from itou.utils.urls import add_url_params
from itou.utils.widgets import DuetDatePickerWidget
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.cities.factories import create_city_saint_andre
from tests.companies.factories import CompanyFactory, JobDescriptionFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationSentByPrescriberFactory,
)
from tests.jobs.factories import create_test_romes_and_appellations
from tests.prescribers.factories import (
    PrescriberMembershipFactory,
    PrescriberOrganizationWithMembershipFactory,
)
from tests.users.factories import JobSeekerFactory
from tests.utils.htmx.test import assertSoupEqual, update_page_with_htmx
from tests.utils.test import BASE_NUM_QUERIES, TestCase, assert_previous_step, parse_response_to_soup


@pytest.mark.usefixtures("unittest_compatibility")
class ProcessListSiaeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        """
        Create three organizations with two members each:
        - pole_emploi: job seekers agency.
        - l_envol: an emergency center for homeless people.
        - hit_pit: a boxing gym looking for boxers.

        Pole Emploi prescribers:
        - Thibault
        - laurie

        L'envol prescribers:
        - Audrey
        - Manu

        Hit Pit staff:
        - Eddie
        """

        # Pole Emploi
        pole_emploi = PrescriberOrganizationWithMembershipFactory(
            authorized=True, name="Pôle emploi", membership__user__first_name="Thibault"
        )
        PrescriberMembershipFactory(organization=pole_emploi, user__first_name="Laurie")
        thibault_pe = pole_emploi.members.get(first_name="Thibault")
        laurie_pe = pole_emploi.members.get(first_name="Laurie")

        # L'Envol
        l_envol = PrescriberOrganizationWithMembershipFactory(name="L'Envol", membership__user__first_name="Manu")
        PrescriberMembershipFactory(organization=l_envol, user__first_name="Audrey")
        audrey_envol = l_envol.members.get(first_name="Audrey")

        # Hit Pit
        hit_pit = CompanyFactory(name="Hit Pit", with_membership=True, membership__user__first_name="Eddie")
        eddie_hit_pit = hit_pit.members.get(first_name="Eddie")

        # Now send applications
        states = list(JobApplicationWorkflow.states)
        remaining_states, last_state = states[:-1], states[-1]
        common_kwargs = {
            "to_company": hit_pit,
            "sender_prescriber_organization": pole_emploi,
            "eligibility_diagnosis": None,
        }
        for i, state in enumerate(remaining_states):
            creation_date = timezone.now() - timezone.timedelta(days=i)
            JobApplicationSentByPrescriberFactory(
                **common_kwargs,
                state=state,
                created_at=creation_date,
                sender=thibault_pe,
            )
        # Treat Maggie specially, tests rely on her.
        creation_date = timezone.now() - timezone.timedelta(days=i + 1)
        maggie = JobSeekerFactory(first_name="Maggie")
        JobApplicationSentByPrescriberFactory(
            **common_kwargs,
            state=last_state,
            created_at=creation_date,
            sender=thibault_pe,
            job_seeker=maggie,
        )
        JobApplicationSentByPrescriberFactory(
            **common_kwargs,
            sender=laurie_pe,
            job_seeker=maggie,
        )

        # Variables available for unit tests
        cls.pole_emploi = pole_emploi
        cls.hit_pit = hit_pit
        cls.l_envol = l_envol
        cls.thibault_pe = thibault_pe
        cls.laurie_pe = laurie_pe
        cls.eddie_hit_pit = eddie_hit_pit
        cls.audrey_envol = audrey_envol
        cls.maggie = maggie

    def test_list_for_siae(self):
        """
        Eddie wants to see a list of job applications sent to his SIAE.
        """
        city = create_city_saint_andre()
        create_test_romes_and_appellations(["N4105"], appellations_per_rome=2)
        appellations = Appellation.objects.all()[:2]
        job1 = JobDescriptionFactory(company=self.hit_pit, appellation=appellations[0], location=city)
        job2 = JobDescriptionFactory(company=self.hit_pit, appellation=appellations[1], location=city)
        for job_application in JobApplication.objects.all():
            job_application.selected_jobs.set([job1, job2])

        # Add a diagnosis present on 2 applications
        diagnosis = EligibilityDiagnosisFactory(job_seeker=self.maggie)
        level1_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
        level2_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()
        diagnosis.administrative_criteria.add(level1_criterion)
        diagnosis.administrative_criteria.add(level2_criterion)

        self.client.force_login(self.eddie_hit_pit)
        with assertNumQueries(
            BASE_NUM_QUERIES
            + 1  # fetch django session
            + 1  # fetch user
            + 2  # check for membership & infos
            + 1  # count new + processing + postponed applications
            #
            # SiaeFilterJobApplicationsForm:
            + 1  # get list of senders (distinct sender_id)
            + 1  # get list of job seekers (distinct job_seeker_id)
            + 1  # get list of administrative criteria
            + 1  # get list of job application
            + 1  # prefetch selected jobs
            + 1  # prefetch jobs appellation
            + 1  # select distinct sender_prescriber_organization
            #
            # Paginate the job applications queryset:
            + 1  # has_suspended_approval subquery
            + 1  # select job applications with annotations
            + 1  # prefetch selected jobs
            + 1  # prefetch jobs appellation
            + 1  # prefetch jobs location
            + 1  # prefetch approvals
            + 1  # manually prefetch administrative_criteria
            #
            # Render template:
            # 9 job applications (1 per state in JobApplicationWorkflow + 1 sent by prescriber)
            # 22 requests, maggie has a diagnosis made by a prescriber in this test
            + 1  # jobapp1: no approval (prefetched ⇒ no query), check PE approval (⇒ no PE approval)
            + 1  # jobapp1: select last valid diagnosis made by prescriber or SIAE (prescriber)
            # 24 requests
            + 1  # jobapp2: no approval (prefetched ⇒ no query), check PE approval (⇒ no PE approval)
            + 1  # jobapp2: select last valid diagnosis made by prescriber or SIAE (SIAE)
            # 26 requests
            + 1  # jobapp3: no approval (prefetched ⇒ no query), check PE approval (⇒ no PE approval)
            + 1  # jobapp3: select last valid diagnosis made by prescriber or SIAE (SIAE)
            # 28 requests
            + 1  # jobapp4: no approval (prefetched ⇒ no query), check PE approval (⇒ no PE approval)
            + 1  # jobapp4: select last valid diagnosis made by prescriber or SIAE (SIAE)
            # 30 requests
            + 1  # jobapp5: no approval (prefetched ⇒ no query), check PE approval (⇒ no PE approval)
            + 1  # jobapp5: select last valid diagnosis made by prescriber or SIAE (SIAE)
            # 32 requests
            + 1  # jobapp6: no approval (prefetched ⇒ no query), check PE approval (⇒ no PE approval)
            + 1  # jobapp6: select last valid diagnosis made by prescriber or SIAE (SIAE)
            # 34 requests
            + 1  # jobapp7: no approval (prefetched ⇒ no query), check PE approval (⇒ no PE approval)
            + 1  # jobapp7: select last valid diagnosis made by prescriber or SIAE (SIAE)
            # 36 requests
            + 1  # jobapp8: no approval (prefetched ⇒ no query), check PE approval (⇒ no PE approval)
            + 1  # jobapp8: select last valid diagnosis made by prescriber or SIAE (SIAE)
            # 38 requests, maggie has a diagnosis made by a prescriber in this test
            + 1  # jobapp9: no approval (prefetched ⇒ no query), check PE approval (⇒ no PE approval)
            + 1  # jobapp8: select last valid diagnosis made by prescriber or SIAE (prescriber)
            + 3  # update session
        ):
            response = self.client.get(reverse("apply:list_for_siae"))

        total_applications = len(response.context["job_applications_page"].object_list)

        # Result page should contain all SIAE's job applications.
        assert total_applications == self.hit_pit.job_applications_received.not_archived().count()

        assert_previous_step(response, reverse("dashboard:index"))

        # Has link to export with back_url set
        export_url = unquote(
            add_url_params(reverse("apply:list_for_siae_exports"), {"back_url": reverse("apply:list_for_siae")})
        )
        assertContains(response, export_url)

        # Has job application card link with back_url set
        job_app = JobApplication.objects.first()
        job_application_link = unquote(
            add_url_params(
                reverse("apply:details_for_company", kwargs={"job_application_id": job_app.pk}),
                {"back_url": reverse("apply:list_for_siae")},
            )
        )
        assertContains(response, job_application_link)

    def test_list_for_siae_show_criteria(self):
        # Add a diagnosis present on 2 applications
        diagnosis = EligibilityDiagnosisFactory(job_seeker=self.maggie)
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

        self.client.force_login(self.eddie_hit_pit)
        # Only show maggie's applications
        params = {"job_seekers": [self.maggie.id]}
        response = self.client.get(reverse("apply:list_for_siae"), params)

        # 4 criteria: all are shown
        assertContains(response, "<li>Allocataire AAH</li>", html=True)
        assertContains(response, "<li>Allocataire ASS</li>", html=True)
        assertContains(response, "<li>Bénéficiaire du RSA</li>", html=True)
        SENIOR_CRITERION = "<li>Senior (+50 ans)</li>"
        assertContains(response, SENIOR_CRITERION, html=True)

        # Add a 5th criterion to the diagnosis
        diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.get(name="DETLD (+ 24 mois)"))

        response = self.client.get(reverse("apply:list_for_siae"), params)
        # Only the 3 first are shown (ordered by level & name)
        # The 4th line has been replaced by "+ 2 autres critères"
        assertContains(response, "<li>Allocataire AAH</li>", html=True)
        assertContains(response, "<li>Allocataire ASS</li>", html=True)
        assertContains(response, "<li>Bénéficiaire du RSA</li>", html=True)
        assertNotContains(response, SENIOR_CRITERION, html=True)
        # DETLD is also not shown
        assertContains(response, "+ 2 autres critères")

    def test_list_for_siae_hide_criteria_for_non_SIAE_employers(self):
        # Add a diagnosis present on 2 applications
        diagnosis = EligibilityDiagnosisFactory(job_seeker=self.maggie)
        # Level 1 criteria
        diagnosis.administrative_criteria.add(AdministrativeCriteria.objects.get(name="Allocataire AAH"))

        TITLE = '<p class="h5">Critères administratifs IAE</p>'
        CRITERION = "<li>Allocataire AAH</li>"

        self.client.force_login(self.eddie_hit_pit)

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
            with self.subTest(kind=kind):
                self.hit_pit.kind = kind
                self.hit_pit.save(update_fields=("kind",))
                # Only show maggie's applications
                response = self.client.get(reverse("apply:list_for_siae"), {"job_seekers": [self.maggie.id]})
                if expect_to_see_criteria[kind]:
                    assertContains(response, TITLE, html=True)
                    assertContains(response, CRITERION, html=True)
                else:
                    assertNotContains(response, TITLE, html=True)
                    assertNotContains(response, CRITERION, html=True)

    def test_list_for_siae_filtered_by_one_state(self):
        """
        Eddie wants to see only accepted job applications.
        """
        self.client.force_login(self.eddie_hit_pit)
        state_accepted = JobApplicationState.ACCEPTED
        response = self.client.get(reverse("apply:list_for_siae"), {"states": [state_accepted]})

        applications = response.context["job_applications_page"].object_list

        assert len(applications) == 1
        assert applications[0].state == state_accepted

    def test_list_for_siae_filtered_by_state_prior_to_hire(self):
        """
        Eddie wants to see only job applications in prior_to_hire state
        """
        PRIOR_TO_HIRE_LABEL = "Action préalable à l’embauche</label>"

        # prior_to_hire filter doesn't exist for non-GEIQ SIAE and is ignored
        self.client.force_login(self.eddie_hit_pit)
        params = {"states": [JobApplicationState.PRIOR_TO_HIRE]}
        response = self.client.get(reverse("apply:list_for_siae"), params)
        assertNotContains(response, PRIOR_TO_HIRE_LABEL)

        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 9

        # With a GEIQ user, the filter is present and works
        self.hit_pit.kind = CompanyKind.GEIQ
        self.hit_pit.save()
        response = self.client.get(reverse("apply:list_for_siae"), params)
        assertContains(response, PRIOR_TO_HIRE_LABEL)

        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 1
        assert applications[0].state == JobApplicationState.PRIOR_TO_HIRE

    def test_list_for_siae_filtered_by_many_states(self):
        """
        Eddie wants to see NEW and PROCESSING job applications.
        """
        self.client.force_login(self.eddie_hit_pit)
        job_applications_states = [JobApplicationState.NEW, JobApplicationState.PROCESSING]
        response = self.client.get(reverse("apply:list_for_siae"), {"states": job_applications_states})

        applications = response.context["job_applications_page"].object_list

        assert len(applications) == 3
        assert applications[0].state.name in job_applications_states

    def test_list_for_siae_filtered_by_dates(self):
        """
        Eddie wants to see job applications sent at a specific date.
        """
        self.client.force_login(self.eddie_hit_pit)
        date_format = DuetDatePickerWidget.INPUT_DATE_FORMAT
        job_applications = self.hit_pit.job_applications_received.not_archived().order_by("created_at")
        jobs_in_range = job_applications[3:]
        start_date = jobs_in_range[0].created_at

        # Negative indexing is not allowed in querysets
        end_date = jobs_in_range[len(jobs_in_range) - 1].created_at
        response = self.client.get(
            reverse("apply:list_for_siae"),
            {
                "start_date": timezone.localdate(start_date).strftime(date_format),
                "end_date": timezone.localdate(end_date).strftime(date_format),
            },
        )
        applications = response.context["job_applications_page"].object_list

        assert len(applications) == 6
        assert applications[0].created_at >= start_date
        assert applications[0].created_at <= end_date

    def test_list_for_siae_empty_dates_in_params(self):
        """
        Our form uses a Datepicker that adds empty start and end dates
        in the HTTP query if they are not filled in by the user.
        Make sure the template loads all available job applications if fields are empty.
        """
        self.client.force_login(self.eddie_hit_pit)
        response = self.client.get(add_url_params(reverse("apply:list_for_siae"), {"start_date": "", "end_date": ""}))
        total_applications = len(response.context["job_applications_page"].object_list)

        assert total_applications == self.hit_pit.job_applications_received.not_archived().count()

    def test_list_for_siae_filtered_by_sender_organization_name(self):
        """
        Eddie wants to see applications sent by Pôle emploi.
        """
        self.client.force_login(self.eddie_hit_pit)
        sender_organization = self.pole_emploi
        response = self.client.get(reverse("apply:list_for_siae"), {"sender_organizations": [sender_organization.id]})

        applications = response.context["job_applications_page"].object_list

        assert len(applications) == 9
        assert applications[0].sender_prescriber_organization.id == sender_organization.id

    def test_list_for_siae_filtered_by_sender_name(self):
        """
        Eddie wants to see applications sent by a member of Pôle emploi.
        """
        self.client.force_login(self.eddie_hit_pit)
        sender = self.thibault_pe
        response = self.client.get(reverse("apply:list_for_siae"), {"senders": [sender.id]})

        applications = response.context["job_applications_page"].object_list

        assert len(applications) == 8
        assert applications[0].sender.id == sender.id

    def test_list_for_siae_filtered_by_job_seeker_name(self):
        """
        Eddie wants to see Maggie's job applications.
        """
        self.client.force_login(self.eddie_hit_pit)
        job_seekers_ids = [self.maggie.id]
        response = self.client.get(reverse("apply:list_for_siae"), {"job_seekers": job_seekers_ids})

        applications = response.context["job_applications_page"].object_list

        assert len(applications) == 2
        assert applications[0].job_seeker.id in job_seekers_ids

    def test_list_for_siae_filtered_by_many_organization_names(self):
        """
        Eddie wants to see applications sent by Pôle emploi and L'Envol.
        """
        self.client.force_login(self.eddie_hit_pit)
        senders_ids = [self.pole_emploi.id, self.l_envol.id]
        response = self.client.get(
            reverse("apply:list_for_siae"), {"sender_organizations": [self.thibault_pe.id, self.audrey_envol.id]}
        )

        applications = response.context["job_applications_page"].object_list

        assert len(applications) == 9
        assert applications[0].sender_prescriber_organization.id in senders_ids

    def test_list_for_siae_filtered_by_pass_state(self):
        """
        Eddie wants to see applications with a suspended or in progress IAE PASS.
        """
        now = timezone.now()
        yesterday = (now - timezone.timedelta(days=1)).date()
        self.client.force_login(self.eddie_hit_pit)
        states_filter = {"states": [JobApplicationState.ACCEPTED, JobApplicationState.NEW]}

        # Without approval
        response = self.client.get(reverse("apply:list_for_siae"), {**states_filter, "pass_iae_active": True})
        assert len(response.context["job_applications_page"].object_list) == 0

        # With a job_application with an approval
        job_application = JobApplicationFactory(
            with_approval=True,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=yesterday,
            approval__start_at=yesterday,
            to_company=self.hit_pit,
        )
        response = self.client.get(reverse("apply:list_for_siae"), {**states_filter, "pass_iae_active": True})
        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 1
        assert job_application in applications

        # Check that adding pass_iae_suspended does not hide the application
        response = self.client.get(
            reverse("apply:list_for_siae"),
            {
                **states_filter,
                "pass_iae_active": True,
                "pass_iae_suspended": True,
            },
        )
        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 1
        assert job_application in applications

        # But pass_iae_suspended alone does not show the application
        suspended_filter = {**states_filter, "pass_iae_suspended": True}
        response = self.client.get(reverse("apply:list_for_siae"), suspended_filter)
        assert len(response.context["job_applications_page"].object_list) == 0

        # Now with a suspension
        SuspensionFactory(
            approval=job_application.approval,
            start_at=yesterday,
            end_at=now + timezone.timedelta(days=2),
        )
        response = self.client.get(reverse("apply:list_for_siae"), suspended_filter)

        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 1
        assert job_application in applications

        # Check that adding pass_iae_active does not hide the application
        response = self.client.get(reverse("apply:list_for_siae"), {**suspended_filter, "pass_iae_active": True})

        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 1
        assert job_application in applications

    def test_list_for_siae_filtered_by_eligibility_validated(self):
        """
        Eddie wants to see applications of job seeker for whom
        the diagnosis of eligibility has been validated.
        """
        self.client.force_login(self.eddie_hit_pit)
        params = {"eligibility_validated": True}

        response = self.client.get(reverse("apply:list_for_siae"), params)
        assert len(response.context["job_applications_page"].object_list) == 0

        # Authorized prescriber diagnosis
        diagnosis = EligibilityDiagnosisFactory(job_seeker=self.maggie)
        response = self.client.get(reverse("apply:list_for_siae"), params)
        # Maggie has two applications, one created in the state loop and the other created by SentByPrescriberFactory
        assert len(response.context["job_applications_page"].object_list) == 2

        # Make sure the diagnostic expired - it should be ignored
        diagnosis.expires_at = timezone.now() - datetime.timedelta(days=diagnosis.EXPIRATION_DELAY_MONTHS * 31 + 1)
        diagnosis.save(update_fields=("expires_at",))
        response = self.client.get(reverse("apply:list_for_siae"), params)
        assert len(response.context["job_applications_page"].object_list) == 0

        # Diagnosis made by eddie_hit_pit's SIAE
        diagnosis.delete()
        diagnosis = EligibilityDiagnosisMadeBySiaeFactory(job_seeker=self.maggie, author_siae=self.hit_pit)
        response = self.client.get(reverse("apply:list_for_siae"), params)
        # Maggie has two applications, one created in the state loop and the other created by SentByPrescriberFactory
        assert len(response.context["job_applications_page"].object_list) == 2

        # Diagnosis made by an other SIAE - it should be ignored
        diagnosis.delete()
        diagnosis = EligibilityDiagnosisMadeBySiaeFactory(job_seeker=self.maggie)
        response = self.client.get(reverse("apply:list_for_siae"), params)
        assert len(response.context["job_applications_page"].object_list) == 0

        # With a valid approval
        approval = ApprovalFactory(user=self.maggie, with_origin_values=True)  # origin_values needed to delete it
        response = self.client.get(reverse("apply:list_for_siae"), params)
        # Maggie has two applications, one created in the state loop and the other created by SentByPrescriberFactory
        assert len(response.context["job_applications_page"].object_list) == 2

        # With an expired approval
        approval_diagnosis = approval.eligibility_diagnosis
        approval.delete()
        approval_diagnosis.delete()
        approval = ApprovalFactory(expired=True)
        response = self.client.get(reverse("apply:list_for_siae"), params)
        assert len(response.context["job_applications_page"].object_list) == 0

    def test_list_for_siae_filtered_by_administrative_criteria(self):
        """
        Eddie wants to see applications of job seeker for whom
        the diagnosis of eligibility has been validated with specific criteria.
        """
        self.client.force_login(self.eddie_hit_pit)

        diagnosis = EligibilityDiagnosisFactory(job_seeker=self.maggie)

        level1_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_1).first()
        level2_criterion = AdministrativeCriteria.objects.filter(level=AdministrativeCriteriaLevel.LEVEL_2).first()
        level1_other_criterion = AdministrativeCriteria.objects.filter(
            level=AdministrativeCriteriaLevel.LEVEL_1
        ).last()

        diagnosis.administrative_criteria.add(level1_criterion)
        diagnosis.administrative_criteria.add(level2_criterion)
        diagnosis.save()

        # Filter by level1 criterion
        response = self.client.get(reverse("apply:list_for_siae"), {"criteria": [level1_criterion.pk]})
        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 2

        # Filter by level2 criterion
        response = self.client.get(reverse("apply:list_for_siae"), {"criteria": [level2_criterion.pk]})
        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 2

        # Filter by two criteria
        response = self.client.get(
            reverse("apply:list_for_siae"), {"criteria": [level1_criterion.pk, level2_criterion.pk]}
        )
        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 2

        # Filter by other criteria
        response = self.client.get(reverse("apply:list_for_siae"), {"criteria": [level1_other_criterion.pk]})
        applications = response.context["job_applications_page"].object_list
        assert len(applications) == 0

    def test_list_for_siae_filtered_by_jobseeker_department(self):
        """
        Eddie wants to see applications of job seeker who live in given department.
        """
        self.client.force_login(self.eddie_hit_pit)

        # Maggie moves to Department 37
        self.maggie.post_code = "37000"
        self.maggie.save()

        response = self.client.get(reverse("apply:list_for_siae"), {"departments": ["37"]})
        applications = response.context["job_applications_page"].object_list

        # Maggie has two applications and is the only one living in department 37.
        assert len(applications) == 2

    def test_list_for_siae_filtered_by_selected_job(self):
        """
        Eddie wants to see applications with a given job appellation.
        """
        self.client.force_login(self.eddie_hit_pit)

        create_test_romes_and_appellations(["M1805", "N1101"], appellations_per_rome=2)
        (appellation1, appellation2) = Appellation.objects.all().order_by("?")[:2]
        JobApplicationSentByJobSeekerFactory(to_company=self.hit_pit, selected_jobs=[appellation1])
        JobApplicationSentByJobSeekerFactory(to_company=self.hit_pit, selected_jobs=[appellation2])

        response = self.client.get(reverse("apply:list_for_siae"), {"selected_jobs": [appellation1.pk]})
        applications = response.context["job_applications_page"].object_list

        assert len(applications) == 1
        assert appellation1 in [job_desc.appellation for job_desc in applications[0].selected_jobs.all()]


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
        filter_form = parse_response_to_soup(response, "#asideFiltersCollapse")
        # GEIQ and non IAE kind do not have a filter on approval and eligibility.
        # Non IAE kind do not have prior action.
        assert str(filter_form) == snapshot(name=kind_snapshot[kind])


def test_list_for_siae_htmx_filters(client):
    company = CompanyFactory(with_membership=True)
    JobApplicationFactory(to_company=company, state=JobApplicationState.ACCEPTED)
    client.force_login(company.members.get())
    response = client.get(reverse("apply:list_for_siae"))
    page = parse_response_to_soup(response, selector="#main")
    # Check the refused checkbox, that triggers the HTMX request.
    [refused_checkbox] = page.find_all("input", attrs={"name": "states", "value": "refused"})
    refused_checkbox["checked"] = ""
    response = client.get(
        reverse("apply:list_for_siae"),
        {"states": ["refused"]},
        headers={"HX-Request": "true"},
    )
    update_page_with_htmx(page, "#asideFiltersCollapse > form", response)
    response = client.get(reverse("apply:list_for_siae"), {"states": ["refused"]})
    fresh_page = parse_response_to_soup(response, selector="#main")
    assertSoupEqual(page, fresh_page)


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


def test_list_for_siae_exports_download(client):
    job_application = JobApplicationFactory()
    client.force_login(job_application.to_company.members.get())

    # Download all job applications
    response = client.get(reverse("apply:list_for_siae_exports_download"))
    assert 200 == response.status_code
    assert "spreadsheetml" in response.get("Content-Type")


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
