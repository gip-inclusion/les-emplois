from django.utils import timezone

from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlencode

from itou.job_applications.models import JobApplicationWorkflow
from itou.job_applications.factories import JobApplicationSentByPrescriberFactory
from itou.prescribers.factories import (
    PrescriberOrganizationWithMembershipFactory,
    AuthorizedPrescriberOrganizationWithMembershipFactory,
)
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.utils.widgets import DatePickerField
from itou.users.factories import DEFAULT_PASSWORD, PrescriberFactory


class ProcessListTest(TestCase):
    def setUp(self):
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
        pole_emploi = AuthorizedPrescriberOrganizationWithMembershipFactory(
            name="Pôle Emploi"
        )
        laurie_pe = PrescriberFactory(first_name="Laurie")
        thibault_pe = pole_emploi.members.first()
        thibault_pe.save(update_fields={"first_name": "Thibault"})
        pole_emploi.members.add(laurie_pe)

        # L'Envol
        l_envol = PrescriberOrganizationWithMembershipFactory(name="L'Envol")
        manu_envol = PrescriberFactory(first_name="Manu")
        audrey_envol = l_envol.members.first()
        audrey_envol.save(update_fields={"first_name": "Audrey"})
        l_envol.members.add(manu_envol)

        # Hit Pit
        hit_pit = SiaeWithMembershipAndJobsFactory(name="Hit Pit")
        eddie_hit_pit = hit_pit.members.first()
        eddie_hit_pit.first_name = "Eddie"
        eddie_hit_pit.save()

        # Now send applications
        for i, state in enumerate(JobApplicationWorkflow.states):
            creation_date = timezone.now() - timezone.timedelta(days=i)
            job_application = JobApplicationSentByPrescriberFactory(
                to_siae=hit_pit,
                state=state,
                created_at=creation_date,
                sender=thibault_pe,
                sender_prescriber_organization=pole_emploi,
            )

        maggie = job_application.job_seeker
        maggie.save(update_fields={"first_name": "Maggie"})
        JobApplicationSentByPrescriberFactory(
            to_siae=hit_pit,
            sender=laurie_pe,
            sender_prescriber_organization=pole_emploi,
            job_seeker=maggie,
        )

        self.prescriber_base_url = reverse("apply:list_for_prescriber")
        self.job_seeker_base_url = reverse("apply:list_for_job_seeker")
        self.siae_base_url = reverse("apply:list_for_siae")

        # Variables available for unit tests
        self.pole_emploi = pole_emploi
        self.hit_pit = hit_pit
        self.thibault_pe = thibault_pe
        self.laurie_pe = laurie_pe
        self.eddie_hit_pit = eddie_hit_pit
        self.maggie = maggie


####################################################
################### Job Seeker #####################
####################################################


# class ProcessListJobSeekerTest(ProcessListTest):
#     def test_list_for_job_seeker_view(self):
#         """
#         Maggie wants to see job applications sent for her.
#         """
#         self.client.login(username=self.maggie.email, password=DEFAULT_PASSWORD)
#         response = self.client.get(self.job_seeker_base_url)

#         # Count job applications used by the template
#         total_applications = len(response.context["job_applications_page"].object_list)

#         # Result page should contain all SIAE's job applications.
#         self.assertEqual(total_applications, self.maggie.job_applications.count())

#     def test_list_for_job_seeker_view__filtered_by_state(self):
#         """
#         Provide a list of job applications sent by a job seeker
#         and filtered by a state.
#         """
#         self.client.login(username=self.maggie.email, password=DEFAULT_PASSWORD)
#         expected_state = self.maggie.job_applications.last().state
#         query = f"states={expected_state}"
#         url = f"{self.job_seeker_base_url}?{query}"
#         response = self.client.get(url)

#         # Count job applications used by the template
#         applications = response.context["job_applications_page"].object_list

#         # Result page should only contain job applications which status
#         # matches the one selected by the user.
#         self.assertGreater(len(applications), 0)

#         for application in applications:
#             self.assertEqual(application.state, expected_state)


####################################################
##################### SIAE #########################
####################################################


