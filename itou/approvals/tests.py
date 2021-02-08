import datetime

from dateutil.relativedelta import relativedelta
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory, ProlongationFactory, SuspensionFactory
from itou.approvals.models import Approval, ApprovalsWrapper, PoleEmploiApproval, Prolongation, Suspension
from itou.job_applications.factories import JobApplicationSentByJobSeekerFactory, JobApplicationWithApprovalFactory
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.factories import SiaeFactory
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, UserFactory


class CommonApprovalQuerySetTest(TestCase):
    """
    Test CommonApprovalQuerySet.
    """

    def test_valid_for_pole_emploi_approval_model(self):
        """
        Test for PoleEmploiApproval model.
        """

        start_at = datetime.date.today() - relativedelta(years=1)
        end_at = start_at + relativedelta(years=1)
        PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = datetime.date.today() - relativedelta(years=5)
        end_at = start_at + relativedelta(years=2)
        PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)

        self.assertEqual(2, PoleEmploiApproval.objects.count())
        self.assertEqual(1, PoleEmploiApproval.objects.valid().count())

    def test_valid_for_approval_model(self):
        """
        Test for Approval model.
        """

        start_at = datetime.date.today() - relativedelta(years=1)
        end_at = start_at + relativedelta(years=1)
        ApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = datetime.date.today() - relativedelta(years=5)
        end_at = start_at + relativedelta(years=2)
        ApprovalFactory(start_at=start_at, end_at=end_at)

        self.assertEqual(2, Approval.objects.count())
        self.assertEqual(1, Approval.objects.valid().count())

    def test_valid(self):

        # Start today, end in 2 years.
        start_at = datetime.date.today()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(Approval.objects.filter(id=approval.id).valid().exists())

        # End today.
        end_at = datetime.date.today()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(Approval.objects.filter(id=approval.id).valid().exists())

        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(Approval.objects.filter(id=approval.id).valid().exists())

        # Ended yesterday.
        end_at = datetime.date.today() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(Approval.objects.filter(id=approval.id).valid().exists())

        # In the future.
        start_at = datetime.date.today() + relativedelta(years=2)
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(Approval.objects.filter(id=approval.id).valid().exists())

    def test_can_be_deleted(self):
        job_app = JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        approval = job_app.approval
        self.assertTrue(approval.can_be_deleted)

        # An approval exists without a Job Application
        approval = ApprovalFactory()
        self.assertFalse(approval.can_be_deleted)

        job_app.state = JobApplicationWorkflow.STATE_REFUSED
        job_app.save()
        self.assertFalse(approval.can_be_deleted)

        JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED, job_seeker=job_app.job_seeker, approval=job_app.approval
        )
        self.assertFalse(approval.can_be_deleted)


