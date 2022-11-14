import datetime
import threading
import time
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core import mail
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.template.defaultfilters import title
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time

from itou.approvals.admin import JobApplicationInline
from itou.approvals.admin_forms import ApprovalAdminForm
from itou.approvals.enums import ApprovalStatus
from itou.approvals.factories import ApprovalFactory, PoleEmploiApprovalFactory, ProlongationFactory, SuspensionFactory
from itou.approvals.models import Approval, PoleEmploiApproval, Prolongation, Suspension
from itou.approvals.notifications import NewProlongationToAuthorizedPrescriberNotification
from itou.employee_record.factories import EmployeeRecordFactory
from itou.employee_record.models import EmployeeRecord
from itou.job_applications.factories import (
    JobApplicationSentByJobSeekerFactory,
    JobApplicationWithApprovalFactory,
    JobApplicationWithoutApprovalFactory,
)
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.enums import SiaeKind
from itou.siaes.factories import SiaeFactory
from itou.siaes.models import Siae
from itou.users.factories import JobSeekerFactory, UserFactory
from itou.utils import constants as global_constants


class CommonApprovalQuerySetTest(TestCase):
    def test_valid_for_pole_emploi_approval_model(self):
        start_at = timezone.localdate() - relativedelta(years=1)
        end_at = start_at + relativedelta(years=1)
        PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = timezone.localdate() - relativedelta(years=5)
        end_at = start_at + relativedelta(years=2)
        PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)

        self.assertEqual(2, PoleEmploiApproval.objects.count())
        self.assertEqual(1, PoleEmploiApproval.objects.valid().count())

    def test_valid_for_approval_model(self):
        start_at = timezone.localdate() - relativedelta(years=1)
        end_at = start_at + relativedelta(years=1)
        ApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = timezone.localdate() - relativedelta(years=5)
        end_at = start_at + relativedelta(years=2)
        ApprovalFactory(start_at=start_at, end_at=end_at)

        self.assertEqual(2, Approval.objects.count())
        self.assertEqual(1, Approval.objects.valid().count())

    def test_valid(self):

        # Start today, end in 2 years.
        start_at = timezone.localdate()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(Approval.objects.filter(id=approval.id).valid().exists())

        # End today.
        end_at = timezone.localdate()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(Approval.objects.filter(id=approval.id).valid().exists())

        # Ended 1 year ago.
        end_at = timezone.localdate() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(Approval.objects.filter(id=approval.id).valid().exists())

        # Ended yesterday.
        end_at = timezone.localdate() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(Approval.objects.filter(id=approval.id).valid().exists())

        # In the future.
        start_at = timezone.localdate() + relativedelta(years=2)
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
        start_at = timezone.localdate() - relativedelta(years=1)
        end_at = start_at + relativedelta(years=1)
        approval_past = ApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = timezone.localdate()
        end_at = start_at + relativedelta(years=2)
        approval_today = ApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = timezone.localdate() + relativedelta(years=2)
        end_at = start_at + relativedelta(years=2)
        approval_future = ApprovalFactory(start_at=start_at, end_at=end_at)

        self.assertEqual(3, Approval.objects.count())
        self.assertEqual([approval_past], list(Approval.objects.starts_in_the_past()))
        self.assertEqual([approval_today], list(Approval.objects.starts_today()))
        self.assertEqual([approval_future], list(Approval.objects.starts_in_the_future()))


