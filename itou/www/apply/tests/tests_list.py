from django.utils import timezone

from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlencode

from itou.job_applications.factories import (
    JobApplicationFactory,
    SiaeWithMembershipFactory,
)
from itou.job_applications.models import JobApplicationWorkflow, JobApplication
from itou.users.factories import DEFAULT_PASSWORD, PrescriberFactory
from itou.job_applications.factories import JobApplicationSentByPrescriberFactory
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.utils.widgets import DatePickerField


class ProcessListJobSeekerAndSIAETest(TestCase):
    def setUp(self):
        # Create 1 JobApplication per available state and attach it to the same SIAE.
        siae = SiaeWithMembershipFactory()
        for i, state in enumerate(JobApplicationWorkflow.states):
            creation_date = timezone.now() - timezone.timedelta(days=i)
            job_application = JobApplicationFactory(
                to_siae=siae, state=state, created_at=creation_date
            )

        # SIAE view
        self.siae_user = job_application.to_siae.members.first()
        self.siae_base_url = reverse("apply:list_for_siae")

        # Candidate view
        self.job_seeker = job_application.job_seeker
        self.job_seeker_base_url = reverse("apply:list_for_job_seeker")

        # Create one more SIAE and one more application
        # so that a job seeker has 2 applications in his dashboard.
        JobApplicationFactory(
            job_seeker=self.job_seeker, to_siae=SiaeWithMembershipFactory()
        )

    def test_list_for_siae_view(self):
        """
        Provide a list of job applications sent to a specific SIAE.
        """
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.siae_base_url)

        # Count job applications used by the template
        total_applications = len(response.context["job_applications_page"].object_list)

        # Result page should contain all SIAE's job applications.
        self.assertEqual(total_applications, len(JobApplicationWorkflow.states))

    def test_list_for_siae_view__filtered_by_one_state(self):
        """
        Provide a list of job applications sent to a specific SIAE.
        Results are filtered by a user-selected state.
        """
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        query = f"states={JobApplicationWorkflow.initial_state}"
        url = f"{self.siae_base_url}?{query}"
        response = self.client.get(url)

        # Count job applications used by the template
        total_applications = len(response.context["job_applications_page"].object_list)

        # Result page should only contain job applications which status
        # matches the one selected by the user.
        self.assertEqual(total_applications, 1)

    def test_list_for_siae_view__filtered_by_many_states(self):
        """
        Provide a list of job applications sent to a specific SIAE.
        Results are filtered by user-selected states.
        """
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        job_application_states = [
            f"states={state.name}"
            for i, state in enumerate(JobApplicationWorkflow.states)
            if i < 2
        ]
        job_application_states = "&".join(job_application_states)

        url = f"{self.siae_base_url}?{job_application_states}"
        response = self.client.get(url)

        total_applications = len(response.context["job_applications_page"].object_list)

        self.assertEqual(total_applications, 2)

    def test_list_for_siae_view__filtered_by_dates(self):
        """
        Provide a list of job applications sent to a specific SIAE.
        Results are filtered by user-selected dates.
        """
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        total_expected = 3
        date_format = DatePickerField().DATE_FORMAT
        job_applications = JobApplication.objects.order_by("created_at")
        jobs_in_range = job_applications[total_expected:]
        start_date = jobs_in_range[0].created_at.strftime(date_format)

        # Negative indexing is not allowed in querysets
        end_date = jobs_in_range[len(jobs_in_range) - 1].created_at.strftime(
            date_format
        )
        query = urlencode({"start_date": start_date, "end_date": end_date})
        url = f"{self.siae_base_url}?{query}"
        response = self.client.get(url)

        # Count job applications used by the template
        total_applications = len(response.context["job_applications_page"].object_list)

        # Result page should only contain job applications which dates
        # match the date range selected by the user.
        self.assertEqual(total_applications, total_expected)

    def test_list_for_siae_view__empty_dates_in_params(self):
        """
        Our form uses a Datepicker that adds empty start and end dates
        in the HTTP query if they are not filled in by the user.
        Make sure the template loads all available job applications if fields are empty.
        """
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        url = f"{self.siae_base_url}?start_date=&end_date="
        response = self.client.get(url)

        # Count job applications used by the template
        total_applications = len(response.context["job_applications_page"].object_list)

        # Result page should only contain job applications which dates
        # match the date range selected by the user.
        self.assertEqual(total_applications, len(JobApplicationWorkflow.states))

    ############################################################
    ################## Job seeker view #########################
    ############################################################
    def test_list_for_job_seeker_view(self):
        """
        Provide a list of job applications sent by a job seeker.
        """
        self.client.login(username=self.job_seeker.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.job_seeker_base_url)

        # Count job applications used by the template
        total_applications = len(response.context["job_applications_page"].object_list)

        # Result page should contain all SIAE's job applications.
        self.assertEqual(total_applications, self.job_seeker.job_applications.count())

    def test_list_for_job_seeker_view__filtered_by_state(self):
        """
        Provide a list of job applications sent by a job seeker
        and filtered by a state.
        """
        self.client.login(username=self.job_seeker.email, password=DEFAULT_PASSWORD)
        query = f"states={JobApplicationWorkflow.initial_state}"
        url = f"{self.job_seeker_base_url}?{query}"
        response = self.client.get(url)

        # Count job applications used by the template
        total_applications = len(response.context["job_applications_page"].object_list)

        # Result page should only contain job applications which status
        # matches the one selected by the user.
        self.assertEqual(total_applications, 1)