class CommonApprovalMixinTest(TestCase):
    """
    Test CommonApprovalMixin.
    """

    def test_waiting_period_end(self):
        end_at = datetime.date(2000, 1, 1)
        start_at = datetime.date(1998, 1, 1)
        approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
        expected = datetime.date(2002, 1, 1)
        self.assertEqual(approval.waiting_period_end, expected)

    def test_is_valid(self):

        # End today.
        end_at = datetime.date.today()
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)

        # Ended yesterday.
        end_at = datetime.date.today() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid)

        # Start tomorrow.
        start_at = datetime.date.today() + relativedelta(days=1)
        end_at = start_at + relativedelta(years=2)
        approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)

    def test_is_in_progress(self):
        start_at = datetime.date.today() - relativedelta(days=10)
        approval = ApprovalFactory(start_at=start_at)
        self.assertTrue(approval.is_in_progress)

    def test_waiting_period(self):

        # End is tomorrow.
        end_at = datetime.date.today() + relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)
        self.assertFalse(approval.is_in_waiting_period)

        # End is today.
        end_at = datetime.date.today()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)
        self.assertFalse(approval.is_in_waiting_period)

        # End is yesterday.
        end_at = datetime.date.today() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid)
        self.assertTrue(approval.is_in_waiting_period)

        # Ended since more than WAITING_PERIOD_YEARS.
        end_at = datetime.date.today() - relativedelta(years=Approval.WAITING_PERIOD_YEARS, days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid)
        self.assertFalse(approval.is_in_waiting_period)

    def test_originates_from_itou(self):
        approval = ApprovalFactory(number="999990000001")
        self.assertTrue(approval.originates_from_itou)
        approval = PoleEmploiApprovalFactory(number="625741810182")
        self.assertFalse(approval.originates_from_itou)

    def test_is_pass_iae(self):
        # PoleEmploiApproval.
        user = JobSeekerFactory()
        approval = PoleEmploiApprovalFactory(pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate)
        self.assertFalse(approval.is_pass_iae)
        # Approval.
        approval = ApprovalFactory(user=user)
        self.assertTrue(approval.is_pass_iae)

    def overlaps_covid_lockdown(self):

        # Overlaps: start before lockdown.
        start_at = Approval.LOCKDOWN_START_AT - relativedelta(years=1)
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="625741810181", start_at=start_at, end_at=end_at)
        self.assertTrue(approval.overlaps_covid_lockdown)

        # Overlaps: start same day as lockdown.
        start_at = Approval.LOCKDOWN_START_AT
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="625741810182", start_at=start_at, end_at=end_at)
        self.assertTrue(approval.overlaps_covid_lockdown)

        # Overlaps: start same day as end of lockdown.
        start_at = Approval.LOCKDOWN_END_AT
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="625741810183", start_at=start_at, end_at=end_at)
        self.assertTrue(approval.overlaps_covid_lockdown)

        # Doesn't overlap: end before lockdown.
        end_at = Approval.LOCKDOWN_START_AT - relativedelta(days=1)
        start_at = end_at - relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="625741810184", start_at=start_at, end_at=end_at)
        self.assertFalse(approval.overlaps_covid_lockdown)

        # Doesn't overlap: start after lockdown.
        start_at = Approval.LOCKDOWN_END_AT + relativedelta(days=1)
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="625741810185", start_at=start_at, end_at=end_at)
        self.assertFalse(approval.overlaps_covid_lockdown)


