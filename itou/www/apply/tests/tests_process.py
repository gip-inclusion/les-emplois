import datetime

from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.urls import reverse

from itou.cities.factories import create_test_cities
from itou.cities.models import City
from itou.eligibility.factories import EligibilityDiagnosisFactory
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.job_applications.factories import (
    JobApplicationSentByAuthorizedPrescriberOrganizationFactory,
    JobApplicationSentByJobSeekerFactory,
    JobApplicationWithApprovalFactory,
)
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.models import Siae
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerWithAddressFactory
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm


class ProcessViewsTest(TestCase):
    def test_details_for_siae(self):
        """Display the details of a job application."""

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_process(self):
        """Ensure that the `process` transition is triggered."""

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:process", kwargs={"job_application_id": job_application.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
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

        post_data = {"refusal_reason": job_application.REFUSAL_REASON_OTHER, "answer": ""}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("answer", response.context["form"].errors, "Answer is mandatory with REFUSAL_REASON_OTHER.")

        post_data = {
            "refusal_reason": job_application.REFUSAL_REASON_OTHER,
            "answer": "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
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

        url = reverse("apply:postpone", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {"answer": ""}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        self.assertTrue(job_application.state.is_postponed)

    def test_accept(self):
        """Test the `accept` transition."""
        create_test_cities(["54", "57"], num_per_department=2)
        city = City.objects.first()

        job_seeker = JobSeekerWithAddressFactory(city=city.name)
        address = {
            "address_line_1": job_seeker.address_line_1,
            "post_code": job_seeker.post_code,
            "city_name": city.name,
            "city": city.slug,
        }
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, job_seeker=job_seeker
        )
        self.assertTrue(job_application.state.is_processing)
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:accept", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Wrong dates: force `hiring_start_at` in past.
        hiring_start_at = datetime.date.today() - relativedelta(days=1)
        hiring_end_at = hiring_start_at + relativedelta(years=2)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime("%d/%m/%Y"),
            "hiring_end_at": hiring_end_at.strftime("%d/%m/%Y"),
            "answer": "",
            **address,
        }
        response = self.client.post(url, data=post_data)
        self.assertFormError(response, "form_accept", "hiring_start_at", JobApplication.ERROR_START_IN_PAST)

        # Wrong dates: end < start.
        hiring_start_at = datetime.date.today()
        hiring_end_at = hiring_start_at - relativedelta(days=1)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime("%d/%m/%Y"),
            "hiring_end_at": hiring_end_at.strftime("%d/%m/%Y"),
            "answer": "",
            **address,
        }
        response = self.client.post(url, data=post_data)
        self.assertFormError(response, "form_accept", None, JobApplication.ERROR_END_IS_BEFORE_START)

        # Duration too long.
        hiring_start_at = datetime.date.today()
        hiring_end_at = hiring_start_at + relativedelta(years=2, days=1)
        post_data = {
            "hiring_start_at": hiring_start_at.strftime("%d/%m/%Y"),
            "hiring_end_at": hiring_end_at.strftime("%d/%m/%Y"),
            "answer": "",
            **address,
        }
        response = self.client.post(url, data=post_data)
        self.assertFormError(response, "form_accept", None, JobApplication.ERROR_DURATION_TOO_LONG)

        # Good duration.
        hiring_start_at = datetime.date.today()
        hiring_end_at = hiring_start_at + relativedelta(years=2)
        post_data = {
            # Data for `JobSeekerPoleEmploiStatusForm`.
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            # Data for `AcceptForm`.
            "hiring_start_at": hiring_start_at.strftime("%d/%m/%Y"),
            "hiring_end_at": hiring_end_at.strftime("%d/%m/%Y"),
            "answer": "",
            **address,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertEqual(response.url, next_url)

        job_application = JobApplication.objects.get(pk=job_application.pk)
        self.assertEqual(job_application.hiring_start_at, hiring_start_at)
        self.assertEqual(job_application.hiring_end_at, hiring_end_at)
        self.assertTrue(job_application.state.is_accepted)

        # No address provided
        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        hiring_start_at = datetime.date.today()
        hiring_end_at = hiring_start_at + relativedelta(years=2)
        post_data = {
            # Data for `JobSeekerPoleEmploiStatusForm`.
            "pole_emploi_id": job_application.job_seeker.pole_emploi_id,
            # Data for `AcceptForm`.
            "hiring_start_at": hiring_start_at.strftime("%d/%m/%Y"),
            "hiring_end_at": hiring_end_at.strftime("%d/%m/%Y"),
            "answer": "",
        }
        with self.assertRaises(KeyError):
            response = self.client.post(url, data=post_data)

    def test_eligibility(self):
        """Test eligibility."""

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING
        )
        self.assertTrue(job_application.state.is_processing)
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        has_considered_valid_diagnoses = job_application.job_seeker.eligibility_diagnoses.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        self.assertFalse(has_considered_valid_diagnoses)

        criterion1 = AdministrativeCriteria.objects.level1().get(pk=1)
        criterion2 = AdministrativeCriteria.objects.level2().get(pk=5)
        criterion3 = AdministrativeCriteria.objects.level2().get(pk=15)

        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Ensure that a manual confirmation is mandatory.
        post_data = {"confirm": "false"}
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)

        post_data = {
            # Administrative criteria level 1.
            f"{AdministrativeCriteriaForm.LEVEL_1_PREFIX}{criterion1.pk}": "true",
            # Administrative criteria level 2.
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion2.pk}": "true",
            f"{AdministrativeCriteriaForm.LEVEL_2_PREFIX}{criterion3.pk}": "true",
            # Confirm.
            "confirm": "true",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        next_url = reverse("apply:details_for_siae", kwargs={"job_application_id": job_application.pk})
        self.assertEqual(response.url, next_url)

        has_considered_valid_diagnoses = job_application.job_seeker.eligibility_diagnoses.has_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        self.assertTrue(has_considered_valid_diagnoses)

        # Check diagnosis.
        eligibility_diagnosis = job_application.job_seeker.eligibility_diagnoses.last_considered_valid(
            job_application.job_seeker, for_siae=job_application.to_siae
        )
        self.assertEqual(eligibility_diagnosis.author, siae_user)
        self.assertEqual(eligibility_diagnosis.author_kind, EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF)
        self.assertEqual(eligibility_diagnosis.author_siae, job_application.to_siae)
        # Check administrative criteria.
        administrative_criteria = eligibility_diagnosis.administrative_criteria.all()
        self.assertEqual(3, administrative_criteria.count())
        self.assertIn(criterion1, administrative_criteria)
        self.assertIn(criterion2, administrative_criteria)
        self.assertIn(criterion3, administrative_criteria)

    def test_eligibility_for_siae_not_subject_to_eligibility_rules(self):
        """Test eligibility for an Siae not subject to eligibility rules."""

        job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory(
            state=JobApplicationWorkflow.STATE_PROCESSING, to_siae__kind=Siae.KIND_GEIQ
        )
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)

        url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_eligibility_wrong_state_for_job_application(self):
        """The eligibility diagnosis page must only be accessible
        in `STATE_PROCESSING` and state `STATE_POSTPONED`."""
        for state in [
            JobApplicationWorkflow.STATE_ACCEPTED,
            JobApplicationWorkflow.STATE_REFUSED,
            JobApplicationWorkflow.STATE_CANCELLED,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]:
            job_application = JobApplicationSentByJobSeekerFactory(state=state)
            siae_user = job_application.to_siae.members.first()
            self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)
            url = reverse("apply:eligibility", kwargs={"job_application_id": job_application.pk})
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)
            self.client.logout()

    def test_cancel(self):
        # Hiring date is today: cancellation should be possible.
        job_application = JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)
        url = reverse("apply:cancel", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        job_application.refresh_from_db()
        self.assertTrue(job_application.state.is_cancelled)

    def test_cannot_cancel(self):
        cancellation_period_end = datetime.date.today() - relativedelta(
            days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED
        )
        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            hiring_start_at=(cancellation_period_end - relativedelta(days=1)),
        )
        siae_user = job_application.to_siae.members.first()
        self.client.login(username=siae_user.email, password=DEFAULT_PASSWORD)
        url = reverse("apply:cancel", kwargs={"job_application_id": job_application.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        job_application.refresh_from_db()
        self.assertFalse(job_application.state.is_cancelled)


class ProcessTemplatesTest(TestCase):
    """
    Test actions available in the details template for the different.
    states of a job application.
    """

    @classmethod
    def setUpTestData(cls):
        """Set up data for the whole TestCase."""
        cls.job_application = JobApplicationSentByAuthorizedPrescriberOrganizationFactory()
        cls.siae_user = cls.job_application.to_siae.members.first()

        kwargs = {"job_application_id": cls.job_application.pk}
        cls.url_details = reverse("apply:details_for_siae", kwargs=kwargs)
        cls.url_process = reverse("apply:process", kwargs=kwargs)
        cls.url_eligibility = reverse("apply:eligibility", kwargs=kwargs)
        cls.url_refuse = reverse("apply:refuse", kwargs=kwargs)
        cls.url_postpone = reverse("apply:postpone", kwargs=kwargs)
        cls.url_accept = reverse("apply:accept", kwargs=kwargs)

    def test_details_template_for_state_new(self):
        """Test actions available when the state is new."""
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertContains(response, self.url_process)
        self.assertNotContains(response, self.url_eligibility)
        self.assertNotContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_processing(self):
        """Test actions available when the state is processing."""
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        self.job_application.state = JobApplicationWorkflow.STATE_PROCESSING
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertContains(response, self.url_eligibility)
        self.assertContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_postponed(self):
        """Test actions available when the state is postponed."""
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        self.job_application.state = JobApplicationWorkflow.STATE_POSTPONED
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertContains(response, self.url_eligibility)
        self.assertContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertNotContains(response, self.url_accept)

    def test_details_template_for_state_postponed_valid_diagnosis(self):
        """Test actions available when the state is postponed."""
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        EligibilityDiagnosisFactory(job_seeker=self.job_application.job_seeker)
        self.job_application.state = JobApplicationWorkflow.STATE_POSTPONED
        self.job_application.save()
        response = self.client.get(self.url_details)
        # Test template content.
        self.assertNotContains(response, self.url_process)
        self.assertNotContains(response, self.url_eligibility)
        self.assertContains(response, self.url_refuse)
        self.assertNotContains(response, self.url_postpone)
        self.assertContains(response, self.url_accept)

    def test_details_template_for_other_states(self):
        """Test actions available for other states."""
        self.client.login(username=self.siae_user.email, password=DEFAULT_PASSWORD)
        for state in [
            JobApplicationWorkflow.STATE_ACCEPTED,
            JobApplicationWorkflow.STATE_REFUSED,
            JobApplicationWorkflow.STATE_OBSOLETE,
        ]:
            self.job_application.state = state
            self.job_application.save()
            response = self.client.get(self.url_details)
            # Test template content.
            self.assertNotContains(response, self.url_process)
            self.assertNotContains(response, self.url_eligibility)
            self.assertNotContains(response, self.url_refuse)
            self.assertNotContains(response, self.url_postpone)
            self.assertNotContains(response, self.url_accept)