class CommonApprovalMixinTest(TestCase):
    def test_waiting_period_end(self):
        end_at = datetime.date(2000, 1, 1)
        start_at = datetime.date(1998, 1, 1)
        approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
        expected = datetime.date(2002, 1, 1)
        self.assertEqual(approval.waiting_period_end, expected)

    def test_is_in_progress(self):
        start_at = timezone.localdate() - relativedelta(days=10)
        approval = ApprovalFactory(start_at=start_at)
        self.assertTrue(approval.is_in_progress)

    def test_waiting_period(self):

        # End is tomorrow.
        end_at = timezone.localdate() + relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid())
        self.assertFalse(approval.is_in_waiting_period)

        # End is today.
        end_at = timezone.localdate()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid())
        self.assertFalse(approval.is_in_waiting_period)

        # End is yesterday.
        end_at = timezone.localdate() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid())
        self.assertTrue(approval.is_in_waiting_period)

        # Ended since more than WAITING_PERIOD_YEARS.
        end_at = timezone.localdate() - relativedelta(years=Approval.WAITING_PERIOD_YEARS, days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid())
        self.assertFalse(approval.is_in_waiting_period)

    def test_originates_from_itou(self):
        approval = ApprovalFactory(number="XXXXX0000001")
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
        approval.start_at = timezone.localdate()
        approval.end_at = timezone.localdate() - datetime.timedelta(days=365 * 2)
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
        start_at = timezone.localdate()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid())

        # End today.
        end_at = timezone.localdate()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertTrue(approval.is_valid())

        # Ended 1 year ago.
        end_at = timezone.localdate() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        self.assertFalse(approval.is_valid())

        # Ended yesterday.
        end_at = timezone.localdate() - relativedelta(days=1)
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
        end_at = timezone.localdate() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval1 = ApprovalFactory(start_at=start_at, end_at=end_at, user=user)

        # Start today, end in 2 years.
        start_at = timezone.localdate()
        end_at = start_at + relativedelta(years=2)
        approval2 = ApprovalFactory(start_at=start_at, end_at=end_at, user=user)

        self.assertFalse(approval1.is_last_for_user)
        self.assertTrue(approval2.is_last_for_user)

    @freeze_time("2022-11-17")
    def test_is_open_to_prolongation(self):
        # Ensure that "now" is "before" the period open to prolongations (12 months after approval start)
        approval = ApprovalFactory(
            start_at=datetime.date(2021, 11, 18),
            end_at=datetime.date(2023, 11, 17),
        )
        self.assertFalse(approval.is_open_to_prolongation)

        # Ensure "now" is in the period open to prolongations.
        approval = ApprovalFactory(
            start_at=datetime.date(2021, 11, 17),
            end_at=datetime.date(2023, 11, 16),
        )
        self.assertTrue(approval.is_open_to_prolongation)

        # until 3 month after the end date, users are allowed to prolong it up to 3 months after the end.
        approval = ApprovalFactory(
            start_at=datetime.date(2020, 8, 18),
            end_at=datetime.date(2022, 8, 17),
        )
        self.assertTrue(approval.is_open_to_prolongation)

        # Ensure "now" is "after" the period open to prolongations.
        approval = ApprovalFactory(
            start_at=datetime.date(2020, 8, 17),
            end_at=datetime.date(2022, 8, 16),
        )
        self.assertFalse(approval.is_open_to_prolongation)

    def test_get_or_create_from_valid(self):
        # FIXME(vperron): This test should be moved to users.tests or jobseekerprofile.tests.

        # With an existing valid `PoleEmploiApproval`.

        user = JobSeekerFactory()
        valid_pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate, number="625741810182"
        )
        approval = user.get_or_create_approval()

        self.assertTrue(isinstance(approval, Approval))
        self.assertEqual(approval.start_at, valid_pe_approval.start_at)
        self.assertEqual(approval.end_at, valid_pe_approval.end_at)
        self.assertEqual(approval.number, valid_pe_approval.number[:12])
        self.assertEqual(approval.user, user)
        self.assertEqual(approval.created_by, None)

        # With an existing valid `Approval`.

        user = JobSeekerFactory()
        valid_approval = ApprovalFactory(user=user, start_at=timezone.localdate() - relativedelta(days=1))
        approval = user.get_or_create_approval()
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
        today = timezone.localdate()
        approval_start_at = today - relativedelta(months=3)
        reasons_to_not_open_process = [
            reason.value for reason in Suspension.Reason if reason.value not in Suspension.REASONS_ALLOWING_UNSUSPEND
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

        for reason in Suspension.REASONS_ALLOWING_UNSUSPEND:
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
        today = timezone.localdate()
        approval_start_at = today - relativedelta(months=3)
        approval = ApprovalFactory(start_at=approval_start_at)
        self.assertFalse(approval.can_be_unsuspended)

    def test_last_in_progress_suspension(self):
        today = timezone.localdate()
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
        today = timezone.localdate()
        approval_start_at = today - relativedelta(months=3)
        approval = ApprovalFactory(start_at=approval_start_at)
        SuspensionFactory(
            approval=approval,
            start_at=approval_start_at + relativedelta(months=1),
            end_at=approval_start_at + relativedelta(months=2),
        )
        self.assertIsNone(approval.last_in_progress_suspension)

    @freeze_time("2022-09-17")
    def test_unsuspend_valid(self):
        today = timezone.localdate()
        approval_start_at = datetime.date(2022, 6, 17)
        suspension_start_date = datetime.date(2022, 7, 17)
        suspension_end_date = datetime.date(2022, 12, 17)
        suspension_expected_end_date = datetime.date(2022, 9, 16)

        REASONS_ALLOWING_UNSUSPEND = [
            Suspension.Reason.BROKEN_CONTRACT.value,
            Suspension.Reason.FINISHED_CONTRACT.value,
            Suspension.Reason.APPROVAL_BETWEEN_CTA_MEMBERS.value,
            Suspension.Reason.CONTRAT_PASSERELLE.value,
            Suspension.Reason.SUSPENDED_CONTRACT.value,
        ]

        for reason in REASONS_ALLOWING_UNSUSPEND:
            with self.subTest(f"reason={reason} expects end_at={suspension_expected_end_date}"):
                approval = ApprovalFactory(start_at=approval_start_at)
                suspension = SuspensionFactory(
                    approval=approval, reason=reason, start_at=suspension_start_date, end_at=suspension_end_date
                )
                approval.unsuspend(hiring_start_at=today)
                suspension.refresh_from_db()
                self.assertEqual(suspension.end_at, suspension_expected_end_date)

    @freeze_time("2022-09-17")
    def test_unsuspend_invalid(self):
        today = timezone.localdate()
        approval_start_at = datetime.date(2022, 6, 17)
        suspension_start_date = datetime.date(2022, 7, 17)
        suspension_end_date = datetime.date(2022, 12, 17)

        invalid_reason = (
            Suspension.Reason.SICKNESS.value,
            Suspension.Reason.MATERNITY.value,
            Suspension.Reason.INCARCERATION.value,
            Suspension.Reason.TRIAL_OUTSIDE_IAE.value,
            Suspension.Reason.DETOXIFICATION.value,
            Suspension.Reason.FORCE_MAJEURE.value,
        )

        for reason in invalid_reason:
            with self.subTest(f"reason={reason} expects end_at={suspension_end_date}"):
                approval = ApprovalFactory(start_at=approval_start_at)
                suspension = SuspensionFactory(
                    approval=approval, reason=reason, start_at=suspension_start_date, end_at=suspension_end_date
                )
                approval.unsuspend(hiring_start_at=today)
                suspension.refresh_from_db()
                self.assertEqual(suspension.end_at, suspension_end_date)

    def test_unsuspend_the_day_suspension_starts(self):
        today = timezone.localdate()
        approval = ApprovalFactory(start_at=today - relativedelta(months=3))
        suspension = SuspensionFactory(
            approval=approval,
            start_at=today,
            end_at=today + relativedelta(months=2),
            reason=Suspension.Reason.BROKEN_CONTRACT.value,
        )
        approval.unsuspend(hiring_start_at=today)
        with self.assertRaises(ObjectDoesNotExist):
            suspension.refresh_from_db()

    def test_state(self):
        now = timezone.localdate()

        expired_approval = ApprovalFactory(
            start_at=now - relativedelta(years=3),
            end_at=now - relativedelta(years=1),
        )
        future_approval = ApprovalFactory(
            start_at=now + relativedelta(days=1),
        )
        valid_approval = ApprovalFactory(
            start_at=now - relativedelta(years=1),
        )
        suspended_approval = ApprovalFactory(
            start_at=now - relativedelta(years=1),
        )
        SuspensionFactory(
            approval=suspended_approval,
            start_at=now - relativedelta(days=1),
            end_at=now + relativedelta(days=1),
        )

        self.assertQuerysetEqual(Approval.objects.invalid(), [expired_approval])
        self.assertEqual(expired_approval.state, ApprovalStatus.EXPIRED)
        self.assertEqual(expired_approval.get_state_display(), "Expiré")

        self.assertQuerysetEqual(Approval.objects.starts_in_the_future(), [future_approval])
        self.assertEqual(future_approval.state, ApprovalStatus.FUTURE)
        self.assertEqual(future_approval.get_state_display(), "Valide (non démarré)")

        self.assertQuerysetEqual(
            Approval.objects.valid().starts_in_the_past(), [valid_approval, suspended_approval], ordered=False
        )
        self.assertEqual(valid_approval.state, ApprovalStatus.VALID)
        self.assertEqual(valid_approval.get_state_display(), "Valide")

        suspended_approval.refresh_from_db()
        self.assertEqual(suspended_approval.is_suspended, True)
        self.assertEqual(suspended_approval.state, ApprovalStatus.SUSPENDED)
        self.assertEqual(suspended_approval.get_state_display(), "Valide (suspendu)")


class PoleEmploiApprovalModelTest(TestCase):
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
        now_date = timezone.localdate() - relativedelta(months=1)
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
    def test_find_for_no_queries(self):
        user = JobSeekerFactory(pole_emploi_id="")
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        self.assertEqual(search_results.count(), 0)

        user = JobSeekerFactory(birthdate=None)
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        self.assertEqual(search_results.count(), 0)

    def test_find_for_user(self):

        # given a User, ensure we can find a PE approval using its pole_emploi_id and not the others.
        user = JobSeekerFactory()
        pe_approval = PoleEmploiApprovalFactory(pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate)
        # just another approval, to be sure we don't find the other one "by chance"
        PoleEmploiApprovalFactory()
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        self.assertEqual(search_results.count(), 1)
        self.assertEqual(search_results.first(), pe_approval)

        # ensure we can find **all** PE approvals using their pole_emploi_id and not the others.
        other_valid_approval = PoleEmploiApprovalFactory(pole_emploi_id=user.pole_emploi_id, birthdate=user.birthdate)
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        self.assertEqual(search_results.count(), 2)
        self.assertEqual(search_results[0], pe_approval)
        self.assertEqual(search_results[1], other_valid_approval)

        # ensure we **also** find PE approvals using the user's NIR.
        nir_approval = PoleEmploiApprovalFactory(nir=user.nir)
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        self.assertEqual(search_results.count(), 3)
        self.assertEqual(search_results[0], pe_approval)
        self.assertEqual(search_results[1], other_valid_approval)
        self.assertEqual(search_results[2], nir_approval)

        # since we can have multiple PE approvals with the same nir, let's fetch them all
        other_nir_approval = PoleEmploiApprovalFactory(nir=user.nir)
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        self.assertEqual(search_results.count(), 4)
        self.assertEqual(search_results[0], pe_approval)
        self.assertEqual(search_results[1], other_valid_approval)
        self.assertEqual(search_results[2], nir_approval)
        self.assertEqual(search_results[3], other_nir_approval)

        # ensure it's not an issue if the PE approval matches both NIR, pole_emploi_id and birthdate.
        nir_approval.birthdate = user.birthdate
        nir_approval.pole_emploi_id = user.pole_emploi_id
        nir_approval.save()

        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        self.assertEqual(search_results.count(), 4)
        self.assertEqual(search_results[0], pe_approval)
        self.assertEqual(search_results[1], other_valid_approval)

        # the order changes because now, the first WHERE clause gets `nir_approval` alone "first",
        # and the ordering on `start_at DESC` doesn't change this as both columns are set to "today".
        # this may depend on PostgreSQL or pysocpg behaviour though, it may be wiser to:
        # - also order by pk or creation date
        # - use a fixture that has a clearly different start_at
        # in order to ensure this test does not become flaky.
        self.assertEqual(search_results[2], other_nir_approval)
        self.assertEqual(search_results[3], nir_approval)

    def test_find_for_no_nir(self):
        user = JobSeekerFactory(nir=None)
        PoleEmploiApprovalFactory(nir=None)  # entirely unrelated
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        self.assertEqual(search_results.count(), 0)


class AutomaticApprovalAdminViewsTest(TestCase):
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

        self.client.force_login(user)

        job_app = JobApplicationWithApprovalFactory(state=JobApplicationWorkflow.STATE_ACCEPTED)
        approval = job_app.approval

        url = reverse("admin:approvals_approval_change", args=[approval.pk])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_data = {
            "start_at": approval.start_at.strftime("%d/%m/%Y"),
            "end_at": approval.end_at.strftime("%d/%m/%Y"),
            "user": job_app.job_seeker.pk,
            "number": "XXXXX1234567",
        }
        response = self.client.post(url, data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["adminform"],
            "number",
            [ApprovalAdminForm.ERROR_NUMBER_CANNOT_BE_CHANGED % approval.number],
        )


class CustomApprovalAdminViewsTest(TestCase):
    def test_manually_add_approval(self):
        user = UserFactory()
        self.client.force_login(user)

        # When a Pôle emploi ID has been forgotten and the user has no NIR, an approval must be delivered
        # with a manual verification.
        job_seeker = JobSeekerFactory(
            nir="", pole_emploi_id="", lack_of_pole_emploi_id_reason=JobSeekerFactory._meta.model.REASON_FORGOTTEN
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
        for siae_kind in [siae_kind for siae_kind in SiaeKind if siae_kind not in Siae.ASP_EMPLOYEE_RECORD_KINDS]:
            not_eligible_siae = SiaeFactory(kind=siae_kind)
            job_application = JobApplicationWithApprovalFactory(to_siae=not_eligible_siae)
            self.assertIn(
                "Pas de fiche salarié crée pour cette candidature",
                JobApplicationInline.employee_record_status(self, job_application),
            )


class SuspensionQuerySetTest(TestCase):
    def test_in_progress(self):
        start_at = timezone.localdate()  # Starts today so it's in progress.
        expected_num = 5
        SuspensionFactory.create_batch(expected_num, start_at=start_at)
        self.assertEqual(expected_num, Suspension.objects.in_progress().count())

    def test_not_in_progress(self):
        start_at = timezone.localdate() - relativedelta(years=1)
        end_at = start_at + relativedelta(months=6)
        expected_num = 3
        SuspensionFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        self.assertEqual(expected_num, Suspension.objects.not_in_progress().count())

    def test_old(self):
        # Starting today.
        start_at = timezone.localdate()
        SuspensionFactory.create_batch(2, start_at=start_at)
        self.assertEqual(0, Suspension.objects.old().count())
        # Old.
        start_at = timezone.localdate() - relativedelta(years=1)
        end_at = Suspension.get_max_end_at(start_at)
        expected_num = 3
        SuspensionFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        self.assertEqual(expected_num, Suspension.objects.old().count())


class SuspensionModelTest(TestCase):
    def test_clean(self):
        today = timezone.localdate()
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
        start_at = timezone.localdate()
        end_at = start_at + expected_duration
        suspension = SuspensionFactory(start_at=start_at, end_at=end_at)
        self.assertEqual(suspension.duration, expected_duration)

    def test_start_in_future(self):
        start_at = timezone.localdate() + relativedelta(days=10)
        # Build provides a local object without saving it to the database.
        suspension = SuspensionFactory.build(start_at=start_at)
        self.assertTrue(suspension.start_in_future)

    def test_start_in_approval_boundaries(self):
        start_at = timezone.localdate()
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
        start_at = timezone.localdate() - relativedelta(days=10)
        # Build provides a local object without saving it to the database.
        suspension = SuspensionFactory.build(start_at=start_at)
        self.assertTrue(suspension.is_in_progress)

    def test_get_overlapping_suspensions(self):
        start_at = timezone.localdate() - relativedelta(days=10)
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
        for kind in [SiaeKind.EI, SiaeKind.ACI]:
            siae = SiaeFactory(kind=kind)
            result = Suspension.Reason.displayed_choices_for_siae(siae)
            self.assertEqual(len(result), 5)
            self.assertEqual(result[-1][0], Suspension.Reason.CONTRAT_PASSERELLE.value)

        # Some other cases
        for kind in [SiaeKind.ETTI, SiaeKind.AI]:
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

    def test_next_min_start_date_without_job_application(self):
        today = timezone.localdate()
        approval = ApprovalFactory()
        siae = SiaeFactory()
        suspension = Suspension(approval=approval, siae=siae, start_at=today, end_at=today)
        suspension.clean()


class SuspensionModelTestTrigger(TestCase):
    def test_save(self):
        """
        Test `trigger_update_approval_end_at` with SQL INSERT.
        An approval's `end_at` is automatically pushed forward when it's suspended.
        """
        start_at = timezone.localdate()

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
        start_at = timezone.localdate()

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
        start_at = timezone.localdate()

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
    def test_in_progress(self):
        start_at = timezone.localdate()  # Starts today so it's in progress.
        expected_num = 5
        ProlongationFactory.create_batch(expected_num, start_at=start_at)
        self.assertEqual(expected_num, Prolongation.objects.in_progress().count())

    def test_not_in_progress(self):
        start_at = timezone.localdate() - relativedelta(years=1)
        end_at = start_at + relativedelta(months=6)
        expected_num = 3
        ProlongationFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        self.assertEqual(expected_num, Prolongation.objects.not_in_progress().count())


class ProlongationManagerTest(TestCase):
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
        start_at = timezone.localdate()

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
        start_at = timezone.localdate()

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
        start_at = timezone.localdate()

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
    def test_clean_with_wrong_start_at(self):
        """
        Given an existing prolongation, when setting a wrong `start_at`
        then a call to `clean()` is rejected.
        """

        approval = ApprovalFactory()
        siae = SiaeFactory(with_membership=True)

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
        self.assertIn(global_constants.ITOU_EMAIL_PROLONGATION, email.body)


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
            self.assertEqual(approval_1.number, "XXXXX0000001")
            self.assertEqual(Approval.objects.count(), 1)

            # if a second one is created after the save, no worries man.
            approval_2 = ApprovalFactory.build(user=UserFactory(), number=None)
            approval_2.save()
            self.assertEqual(approval_2.number, "XXXXX0000002")

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

        self.assertEqual(approval.number, "XXXXX0000002")
        self.assertEqual(approval2.number, "XXXXX0000003")


class PENotificationMixinTestCase(TestCase):
    def test_base_values(self):
        approval = ApprovalFactory()
        self.assertEqual(approval.pe_notification_status, "notification_pending")
        self.assertEqual(approval.pe_notification_time, None)
        self.assertEqual(approval.pe_notification_endpoint, None)
        self.assertEqual(approval.pe_notification_exit_code, None)

    def test_save_error(self):
        now = timezone.now()
        approval = ApprovalFactory()
        approval.pe_save_error("foo", "bar", at=now)
        approval.refresh_from_db()
        self.assertEqual(approval.pe_notification_status, "notification_error")
        self.assertEqual(approval.pe_notification_time, now)
        self.assertEqual(approval.pe_notification_endpoint, "foo")
        self.assertEqual(approval.pe_notification_exit_code, "bar")

    def test_save_success(self):
        now = timezone.now()
        approval = ApprovalFactory()
        approval.pe_save_success(at=now)
        approval.refresh_from_db()
        self.assertEqual(approval.pe_notification_status, "notification_success")
        self.assertEqual(approval.pe_notification_time, now)
        self.assertEqual(approval.pe_notification_endpoint, None)
        self.assertEqual(approval.pe_notification_exit_code, None)

    def test_save_should_retry(self):
        now = timezone.now()
        approval = ApprovalFactory()
        approval.pe_save_should_retry(at=now)
        approval.refresh_from_db()
        self.assertEqual(approval.pe_notification_status, "notification_should_retry")
        self.assertEqual(approval.pe_notification_time, now)
        self.assertEqual(approval.pe_notification_endpoint, None)
        self.assertEqual(approval.pe_notification_exit_code, None)