class ApprovalModelTest(TestCase):
    """
    Test Approval model.
    """

    def test_clean(self):
        approval = ApprovalFactory()
        approval.start_at = datetime.date.today()
        approval.end_at = datetime.date.today() - datetime.timedelta(days=365 * 2)
        with self.assertRaises(ValidationError):
            approval.save()

    def test_get_next_number(self):

        PREFIX = Approval.ASP_ITOU_PREFIX

        now = timezone.now().date()
        current_year = now.strftime("%y")

        # No pre-existing objects.
        expected_number = f"{PREFIX}{current_year}00001"
        self.assertEqual(Approval.get_next_number(), expected_number)

        # With pre-existing objects.
        ApprovalFactory(number=f"{PREFIX}{current_year}00038", start_at=now)
        ApprovalFactory(number=f"{PREFIX}{current_year}00039", start_at=now)
        ApprovalFactory(number=f"{PREFIX}{current_year}00040", start_at=now)
        expected_number = f"{PREFIX}{current_year}00041"
        self.assertEqual(Approval.get_next_number(), expected_number)
        Approval.objects.all().delete()

        # Date of hiring in the past.
        hiring_start_at = now - relativedelta(years=3)
        year = hiring_start_at.strftime("%y")
        ApprovalFactory(number=f"{PREFIX}{year}99998", start_at=hiring_start_at)
        expected_number = f"{PREFIX}{year}99999"
        self.assertEqual(Approval.get_next_number(hiring_start_at), expected_number)
        Approval.objects.all().delete()

        # Date of hiring in the future.
        hiring_start_at = now + relativedelta(years=3)
        year = hiring_start_at.strftime("%y")
        ApprovalFactory(number=f"{PREFIX}{year}00020", start_at=hiring_start_at)
        expected_number = f"{PREFIX}{year}00021"
        self.assertEqual(Approval.get_next_number(hiring_start_at), expected_number)
        Approval.objects.all().delete()

        # With pre-existing Pôle emploi approval.
        ApprovalFactory(number="625741810182", start_at=now)
        expected_number = f"{PREFIX}{current_year}00001"
        self.assertEqual(Approval.get_next_number(), expected_number)
        Approval.objects.all().delete()

        # With various pre-existing objects.
        ApprovalFactory(number=f"{PREFIX}{current_year}00222", start_at=now)
        ApprovalFactory(number="625741810182", start_at=now)
        expected_number = f"{PREFIX}{current_year}00223"
        self.assertEqual(Approval.get_next_number(), expected_number)
        Approval.objects.all().delete()

    def test_is_valid(self):

        # Start today, end in 2 years.
        start_at = datetime.date.today()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)

        # End today.
        end_at = datetime.date.today()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid)

        # Ended 1 year ago.
        end_at = datetime.date.today() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid)

        # Ended yesterday.
        end_at = datetime.date.today() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid)

    def test_number_with_spaces(self):

        approval = ApprovalFactory(number="999990000001")
        expected = "99999 00 00001"
        self.assertEqual(approval.number_with_spaces, expected)

    def test_can_be_suspended_by_siae(self):
        job_application = JobApplicationWithApprovalFactory(
            state=JobApplicationWorkflow.STATE_ACCEPTED,
            # Ensure that the job_application cannot be canceled.
            hiring_start_at=datetime.date.today()
            - relativedelta(days=JobApplication.CANCELLATION_DAYS_AFTER_HIRING_STARTED)
            - relativedelta(days=1),
        )
        self.assertFalse(job_application.can_be_cancelled)
        siae = job_application.to_siae
        self.assertTrue(job_application.approval.can_be_suspended_by_siae(siae))
        siae2 = SiaeFactory()
        self.assertFalse(job_application.approval.can_be_suspended_by_siae(siae2))

    def test_get_or_create_from_valid(self):

        # With an existing valid `PoleEmploiApproval`.

        user = JobSeekerFactory()
        valid_pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate, number="625741810182A01"
        )
        approvals_wrapper = ApprovalsWrapper(user)

        approval = Approval.get_or_create_from_valid(approvals_wrapper)

        self.assertTrue(isinstance(approval, Approval))
        self.assertEqual(approval.start_at, valid_pe_approval.start_at)
        self.assertEqual(approval.end_at, valid_pe_approval.end_at)
        self.assertEqual(approval.number, valid_pe_approval.number[:12])
        self.assertEqual(approval.user, user)
        self.assertEqual(approval.created_by, None)

        # With an existing valid `Approval`.

        user = JobSeekerFactory()
        valid_approval = ApprovalFactory(user=user, start_at=datetime.date.today() - relativedelta(days=1))
        approvals_wrapper = ApprovalsWrapper(user)

        approval = Approval.get_or_create_from_valid(approvals_wrapper)
        self.assertTrue(isinstance(approval, Approval))
        self.assertEqual(approval, valid_approval)

    def test_covid_lockdown_extension_for_approval_originally_issued_by_pe(self):

        extension_delta_months = relativedelta(months=Approval.LOCKDOWN_EXTENSION_DELAY_MONTHS)

        # Overlaps: start before lockdown.
        start_at = Approval.LOCKDOWN_START_AT - relativedelta(years=1)
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="625741810181", start_at=start_at, end_at=end_at)
        self.assertEqual(approval.end_at, end_at + extension_delta_months)  # Should be extended.

        # Overlaps: start same day as lockdown.
        start_at = Approval.LOCKDOWN_START_AT
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="625741810182", start_at=start_at, end_at=end_at)
        self.assertEqual(approval.end_at, end_at + extension_delta_months)  # Should be extended.

        # Overlaps: start same day as end of lockdown.
        start_at = Approval.LOCKDOWN_END_AT
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="625741810183", start_at=start_at, end_at=end_at)
        self.assertEqual(approval.end_at, end_at + extension_delta_months)  # Should be extended.

        # Doesn't overlap: end before lockdown.
        end_at = Approval.LOCKDOWN_START_AT - relativedelta(days=1)
        start_at = end_at - relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="625741810184", start_at=start_at, end_at=end_at)
        self.assertEqual(approval.end_at, end_at)  # Should NOT be extended.

        # Doesn't overlap: start after lockdown.
        start_at = Approval.LOCKDOWN_END_AT + relativedelta(days=1)
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="625741810185", start_at=start_at, end_at=end_at)
        self.assertEqual(approval.end_at, end_at)  # Should NOT be extended.

        # An overlapping Itou approval should not be extended.
        start_at = Approval.LOCKDOWN_START_AT
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        approval = ApprovalFactory(number="999990000001", start_at=start_at, end_at=end_at)
        self.assertEqual(approval.end_at, end_at)  # Should NOT extended.


