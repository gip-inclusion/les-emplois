import datetime

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils.http import urlencode

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from itou.approvals.models import ApprovalsWrapper
from itou.job_applications.models import JobApplication
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import (
    SiaeWithMembershipAndJobsFactory,
    SiaeWithMembershipFactory,
)
from itou.siaes.models import Siae
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, PrescriberFactory


class ApplyAsJobSeekerTest(TestCase):
    def test_apply_as_jobseeker(self):
        """Apply as jobseeker."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = JobSeekerFactory(birthdate=None)
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": None,
            "to_siae_pk": siae.pk,
            "sender_pk": None,
            "sender_kind": None,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_sender", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the sender.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": None,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_JOB_SEEKER,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": user.pk,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_JOB_SEEKER,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse(
            "apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk}
        )
        self.assertEqual(response.url, next_url)

        # Step check job seeker info.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "birthdate": "20/12/1978",
            "phone": "0610203040",
            "pole_emploi_id": "1234567A",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = get_user_model().objects.get(pk=user.pk)
        self.assertEqual(user.birthdate.strftime("%d/%m/%Y"), post_data["birthdate"])
        self.assertEqual(user.phone, post_data["phone"])
        self.assertEqual(user.pole_emploi_id, post_data["pole_emploi_id"])

        next_url = reverse(
            "apply:step_check_prev_applications", kwargs={"siae_pk": siae.pk}
        )
        self.assertEqual(response.url, next_url)

        # Step check previous job applications.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step eligibility.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_application", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step application.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "selected_jobs": [siae.job_description_through.first().pk],
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
        self.assertEqual(job_application.selected_jobs.count(), 1)
        self.assertEqual(
            job_application.selected_jobs.first().pk, post_data["selected_jobs"][0]
        )

    def test_apply_as_jobseeker_with_approval_in_waiting_period(self):
        """Apply as jobseeker with an approval in waiting period."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        user = JobSeekerFactory()
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at,
            end_at=end_at,
        )
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})

        # Follow all redirections…
        response = self.client.get(url, follow=True)

        # …until the expected 403.
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.context["exception"],
            ApprovalsWrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_USER,
        )
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(
            last_url,
            reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk}),
        )


class ApplyAsAuthorizedPrescriberTest(TestCase):
    def test_apply_as_authorized_prescriber(self):
        """Apply as authorized prescriber."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(
            is_authorized=True
        )
        user = prescriber_organization.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": None,
            "to_siae_pk": siae.pk,
            "sender_pk": None,
            "sender_kind": None,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_sender", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the sender.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": None,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": prescriber_organization.pk,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {"email": "new.job.seeker@test.com"}
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_create_job_seeker", kwargs={"siae_pk": siae.pk})
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
            "pole_emploi_id": "12345678",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        new_job_seeker = get_user_model().objects.get(email=post_data["email"])

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": new_job_seeker.pk,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": prescriber_organization.pk,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step eligibility.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        self.assertFalse(new_job_seeker.has_eligibility_diagnosis)

        response = self.client.post(next_url)
        self.assertEqual(response.status_code, 302)

        self.assertTrue(new_job_seeker.has_eligibility_diagnosis)

        next_url = reverse("apply:step_application", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step application.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "selected_jobs": [
                siae.job_description_through.first().pk,
                siae.job_description_through.last().pk,
            ],
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
        self.assertEqual(job_application.selected_jobs.count(), 2)
        self.assertEqual(
            job_application.selected_jobs.first().pk, post_data["selected_jobs"][0]
        )
        self.assertEqual(
            job_application.selected_jobs.last().pk, post_data["selected_jobs"][1]
        )

    def test_apply_as_authorized_prescriber_for_approval_in_waiting_period(self):
        """Apply as authorized prescriber for a job seeker with an approval in waiting period."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        job_seeker = JobSeekerFactory()

        # Create an approval in waiting period.
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=job_seeker, start_at=start_at, end_at=end_at)

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(
            is_authorized=True
        )
        user = prescriber_organization.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})

        # Follow all redirections…
        response = self.client.get(url, follow=True)

        # …until a job seeker has to be determined…
        self.assertEqual(response.status_code, 200)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(
            last_url, reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        )

        # …choose one, then follow all redirections…
        post_data = {"email": job_seeker.email}
        response = self.client.post(last_url, data=post_data, follow=True)

        # …until the eligibility step which should trigger a 200 OK.
        self.assertEqual(response.status_code, 200)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(
            last_url, reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        )

    def test_apply_to_a_geiq_as_authorized_prescriber(self):
        """Apply to a GEIC as authorized prescriber."""

        siae = SiaeWithMembershipAndJobsFactory(
            kind=Siae.KIND_GEIQ, romes=("N1101", "N1105")
        )

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(
            is_authorized=True
        )
        user = prescriber_organization.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": None,
            "to_siae_pk": siae.pk,
            "sender_pk": None,
            "sender_kind": None,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_sender", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the sender.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": None,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": prescriber_organization.pk,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {"email": "new.job.seeker@test.com"}
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_create_job_seeker", kwargs={"siae_pk": siae.pk})
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
            "pole_emploi_id": "12345678",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        new_job_seeker = get_user_model().objects.get(email=post_data["email"])

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": new_job_seeker.pk,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": prescriber_organization.pk,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step eligibility (not required when applying to a GEIQ).
        # ----------------------------------------------------------------------

        response = self.client.post(next_url)
        self.assertEqual(response.status_code, 302)

        self.assertFalse(new_job_seeker.has_eligibility_diagnosis)

        next_url = reverse("apply:step_application", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step application.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "selected_jobs": [
                siae.job_description_through.first().pk,
                siae.job_description_through.last().pk,
            ],
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
        self.assertEqual(job_application.selected_jobs.count(), 2)
        self.assertEqual(
            job_application.selected_jobs.first().pk, post_data["selected_jobs"][0]
        )
        self.assertEqual(
            job_application.selected_jobs.last().pk, post_data["selected_jobs"][1]
        )


class ApplyAsPrescriberTest(TestCase):
    def test_apply_as_prescriber(self):
        """Apply as prescriber."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = PrescriberFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": None,
            "to_siae_pk": siae.pk,
            "sender_pk": None,
            "sender_kind": None,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_sender", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the sender.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": None,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {"email": "new.job.seeker@test.com"}
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_create_job_seeker", kwargs={"siae_pk": siae.pk})
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
            "pole_emploi_id": "12345678",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        new_job_seeker = get_user_model().objects.get(email=post_data["email"])

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": new_job_seeker.pk,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step eligibility.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_application", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step application.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "selected_jobs": [
                siae.job_description_through.first().pk,
                siae.job_description_through.last().pk,
            ],
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
        self.assertEqual(job_application.sender_prescriber_organization, None)
        self.assertEqual(
            job_application.state, job_application.state.workflow.STATE_NEW
        )
        self.assertEqual(job_application.message, post_data["message"])
        self.assertEqual(job_application.answer, "")
        self.assertEqual(job_application.selected_jobs.count(), 2)
        self.assertEqual(
            job_application.selected_jobs.first().pk, post_data["selected_jobs"][0]
        )
        self.assertEqual(
            job_application.selected_jobs.last().pk, post_data["selected_jobs"][1]
        )

    def test_apply_as_prescriber_for_approval_in_waiting_period(self):
        """Apply as prescriber for a job seeker with an approval in waiting period."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        job_seeker = JobSeekerFactory()

        # Create an approval in waiting period.
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=job_seeker, start_at=start_at, end_at=end_at)

        user = PrescriberFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})

        # Follow all redirections…
        response = self.client.get(url, follow=True)

        # …until a job seeker has to be determined…
        self.assertEqual(response.status_code, 200)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(
            last_url, reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        )

        # …choose one, then follow all redirections…
        post_data = {"email": job_seeker.email}
        response = self.client.post(last_url, data=post_data, follow=True)

        # …until the expected 403.
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.context["exception"],
            ApprovalsWrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY,
        )
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(
            last_url,
            reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk}),
        )


