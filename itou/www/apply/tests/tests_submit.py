from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlencode

from itou.job_applications.models import JobApplication
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory


class ApplyAsJobSeekerTest(TestCase):
    def test_apply(self):
        """Apply as a jobseeker."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = JobSeekerFactory(birthdate=None)
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siret": siae.siret})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        self.assertEqual(session_data["to_siae"], siae.pk)
        self.assertEqual(session_data["to_siae_siret"], siae.siret)

        next_url = reverse("apply:step_sender", kwargs={"siret": siae.siret})
        self.assertEqual(response.url, next_url)

        # Step determine the sender.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        self.assertEqual(session_data["sender"], user.pk)
        self.assertEqual(
            session_data["sender_kind"], JobApplication.SENDER_KIND_JOB_SEEKER
        )
        self.assertEqual(session_data["sender_prescriber_organization"], None)

        next_url = reverse("apply:step_job_seeker", kwargs={"siret": siae.siret})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        self.assertEqual(session_data["job_seeker"], user.pk)

        next_url = reverse("apply:step_application", kwargs={"siret": siae.siret})
        self.assertEqual(response.url, next_url)

        # Step application.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "jobs": [siae.jobs.first().pk],
            "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:list_for_job_seeker")
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(
            job_seeker=user, sender=user, to_siae=siae
        )
        self.assertEqual(
            job_application.sender_kind, JobApplication.SENDER_KIND_JOB_SEEKER
        )
        self.assertEqual(job_application.sender_siae, None)
        self.assertEqual(job_application.sender_prescriber_organization, None)
        self.assertEqual(
            job_application.state, job_application.state.workflow.STATE_NEW
        )
        self.assertEqual(job_application.message, post_data["message"])
        self.assertEqual(job_application.answer, "")
        self.assertEqual(job_application.jobs.count(), 1)
        self.assertEqual(job_application.jobs.first().pk, post_data["jobs"][0])


class ApplyAsPrescriberTest(TestCase):
    def test_apply_as_authorized_prescriber(self):
        """Apply as an authorized prescriber."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(
            is_authorized=True
        )
        user = prescriber_organization.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siret": siae.siret})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        self.assertEqual(session_data["to_siae"], siae.pk)
        self.assertEqual(session_data["to_siae_siret"], siae.siret)

        next_url = reverse("apply:step_sender", kwargs={"siret": siae.siret})
        self.assertEqual(response.url, next_url)

        # Step determine the sender.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        self.assertEqual(session_data["sender"], user.pk)
        self.assertEqual(
            session_data["sender_kind"], JobApplication.SENDER_KIND_PRESCRIBER
        )
        self.assertEqual(
            session_data["sender_prescriber_organization"], prescriber_organization.pk
        )

        next_url = reverse("apply:step_job_seeker", kwargs={"siret": siae.siret})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {"email": "new.job.seeker@test.com"}
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_create_job_seeker", kwargs={"siret": siae.siret})
        args = urlencode({"email": post_data["email"]})
        self.assertEqual(response.url, f"{next_url}?{args}")

        # Step create a job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "email": "new.job.seeker@test.com",
            "first_name": "John",
            "last_name": "Doe",
            "birthdate": "20/12/1978",
            "phone": "0610200305",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        new_job_seeker = get_user_model().objects.get(email=post_data["email"])

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        self.assertEqual(session_data["job_seeker"], new_job_seeker.pk)

        next_url = reverse("apply:step_application", kwargs={"siret": siae.siret})
        self.assertEqual(response.url, next_url)

        # Step application.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "jobs": [siae.jobs.first().pk, siae.jobs.last().pk],
            "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:list_for_prescriber")
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(
            job_seeker=new_job_seeker, sender=user, to_siae=siae
        )
        self.assertEqual(
            job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER
        )
        self.assertEqual(job_application.sender_siae, None)
        self.assertEqual(
            job_application.sender_prescriber_organization, prescriber_organization
        )
        self.assertEqual(
            job_application.state, job_application.state.workflow.STATE_NEW
        )
        self.assertEqual(job_application.message, post_data["message"])
        self.assertEqual(job_application.answer, "")
        self.assertEqual(job_application.jobs.count(), 2)
        self.assertEqual(job_application.jobs.first().pk, post_data["jobs"][0])
        self.assertEqual(job_application.jobs.last().pk, post_data["jobs"][1])