class PoleEmploiApprovalModelTest(TestCase):
    """
    Test PoleEmploiApproval model.
    """

    def test_format_name_as_pole_emploi(self):
        self.assertEqual(PoleEmploiApproval.format_name_as_pole_emploi(" François"), "FRANCOIS")
        self.assertEqual(PoleEmploiApproval.format_name_as_pole_emploi("M'Hammed "), "M'HAMMED")
        self.assertEqual(PoleEmploiApproval.format_name_as_pole_emploi("     jean kevin  "), "JEAN KEVIN")
        self.assertEqual(PoleEmploiApproval.format_name_as_pole_emploi("     Jean-Kevin  "), "JEAN-KEVIN")
        self.assertEqual(PoleEmploiApproval.format_name_as_pole_emploi("Kertész István"), "KERTESZ ISTVAN")
        self.assertEqual(PoleEmploiApproval.format_name_as_pole_emploi("Backer-Grøndahl"), "BACKER-GRONDAHL")
        self.assertEqual(PoleEmploiApproval.format_name_as_pole_emploi("désirée artôt"), "DESIREE ARTOT")
        self.assertEqual(PoleEmploiApproval.format_name_as_pole_emploi("N'Guessan"), "N'GUESSAN")
        self.assertEqual(PoleEmploiApproval.format_name_as_pole_emploi("N Guessan"), "N GUESSAN")

    def test_number_with_spaces(self):

        # 12 chars.
        pole_emploi_approval = PoleEmploiApprovalFactory(number="400121910144")
        expected = "40012 19 10144"
        self.assertEqual(pole_emploi_approval.number_with_spaces, expected)

        # 15 chars.
        pole_emploi_approval = PoleEmploiApprovalFactory(number="010331610106A01")
        expected = "01033 16 10106 A01"
        self.assertEqual(pole_emploi_approval.number_with_spaces, expected)


class PoleEmploiApprovalManagerTest(TestCase):
    """
    Test PoleEmploiApprovalManager.
    """

    def test_find_for(self):

        user = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory(pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate)
        search_results = PoleEmploiApproval.objects.find_for(user)
        self.assertEqual(search_results.count(), 1)
        self.assertEqual(search_results.first(), pe_approval)
        PoleEmploiApproval.objects.all().delete()