class ProcessListPrescriberTest(TestCase):
    def setUp(self):
        siae = SiaeWithMembershipFactory()
        self.prescriber = PrescriberFactory()
        for i, state in enumerate(JobApplicationWorkflow.states):
            creation_date = timezone.now() - timezone.timedelta(days=i)
            JobApplicationSentByPrescriberFactory(
                to_siae=siae,
                state=state,
                created_at=creation_date,
                sender=self.prescriber,
            )
        self.prescriber_base_url = reverse("apply:list_for_prescriber")

        # Apply as another prescriber to be able to filter.
        self.organization = PrescriberOrganizationWithMembershipFactory()
        self.second_prescriber = self.organization.members.first()
        JobApplicationSentByPrescriberFactory(sender=self.prescriber)

    def test_list_for_prescriber_view(self):
        """
        Provide a list of job applications sent by a prescriber.
        """
        self.client.login(username=self.prescriber.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.prescriber_base_url)

        # Count job applications used by the template
        total_applications = len(response.context["job_applications_page"].object_list)

        self.assertEqual(
            total_applications, self.prescriber.job_applications_sent.count()
        )

    def test_view__filtered_by_state(self):
        """
        Provide a list of job applications sent by a prescriber
        and filtered by a state.
        """
        self.client.login(username=self.prescriber.email, password=DEFAULT_PASSWORD)
        expected_state = JobApplicationWorkflow.initial_state
        query = f"states={expected_state}"
        url = f"{self.prescriber_base_url}?{query}"
        response = self.client.get(url)

        applications = response.context["job_applications_page"].object_list
        for application in applications:
            self.assertEqual(application.state, expected_state)

    def test_view__filtered_by_sender_first_name(self):
        """
        Provide a list of job applications sent by a prescriber
        and filtered by a state.
        """
        self.client.login(username=self.prescriber.email, password=DEFAULT_PASSWORD)
        expected_name = self.second_prescriber.first_name
        query = f"sender={expected_name}"
        url = f"{self.prescriber_base_url}?{query}"
        response = self.client.get(url)

        applications = response.context["job_applications_page"].object_list
        for application in applications:
            self.assertEqual(application.sender.first_name, expected_name)

    def test_view__filtered_by_sender_last_name(self):
        """
        Provide a list of job applications sent by a prescriber
        and filtered by a state.
        """
        self.client.login(username=self.prescriber.email, password=DEFAULT_PASSWORD)
        expected_name = self.second_prescriber.last_name
        query = f"sender={expected_name}"
        url = f"{self.prescriber_base_url}?{query}"
        response = self.client.get(url)

        applications = response.context["job_applications_page"].object_list
        for application in applications:
            self.assertEqual(application.sender.first_name, expected_name)

    def test_view__filtered_by_sender_organization_name(self):
        """
        Provide a list of job applications sent by a prescriber
        and filtered by a state.
        """
        self.client.login(
            username=self.second_prescriber.email, password=DEFAULT_PASSWORD
        )
        sender_oragnization_name = self.organization.name
        query = f"sender={sender_oragnization_name}"
        url = f"{self.prescriber_base_url}?{query}"
        response = self.client.get(url)

        # Count job applications used by the template
        applications = response.context["job_applications_page"].object_list

        applications = response.context["job_applications_page"].object_list
        for application in applications:
            self.assertEqual(
                application.sender_prescriber_organization.name,
                sender_oragnization_name,
            )
