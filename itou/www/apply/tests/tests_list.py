from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlencode

from itou.job_applications.factories import (
    JobApplicationFactory,
    SiaeWithMembershipFactory,
)
from itou.job_applications.models import JobApplicationWorkflow
from itou.users.factories import DEFAULT_PASSWORD


class ProcessListTest(TestCase):
    def setUp(self):
        # Create 1 JobApplication per available state and attach it to the same SIAE.
        siae = SiaeWithMembershipFactory()
        for state in JobApplicationWorkflow.states:
            job_application = JobApplicationFactory(
                to_siae=siae,
                state=state,
            )

        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)
        self.base_url = reverse("apply:list_for_siae")


    def test_list_for_siae_view(self):
        """
        Provide a list of job applications sent to a specific SIAE.
        """
        response = self.client.get(self.base_url)

        # Count job applications used by the template
        total_applications = len(response.context['job_applications_page'].object_list)

        # Result page should contain all SIAE's job applications.
        self.assertGreater(total_applications, len(JobApplicationWorkflow.states))


    def test_list_for_siae_view__filtered_by_one_state(self):
        """
        Provide a list of job applications sent to a specific SIAE.
        Results are filtered by a user-selected state.
        """
        query = f"states={JobApplicationWorkflow.initial_state}"
        url = f'{self.base_url}?{query}'
        response = self.client.get(url)

        # Count job applications used by the template
        total_applications = len(response.context['job_applications_page'].object_list)

        # Result page should only contain job applications which status
        # matches the one selected by the user.
        self.assertEqual(total_applications, 1)


    def test_list_for_siae_view__filtered_by_many_states(self):
        """
        Provide a list of job applications sent to a specific SIAE.
        Results are filtered by user-selected states.
        """
        job_application_states = [
            f"states={state.name}" for i, state in enumerate(JobApplicationWorkflow.states)
            if i < 2
        ]
        job_application_states = '&'.join(job_application_states)

        url = f'{self.base_url}?{job_application_states}'
        response = self.client.get(url)

        # Count job applications used by the template
        total_applications = len(response.context['job_applications_page'].object_list)

        # Result page should only contain job applications which status
        # matches the one selected by the user.
        self.assertEqual(total_applications, 2)