class ApprovalsWrapperTest(TestCase):
    """
    Test ApprovalsWrapper.
    """

    def test_merge_approvals_timeline_case1(self):

        user = JobSeekerFactory()

        # Approval.
        approval = ApprovalFactory(user=user, start_at=datetime.date(2016, 12, 20), end_at=datetime.date(2018, 12, 20))

        # PoleEmploiApproval 1.
        pe_approval_1 = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=datetime.date(2018, 12, 20),
            end_at=datetime.date(2020, 12, 20),
        )

        # PoleEmploiApproval 2.
        # Same `start_at` as PoleEmploiApproval 1.
        # But `end_at` earlier than PoleEmploiApproval 1.
        pe_approval_2 = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=datetime.date(2018, 12, 20),
            end_at=datetime.date(2019, 12, 19),
        )

        # Check timeline.
        approvals_wrapper = ApprovalsWrapper(user)
        self.assertEqual(len(approvals_wrapper.merged_approvals), 3)
        self.assertEqual(approvals_wrapper.merged_approvals[0], pe_approval_1)
        self.assertEqual(approvals_wrapper.merged_approvals[1], pe_approval_2)
        self.assertEqual(approvals_wrapper.merged_approvals[2], approval)

    def test_merge_approvals_timeline_case2(self):

        user = JobSeekerFactory()

        # PoleEmploiApproval 1.
        pe_approval_1 = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=datetime.date(2020, 3, 17),
            end_at=datetime.date(2020, 6, 16),
        )

        # PoleEmploiApproval 2.
        # `start_at` earlier than PoleEmploiApproval 1.
        # `end_at` after PoleEmploiApproval 1.
        pe_approval_2 = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=datetime.date(2020, 3, 2),
            end_at=datetime.date(2022, 3, 2),
        )

        # Check timeline.
        approvals_wrapper = ApprovalsWrapper(user)
        self.assertEqual(len(approvals_wrapper.merged_approvals), 2)
        self.assertEqual(approvals_wrapper.merged_approvals[0], pe_approval_2)
        self.assertEqual(approvals_wrapper.merged_approvals[1], pe_approval_1)

    def test_merge_approvals_pass_and_pe_valid(self):
        user = JobSeekerFactory()
        start_at = timezone.now() - relativedelta(months=2)
        end_at = start_at + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)

        # PASS IAE
        pass_iae = ApprovalFactory(
            user=user,
            start_at=start_at,
            end_at=end_at,
        )

        # PoleEmploiApproval
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at,
            end_at=end_at + relativedelta(days=1),
        )

        PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at,
            end_at=end_at + relativedelta(days=2),
        )

        approvals_wrapper = ApprovalsWrapper(user=user)
        self.assertEqual(pass_iae, approvals_wrapper.latest_approval)

    def test_status_without_approval(self):
        user = JobSeekerFactory()
        approvals_wrapper = ApprovalsWrapper(user)
        self.assertEqual(approvals_wrapper.status, ApprovalsWrapper.NONE_FOUND)
        self.assertFalse(approvals_wrapper.has_valid)
        self.assertFalse(approvals_wrapper.has_in_waiting_period)
        self.assertEqual(approvals_wrapper.latest_approval, None)

    def test_status_with_valid_approval(self):
        user = JobSeekerFactory()
        approval = ApprovalFactory(user=user, start_at=datetime.date.today() - relativedelta(days=1))
        approvals_wrapper = ApprovalsWrapper(user)
        self.assertEqual(approvals_wrapper.status, ApprovalsWrapper.VALID)
        self.assertTrue(approvals_wrapper.has_valid)
        self.assertFalse(approvals_wrapper.has_in_waiting_period)
        self.assertEqual(approvals_wrapper.latest_approval, approval)

    def test_status_approval_in_waiting_period(self):
        user = JobSeekerFactory()
        end_at = datetime.date.today() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        approvals_wrapper = ApprovalsWrapper(user)
        self.assertEqual(approvals_wrapper.status, ApprovalsWrapper.IN_WAITING_PERIOD)
        self.assertFalse(approvals_wrapper.has_valid)
        self.assertTrue(approvals_wrapper.has_in_waiting_period)
        self.assertEqual(approvals_wrapper.latest_approval, approval)

    def test_status_approval_with_elapsed_waiting_period(self):
        user = JobSeekerFactory()
        end_at = datetime.date.today() - relativedelta(years=3)
        start_at = end_at - relativedelta(years=2)
        ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        approvals_wrapper = ApprovalsWrapper(user)
        self.assertEqual(approvals_wrapper.status, ApprovalsWrapper.NONE_FOUND)
        self.assertFalse(approvals_wrapper.has_valid)
        self.assertFalse(approvals_wrapper.has_in_waiting_period)
        self.assertEqual(approvals_wrapper.latest_approval, None)

    def test_status_with_valid_pole_emploi_approval(self):
        user = JobSeekerFactory()
        approval = PoleEmploiApprovalFactory(pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate)
        approvals_wrapper = ApprovalsWrapper(user)
        self.assertEqual(approvals_wrapper.status, ApprovalsWrapper.VALID)
        self.assertTrue(approvals_wrapper.has_valid)
        self.assertFalse(approvals_wrapper.has_in_waiting_period)
        self.assertEqual(approvals_wrapper.latest_approval, approval)


