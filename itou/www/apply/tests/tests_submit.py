import datetime
from unittest import mock

import pytz
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory
from itou.approvals.models import ApprovalsWrapper, PoleEmploiApproval
from itou.cities.factories import create_test_cities
from itou.cities.models import City
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.models import JobApplication
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeWithMembershipAndJobsFactory, SiaeWithMembershipFactory
from itou.siaes.models import Siae
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, PrescriberFactory
from itou.users.models import User
from itou.utils.storage.s3 import S3Upload


class ApplyAsJobSeekerTest(TestCase):
    @property
    def default_session_data(self):
        return {
            "back_url": None,
            "job_seeker_pk": None,
            "nir": None,
            "to_siae_pk": None,
            "sender_pk": None,
            "sender_kind": None,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }

    def test_apply_as_jobseeker(self):
        """Apply as jobseeker."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = JobSeekerFactory(birthdate=None, nir="")
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = self.default_session_data | {
            "to_siae_pk": siae.pk,
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
        expected_session_data = self.default_session_data | {
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_JOB_SEEKER,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step check job seeker NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}

        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(pk=user.pk)
        self.assertEqual(user.nir, nir)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = self.default_session_data | {
            "job_seeker_pk": user.pk,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_JOB_SEEKER,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step check job seeker info.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {"birthdate": "20/12/1978", "phone": "0610203040", "pole_emploi_id": "1234567A"}

        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(pk=user.pk)
        self.assertEqual(user.birthdate.strftime("%d/%m/%Y"), post_data["birthdate"])
        self.assertEqual(user.phone, post_data["phone"])

        self.assertEqual(user.pole_emploi_id, post_data["pole_emploi_id"])

        next_url = reverse("apply:step_check_prev_applications", kwargs={"siae_pk": siae.pk})
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

        # Test fields mandatory to upload to S3
        s3_upload = S3Upload(kind="resume")
        resume_config = s3_upload.config
        s3_form_endpoint = s3_upload.form_values["url"]

        # Don't test S3 form fields as it led to flaky tests and
        # it's already done by the Boto library.
        self.assertContains(response, s3_form_endpoint)

        # Config variables
        resume_config.pop("upload_expiration")
        for _, value in resume_config.items():
            self.assertContains(response, value)

        post_data = {
            "selected_jobs": [siae.job_description_through.first().pk],
            "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "resume_link": "https://server.com/rocky-balboa.pdf",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_application_sent", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(job_seeker=user, sender=user, to_siae=siae)
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_JOB_SEEKER)
        self.assertEqual(job_application.sender_siae, None)
        self.assertEqual(job_application.sender_prescriber_organization, None)
        self.assertEqual(job_application.state, job_application.state.workflow.STATE_NEW)
        self.assertEqual(job_application.message, post_data["message"])
        self.assertEqual(job_application.answer, "")
        self.assertEqual(job_application.selected_jobs.count(), 1)
        self.assertEqual(job_application.selected_jobs.first().pk, post_data["selected_jobs"][0])
        self.assertEqual(job_application.resume_link, post_data["resume_link"])

    def test_apply_as_job_seeker_temporary_nir(self):
        """
        Full path is tested above. See test_apply_as_job_seeker.
        """
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        user = JobSeekerFactory(nir="")
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 200)
        next_url = reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae.pk})

        # Follow all redirections until NIR.
        # ----------------------------------------------------------------------
        nir = "123456789KLOIU"
        post_data = {"nir": nir}

        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

        # Temporary number should be skipped.
        post_data = {"nir": nir, "skip": 1}
        response = self.client.post(next_url, data=post_data, follow=True)
        last_url = response.redirect_chain[-1][0]
        expected_url = reverse("apply:step_application", kwargs={"siae_pk": siae.pk})
        self.assertEqual(last_url, expected_url)
        self.assertEqual(response.status_code, 200)

        # Step application.
        # ----------------------------------------------------------------------

        response = self.client.get(last_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "selected_jobs": [siae.job_description_through.first().pk],
            "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "resume_link": "https://server.com/rocky-balboa.pdf",
        }
        response = self.client.post(last_url, data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        last_url = response.redirect_chain[-1][0]
        next_url = reverse("apply:step_application_sent", kwargs={"siae_pk": siae.pk})
        self.assertEqual(last_url, next_url)
        user.refresh_from_db()
        self.assertFalse(user.nir)

    def test_apply_as_jobseeker_to_siae_with_approval_in_waiting_period(self):
        """
        Apply as jobseeker to a SIAE (not a GEIQ) with an approval in waiting period.
        Waiting period cannot be bypassed.
        """

        # Avoid COVID lockdown specific cases
        now_date = PoleEmploiApproval.LOCKDOWN_START_AT - relativedelta(months=1)
        now = timezone.datetime(year=now_date.year, month=now_date.month, day=now_date.day, tzinfo=pytz.utc)

        with mock.patch("django.utils.timezone.now", side_effect=lambda: now):
            siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
            user = JobSeekerFactory()
            end_at = now_date - relativedelta(days=30, months=PoleEmploiApproval.SUPPORT_EXTENSION_DELAY_MONTHS)
            start_at = end_at - relativedelta(years=2)
            PoleEmploiApprovalFactory(
                pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate, start_at=start_at, end_at=end_at
            )
            self.client.login(username=user.email, password=DEFAULT_PASSWORD)

            url = reverse("apply:start", kwargs={"siae_pk": siae.pk})

            # Follow all redirections…
            response = self.client.get(url, follow=True)

            # …until the expected 403.
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.context["exception"], ApprovalsWrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_USER)
            last_url = response.redirect_chain[-1][0]
            self.assertEqual(last_url, reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk}))


class ApplyAsAuthorizedPrescriberTest(TestCase):
    def setUp(self):
        create_test_cities(["57"], num_per_department=1)
        self.city = City.objects.first()

    @property
    def default_session_data(self):
        return {
            "back_url": None,
            "job_seeker_pk": None,
            "nir": None,
            "to_siae_pk": None,
            "sender_pk": None,
            "sender_kind": None,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }

    def test_apply_as_authorized_prescriber(self):
        """Apply as authorized prescriber."""

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(is_authorized=True)
        user = prescriber_organization.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = self.default_session_data | {
            "to_siae_pk": siae.pk,
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
        expected_session_data = self.default_session_data | {
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
            "sender_prescriber_organization_pk": prescriber_organization.pk,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = self.default_session_data | {
            "nir": nir,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
            "sender_prescriber_organization_pk": prescriber_organization.pk,
        }

        next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {"email": "new.job.seeker@test.com", "save": "1"}
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
            "address_line_1": "36, rue du 6 Mai 1956",
            "post_code": self.city.post_codes[0],
            "city": self.city.name,
            "city_slug": self.city.slug,
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        new_job_seeker = User.objects.get(email=post_data["email"])

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = self.default_session_data | {
            "job_seeker_pk": new_job_seeker.pk,
            "nir": new_job_seeker.nir,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
            "sender_prescriber_organization_pk": prescriber_organization.pk,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step eligibility.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        self.assertFalse(EligibilityDiagnosis.objects.has_considered_valid(new_job_seeker, for_siae=siae))

        response = self.client.post(next_url)
        self.assertEqual(response.status_code, 302)

        self.assertTrue(EligibilityDiagnosis.objects.has_considered_valid(new_job_seeker, for_siae=siae))

        next_url = reverse("apply:step_application", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step application.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "selected_jobs": [siae.job_description_through.first().pk, siae.job_description_through.last().pk],
            "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "resume_link": "https://server.com/rockie-balboa.pdf",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_application_sent", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(job_seeker=new_job_seeker, sender=user, to_siae=siae)
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER)
        self.assertEqual(job_application.sender_siae, None)
        self.assertEqual(job_application.sender_prescriber_organization, prescriber_organization)
        self.assertEqual(job_application.state, job_application.state.workflow.STATE_NEW)
        self.assertEqual(job_application.message, post_data["message"])
        self.assertEqual(job_application.answer, "")
        self.assertEqual(job_application.selected_jobs.count(), 2)
        self.assertEqual(job_application.selected_jobs.first().pk, post_data["selected_jobs"][0])
        self.assertEqual(job_application.selected_jobs.last().pk, post_data["selected_jobs"][1])
        self.assertEqual(job_application.resume_link, post_data["resume_link"])

    def test_apply_as_authorized_prescriber_to_siae_for_approval_in_waiting_period(self):
        """
        Apply as authorized prescriber to a SIAE for a job seeker with an approval in waiting period.
        Being an authorized prescriber bypasses the waiting period.
        """

        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))

        job_seeker = JobSeekerFactory()

        # Create an approval in waiting period.
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=job_seeker, start_at=start_at, end_at=end_at)

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(is_authorized=True)
        user = prescriber_organization.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})

        # Follow all redirections…
        response = self.client.get(url, follow=True)

        # …until a job seeker has to be determined…
        self.assertEqual(response.status_code, 200)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(last_url, reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae.pk}))

        # …choose one, then follow all redirections…
        post_data = {"nir": job_seeker.nir, "confirm": 1}
        response = self.client.post(last_url, data=post_data, follow=True)

        # …until the eligibility step which should trigger a 200 OK.
        self.assertEqual(response.status_code, 200)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(last_url, reverse("apply:step_eligibility", kwargs={"siae_pk": siae.pk}))

    def test_apply_to_a_geiq_as_authorized_prescriber(self):
        """Apply to a GEIQ as authorized prescriber."""

        siae = SiaeWithMembershipAndJobsFactory(kind=Siae.KIND_GEIQ, romes=("N1101", "N1105"))

        prescriber_organization = PrescriberOrganizationWithMembershipFactory(is_authorized=True)
        user = prescriber_organization.members.first()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)
        job_seeker = JobSeekerFactory()

        # Entry point.
        # ----------------------------------------------------------------------

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = self.default_session_data | {
            "to_siae_pk": siae.pk,
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
        expected_session_data = self.default_session_data | {
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
            "sender_prescriber_organization_pk": prescriber_organization.pk,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {"nir": job_seeker.nir, "confirm": 1}
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step eligibility (not required when applying to a GEIQ).
        # ----------------------------------------------------------------------

        # Follow all redirections…
        response = self.client.post(next_url, follow=True)
        self.assertEqual(response.status_code, 200)

        self.assertFalse(EligibilityDiagnosis.objects.has_considered_valid(job_seeker, for_siae=siae))

        # …until it hits the job application page.
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(last_url, reverse("apply:step_application", kwargs={"siae_pk": siae.pk}))

        # Step application.
        # ----------------------------------------------------------------------

        response = self.client.get(last_url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "selected_jobs": [siae.job_description_through.first().pk, siae.job_description_through.last().pk],
            "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "resume_link": "https://server.com/rockie-balboa.pdf",
        }
        response = self.client.post(last_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_application_sent", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(job_seeker=job_seeker, sender=user, to_siae=siae)
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER)
        self.assertEqual(job_application.sender_siae, None)
        self.assertEqual(job_application.sender_prescriber_organization, prescriber_organization)
        self.assertEqual(job_application.state, job_application.state.workflow.STATE_NEW)
        self.assertEqual(job_application.message, post_data["message"])
        self.assertEqual(job_application.answer, "")
        self.assertEqual(job_application.selected_jobs.count(), 2)
        self.assertEqual(job_application.selected_jobs.first().pk, post_data["selected_jobs"][0])
        self.assertEqual(job_application.selected_jobs.last().pk, post_data["selected_jobs"][1])
        self.assertEqual(job_application.resume_link, post_data["resume_link"])


class ApplyAsPrescriberTest(TestCase):
    def setUp(self):
        create_test_cities(["67"], num_per_department=10)

    @property
    def default_session_data(self):
        return {
            "back_url": None,
            "job_seeker_pk": None,
            "nir": None,
            "to_siae_pk": None,
            "sender_pk": None,
            "sender_kind": None,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }

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
        expected_session_data = self.default_session_data | {
            "to_siae_pk": siae.pk,
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
        expected_session_data = self.default_session_data | {
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = self.default_session_data | {
            "nir": nir,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
        }

        next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {"email": "new.job.seeker@test.com", "save": "1"}
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
            "address_line_1": "55, avenue de la Rose",
            "address_line_2": "7e étage",
            "post_code": "67200",
            "city": "Sommerau (67)",
            "city_slug": "sommerau-67",
        }

        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        new_job_seeker = User.objects.get(email=post_data["email"])

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = self.default_session_data | {
            "job_seeker_pk": new_job_seeker.pk,
            "nir": new_job_seeker.nir,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_PRESCRIBER,
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
            "selected_jobs": [siae.job_description_through.first().pk, siae.job_description_through.last().pk],
            "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "resume_link": "https://server.com/rockie-balboa.pdf",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_application_sent", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(job_seeker=new_job_seeker, sender=user, to_siae=siae)
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_PRESCRIBER)
        self.assertEqual(job_application.sender_siae, None)
        self.assertEqual(job_application.sender_prescriber_organization, None)
        self.assertEqual(job_application.state, job_application.state.workflow.STATE_NEW)
        self.assertEqual(job_application.message, post_data["message"])
        self.assertEqual(job_application.answer, "")
        self.assertEqual(job_application.selected_jobs.count(), 2)
        self.assertEqual(job_application.selected_jobs.first().pk, post_data["selected_jobs"][0])
        self.assertEqual(job_application.selected_jobs.last().pk, post_data["selected_jobs"][1])
        self.assertEqual(job_application.resume_link, post_data["resume_link"])

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
        self.assertEqual(last_url, reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae.pk}))

        # …choose one, then follow all redirections…
        post_data = {"nir": job_seeker.nir, "confirm": 1}
        response = self.client.post(last_url, data=post_data, follow=True)

        # …until the expected 403.
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.context["exception"], ApprovalsWrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(last_url, reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk}))


class ApplyAsPrescriberNirExceptionsTest(TestCase):
    """
    The following normal use cases are tested in tests above:
        - job seeker creation,
        - job seeker found with a unique NIR.
    But, for historical reasons, our database is not perfectly clean.
    Some job seekers share the same NIR as the historical unique key was the e-mail address.
    Or the NIR is not found because their account was created before
    we added this possibility.
    """

    def create_test_data(self):
        siae = SiaeWithMembershipAndJobsFactory(romes=("N1101", "N1105"))
        # Only authorized prescribers can add a NIR.
        # See User.can_add_nir
        prescriber_organization = PrescriberOrganizationWithMembershipFactory(is_authorized=True)
        user = prescriber_organization.members.first()
        return siae, user

    def test_one_account_no_nir(self):
        """
        No account with this NIR is found.
        A search by email is proposed.
        An account is found for this email.
        This NIR account is empty.
        An update is expected.
        """
        job_seeker = JobSeekerFactory(nir="")
        # Create an approval to bypass the eligibility diagnosis step.
        PoleEmploiApprovalFactory(birthdate=job_seeker.birthdate, pole_emploi_id=job_seeker.pole_emploi_id)
        siae, user = self.create_test_data()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:start", kwargs={"siae_pk": siae.pk})

        # Follow all redirections…
        response = self.client.get(url, follow=True)

        # …until a job seeker has to be determined.
        self.assertEqual(response.status_code, 200)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(last_url, reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae.pk}))

        # Enter an a non-existing NIR.
        # ----------------------------------------------------------------------
        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}
        response = self.client.post(last_url, data=post_data)
        next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        self.assertRedirects(response, next_url)

        # Enter an existing email.
        # ----------------------------------------------------------------------
        post_data = {"email": job_seeker.email, "save": "1"}
        response = self.client.post(next_url, data=post_data)
        next_url = reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk})
        self.assertRedirects(response, next_url, target_status_code=302)

        # Follow all redirections until the end.
        # ----------------------------------------------------------------------
        response = self.client.get(next_url, follow=True)
        self.assertTrue(response.status_code, 200)

        next_url = reverse("apply:step_application", kwargs={"siae_pk": siae.pk})
        post_data = {
            "selected_jobs": [siae.job_description_through.first().pk, siae.job_description_through.last().pk],
            "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "resume_link": "https://server.com/rockie-balboa.pdf",
        }
        response = self.client.post(next_url, data=post_data, follow=True)
        expected_url = reverse("apply:step_application_sent", kwargs={"siae_pk": siae.pk})
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(expected_url, last_url)

        # Make sure the job seeker NIR is now filled in.
        # ----------------------------------------------------------------------
        job_seeker.refresh_from_db()
        self.assertEqual(job_seeker.nir, nir)


class ApplyAsSiaeTest(TestCase):
    def setUp(self):
        create_test_cities(["57"], num_per_department=1)
        self.city = City.objects.first()

    @property
    def default_session_data(self):
        return {
            "back_url": None,
            "job_seeker_pk": None,
            "nir": None,
            "to_siae_pk": None,
            "sender_pk": None,
            "sender_kind": None,
            "sender_siae_pk": None,
            "sender_prescriber_organization_pk": None,
            "job_description_id": None,
        }

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
        expected_session_data = self.default_session_data | {
            "to_siae_pk": siae.pk,
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
        expected_session_data = self.default_session_data | {
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_SIAE_STAFF,
            "sender_siae_pk": siae.pk,
        }
        self.assertDictEqual(session_data, expected_session_data)

        next_url = reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step determine the job seeker with a NIR.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        nir = "141068078200557"
        post_data = {"nir": nir, "confirm": 1}
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)
        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = self.default_session_data | {
            "nir": nir,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_SIAE_STAFF,
            "sender_siae_pk": siae.pk,
        }

        next_url = reverse("apply:step_job_seeker", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        # Step get job seeker e-mail.
        # ----------------------------------------------------------------------

        response = self.client.get(next_url)
        self.assertEqual(response.status_code, 200)

        post_data = {"email": "new.job.seeker@test.com", "save": "1"}
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
            "address_line_1": "36, rue du 6 Mai 1956",
            "post_code": self.city.post_codes[0],
            "city": self.city.name,
            "city_slug": self.city.slug,
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        new_job_seeker = User.objects.get(email=post_data["email"])

        session = self.client.session
        session_data = session[settings.ITOU_SESSION_JOB_APPLICATION_KEY]
        expected_session_data = self.default_session_data | {
            "job_seeker_pk": new_job_seeker.pk,
            "nir": new_job_seeker.nir,
            "to_siae_pk": siae.pk,
            "sender_pk": user.pk,
            "sender_kind": JobApplication.SENDER_KIND_SIAE_STAFF,
            "sender_siae_pk": siae.pk,
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
            "selected_jobs": [siae.job_description_through.first().pk, siae.job_description_through.last().pk],
            "message": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "resume_link": "https://server.com/rockie-balboa.pdf",
        }
        response = self.client.post(next_url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:step_application_sent", kwargs={"siae_pk": siae.pk})
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(job_seeker=new_job_seeker, sender=user, to_siae=siae)
        self.assertEqual(job_application.sender_kind, JobApplication.SENDER_KIND_SIAE_STAFF)
        self.assertEqual(job_application.sender_siae, siae)
        self.assertEqual(job_application.sender_prescriber_organization, None)
        self.assertEqual(job_application.state, job_application.state.workflow.STATE_NEW)
        self.assertEqual(job_application.message, post_data["message"])
        self.assertEqual(job_application.answer, "")
        self.assertEqual(job_application.selected_jobs.count(), 2)
        self.assertEqual(job_application.selected_jobs.first().pk, post_data["selected_jobs"][0])
        self.assertEqual(job_application.selected_jobs.last().pk, post_data["selected_jobs"][1])
        self.assertEqual(job_application.resume_link, post_data["resume_link"])

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
        self.assertEqual(last_url, reverse("apply:step_check_job_seeker_nir", kwargs={"siae_pk": siae.pk}))

        # …choose one, then follow all redirections…
        post_data = {
            "nir": job_seeker.nir,
            "confirm": 1,
        }
        response = self.client.post(last_url, data=post_data, follow=True)

        # …until the expected 403.
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.context["exception"], ApprovalsWrapper.ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY)
        last_url = response.redirect_chain[-1][0]
        self.assertEqual(last_url, reverse("apply:step_check_job_seeker_info", kwargs={"siae_pk": siae.pk}))
