from django.test import TestCase
from django.urls import reverse

from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.users.factories import DEFAULT_PASSWORD
from itou.job_applications.factories import (
    JobApplicationSentByAuthorizedPrescriberOrganizationFactory,
    JobApplicationSentByJobSeekerFactory,
)


class ProcessViewsTest(TestCase):
    def test_details_for_siae(self):
        """Display the details of a job application."""

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.pk}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_process(self):
        """Ensure that the `process` transition is triggered."""

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse(
            "apply:process", kwargs={"job_application_id": job_application.pk}
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.pk}
        )
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        self.assertTrue(job_application.state.is_processing)

    def test_refuse(self):
        """Ensure that the `refuse` transition is triggered."""

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        self.assertTrue(job_application.state.is_processing)
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:refuse", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "refusal_reason": job_application.REFUSAL_REASON_OTHER,
            "answer": "",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "answer",
            response.context["form"].errors,
            "Answer is mandatory with REFUSAL_REASON_OTHER.",
        )

        post_data = {
            "refusal_reason": job_application.REFUSAL_REASON_OTHER,
            "answer": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.pk}
        )
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        self.assertTrue(job_application.state.is_refused)

    def test_postpone(self):
        """Ensure that the `postpone` transition is triggered."""

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        self.assertTrue(job_application.state.is_processing)
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse(
            "apply:postpone", kwargs={"job_application_id": job_application.pk}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Answer is optional.
        post_data = {"answer": ""}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.pk}
        )
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        self.assertTrue(job_application.state.is_postponed)

    def test_accept(self):
        """Ensure that the `accept` transition is triggered."""

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        self.assertTrue(job_application.state.is_processing)
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Answer is optional.
        post_data = {"answer": ""}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.pk}
        )
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        self.assertTrue(job_application.state.is_accepted)

    def test_eligibility(self):
        """Test eligibility."""

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        self.assertTrue(job_application.state.is_processing)
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        self.assertFalse(job_application.job_seeker.has_eligibility_diagnosis)

        url = reverse(
            "apply:eligibility", kwargs={"job_application_id": job_application.pk}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "faire_face_a_des_difficultes_administratives_ou_juridiques": [
                "prendre_en_compte_une_problematique_judiciaire"
            ],
            "criteres_administratifs_de_niveau_1": ["beneficiaire_du_rsa"],
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse(
            "apply:details_for_siae", kwargs={"job_application_id": job_application.pk}
        )
        self.assertEqual(response.url, next_url)

        self.assertTrue(job_application.job_seeker.has_eligibility_diagnosis)

    def test_eligibility_wrong_state_for_job_application(self):
        """The eligibility diagnosis page must only be accessible in `STATE_PROCESSING`."""
        for state in [
            JobApplicationWorkflow.STATE_POSTPONED,
            JobApplicationWorkflow.STATE_ACCEPTED,
            JobApplicationWorkflow.STATE_REFUSED,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]:
            job_application = JobApplicationSentByJobSeekerFactory(state=state)
            siae_user = job_application.to_siae.members.first()
            self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)
            url = reverse(
                "apply:eligibility", kwargs={"job_application_id": job_application.pk}
            )
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)
            self.client.logout()