class CustomAdminViewsTest(TestCase):
    """
    Test custom admin views.
    """

    def test_manually_add_approval(self):
        user = UserFactory()
        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        # When a Pôle emploi ID has been forgotten, an approval must be delivered
        # with a manual verification.
        job_seeker = JobSeekerFactory(
            pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_FORGOTTEN
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationWorkflow.STATE_PROCESSING,
            approval=None,
            approval_number_sent_by_email=False,
        )
        job_application.accept(user=job_application.to_siae.members.first())

        # Delete emails sent by previous transition.
        mail.outbox = []

        url = reverse("admin:approvals_approval_manually_add_approval", args=[job_application.pk])

        # Not enough perms.
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        user.is_staff = True
        user.save()
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="add_approval")
        user.user_permissions.add(permission)

        # With good perms.
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Create an approval.
        post_data = {
            "start_at": job_application.hiring_start_at.strftime("%d/%m/%Y"),
            "end_at": job_application.hiring_end_at.strftime("%d/%m/%Y"),
            "number": "400121910144",
            "user": job_application.job_seeker.pk,
            "created_by": user.pk,
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 302)

        # An approval should have been created, attached to the job
        # application, and sent by email.
        job_application = JobApplication.objects.get(pk=job_application.pk)
        self.assertTrue(job_application.approval_number_sent_by_email)
        self.assertIsNotNone(job_application.approval_number_sent_at)
        self.assertEqual(job_application.approval_manually_delivered_by, user)
        self.assertEqual(job_application.approval_delivery_mode, job_application.APPROVAL_DELIVERY_MODE_MANUAL)

        approval = job_application.approval
        self.assertEqual(approval.created_by, user)
        self.assertEqual(approval.number, post_data["number"])
        self.assertEqual(approval.user, job_application.job_seeker)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn(approval.number_with_spaces, email.body)


class SuspensionQuerySetTest(TestCase):
    """
    Test SuspensionQuerySet.
    """

    def test_in_progress(self):
        start_at = datetime.date.today()  # Starts today so it's in progress.
        expected_num = 5
        SuspensionFactory.create_batch(expected_num, start_at=start_at)
        self.assertEqual(expected_num, Suspension.objects.in_progress().count())

    def test_not_in_progress(self):
        start_at = datetime.date.today() - relativedelta(years=1)
        end_at = start_at + relativedelta(months=6)
        expected_num = 3
        SuspensionFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        self.assertEqual(expected_num, Suspension.objects.not_in_progress().count())

    def test_old(self):
        # Starting today.
        start_at = datetime.date.today()
        SuspensionFactory.create_batch(2, start_at=start_at)
        self.assertEqual(0, Suspension.objects.old().count())
        # Old.
        start_at = datetime.date.today() - relativedelta(years=1)
        end_at = Suspension.get_max_end_at(start_at)
        expected_num = 3
        SuspensionFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        self.assertEqual(expected_num, Suspension.objects.old().count())


