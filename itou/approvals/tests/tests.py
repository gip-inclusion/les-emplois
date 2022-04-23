import datetime
import threading
import time
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.template.defaultfilters import title
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from itou.approvals.admin import JobApplicationInline
from itou.approvals.admin_forms import ApprovalAdminForm
from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory, ProlongationFactory, SuspensionFactory
from itou.approvals.models import Approval, ApprovalsWrapper, PoleEmploiApproval, Prolongation, Suspension
from itou.approvals.notifications import NewProlongationToAuthorizedPrescriberNotification
from itou.eligibility.factories import EligibilityDiagnosisFactory, EligibilityDiagnosisMadeBySiaeFactory
from itou.employee_record.factories import EmployeeRecordFactory
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.factories import (
    JobApplicationSentByJobSeekerFactory,
    JobApplicationWithApprovalFactory,
    JobApplicationWithoutApprovalFactory,
)
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.factories import AuthorizedPrescriberOrganizationFactory, PrescriberOrganizationFactory
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
from itou.siaes.models import Siae
from itou.users.factories import DEFAULT_PASSWORD, JobSeekerFactory, UserFactory


class CommonApprovalQuerySetTest(TestCase):
    """
    Test CommonApprovalQuerySet.
    """

    def test_valid_for_pole_emploi_approval_model(self):
        """
        Test for PoleEmploiApproval model.
        """

        start_at = timezone.now().date() - relativedelta(years=1)
        end_at = start_at + relativedelta(years=1)
        PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = timezone.now().date() - relativedelta(years=5)
        end_at = start_at + relativedelta(years=2)
        PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)

        self.assertEqual(2, PoleEmploiApproval.objects.count())
        self.assertEqual(1, PoleEmploiApproval.objects.valid().count())

    def test_valid_for_approval_model(self):
        """
        Test for Approval model.
        """

        start_at = timezone.now().date() - relativedelta(years=1)
        end_at = start_at + relativedelta(years=1)
        ApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = timezone.now().date() - relativedelta(years=5)
        end_at = start_at + relativedelta(years=2)
        ApprovalFactory(start_at=start_at, end_at=end_at)

        self.assertEqual(2, Approval.objects.count())
        self.assertEqual(1, Approval.objects.valid().count())

    def test_valid(self):

        # Start today, end in 2 years.
        start_at = timezone.now().date()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(Approval.objects.filter(id=approval.id).valid().exists())

        # End today.
        end_at = timezone.now().date()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(Approval.objects.filter(id=approval.id).valid().exists())

        # Ended 1 year ago.
        end_at = timezone.now().date() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(Approval.objects.filter(id=approval.id).valid().exists())

        # Ended yesterday.
        end_at = timezone.now().date() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(Approval.objects.filter(id=approval.id).valid().exists())

        # In the future.
        start_at = timezone.now().date() + relativedelta(years=2)
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

    def test_starts_date_filters_for_approval_model(self):
        """
        tests for starts_in_the_past, starts_today and starts_in_the_future
        """
        start_at = timezone.now().date() - relativedelta(years=1)
        end_at = start_at + relativedelta(years=1)
        approval_past = ApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = timezone.now().date()
        end_at = start_at + relativedelta(years=2)
        approval_today = ApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = timezone.now().date() + relativedelta(years=2)
        end_at = start_at + relativedelta(years=2)
        approval_future = ApprovalFactory(start_at=start_at, end_at=end_at)

        self.assertEqual(3, Approval.objects.count())
        self.assertEqual([approval_past], list(Approval.objects.starts_in_the_past()))
        self.assertEqual([approval_today], list(Approval.objects.starts_today()))
        self.assertEqual([approval_future], list(Approval.objects.starts_in_the_future()))


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

    def test_is_in_progress(self):
        start_at = timezone.now().date() - relativedelta(days=10)
        approval = ApprovalFactory(start_at=start_at)
        self.assertTrue(approval.is_in_progress)

    def test_waiting_period(self):

        # End is tomorrow.
        end_at = timezone.now().date() + relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid())
        self.assertFalse(approval.is_in_waiting_period)

        # End is today.
        end_at = timezone.now().date()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid())
        self.assertFalse(approval.is_in_waiting_period)

        # End is yesterday.
        end_at = timezone.now().date() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid())
        self.assertTrue(approval.is_in_waiting_period)

        # Ended since more than WAITING_PERIOD_YEARS.
        end_at = timezone.now().date() - relativedelta(years=Approval.WAITING_PERIOD_YEARS, days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid())
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