class ProcessListSiaeTest(ProcessListTest):
    def test_list_for_siae_view(self):
        """
        Eddie wants to see a list of job applications sent to his SIAE.
        """
        self.client.login(username=self.eddie_hit_pit.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.siae_base_url)

        total_applications = len(response.context["job_applications_page"].object_list)

        # Result page should contain all SIAE's job applications.
        self.assertEqual(
            total_applications, self.hit_pit.job_applications_received.count()
        )

    def test_list_for_siae_view__filtered_by_one_state(self):
        """
        Eddie wants to see only accepted job applications.
        """
        self.client.login(username=self.eddie_hit_pit.email, password=DEFAULT_PASSWORD)
        state_accepted = JobApplicationWorkflow.STATE_ACCEPTED
        query = f"states={state_accepted}"
        url = f"{self.siae_base_url}?{query}"
        response = self.client.get(url)

        applications = response.context["job_applications_page"].object_list

        self.assertGreater(len(applications), 0)

        for application in applications:
            self.assertEqual(application.state, state_accepted)

    def test_list_for_siae_view__filtered_by_many_states(self):
        """
        Eddie wants to see NEW and PROCESSING job applications.
        """
        self.client.login(username=self.eddie_hit_pit.email, password=DEFAULT_PASSWORD)
        job_applications_states = [
            JobApplicationWorkflow.STATE_NEW,
            JobApplicationWorkflow.STATE_PROCESSING,
        ]
        job_applications_states_str = [
            f"states={state}" for state in job_applications_states
        ]
        job_applications_states_str = "&".join(job_applications_states_str)

        url = f"{self.siae_base_url}?{job_applications_states_str}"
        response = self.client.get(url)

        applications = response.context["job_applications_page"].object_list

        self.assertGreater(len(applications), 0)

        for application in applications:
            self.assertIn(application.state.name, job_applications_states)

    def test_list_for_siae_view__filtered_by_dates(self):
        """
        Eddie wants to see job applications sent at a specific date.
        """
        self.client.login(username=self.eddie_hit_pit.email, password=DEFAULT_PASSWORD)
        date_format = DatePickerField().DATE_FORMAT
        job_applications = self.hit_pit.job_applications_received.order_by("created_at")
        jobs_in_range = job_applications[3:]
        start_date = jobs_in_range[0].created_at

        # Negative indexing is not allowed in querysets
        end_date = jobs_in_range[len(jobs_in_range) - 1].created_at
        query = urlencode(
            {
                "start_date": start_date.strftime(date_format),
                "end_date": end_date.strftime(date_format),
            }
        )
        url = f"{self.siae_base_url}?{query}"
        response = self.client.get(url)
        applications = response.context["job_applications_page"].object_list

        self.assertGreater(len(applications), 0)

        for application in applications:
            self.assertGreaterEqual(application.created_at, start_date)
            self.assertLessEqual(application.created_at, end_date)

    def test_list_for_siae_view__empty_dates_in_params(self):
        """
        Our form uses a Datepicker that adds empty start and end dates
        in the HTTP query if they are not filled in by the user.
        Make sure the template loads all available job applications if fields are empty.
        """
        self.client.login(username=self.eddie_hit_pit.email, password=DEFAULT_PASSWORD)
        url = f"{self.siae_base_url}?start_date=&end_date="
        response = self.client.get(url)
        total_applications = len(response.context["job_applications_page"].object_list)

        self.assertEqual(
            total_applications, self.hit_pit.job_applications_received.count()
        )

    def test_view__filtered_by_sender_organization_name(self):
        """
        Eddie wants to see applications sent by Pôle Emploi.
        """
        self.client.login(username=self.eddie_hit_pit.email, password=DEFAULT_PASSWORD)
        sender_organization = self.pole_emploi
        query = f"sender_organization={sender_organization.id}"
        url = f"{self.siae_base_url}?{query}"
        response = self.client.get(url)

        applications = response.context["job_applications_page"].object_list

        self.assertGreater(len(applications), 0)

        for application in applications:
            self.assertEqual(
                application.sender_prescriber_organization.id, sender_organization.id
            )

    def test_view__filtered_by_sender_name(self):
        """
        Eddie wants to see applications sent by Pôle Emploi.
        """
        self.client.login(username=self.eddie_hit_pit.email, password=DEFAULT_PASSWORD)
        sender = self.thibault_pe
        query = f"sender={sender.id}"
        url = f"{self.siae_base_url}?{query}"
        response = self.client.get(url)

        applications = response.context["job_applications_page"].object_list

        self.assertGreater(len(applications), 0)

        for application in applications:
            self.assertEqual(application.sender.id, sender.id)


# ####################################################
# ################### Prescriber #####################
# ####################################################


# class ProcessListPrescriberTest(ProcessListTest):
#     def test_list_for_prescriber_view(self):
#         """
#         Connect as Thibault to see a list of job applications
#         sent by his organization (Pôle Emploi).
#         """
#         self.client.login(username=self.thibault_pe.email, password=DEFAULT_PASSWORD)
#         response = self.client.get(self.prescriber_base_url)

#         # Count job applications used by the template
#         total_applications = len(response.context["job_applications_page"].object_list)

#         self.assertEqual(
#             total_applications, self.pole_emploi.jobapplication_set.count()
#         )

#     def test_view__filtered_by_state(self):
#         """
#         Thibault wants to filter a list of job applications
#         by the default initial state.
#         """
#         self.client.login(username=self.thibault_pe.email, password=DEFAULT_PASSWORD)
#         expected_state = JobApplicationWorkflow.initial_state
#         query = f"states={expected_state}"
#         url = f"{self.prescriber_base_url}?{query}"
#         response = self.client.get(url)

#         applications = response.context["job_applications_page"].object_list
#         self.assertGreater(len(applications), 0)

#         for application in applications:
#             self.assertEqual(application.state, expected_state)

#     def test_view__filtered_by_sender_first_name(self):
#         """
#         Thibault wants to see job applications sent by his colleague Laurie.
#         He filters results using her first name.
#         """
#         self.client.login(username=self.thibault_pe.email, password=DEFAULT_PASSWORD)
#         expected_name = self.laurie_pe.first_name
#         query = f"sender={expected_name}"
#         url = f"{self.prescriber_base_url}?{query}"
#         response = self.client.get(url)

#         applications = response.context["job_applications_page"].object_list
#         self.assertGreater(len(applications), 0)

#         for application in applications:
#             self.assertEqual(application.sender.first_name, expected_name)

#     def test_view__filtered_by_sender_last_name(self):
#         """
#         Thibault wants to see job applications sent by his colleague Laurie.
#         He filters results using her last name.
#         """
#         self.client.login(username=self.thibault_pe.email, password=DEFAULT_PASSWORD)
#         expected_name = self.laurie_pe.last_name
#         query = f"sender={expected_name}"
#         url = f"{self.prescriber_base_url}?{query}"
#         response = self.client.get(url)

#         applications = response.context["job_applications_page"].object_list
#         self.assertGreater(len(applications), 0)

#         for application in applications:
#             self.assertEqual(application.sender.last_name, expected_name)