class SuspensionModelTest(TestCase):
    """
    Test Suspension model.
    """

    def test_duration(self):
        expected_duration = datetime.timedelta(days=2)
        start_at = datetime.date.today()
        end_at = start_at + expected_duration
        suspension = SuspensionFactory(start_at=start_at, end_at=end_at)
        self.assertEqual(suspension.duration, expected_duration)

    def test_start_in_future(self):
        start_at = datetime.date.today() + relativedelta(days=10)
        # Build provides a local object without saving it to the database.
        suspension = SuspensionFactory.build(start_at=start_at)
        self.assertTrue(suspension.start_in_future)

    def test_start_in_approval_boundaries(self):
        start_at = datetime.date.today()
        end_at = start_at + relativedelta(days=10)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        # Build provides a local object without saving it to the database.
        suspension = SuspensionFactory.build(approval=approval, start_at=start_at)

        # Equal to lower boundary.
        self.assertTrue(suspension.start_in_approval_boundaries)

        # In boundaries.
        suspension.start_at = approval.start_at + relativedelta(days=5)
        self.assertTrue(suspension.start_in_approval_boundaries)

        # Equal to upper boundary.
        suspension.start_at = approval.end_at
        self.assertTrue(suspension.start_in_approval_boundaries)

        # Before lower boundary.
        suspension.start_at = approval.start_at - relativedelta(days=1)
        self.assertFalse(suspension.start_in_approval_boundaries)

        # After upper boundary.
        suspension.start_at = approval.end_at + relativedelta(days=1)
        self.assertFalse(suspension.start_in_approval_boundaries)

    def test_is_in_progress(self):
        start_at = datetime.date.today() - relativedelta(days=10)
        # Build provides a local object without saving it to the database.
        suspension = SuspensionFactory.build(start_at=start_at)
        self.assertTrue(suspension.is_in_progress)

    def test_get_overlapping_suspensions(self):
        start_at = datetime.date.today() - relativedelta(days=10)
        approval = ApprovalFactory(start_at=start_at)
        suspension1 = SuspensionFactory(approval=approval, start_at=start_at)

        # Start same day as suspension1.
        # Build provides a local object without saving it to the database.
        suspension2 = SuspensionFactory.build(approval=approval, siae=suspension1.siae, start_at=start_at)
        self.assertTrue(suspension2.get_overlapping_suspensions().exists())

        # Start at suspension1.end_at.
        suspension2.start_at = suspension1.end_at
        suspension2.end_at = Suspension.get_max_end_at(suspension2.start_at)
        self.assertTrue(suspension2.get_overlapping_suspensions().exists())

        # Cover suspension1.
        suspension2.start_at = suspension1.start_at - relativedelta(days=1)
        suspension2.end_at = suspension1.end_at + relativedelta(days=1)
        self.assertTrue(suspension2.get_overlapping_suspensions().exists())

        # End before suspension1.
        suspension2.start_at = suspension1.start_at - relativedelta(years=2)
        suspension2.end_at = Suspension.get_max_end_at(suspension2.start_at)
        self.assertFalse(suspension2.get_overlapping_suspensions().exists())

    def test_save(self):
        """
        Test `trigger_update_approval_end_at` with SQL INSERT.
        An approval's `end_at` is automatically pushed forward when it's suspended.
        """
        start_at = datetime.date.today()

        approval = ApprovalFactory(start_at=start_at)
        initial_duration = approval.duration

        suspension = SuspensionFactory(approval=approval, start_at=start_at)

        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration + suspension.duration)

    def test_delete(self):
        """
        Test `trigger_update_approval_end_at` with SQL DELETE.
        An approval's `end_at` is automatically pushed back when it's suspended.
        """
        start_at = datetime.date.today()

        approval = ApprovalFactory(start_at=start_at)
        initial_duration = approval.duration

        suspension = SuspensionFactory(approval=approval, start_at=start_at)
        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration + suspension.duration)

        suspension.delete()

        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration)

    def test_save_and_edit(self):
        """
        Test `trigger_update_approval_end_at` with SQL UPDATE.
        An approval's `end_at` is automatically pushed back and forth when
        one of its suspension is saved, then edited to be shorter.
        """
        start_at = datetime.date.today()

        approval = ApprovalFactory(start_at=start_at)
        initial_duration = approval.duration

        # New suspension.
        suspension = SuspensionFactory(approval=approval, start_at=start_at)
        suspension_duration_1 = suspension.duration
        approval.refresh_from_db()
        approval_duration_2 = approval.duration

        # Edit suspension to be shorter.
        suspension.end_at -= relativedelta(months=2)
        suspension.save()
        suspension_duration_2 = suspension.duration
        approval.refresh_from_db()
        approval_duration_3 = approval.duration

        # Check suspension duration.
        self.assertNotEqual(suspension_duration_1, suspension_duration_2)
        # Check approval duration.
        self.assertNotEqual(initial_duration, approval_duration_2)
        self.assertNotEqual(approval_duration_2, approval_duration_3)
        self.assertEqual(approval_duration_3, initial_duration + suspension_duration_2)


class ProlongationQuerySetTest(TestCase):
    """
    Test ProlongationQuerySet.
    """

    def test_in_progress(self):
        start_at = datetime.date.today()  # Starts today so it's in progress.
        expected_num = 5
        ProlongationFactory.create_batch(expected_num, start_at=start_at)
        self.assertEqual(expected_num, Prolongation.objects.in_progress().count())

    def test_not_in_progress(self):
        start_at = datetime.date.today() - relativedelta(years=1)
        end_at = start_at + relativedelta(months=6)
        expected_num = 3
        ProlongationFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        self.assertEqual(expected_num, Prolongation.objects.not_in_progress().count())