class ApprovalModelTest(TestCase):
    def test_clean(self):
        approval = ApprovalFactory()
        approval.start_at = timezone.now().date()
        approval.end_at = timezone.now().date() - datetime.timedelta(days=365 * 2)
        with self.assertRaises(ValidationError):
            approval.save()

    def test_get_next_number(self):

        # No pre-existing objects.
        expected_number = f"{Approval.ASP_ITOU_PREFIX}0000001"
        next_number = Approval.get_next_number()
        self.assertEqual(next_number, expected_number)

        # With pre-existing objects.
        ApprovalFactory(number=f"{Approval.ASP_ITOU_PREFIX}0000040")
        expected_number = f"{Approval.ASP_ITOU_PREFIX}0000041"
        next_number = Approval.get_next_number()
        self.assertEqual(next_number, expected_number)
        Approval.objects.all().delete()

        # With pre-existing Pôle emploi approval.
        ApprovalFactory(number="625741810182")
        expected_number = f"{Approval.ASP_ITOU_PREFIX}0000001"
        next_number = Approval.get_next_number()
        self.assertEqual(next_number, expected_number)
        Approval.objects.all().delete()

        # With various pre-existing objects.
        ApprovalFactory(number=f"{Approval.ASP_ITOU_PREFIX}8888882")
        ApprovalFactory(number="625741810182")
        expected_number = f"{Approval.ASP_ITOU_PREFIX}8888883"
        next_number = Approval.get_next_number()
        self.assertEqual(next_number, expected_number)
        Approval.objects.all().delete()

        demo_prefix = "XXXXX"
        with mock.patch.object(Approval, "ASP_ITOU_PREFIX", demo_prefix):
            ApprovalFactory(number=f"{demo_prefix}0044440")
            expected_number = f"{demo_prefix}0044441"
            next_number = Approval.get_next_number()
            self.assertEqual(next_number, expected_number)
            Approval.objects.all().delete()

        ApprovalFactory(number=f"{Approval.ASP_ITOU_PREFIX}9999999")
        with self.assertRaises(RuntimeError):
            next_number = Approval.get_next_number()
        Approval.objects.all().delete()

    def test_is_valid(self):

        # Start today, end in 2 years.
        start_at = timezone.now().date()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid())

        # End today.
        end_at = timezone.now().date()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid())

        # Ended 1 year ago.
        end_at = timezone.now().date() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid())

        # Ended yesterday.
        end_at = timezone.now().date() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid())

    def test_number_with_spaces(self):

        approval = ApprovalFactory(number="999990000001")
        expected = "99999 00 00001"
        self.assertEqual(approval.number_with_spaces, expected)

    def test_is_last_for_user(self):

        user = JobSeekerFactory()

        # Ended 1 year ago.
        end_at = timezone.now().date() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval1 = ApprovalFactory(start_at=start_at, end_at=end_at, user=user)

        # Start today, end in 2 years.
        start_at = timezone.now().date()
        end_at = start_at + relativedelta(years=2)
        approval2 = ApprovalFactory(start_at=start_at, end_at=end_at, user=user)

        self.assertFalse(approval1.is_last_for_user)
        self.assertTrue(approval2.is_last_for_user)

    def test_is_open_to_prolongation(self):

        today = timezone.now().date()

        # Ensure that "now" is "before" the period open to prolongations.
        end_at = (
            today + relativedelta(months=Approval.IS_OPEN_TO_PROLONGATION_BOUNDARIES_MONTHS) + relativedelta(days=5)
        )
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_open_to_prolongation)

        # Ensure "now" is in the period open to prolongations.
        # Even if the approval ended 1 month ago, users are allowed to prolong it up to 3 months after the end.
        end_at = today - relativedelta(months=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_open_to_prolongation)

        # Ensure "now" is "after" the period open to prolongations.
        end_at = (
            today - relativedelta(months=Approval.IS_OPEN_TO_PROLONGATION_BOUNDARIES_MONTHS) - relativedelta(days=5)
        )
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_open_to_prolongation)

    def test_get_or_create_from_valid(self):

        # With an existing valid `PoleEmploiApproval`.

        user = JobSeekerFactory()
        valid_pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate, number="625741810182"
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
        valid_approval = ApprovalFactory(user=user, start_at=timezone.now().date() - relativedelta(days=1))
        approvals_wrapper = ApprovalsWrapper(user)

        approval = Approval.get_or_create_from_valid(approvals_wrapper)
        self.assertTrue(isinstance(approval, Approval))
        self.assertEqual(approval, valid_approval)

    def test_is_from_ai_stock(self):
        approval_created_at = settings.AI_EMPLOYEES_STOCK_IMPORT_DATE
        developer = UserFactory(email=settings.AI_EMPLOYEES_STOCK_DEVELOPER_EMAIL)

        approval = ApprovalFactory()
        self.assertFalse(approval.is_from_ai_stock)

        approval = ApprovalFactory(created_at=approval_created_at)
        self.assertFalse(approval.is_from_ai_stock)

        approval = ApprovalFactory(created_at=approval_created_at, created_by=developer)
        self.assertTrue(approval.is_from_ai_stock)

    def test_is_open_to_application_process_with_suspension(self):
        today = timezone.now().date()
        approval_start_at = today - relativedelta(months=3)
        reasons_to_not_open_process = [
            reason.value for reason in Suspension.Reason if reason.value not in Suspension.REASONS_TO_UNSUSPEND
        ]

        for reason_to_refuse in reasons_to_not_open_process:
            approval = ApprovalFactory(start_at=approval_start_at)
            suspension = SuspensionFactory(
                approval=approval,
                start_at=today - relativedelta(days=1),
                end_at=today + relativedelta(months=1),
                reason=reason_to_refuse,
            )
            self.assertFalse(approval.can_be_unsuspended)
            suspension.delete()
            approval.delete()

        for reason in Suspension.REASONS_TO_UNSUSPEND:
            approval = ApprovalFactory(start_at=approval_start_at)
            suspension = SuspensionFactory(
                approval=approval,
                start_at=today - relativedelta(days=1),
                end_at=today + relativedelta(months=1),
                reason=reason,
            )

            self.assertTrue(approval.can_be_unsuspended)
            suspension.delete()
            approval.delete()

    def test_can_be_unsuspended_without_suspension(self):
        today = timezone.now().date()
        approval_start_at = today - relativedelta(months=3)
        approval = ApprovalFactory(start_at=approval_start_at)
        self.assertFalse(approval.can_be_unsuspended)

    def test_last_in_progress_suspension(self):
        today = timezone.now().date()
        approval_start_at = today - relativedelta(months=3)
        approval = ApprovalFactory(start_at=approval_start_at)
        SuspensionFactory(
            approval=approval,
            start_at=approval_start_at + relativedelta(months=1),
            end_at=approval_start_at + relativedelta(months=2),
        )
        suspension = SuspensionFactory(
            approval=approval,
            start_at=today - relativedelta(days=1),
            end_at=today + relativedelta(months=2),
            reason=Suspension.Reason.BROKEN_CONTRACT.value,
        )
        self.assertEqual(suspension.pk, approval.last_in_progress_suspension.pk)

    def test_last_in_progress_without_suspension_in_progress(self):
        today = timezone.now().date()
        approval_start_at = today - relativedelta(months=3)
        approval = ApprovalFactory(start_at=approval_start_at)
        SuspensionFactory(
            approval=approval,
            start_at=approval_start_at + relativedelta(months=1),
            end_at=approval_start_at + relativedelta(months=2),
        )
        self.assertIsNone(approval.last_in_progress_suspension)

    def test_unsuspend(self):
        today = timezone.now().date()
        approval_start_at = today - relativedelta(months=3)
        approval = ApprovalFactory(start_at=approval_start_at)
        suspension = SuspensionFactory(
            approval=approval,
            start_at=approval_start_at + relativedelta(months=1),
            end_at=today + relativedelta(months=2),
            reason=Suspension.Reason.BROKEN_CONTRACT.value,
        )
        approval.unsuspend(hiring_start_at=today)
        suspension.refresh_from_db()
        self.assertEqual(suspension.end_at, today - relativedelta(days=1))

    def test_unsuspend_invalid(self):
        today = timezone.now().date()
        approval_start_at = today - relativedelta(months=3)
        approval = ApprovalFactory(start_at=approval_start_at)
        suspension_end_at = today + relativedelta(months=2)
        suspension = SuspensionFactory(
            approval=approval,
            start_at=approval_start_at + relativedelta(months=1),
            end_at=suspension_end_at,
            reason=Suspension.Reason.SUSPENDED_CONTRACT.value,
        )
        approval.unsuspend(hiring_start_at=today)
        suspension.refresh_from_db()
        self.assertEqual(suspension.end_at, suspension_end_at)


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
        pole_emploi_approval = PoleEmploiApprovalFactory(number="400121910144")
        expected = "40012 19 10144"
        self.assertEqual(pole_emploi_approval.number_with_spaces, expected)

    def test_is_valid(self):
        now_date = timezone.now().date() - relativedelta(months=1)
        now = datetime.datetime(year=now_date.year, month=now_date.month, day=now_date.day)

        with mock.patch("django.utils.timezone.now", side_effect=lambda: now):
            # Ends today.
            end_at = now_date
            start_at = end_at - relativedelta(years=2)
            approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
            self.assertTrue(approval.is_valid())

            # Ended yesterday.
            end_at = now_date - relativedelta(days=1)
            start_at = end_at - relativedelta(years=2)
            approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
            self.assertFalse(approval.is_valid())

            # Starts tomorrow.
            start_at = now_date + relativedelta(days=1)
            end_at = start_at + relativedelta(years=2)
            approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
            self.assertTrue(approval.is_valid())


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

    def get_approval_wrapper_in_waiting_period(self):
        """
        Helper method used by several tests below.
        """
        user = JobSeekerFactory()
        end_at = timezone.now().date() - relativedelta(days=30)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(user=user, start_at=start_at, end_at=end_at)
        approvals_wrapper = ApprovalsWrapper(user)
        self.assertTrue(approvals_wrapper.has_in_waiting_period)
        self.assertEqual(approvals_wrapper.latest_approval, approval)
        return approvals_wrapper

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

    def test_merge_approvals_discard_pe_approval_in_future(self):
        """
        We filter out the pole emploi approval with a starting date in the future
        """
        user = JobSeekerFactory()

        start_at_in_the_future = timezone.now() + relativedelta(months=2)
        end_at = start_at_in_the_future + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS)
        # PoleEmploiApproval 1.
        # It should be discarded since its starts in the future
        PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at_in_the_future,
            end_at=end_at,
        )

        # PoleEmploiApproval 2.
        start_at_in_the_past = timezone.now() - relativedelta(months=2)
        pe_approval_2 = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=start_at_in_the_past,
            end_at=start_at_in_the_past + relativedelta(years=Approval.DEFAULT_APPROVAL_YEARS),
        )

        # Check that only one approval is taken into account
        approvals_wrapper = ApprovalsWrapper(user)
        self.assertEqual(len(approvals_wrapper.merged_approvals), 1)
        self.assertEqual(approvals_wrapper.merged_approvals[0], pe_approval_2)

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
        approval = ApprovalFactory(user=user, start_at=timezone.now().date() - relativedelta(days=1))
        approvals_wrapper = ApprovalsWrapper(user)
        self.assertEqual(approvals_wrapper.status, ApprovalsWrapper.VALID)
        self.assertTrue(approvals_wrapper.has_valid)
        self.assertFalse(approvals_wrapper.has_in_waiting_period)
        self.assertEqual(approvals_wrapper.latest_approval, approval)

    def test_status_approval_in_waiting_period(self):
        approvals_wrapper = self.get_approval_wrapper_in_waiting_period()
        self.assertEqual(approvals_wrapper.status, ApprovalsWrapper.IN_WAITING_PERIOD)
        self.assertFalse(approvals_wrapper.has_valid)

    def test_status_approval_with_elapsed_waiting_period(self):
        user = JobSeekerFactory()
        end_at = timezone.now().date() - relativedelta(years=3)
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

    def test_cannot_bypass_waiting_period(self):
        approvals_wrapper = self.get_approval_wrapper_in_waiting_period()

        # Waiting period cannot be bypassed for SIAE if no prescriber.
        self.assertTrue(
            approvals_wrapper.cannot_bypass_waiting_period(
                siae=SiaeFactory(kind=Siae.KIND_ETTI), sender_prescriber_organization=None
            )
        )

        # Waiting period cannot be bypassed for SIAE if unauthorized prescriber.
        self.assertTrue(
            approvals_wrapper.cannot_bypass_waiting_period(
                siae=SiaeFactory(kind=Siae.KIND_ETTI), sender_prescriber_organization=PrescriberOrganizationFactory()
            )
        )

        # Waiting period is bypassed for SIAE if authorized prescriber.
        self.assertFalse(
            approvals_wrapper.cannot_bypass_waiting_period(
                siae=SiaeFactory(kind=Siae.KIND_ETTI),
                sender_prescriber_organization=AuthorizedPrescriberOrganizationFactory(),
            )
        )

        # Waiting period is bypassed for GEIQ even if no prescriber.
        self.assertFalse(
            approvals_wrapper.cannot_bypass_waiting_period(
                siae=SiaeFactory(kind=Siae.KIND_GEIQ), sender_prescriber_organization=None
            )
        )

        # Waiting period is bypassed for GEIQ even if unauthorized prescriber.
        self.assertFalse(
            approvals_wrapper.cannot_bypass_waiting_period(
                siae=SiaeFactory(kind=Siae.KIND_GEIQ), sender_prescriber_organization=PrescriberOrganizationFactory()
            )
        )

        # Waiting period is bypassed if a valid diagnosis made by an authorized prescriber exists.
        diag = EligibilityDiagnosisFactory(job_seeker=approvals_wrapper.user)
        self.assertFalse(
            approvals_wrapper.cannot_bypass_waiting_period(
                siae=SiaeFactory(kind=Siae.KIND_ETTI),
                sender_prescriber_organization=None,
            )
        )
        diag.delete()

        # Waiting period cannot be bypassed if a valid diagnosis exists
        # but was not made by an authorized prescriber.
        diag = EligibilityDiagnosisMadeBySiaeFactory(job_seeker=approvals_wrapper.user)
        self.assertTrue(
            approvals_wrapper.cannot_bypass_waiting_period(
                siae=SiaeFactory(kind=Siae.KIND_ETTI),
                sender_prescriber_organization=None,
            )
        )
        diag.delete()