class ApplyAsSiaeTest(TestCase):
    def test_perms_for_siae(self):
        """An SIAE can postulate only for itself."""
        siae1 = SiaeWithMembershipFactory()
        siae2 = SiaeWithMembershipFactory()

        user = siae1.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:start", kwargs={"siae_pk": siae2.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_apply_as_siae(self):
        """Apply as SIAE."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": None,
            "to_siae_pk": siae.pk,
            "sender_pk": None,
            "sender_kind": None,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_sender", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the sender.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": None,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_SIAE_STAFF,
            "sender_siae_pk": siae.pk,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {"email": "new.job.seeker@test.com"}
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_create_job_seeker", kwargs={"siae_pk": siae.pk})
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
            "pole_emploi_id": "12345678",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        new_job_seeker = get_user_model().objects.get(email=post_data["email"])

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = {
            "job_seeker_pk": new_job_seeker.pk,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_SIAE_STAFF,
            "sender_siae_pk": siae.pk,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step eligibility.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_application", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step application.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "selected_jobs": [
                siae.job_description_through.first().pk,
                siae.job_description_through.last().pk,
            ],
            "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:list_for_siae")
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(
            job_seeker=new_job_seeker, sender=user, to_siae=siae
        )
        self.assertEqual(
            job_application.sender_kind, JobApplication.SENDER_KIND_SIAE_STAFF
        )
        self.assertEqual(job_application.sender_siae, siae)
        self.assertEqual(job_application.sender_prescriber_organization, None)
        self.assertEqual(
            job_application.state, job_application.state.workflow.STATE_NEW
        )
        self.assertEqual(job_application.message, post_data["message"])
        self.assertEqual(job_application.answer, "")
        self.assertEqual(job_application.selected_jobs.count(), 2)
        self.assertEqual(
            job_application.selected_jobs.first().pk, post_data["selected_jobs"][0]
        )
        self.assertEqual(
            job_application.selected_jobs.last().pk, post_data["selected_jobs"][1]
        )

    def test_apply_as_siae_for_approval_in_waiting_period(self):
        """Apply as SIAE for a job seeker with an approval in waiting period."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        job_seeker = JobSeekerFactory()

        # Create an approval in waiting period.
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=job_seeker, start_at=start_at, end_at=end_at)

        user = siae.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})

        # Follow all redirections…
        response = self.client.get(url, follow=True)

        # …until a job seeker has to be determined…
        self.assertEqual(response.status_code, 200)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(
            last_url, reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        )

        # …choose one, then follow all redirections…
        post_data = {"email": job_seeker.email}
        response = self.client.post(last_url, data=post_data, follow=True)

        # …until the expected 403.
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.context["exception"],
            ApprovalsWrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY,
        )
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(
            last_url,
            reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk}),
        )