class ProlongationModelTest(TestCase):
    """
    Test Prolongation model.
    """

    def test_get_start_at(self):

        end_at = datetime.date(2021, 2, 1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)

        prolongation_start_at = Prolongation.get_start_at(approval)
        expected_start_at = datetime.date(2021, 2, 2)  # One day after `approval.end_at`.
        self.assertEqual(prolongation_start_at, expected_start_at)

    def test_get_max_end_at(self):

        start_at = datetime.date(2021, 2, 1)

        reason = Prolongation.Reason.COMPLETE_TRAINING.value
        expected_max_end_at = datetime.date(2021, 7, 31)  # 6 months.
        max_end_at = Prolongation.get_max_end_at(start_at, reason=reason)
        self.assertEqual(max_end_at, expected_max_end_at)

        reason = Prolongation.Reason.RQTH.value
        expected_max_end_at = datetime.date(2022, 1, 31)  # 1 year.
        max_end_at = Prolongation.get_max_end_at(start_at, reason=reason)
        self.assertEqual(max_end_at, expected_max_end_at)

        reason = Prolongation.Reason.SENIOR.value
        expected_max_end_at = datetime.date(2022, 1, 31)  # 1 year.
        max_end_at = Prolongation.get_max_end_at(start_at, reason=reason)
        self.assertEqual(max_end_at, expected_max_end_at)

        reason = Prolongation.Reason.PARTICULAR_DIFFICULTIES.value
        expected_max_end_at = datetime.date(2022, 1, 31)  # 1 year.
        max_end_at = Prolongation.get_max_end_at(start_at, reason=reason)
        self.assertEqual(max_end_at, expected_max_end_at)

    def test_save(self):
        """
        Test `trigger_update_approval_end_at_for_prolongation` with SQL INSERT.
        An approval's `end_at` is automatically pushed forward when it's prolongation
        is validated.
        """
        start_at = datetime.date.today()

        approval = ApprovalFactory(start_at=start_at)
        initial_duration = approval.duration

        # When the status is NOT validated, the approval duration stays the same.
        prolongation = ProlongationFactory(approval=approval, start_at=start_at, status=Prolongation.Status.REFUSED)
        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration)

        # When the status is validated, the approval duration is prolongated.
        prolongation.status = Prolongation.Status.VALIDATED
        prolongation.save()
        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration + prolongation.duration)

    def test_delete(self):
        """
        Test `trigger_update_approval_end_at_for_prolongation` with SQL DELETE.
        An approval's `end_at` is automatically pushed back when it's prolongation
        is deleted.
        """
        start_at = datetime.date.today()

        approval = ApprovalFactory(start_at=start_at)
        initial_duration = approval.duration

        # When the status is validated, the approval duration is prolongated.
        prolongation = ProlongationFactory(approval=approval, start_at=start_at, status=Prolongation.Status.VALIDATED)
        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration + prolongation.duration)

        prolongation.delete()

        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration)

        # When the status is not validated, the approval duration stays the same.
        prolongation = ProlongationFactory(approval=approval, start_at=start_at, status=Prolongation.Status.NOT_SET)
        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration)

        prolongation.delete()

        # The approval duration must stay the same.
        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration)

    def test_save_and_edit(self):
        """
        Test `trigger_update_approval_end_at_for_prolongation` with SQL UPDATE.
        An approval's `end_at` is automatically pushed back and forth when
        one of its valid prolongation is saved, then edited to be shorter.
        """
        start_at = datetime.date.today()

        approval = ApprovalFactory(start_at=start_at)
        initial_approval_duration = approval.duration

        # New prolongation. When the status is validated, the approval duration is prolongated.
        prolongation = ProlongationFactory(approval=approval, start_at=start_at, status=Prolongation.Status.VALIDATED)
        prolongation_duration_1 = prolongation.duration
        approval.refresh_from_db()
        approval_duration_2 = approval.duration

        # Edit prolongation to be shorter.
        prolongation.end_at -= relativedelta(months=2)
        prolongation.save()
        prolongation_duration_2 = prolongation.duration
        approval.refresh_from_db()
        approval_duration_3 = approval.duration

        # Prolongation durations must be different.
        self.assertNotEqual(prolongation_duration_1, prolongation_duration_2)

        # Approval durations must be different.
        self.assertNotEqual(initial_approval_duration, approval_duration_2)
        self.assertNotEqual(approval_duration_2, approval_duration_3)

        self.assertEqual(approval_duration_3, initial_approval_duration + prolongation_duration_2)

        # Remove the validated status, the approval duration must be reset.
        prolongation.status = Prolongation.Status.REFUSED
        prolongation.save()
        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_approval_duration)
