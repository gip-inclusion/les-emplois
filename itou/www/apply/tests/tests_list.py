from django.utils import timezone

from django.test import TestCase
from django.urls import reverse

from itou.job_applications.models import JobApplicationWorkflow
from itou.job_applications.factories import JobApplicationSentByPrescriberFactory
from itou.prescribers.factories import (
    PrescriberOrganizationWithMembershipFactory,
    AuthorizedPrescriberOrganizationWithMembershipFactory
)
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import DEFAULT_PASSWORD, PrescriberFactory


class ProcessListPrescriberTest(TestCase):
    def setUp(self):
        """
        Create three organizations with two members each:
        - pole_emploi: job seekers agency.
        - l_envol: an emergency center for homeless people.
        - hit_pit: a boxing gym looking for boxers.

        Pole Emploi prescribers:
        - Thibault
        - Elsa

        L'envol prescribers:
        - Audrey
        - Manu

        Hit Pit staff:
        - Eddie
        """

        # Pole Emploi
        pole_emploi = AuthorizedPrescriberOrganizationWithMembershipFactory(
            name="Pôle Emploi",
        )
        elsa_pe = PrescriberFactory(
            first_name="Elsa",
        )
        thibault_pe = pole_emploi.members.first()
        thibault_pe.save(update_fields={"first_name": "Thibault"})
        pole_emploi.members.add(elsa_pe)

        # L'Envol
        l_envol = PrescriberOrganizationWithMembershipFactory(
            name="L'Envol",
        )
        manu_envol = PrescriberFactory(
            first_name="Manu",
        )
        audrey_envol = l_envol.members.first()
        audrey_envol.save(update_fields={"first_name": "Audrey"})
        l_envol.members.add(manu_envol)

        # Hit Pit
        hit_pit = SiaeWithMembershipAndJobsFactory(
            name="Hit Pit",
        )
        eddie_hit_pit = hit_pit.members.first()
        eddie_hit_pit.first_name = "Eddie"
        eddie_hit_pit.save()

        # Now send applications
        for i, state in enumerate(JobApplicationWorkflow.states):
            creation_date = timezone.now() - timezone.timedelta(days=i)
            JobApplicationSentByPrescriberFactory(
                to_siae=hit_pit,
                state=state,
                created_at=creation_date,
                sender=thibault_pe,
                sender_prescriber_organization=pole_emploi,
            )
        JobApplicationSentByPrescriberFactory(
            to_siae=hit_pit,
            sender=elsa_pe,
            sender_prescriber_organization=pole_emploi,
        )

        self.prescriber_base_url = reverse("apply:list_for_prescriber")

        # Available for unit tests
        self.pole_emploi = pole_emploi
        self.thibault_pe = thibault_pe
        self.elsa_pe = elsa_pe


    def test_list_for_prescriber_view(self):
        """
        Connect as Thibault to see a list of job applications
        sent by his organization (Pôle Emploi).
        """
        self.client.login(username=self.thibault_pe.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.prescriber_base_url)

        # Count job applications used by the template
        total_applications = len(response.context["job_applications_page"].object_list)

        self.assertEqual(
            total_applications, self.pole_emploi.jobapplication_set.count()
        )

    def test_view__filtered_by_state(self):
        """
        Thibault wants to filter a list of job applications
        by the default initial state.
        """
        self.client.login(username=self.thibault_pe.email, password=DEFAULT_PASSWORD)
        expected_state = JobApplicationWorkflow.initial_state
        query = f"states={expected_state}"
        url = f"{self.prescriber_base_url}?{query}"
        response = self.client.get(url)

        applications = response.context["job_applications_page"].object_list
        self.assertGreater(len(applications), 0)

        for application in applications:
            self.assertEqual(application.state, expected_state)

    def test_view__filtered_by_sender_first_name(self):
        """
        Thibault wants to see job applications sent by his colleague Elsa.
        He filters results using her first name.
        """
        self.client.login(username=self.thibault_pe.email, password=DEFAULT_PASSWORD)

        # He wants to see applications sent by his colleague Elsa.
        expected_name = self.elsa_pe.first_name
        query = f"sender={expected_name}"
        url = f"{self.prescriber_base_url}?{query}"
        response = self.client.get(url)

        applications = response.context["job_applications_page"].object_list
        self.assertGreater(len(applications), 0)

        for application in applications:
            self.assertEqual(application.sender.first_name, expected_name)

    def test_view__filtered_by_sender_last_name(self):
        """
        Thibault wants to see job applications sent by his colleague Elsa.
        He filters results using her last name.
        """
        self.client.login(username=self.thibault_pe.email, password=DEFAULT_PASSWORD)

        # He wants to see applications sent by his colleague Elsa.
        expected_name = self.elsa_pe.last_name
        query = f"sender={expected_name}"
        url = f"{self.prescriber_base_url}?{query}"
        response = self.client.get(url)

        applications = response.context["job_applications_page"].object_list
        self.assertGreater(len(applications), 0)

        for application in applications:
            self.assertEqual(application.sender.last_name, expected_name)