class AutomaticApprovalAdminViewsTest(TestCase):
    """
    Test Approval automatic admin views.
    """

    def test_edit_approval_with_a_wrong_number(self):
        """
        Given an existing approval, when setting a different number,
        then the save is rejected.
        """
        user = UserFactory()
        user.is_staff = True
        user.save()
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="change_approval")
        user.user_permissions.add(permission)

        self.client.login(username=user.email, password=DEFAULT_PASSWORD)

        job_app = JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        approval = job_app.approval

        url = reverse("admin:approvals_approval_change", args=[approval.pk])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "start_at": approval.start_at.strftime("%d/%m/%Y"),
            "end_at": approval.end_at.strftime("%d/%m/%Y"),
            "user": job_app.job_seeker.pk,
            "number": "999991234567",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response, "adminform", "number", [ApprovalAdminForm.ERROR_NUMBER_CANNOT_BE_CHANGED % approval.number]
        )


class CustomApprovalAdminViewsTest(TestCase):
    """
    Test Approval custom admin views.
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

        # Les numéros avec le préfixe `ASP_ITOU_PREFIX` ne doivent pas pouvoir
        # être délivrés à la main dans l'admin.
        post_data = {
            "start_at": job_application.hiring_start_at.strftime("%d/%m/%Y"),
            "end_at": job_application.hiring_end_at.strftime("%d/%m/%Y"),
            "user": job_application.job_seeker.pk,
            "created_by": user.pk,
            "number": f"{Approval.ASP_ITOU_PREFIX}1234567",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("number", response.context["form"].errors, ApprovalAdminForm.ERROR_NUMBER)

        # Create an approval.
        post_data = {
            "start_at": job_application.hiring_start_at.strftime("%d/%m/%Y"),
            "end_at": job_application.hiring_end_at.strftime("%d/%m/%Y"),
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
        self.assertEqual(approval.user, job_application.job_seeker)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn(approval.number_with_spaces, email.body)

    def test_employee_record_status(self):
        # test employee record exists
        job_application = JobApplicationWithApprovalFactory()
        EmployeeRecordFactory(job_application=job_application)
        employee_record_id = EmployeeRecord.objects.get(job_application_id=job_application.id).id
        msg = JobApplicationInline.employee_record_status(self, job_application)
        self.assertIn(f"<a href='/admin/employee_record/employeerecord/{employee_record_id}/change/'>", msg)

        # test employee record creation is pending
        today = datetime.date.today()
        for siae_kind in Siae.ASP_EMPLOYEE_RECORD_KINDS:
            eligible_siae = SiaeFactory(kind=siae_kind)
            job_application = JobApplicationWithApprovalFactory(to_siae=eligible_siae, hiring_start_at=today)
            self.assertIn(
                "Fiche salarié en attente de creation",
                JobApplicationInline.employee_record_status(self, job_application),
            )

        # test no employee record for this application
        ## cannot have employee record
        job_application = JobApplicationWithoutApprovalFactory()
        self.assertIn(
            "Pas de fiche salarié crée pour cette candidature",
            JobApplicationInline.employee_record_status(self, job_application),
        )

        ## can_use_employee_record
        for siae_kind in [
            siae_kind for siae_kind, _ in Siae.KIND_CHOICES if siae_kind not in Siae.ASP_EMPLOYEE_RECORD_KINDS
        ]:
            not_eligible_siae = SiaeFactory(kind=siae_kind)
            job_application = JobApplicationWithApprovalFactory(to_siae=not_eligible_siae)
            self.assertIn(
                "Pas de fiche salarié crée pour cette candidature",
                JobApplicationInline.employee_record_status(self, job_application),
            )


class SuspensionQuerySetTest(TestCase):
    """
    Test SuspensionQuerySet.
    """

    def test_in_progress(self):
        start_at = timezone.now().date()  # Starts today so it's in progress.
        expected_num = 5
        SuspensionFactory.create_batch(expected_num, start_at=start_at)
        self.assertEqual(expected_num, Suspension.objects.in_progress().count())

    def test_not_in_progress(self):
        start_at = timezone.now().date() - relativedelta(years=1)
        end_at = start_at + relativedelta(months=6)
        expected_num = 3
        SuspensionFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        self.assertEqual(expected_num, Suspension.objects.not_in_progress().count())

    def test_old(self):
        # Starting today.
        start_at = timezone.now().date()
        SuspensionFactory.create_batch(2, start_at=start_at)
        self.assertEqual(0, Suspension.objects.old().count())
        # Old.
        start_at = timezone.now().date() - relativedelta(years=1)
        end_at = Suspension.get_max_end_at(start_at)
        expected_num = 3
        SuspensionFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        self.assertEqual(expected_num, Suspension.objects.old().count())


class SuspensionModelTest(TestCase):
    """
    Test Suspension model.
    """

    def test_clean(self):
        today = timezone.now().date()
        start_at = today - relativedelta(days=Suspension.MAX_RETROACTIVITY_DURATION_DAYS * 2)
        end_at = start_at + relativedelta(months=2)
        approval = ApprovalFactory.build(start_at=start_at, end_at=end_at)

        # Suspension.start_date is too old.
        suspension = SuspensionFactory.build(approval=approval)
        suspension.start_at = start_at - relativedelta(days=Suspension.MAX_RETROACTIVITY_DURATION_DAYS + 1)
        with self.assertRaises(ValidationError):
            suspension.clean()

        # suspension.end_at < suspension.start_at
        suspension = SuspensionFactory.build(approval=approval)
        suspension.start_at = start_at
        suspension.end_at = start_at - relativedelta(months=1)
        with self.assertRaises(ValidationError):
            suspension.clean()

        # Suspension.start_at is in the future.
        suspension = SuspensionFactory.build(approval=approval)
        suspension.start_at = today + relativedelta(days=2)
        suspension.end_at = end_at
        with self.assertRaises(ValidationError):
            suspension.clean()

    def test_duration(self):
        expected_duration = datetime.timedelta(days=2)
        start_at = timezone.now().date()
        end_at = start_at + expected_duration
        suspension = SuspensionFactory(start_at=start_at, end_at=end_at)
        self.assertEqual(suspension.duration, expected_duration)

    def test_start_in_future(self):
        start_at = timezone.now().date() + relativedelta(days=10)
        # Build provides a local object without saving it to the database.
        suspension = SuspensionFactory.build(start_at=start_at)
        self.assertTrue(suspension.start_in_future)

    def test_start_in_approval_boundaries(self):
        start_at = timezone.now().date()
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
        start_at = timezone.now().date() - relativedelta(days=10)
        # Build provides a local object without saving it to the database.
        suspension = SuspensionFactory.build(start_at=start_at)
        self.assertTrue(suspension.is_in_progress)

    def test_get_overlapping_suspensions(self):
        start_at = timezone.now().date() - relativedelta(days=10)
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

    def test_displayed_choices_for_siae(self):
        # EI and ACI kind have one more choice
        for kind in [Siae.KIND_EI, Siae.KIND_ACI]:
            siae = SiaeFactory(kind=kind)
            result = Suspension.Reason.displayed_choices_for_siae(siae)
            self.assertEqual(len(result), 5)
            self.assertEqual(result[-1][0], Suspension.Reason.CONTRAT_PASSERELLE.value)

        # Some other cases
        for kind in [Siae.KIND_ETTI, Siae.KIND_AI]:
            siae = SiaeFactory(kind=kind)
            result = Suspension.Reason.displayed_choices_for_siae(siae)
            self.assertEqual(len(result), 4)

    def test_next_min_start_date(self):
        today = timezone.localdate()
        start_at = today - relativedelta(days=10)

        job_application_1 = JobApplicationWithApprovalFactory(hiring_start_at=today)
        job_application_2 = JobApplicationWithApprovalFactory(hiring_start_at=start_at)
        job_application_3 = JobApplicationWithApprovalFactory(hiring_start_at=start_at, created_from_pe_approval=True)
        job_application_4 = JobApplicationWithApprovalFactory(hiring_start_at=None, created_from_pe_approval=True)

        # TODO: must be checked with PO
        # - empty hiring start date
        # - `with_retroactivity_limitation` set to `False`
        # What should be the expected suspension mimimum start date ?

        min_start_at = Suspension.next_min_start_at(job_application_1.approval)
        self.assertEqual(min_start_at, today)

        # Same rules apply for PE approval and PASS IAE
        min_start_at = Suspension.next_min_start_at(job_application_2.approval)
        self.assertEqual(min_start_at, start_at)
        min_start_at = Suspension.next_min_start_at(job_application_3.approval)
        self.assertEqual(min_start_at, start_at)

        # Fix a type error when creating a suspension:
        min_start_at = Suspension.next_min_start_at(job_application_4.approval)
        self.assertEqual(min_start_at, today - datetime.timedelta(days=Suspension.MAX_RETROACTIVITY_DURATION_DAYS))


class SuspensionModelTestTrigger(TestCase):
    """
    Test `trigger_update_approval_end_at`.
    """

    def test_save(self):
        """
        Test `trigger_update_approval_end_at` with SQL INSERT.
        An approval's `end_at` is automatically pushed forward when it's suspended.
        """
        start_at = timezone.now().date()

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
        start_at = timezone.now().date()

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
        start_at = timezone.now().date()

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
        start_at = timezone.now().date()  # Starts today so it's in progress.
        expected_num = 5
        ProlongationFactory.create_batch(expected_num, start_at=start_at)
        self.assertEqual(expected_num, Prolongation.objects.in_progress().count())

    def test_not_in_progress(self):
        start_at = timezone.now().date() - relativedelta(years=1)
        end_at = start_at + relativedelta(months=6)
        expected_num = 3
        ProlongationFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        self.assertEqual(expected_num, Prolongation.objects.not_in_progress().count())


class ProlongationManagerTest(TestCase):
    """
    Test ProlongationManager.
    """

    def test_get_cumulative_duration_for_any_reasons(self):
        """
        It should return the cumulative duration of all prolongations of the given approval.
        """

        approval = ApprovalFactory()

        prolongation1_days = 30

        prolongation1 = ProlongationFactory(
            approval=approval,
            start_at=approval.end_at,
            end_at=approval.end_at + relativedelta(days=prolongation1_days),
            reason=Prolongation.Reason.COMPLETE_TRAINING.value,
        )

        prolongation2_days = 14

        ProlongationFactory(
            approval=approval,
            start_at=prolongation1.end_at,
            end_at=prolongation1.end_at + relativedelta(days=prolongation2_days),
            reason=Prolongation.Reason.RQTH.value,
        )

        expected_duration = datetime.timedelta(days=prolongation1_days + prolongation2_days)
        self.assertEqual(expected_duration, Prolongation.objects.get_cumulative_duration_for(approval))

    def test_get_cumulative_duration_for_rqth(self):
        """
        It should return the cumulative duration of all prolongations of the given approval
        only for the RQTH reason.
        """

        approval = ApprovalFactory()

        prolongation1_days = 30

        prolongation1 = ProlongationFactory(
            approval=approval,
            start_at=approval.end_at,
            end_at=approval.end_at + relativedelta(days=prolongation1_days),
            reason=Prolongation.Reason.COMPLETE_TRAINING.value,
        )

        prolongation2_days = 14

        prolongation2 = ProlongationFactory(
            approval=approval,
            start_at=prolongation1.end_at,
            end_at=prolongation1.end_at + relativedelta(days=prolongation2_days),
            reason=Prolongation.Reason.RQTH.value,
        )

        prolongation3_days = 60

        ProlongationFactory(
            approval=approval,
            start_at=prolongation2.end_at,
            end_at=prolongation2.end_at + relativedelta(days=prolongation3_days),
            reason=Prolongation.Reason.RQTH.value,
        )

        expected_duration = datetime.timedelta(days=prolongation2_days + prolongation3_days)
        self.assertEqual(
            expected_duration,
            Prolongation.objects.get_cumulative_duration_for(approval, reason=Prolongation.Reason.RQTH.value),
        )


class ProlongationModelTestTrigger(TestCase):
    """
    Test `trigger_update_approval_end_at_for_prolongation`.
    """

    def test_save(self):
        """
        Test `trigger_update_approval_end_at_for_prolongation` with SQL INSERT.
        An approval's `end_at` is automatically pushed forward when it is prolongated.
        """
        start_at = timezone.now().date()

        approval = ApprovalFactory(start_at=start_at)
        initial_duration = approval.duration

        prolongation = ProlongationFactory(approval=approval, start_at=start_at)

        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration + prolongation.duration)

    def test_delete(self):
        """
        Test `trigger_update_approval_end_at_for_prolongation` with SQL DELETE.
        An approval's `end_at` is automatically pushed back when its prolongation
        is deleted.
        """
        start_at = timezone.now().date()

        approval = ApprovalFactory(start_at=start_at)
        initial_duration = approval.duration

        prolongation = ProlongationFactory(approval=approval, start_at=start_at)
        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration + prolongation.duration)

        prolongation.delete()

        approval.refresh_from_db()
        self.assertEqual(approval.duration, initial_duration)

    def test_save_and_edit(self):
        """
        Test `trigger_update_approval_end_at_for_prolongation` with SQL UPDATE.
        An approval's `end_at` is automatically pushed back and forth when
        one of its valid prolongation is saved, then edited to be shorter.
        """
        start_at = timezone.now().date()

        approval = ApprovalFactory(start_at=start_at)
        initial_approval_duration = approval.duration

        # New prolongation.
        prolongation = ProlongationFactory(approval=approval, start_at=start_at)
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


class ProlongationModelTestConstraint(TestCase):
    def test_exclusion_constraint(self):

        approval = ApprovalFactory()

        initial_prolongation = ProlongationFactory(
            approval=approval,
            start_at=approval.end_at,
        )

        with self.assertRaises(IntegrityError):
            # A prolongation that starts the same day as initial_prolongation.
            ProlongationFactory(
                approval=approval,
                declared_by_siae=initial_prolongation.declared_by_siae,
                start_at=approval.end_at,
            )


class ProlongationModelTest(TestCase):
    """
    Test Prolongation model.
    """

    def test_clean_with_wrong_start_at(self):
        """
        Given an existing prolongation, when setting a wrong `start_at`
        then a call to `clean()` is rejected.
        """

        approval = ApprovalFactory()
        siae = SiaeWithMembershipFactory()

        start_at = approval.end_at - relativedelta(days=2)
        end_at = start_at + relativedelta(months=1)

        # We need an object without `pk` to test `clean()`, so we use `build`
        # which provides a local object without saving it to the database.
        prolongation = ProlongationFactory.build(
            start_at=start_at, end_at=end_at, approval=approval, declared_by_siae=siae
        )

        with self.assertRaises(ValidationError) as error:
            prolongation.clean()
        self.assertIn("La date de début doit être la même que la date de fin du PASS IAE", error.exception.message)

    def test_get_start_at(self):

        end_at = datetime.date(2021, 2, 1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)

        prolongation_start_at = Prolongation.get_start_at(approval)
        self.assertEqual(prolongation_start_at, end_at)

    def test_get_max_end_at(self):

        start_at = datetime.date(2021, 2, 1)

        reason = Prolongation.Reason.SENIOR_CDI.value
        expected_max_end_at = datetime.date(2031, 1, 31)  # 10 years.
        max_end_at = Prolongation.get_max_end_at(start_at, reason=reason)
        self.assertEqual(max_end_at, expected_max_end_at)

        reason = Prolongation.Reason.COMPLETE_TRAINING.value
        expected_max_end_at = datetime.date(2023, 1, 31)  # 2 years.
        max_end_at = Prolongation.get_max_end_at(start_at, reason=reason)
        self.assertEqual(max_end_at, expected_max_end_at)

        reason = Prolongation.Reason.RQTH.value
        expected_max_end_at = datetime.date(2024, 1, 31)  # 3 years.
        max_end_at = Prolongation.get_max_end_at(start_at, reason=reason)
        self.assertEqual(max_end_at, expected_max_end_at)

        reason = Prolongation.Reason.SENIOR.value
        expected_max_end_at = datetime.date(2026, 1, 31)  # 5 years.
        max_end_at = Prolongation.get_max_end_at(start_at, reason=reason)
        self.assertEqual(max_end_at, expected_max_end_at)

        reason = Prolongation.Reason.PARTICULAR_DIFFICULTIES.value
        expected_max_end_at = datetime.date(2022, 1, 31)  # 3 years.
        max_end_at = Prolongation.get_max_end_at(start_at, reason=reason)
        self.assertEqual(max_end_at, expected_max_end_at)

        reason = Prolongation.Reason.HEALTH_CONTEXT.value
        expected_max_end_at = datetime.date(2022, 1, 31)  # 1 year.
        max_end_at = Prolongation.get_max_end_at(start_at, reason=reason)
        self.assertEqual(max_end_at, expected_max_end_at)

    def test_time_boundaries(self):
        """
        Test that the upper bound of preceding time interval is the lower bound of the next.
        E.g.:
                  Approval: 02/03/2019 -> 01/03/2021
            Prolongation 1: 01/03/2021 -> 31/03/2021
            Prolongation 2: 31/03/2021 -> 30/04/2021
        """

        # Approval.

        start_at = datetime.date(2019, 3, 2)
        end_at = datetime.date(2021, 3, 1)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        initial_approval_duration = approval.duration

        # Prolongation 1.

        expected_end_at = datetime.date(2021, 3, 31)

        prolongation1 = ProlongationFactory(
            approval=approval,
            start_at=approval.end_at,
            end_at=expected_end_at,
            reason=Prolongation.Reason.COMPLETE_TRAINING.value,
        )

        approval.refresh_from_db()
        self.assertEqual(prolongation1.end_at, expected_end_at)
        self.assertEqual(approval.end_at, expected_end_at)

        # Prolongation 2.

        expected_end_at = datetime.date(2021, 4, 30)

        prolongation2 = ProlongationFactory(
            approval=approval,
            start_at=prolongation1.end_at,
            end_at=expected_end_at,
            reason=Prolongation.Reason.COMPLETE_TRAINING.value,
        )

        approval.refresh_from_db()
        self.assertEqual(prolongation2.end_at, expected_end_at)
        self.assertEqual(approval.end_at, expected_end_at)

        # Check duration.

        self.assertEqual(
            approval.duration, initial_approval_duration + prolongation1.duration + prolongation2.duration
        )

    def test_get_overlapping_prolongations(self):

        approval = ApprovalFactory()

        initial_prolongation = ProlongationFactory(
            approval=approval,
            start_at=approval.end_at,
        )

        # A prolongation that starts the same day as initial_prolongation.
        # Build provides a local object without saving it to the database.
        valid_prolongation = ProlongationFactory.build(
            approval=approval,
            declared_by_siae=initial_prolongation.declared_by_siae,
            start_at=approval.end_at,
        )
        self.assertTrue(valid_prolongation.get_overlapping_prolongations().exists())
        self.assertTrue(initial_prolongation, valid_prolongation.get_overlapping_prolongations().exists())

    def test_has_reached_max_cumulative_duration_for_complete_training(self):

        approval = ApprovalFactory()

        duration = Prolongation.MAX_CUMULATIVE_DURATION[Prolongation.Reason.COMPLETE_TRAINING.value]["duration"]

        prolongation = ProlongationFactory(
            approval=approval,
            start_at=approval.end_at,
            end_at=approval.end_at + duration,
            reason=Prolongation.Reason.COMPLETE_TRAINING.value,
        )

        self.assertFalse(prolongation.has_reached_max_cumulative_duration())
        self.assertTrue(
            prolongation.has_reached_max_cumulative_duration(additional_duration=datetime.timedelta(days=1))
        )

    def test_has_reached_max_cumulative_duration_for_particular_difficulties(self):

        approval = ApprovalFactory()

        prolongation1 = ProlongationFactory(
            approval=approval,
            start_at=approval.end_at,
            end_at=approval.end_at + datetime.timedelta(days=365 * 2),  # 2 years
            reason=Prolongation.Reason.PARTICULAR_DIFFICULTIES.value,
        )

        self.assertFalse(prolongation1.has_reached_max_cumulative_duration())

        prolongation2 = ProlongationFactory(
            approval=approval,
            start_at=prolongation1.end_at,
            end_at=prolongation1.end_at + datetime.timedelta(days=365),  # 1 year,
            reason=Prolongation.Reason.PARTICULAR_DIFFICULTIES.value,
        )

        self.assertFalse(prolongation2.has_reached_max_cumulative_duration())
        self.assertTrue(
            prolongation2.has_reached_max_cumulative_duration(additional_duration=datetime.timedelta(days=1))
        )


class ProlongationNotificationsTest(TestCase):
    """
    Test Prolongation notifications.
    """

    def test_new_prolongation_to_authorized_prescriber_notification(self):

        prolongation = ProlongationFactory()

        email = NewProlongationToAuthorizedPrescriberNotification(prolongation).email

        # To.
        self.assertIn(prolongation.validated_by.email, email.to)
        self.assertEqual(len(email.to), 1)

        # Body.

        self.assertIn(prolongation.start_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(prolongation.end_at.strftime("%d/%m/%Y"), email.body)
        self.assertIn(prolongation.get_reason_display(), email.body)
        self.assertIn(title(prolongation.declared_by.get_full_name()), email.body)

        self.assertIn(prolongation.declared_by_siae.display_name, email.body)
        self.assertIn(prolongation.approval.number_with_spaces, email.body)
        self.assertIn(title(prolongation.approval.user.first_name), email.body)
        self.assertIn(title(prolongation.approval.user.last_name), email.body)
        self.assertIn(settings.ITOU_EMAIL_PROLONGATION, email.body)


class ApprovalConcurrentModelTest(TransactionTestCase):
    """
    Uses TransactionTestCase that truncates all tables after every test, instead of TestCase
    that uses transaction.
    This way we can appropriately test the select_for_update() behaviour.
    """

    def test_nominal_process(self):
        with transaction.atomic():
            # create a first approval out of the blue, ensure the number is correct.
            approval_1 = ApprovalFactory.build(user=UserFactory(), number=None)
            self.assertEqual(Approval.objects.count(), 0)
            approval_1.save()
            self.assertEqual(approval_1.number, "999990000001")
            self.assertEqual(Approval.objects.count(), 1)

            # if a second one is created after the save, no worries man.
            approval_2 = ApprovalFactory.build(user=UserFactory(), number=None)
            approval_2.save()
            self.assertEqual(approval_2.number, "999990000002")

    def test_race_condition(self):
        """Demonstrate the issue where two concurrent requests are locking the last row of
        the Approval table (effectively, preventing each other from modifying it at the same
        time) but still be wrong in evaluating the next number: the selected line is the same
        so the number also is.
        What we can do though is selecting the FIRST line just for locking (cheap semaphore)
        and then select the last one.
        """
        # create a first Approval so that the last() in get_next_number actually has something
        # to select_for_update() and will effectively lock the last row.
        with transaction.atomic():
            ApprovalFactory(user=UserFactory(), number=None)

        user1 = UserFactory()
        user2 = UserFactory()

        approval = None
        approval2 = None

        # We are going to simulate two concurrent requests inside two atomic transaction blocks.
        # The goal is to simulate two concurrent Approval.accept() requests.
        # Let's do like they do in the Django tests themselves: use threads and sleep().
        def first_request():
            nonlocal approval
            with transaction.atomic():
                approval = ApprovalFactory.build(user=user1, number=Approval.get_next_number())
                time.sleep(0.2)  # sleep long enough for the concurrent request to start
                approval.save()

        def concurrent_request():
            nonlocal approval2
            with transaction.atomic():
                time.sleep(0.1)  # ensure we are not the first to take the lock
                approval2 = ApprovalFactory.build(user=user2, number=Approval.get_next_number())
                time.sleep(0.2)  # sleep long enough to save() after the first request's save()
                approval2.save()

        t1 = threading.Thread(target=first_request)
        t2 = threading.Thread(target=concurrent_request)
        t1.start()
        t2.start()
        t1.join()
        t2.join()  # without the singleton we would suffer from IntegrityError here

        self.assertEqual(approval.number, "999990000002")
        self.assertEqual(approval2.number, "999990000003")
