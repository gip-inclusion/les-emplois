import datetime
import threading
import time
import uuid
from unittest import mock

import factory
import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages.test import MessagesTestMixin
from django.core import mail
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, ProgrammingError, connection, transaction
from django.forms import model_to_dict
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertQuerySetEqual

from itou.approvals.admin import JobApplicationInline
from itou.approvals.admin_forms import ApprovalAdminForm
from itou.approvals.constants import PROLONGATION_REPORT_FILE_REASONS
from itou.approvals.enums import ApprovalStatus, Origin, ProlongationReason
from itou.approvals.models import Approval, CancelledApproval, PoleEmploiApproval, Prolongation, Suspension
from itou.companies.enums import CompanyKind
from itou.employee_record.enums import Status
from itou.files.models import File
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplication
from itou.users.enums import LackOfPoleEmploiId
from itou.utils.apis import enums as api_enums
from tests.approvals.factories import (
    ApprovalFactory,
    PoleEmploiApprovalFactory,
    ProlongationFactory,
    ProlongationRequestFactory,
    SuspensionFactory,
)
from tests.companies.factories import CompanyFactory
from tests.eligibility.factories import EligibilityDiagnosisFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from tests.users.factories import ItouStaffFactory, JobSeekerFactory
from tests.utils.test import TestCase


class CommonApprovalQuerySetTest(TestCase):
    def test_valid_for_pole_emploi_approval_model(self):
        start_at = timezone.localdate() - datetime.timedelta(days=365)
        end_at = start_at + datetime.timedelta(days=365)
        PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = timezone.localdate() - relativedelta(years=5)
        end_at = start_at + relativedelta(years=2)
        PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)

        assert 2 == PoleEmploiApproval.objects.count()
        assert 1 == PoleEmploiApproval.objects.valid().count()

    def test_valid_for_approval_model(self):
        start_at = timezone.localdate() - datetime.timedelta(days=365)
        end_at = start_at + datetime.timedelta(days=365)
        ApprovalFactory(start_at=start_at, end_at=end_at)

        start_at = timezone.localdate() - relativedelta(years=5)
        end_at = start_at + relativedelta(years=2)
        ApprovalFactory(start_at=start_at, end_at=end_at)

        assert 2 == Approval.objects.count()
        assert 1 == Approval.objects.valid().count()

    def test_valid(self):
        # Start today, end in 2 years.
        start_at = timezone.localdate()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert Approval.objects.filter(id=approval.id).valid().exists()

        # End today.
        end_at = timezone.localdate()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert Approval.objects.filter(id=approval.id).valid().exists()

        # Ended 1 year ago.
        end_at = timezone.localdate() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert not Approval.objects.filter(id=approval.id).valid().exists()

        # Ended yesterday.
        end_at = timezone.localdate() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert not Approval.objects.filter(id=approval.id).valid().exists()

        # In the future.
        start_at = timezone.localdate() + relativedelta(years=2)
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert Approval.objects.filter(id=approval.id).valid().exists()

    def test_can_be_delete_no_app(self):
        approval = ApprovalFactory()
        assert not approval.can_be_deleted()

    def test_can_be_deleted_one_app(self):
        job_app = JobApplicationFactory(with_approval=True)
        approval = job_app.approval
        assert approval.can_be_deleted()

    def test_can_be_deleted_multiple_apps(self):
        job_app = JobApplicationFactory(with_approval=True)
        JobApplicationFactory(with_approval=True, job_seeker=job_app.job_seeker, approval=job_app.approval)
        assert not job_app.approval.can_be_deleted()

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

        assert 3 == Approval.objects.count()
        assert [approval_past] == list(Approval.objects.starts_in_the_past())
        assert [approval_today] == list(Approval.objects.starts_today())
        assert [approval_future] == list(Approval.objects.starts_in_the_future())


class CommonApprovalMixinTest(TestCase):
    def test_waiting_period_end(self):
        end_at = datetime.date(2000, 1, 1)
        start_at = datetime.date(1998, 1, 1)
        approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
        expected = datetime.date(2002, 1, 1)
        assert approval.waiting_period_end == expected

    def test_is_in_progress(self):
        start_at = timezone.localdate() - relativedelta(days=10)
        approval = ApprovalFactory(start_at=start_at)
        assert approval.is_in_progress

    def test_waiting_period(self):
        # End is tomorrow.
        end_at = timezone.localdate() + relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert approval.is_valid()
        assert not approval.is_in_waiting_period

        # End is today.
        end_at = timezone.localdate()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert approval.is_valid()
        assert not approval.is_in_waiting_period

        # End is yesterday.
        end_at = timezone.localdate() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert not approval.is_valid()
        assert approval.is_in_waiting_period

        # Ended since more than WAITING_PERIOD_YEARS.
        end_at = timezone.localdate() - relativedelta(years=Approval.WAITING_PERIOD_YEARS, days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert not approval.is_valid()
        assert not approval.is_in_waiting_period

    def test_is_pass_iae(self):
        # PoleEmploiApproval.
        user = JobSeekerFactory()
        approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id, birthdate=user.birthdate
        )
        assert not approval.is_pass_iae
        # Approval.
        approval = ApprovalFactory(user=user)
        assert approval.is_pass_iae


class ApprovalModelTest(TestCase):
    def test_clean(self):
        approval = ApprovalFactory()
        approval.start_at = timezone.localdate()
        approval.end_at = timezone.localdate() - datetime.timedelta(days=365 * 2)
        with pytest.raises(ValidationError):
            approval.save()

    def test_get_next_number_no_preexisting_approval(self):
        expected_number = f"{Approval.ASP_ITOU_PREFIX}0000001"
        next_number = Approval.get_next_number()
        assert next_number == expected_number

    def test_get_next_number_with_preexisting_approval(self):
        ApprovalFactory(number=f"{Approval.ASP_ITOU_PREFIX}0000040")
        expected_number = f"{Approval.ASP_ITOU_PREFIX}0000041"
        next_number = Approval.get_next_number()
        assert next_number == expected_number

    def test_get_next_number_with_preexisting_pe_approval(self):
        # With pre-existing Pôle emploi approval.
        ApprovalFactory(number="625741810182", origin_pe_approval=True)
        expected_number = f"{Approval.ASP_ITOU_PREFIX}0000001"
        next_number = Approval.get_next_number()
        assert next_number == expected_number

    def test_get_next_number_with_both_preexisting_objects(self):
        ApprovalFactory(number=f"{Approval.ASP_ITOU_PREFIX}8888882")
        ApprovalFactory(number="625741810182", origin_pe_approval=True)
        expected_number = f"{Approval.ASP_ITOU_PREFIX}8888883"
        next_number = Approval.get_next_number()
        assert next_number == expected_number

    def test_get_next_number_with_demo_prefix(self):
        demo_prefix = "XXXXX"
        with mock.patch.object(Approval, "ASP_ITOU_PREFIX", demo_prefix):
            ApprovalFactory(number=f"{demo_prefix}0044440")
            expected_number = f"{demo_prefix}0044441"
            next_number = Approval.get_next_number()
            assert next_number == expected_number

    def test_get_next_number_last_possible_number(self):
        ApprovalFactory(number=f"{Approval.ASP_ITOU_PREFIX}9999999")
        with pytest.raises(RuntimeError):
            Approval.get_next_number()

    def test_cannot_mass_delete_approvals(self):
        with pytest.raises(NotImplementedError):
            Approval.objects.all().delete()

    def test_is_valid(self):
        # Start today, end in 2 years.
        start_at = timezone.localdate()
        end_at = start_at + relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert approval.is_valid()

        # End today.
        end_at = timezone.localdate()
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert approval.is_valid()

        # Ended 1 year ago.
        end_at = timezone.localdate() - relativedelta(years=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert not approval.is_valid()

        # Ended yesterday.
        end_at = timezone.localdate() - relativedelta(days=1)
        start_at = end_at - relativedelta(years=2)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        assert not approval.is_valid()

    def test_number_with_spaces(self):
        approval = ApprovalFactory(number="XXXXX0000001")
        expected = "XXXXX 00 00001"
        assert approval.number_with_spaces == expected

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

        assert not approval1.is_last_for_user
        assert approval2.is_last_for_user

    @freeze_time("2022-11-17")
    def test_is_open_to_prolongation(self):
        # Ensure that "now" is "before" the period open to prolongations (7 months before approval end)
        approval = ApprovalFactory(
            start_at=datetime.date(2021, 6, 17),
            end_at=datetime.date(2023, 6, 18),
        )
        assert not approval.is_open_to_prolongation

        # Ensure "now" is in the period open to prolongations.
        approval = ApprovalFactory(
            start_at=datetime.date(2021, 6, 16),
            end_at=datetime.date(2023, 6, 15),
        )
        assert approval.is_open_to_prolongation

        # users are not allowed to make a prolongation 3 months after the approval end anymore.
        approval = ApprovalFactory(
            start_at=datetime.date(2020, 8, 18),
            end_at=datetime.date(2022, 8, 17),
        )
        assert not approval.is_open_to_prolongation

        # Ensure "now" is "after" the period open to prolongations.
        approval = ApprovalFactory(
            start_at=datetime.date(2020, 8, 17),
            end_at=datetime.date(2022, 8, 16),
        )
        assert not approval.is_open_to_prolongation

    def test_get_or_create_from_valid(self):
        # FIXME(vperron): This test should be moved to users.tests or jobseekerprofile.tests.

        # With an existing valid `PoleEmploiApproval`.

        user = JobSeekerFactory(with_pole_emploi_id=True)
        job_application = JobApplicationFactory(job_seeker=user)
        valid_pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.birthdate,
            number="625741810182",
        )
        approval = user.get_or_create_approval(origin_job_application=job_application)

        assert isinstance(approval, Approval)
        assert approval.start_at == valid_pe_approval.start_at
        assert approval.end_at == valid_pe_approval.end_at
        assert approval.number == valid_pe_approval.number[:12]
        assert approval.user == user
        assert approval.created_by is None
        assert approval.origin == Origin.PE_APPROVAL
        assert approval.origin_siae_kind == job_application.to_company.kind
        assert approval.origin_siae_siret == job_application.to_company.siret
        assert approval.origin_sender_kind == job_application.sender_kind
        assert approval.origin_prescriber_organization_kind == ""

        # With an existing valid `Approval`.

        user = JobSeekerFactory()
        job_application = JobApplicationFactory(job_seeker=user, sent_by_authorized_prescriber_organisation=True)
        valid_approval = ApprovalFactory(user=user, start_at=timezone.localdate() - relativedelta(days=1))
        approval = user.get_or_create_approval(origin_job_application=job_application)
        assert isinstance(approval, Approval)
        assert approval == valid_approval

    def test_can_be_unsuspended_without_suspension(self):
        today = timezone.localdate()
        approval_start_at = today - relativedelta(months=3)
        approval = ApprovalFactory(start_at=approval_start_at)
        assert not approval.can_be_unsuspended

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
        assert suspension.pk == approval.last_in_progress_suspension.pk

    def test_last_in_progress_without_suspension_in_progress(self):
        today = timezone.localdate()
        approval_start_at = today - relativedelta(months=3)
        approval = ApprovalFactory(start_at=approval_start_at)
        SuspensionFactory(
            approval=approval,
            start_at=approval_start_at + relativedelta(months=1),
            end_at=approval_start_at + relativedelta(months=2),
        )
        assert approval.last_in_progress_suspension is None

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
                    approval=approval,
                    reason=reason,
                    start_at=suspension_start_date,
                    end_at=suspension_end_date,
                )
                approval.unsuspend(hiring_start_at=today)
                suspension.refresh_from_db()
                assert suspension.end_at == suspension_expected_end_date

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
                    approval=approval,
                    reason=reason,
                    start_at=suspension_start_date,
                    end_at=suspension_end_date,
                )
                approval.unsuspend(hiring_start_at=today)
                suspension.refresh_from_db()
                assert suspension.end_at == suspension_end_date

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
        with pytest.raises(ObjectDoesNotExist):
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

        self.assertQuerySetEqual(Approval.objects.invalid(), [expired_approval])
        assert expired_approval.state == ApprovalStatus.EXPIRED
        assert expired_approval.get_state_display() == "Expiré"

        self.assertQuerySetEqual(Approval.objects.starts_in_the_future(), [future_approval])
        assert future_approval.state == ApprovalStatus.FUTURE
        assert future_approval.get_state_display() == "Valide (non démarré)"

        self.assertQuerySetEqual(
            Approval.objects.valid().starts_in_the_past(),
            [valid_approval, suspended_approval],
            ordered=False,
        )
        assert valid_approval.state == ApprovalStatus.VALID
        assert valid_approval.get_state_display() == "Valide"

        suspended_approval.refresh_from_db()
        assert suspended_approval.is_suspended is True
        assert suspended_approval.state == ApprovalStatus.SUSPENDED
        assert suspended_approval.get_state_display() == "Valide (suspendu)"

    def tests_is_suspended(self):
        now = timezone.localdate()
        ApprovalFactory(start_at=now - relativedelta(years=1))
        ApprovalFactory(start_at=now - relativedelta(years=1))

        # No prefetch
        num_queries = 1  # fetch approvals
        num_queries += 2  # check suspensions for each approvals
        with self.assertNumQueries(num_queries):
            approvals = Approval.objects.all()
            for approval in approvals:
                approval.state

        # With prefetch
        num_queries = 1  # fetch approvals
        num_queries += 1  # check suspensions based on prefetched data
        with self.assertNumQueries(num_queries):
            approvals = Approval.objects.all().prefetch_related("suspension_set")
            for approval in approvals:
                approval.state

    @freeze_time("2022-11-22")
    def test_remainder(self):
        approval = ApprovalFactory(
            start_at=datetime.date(2021, 3, 25),
            end_at=datetime.date(2023, 3, 24),
        )
        assert approval.remainder == datetime.timedelta(days=123)

        # Futur prolongation, adding 4 days to approval.end_date.
        ProlongationFactory(
            approval=approval,
            start_at=datetime.date(2023, 3, 20),
            end_at=datetime.date(2023, 3, 24),
        )
        # Past prolongation, adding 5 days to approval.end_date.
        ProlongationFactory(
            approval=approval,
            start_at=datetime.date(2021, 3, 25),
            end_at=datetime.date(2021, 3, 30),
        )
        # Ongoing prolongation, adding 30 days to approval.end_date.
        ProlongationFactory(
            approval=approval,
            start_at=datetime.date(2021, 11, 1),
            end_at=datetime.date(2021, 12, 1),
        )

        del approval.remainder
        approval.refresh_from_db()
        prolonged_remainder = 123 + 4 + 5 + 30
        assert approval.remainder == datetime.timedelta(days=prolonged_remainder)

        # Past suspension (ignored), adding 5 days to approval.end_date.
        SuspensionFactory(
            approval=approval,
            start_at=datetime.date(2021, 3, 25),
            end_at=datetime.date(2021, 3, 30),
        )
        # Ongoing suspension, adding 30 days to approval.end_date, but only 10 of them remain.
        SuspensionFactory(
            approval=approval,
            start_at=datetime.date(2022, 11, 1),
            end_at=datetime.date(2022, 12, 1),
        )
        # Clear cache
        del approval.remainder
        approval.refresh_from_db()
        # Substract to remainder the remaining suspension time
        assert approval.remainder == datetime.timedelta(days=(prolonged_remainder + 5 + 30 - 10))

    @freeze_time("2023-04-26")
    def test_remainder_as_date(self):
        """
        Only test return type and value as the algorithm is already tested in `self.test_remainder`.
        """
        approval = ApprovalFactory(
            start_at=datetime.date(2021, 7, 26),
            end_at=datetime.date(2023, 7, 25),
        )
        assert approval.remainder_as_date == datetime.date(2023, 7, 25)

    def test_diagnosis_constraint(self):
        ApprovalFactory(origin_ai_stock=True)
        ApprovalFactory(origin_pe_approval=True)

        with transaction.atomic():
            with pytest.raises(IntegrityError):
                ApprovalFactory(eligibility_diagnosis=None, origin=Origin.DEFAULT)

        with transaction.atomic():
            with pytest.raises(IntegrityError):
                ApprovalFactory(eligibility_diagnosis=None, origin=Origin.ADMIN)

    def test_deleting_an_approval_creates_a_deleted_one(self):
        job_application = JobApplicationFactory(with_approval=True)
        user = job_application.job_seeker
        approval = job_application.approval

        assert user.latest_common_approval == approval
        assert job_application.approval == approval
        assertQuerySetEqual(Approval.objects.all(), [approval])

        approval.delete()

        # pretty
        assertQuerySetEqual(Approval.objects.all(), Approval.objects.none())
        user.refresh_from_db()
        assertQuerySetEqual(user.approvals.all(), Approval.objects.none())
        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.approval is None

    def test_deleting_an_approval_prefer_origin_values(self):
        job_application = JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.EI,
        )
        job_application.accept(user=job_application.to_company.members.first())

        approval = job_application.approval

        assert approval.origin_siae_siret == job_application.to_company.siret

        other_application = JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
            to_company__kind=CompanyKind.ETTI,
            job_seeker_id=job_application.job_seeker_id,  # Use pk to avoid cached_property invalidations
        )
        other_application.accept(user=other_application.to_company.members.first())

        job_application.cancel(user=job_application.to_company.members.first())
        job_application.delete()

        origin_siae = job_application.to_company
        approval.delete()
        # Approval was successfully deleted
        assert Approval.objects.first() is None
        # And the cancelled approval kept the original values (from the first application)
        cancelled_approval = CancelledApproval.objects.get()
        assert cancelled_approval.origin_siae_kind == CompanyKind.EI
        assert cancelled_approval.origin_siae_siret == origin_siae.siret

    def test_deleting_an_approval_without_application_linked(self):
        job_application = JobApplicationFactory(
            state=JobApplicationState.PROCESSING,
        )
        job_application.accept(user=job_application.to_company.members.first())

        approval = job_application.approval

        assert approval.origin_siae_siret == job_application.to_company.siret
        origin_siae = job_application.to_company

        # Admin action
        job_application.delete()

        approval.delete()
        # Approval was successfully deleted
        assert Approval.objects.first() is None
        # And the cancelled approval kept the original values (from the first application)
        cancelled_approval = CancelledApproval.objects.get()
        assert cancelled_approval.origin_siae_kind == origin_siae.kind
        assert cancelled_approval.origin_siae_siret == origin_siae.siret

    def test_date_modification_causes_notification_pending(self):
        approval = ApprovalFactory(pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS)
        approval.start_at += datetime.timedelta(days=1)
        approval.save(update_fields=("start_at",))
        approval.refresh_from_db()
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING

        approval.pe_notification_status = api_enums.PEApiNotificationStatus.ERROR
        approval.save(update_fields=("pe_notification_status",))

        approval.refresh_from_db()
        approval.end_at += datetime.timedelta(days=1)
        approval.save(update_fields=("end_at",))
        approval.refresh_from_db()
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING

    def test_date_and_pe_notification_status_modification_impossible(self):
        approval = ApprovalFactory(pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS)
        approval.start_at += datetime.timedelta(days=1)
        approval.pe_notification_status = api_enums.PEApiNotificationStatus.SHOULD_RETRY
        with pytest.raises(ProgrammingError):
            approval.save()


class PoleEmploiApprovalModelTest(TestCase):
    def test_format_name_as_pole_emploi(self):
        assert PoleEmploiApproval.format_name_as_pole_emploi(" François") == "FRANCOIS"
        assert PoleEmploiApproval.format_name_as_pole_emploi("M'Hammed ") == "M'HAMMED"
        assert PoleEmploiApproval.format_name_as_pole_emploi("     jean kevin  ") == "JEAN KEVIN"
        assert PoleEmploiApproval.format_name_as_pole_emploi("     Jean-Kevin  ") == "JEAN-KEVIN"
        assert PoleEmploiApproval.format_name_as_pole_emploi("Kertész István") == "KERTESZ ISTVAN"
        assert PoleEmploiApproval.format_name_as_pole_emploi("Backer-Grøndahl") == "BACKER-GRONDAHL"
        assert PoleEmploiApproval.format_name_as_pole_emploi("désirée artôt") == "DESIREE ARTOT"
        assert PoleEmploiApproval.format_name_as_pole_emploi("N'Guessan") == "N'GUESSAN"
        assert PoleEmploiApproval.format_name_as_pole_emploi("N Guessan") == "N GUESSAN"

    def test_number_with_spaces(self):
        pole_emploi_approval = PoleEmploiApprovalFactory(number="400121910144")
        expected = "40012 19 10144"
        assert pole_emploi_approval.number_with_spaces == expected

    def test_is_valid(self):
        now_date = timezone.localdate() - relativedelta(months=1)
        now = datetime.datetime(year=now_date.year, month=now_date.month, day=now_date.day)

        with mock.patch("django.utils.timezone.now", side_effect=lambda: now):
            # Ends today.
            end_at = now_date
            start_at = end_at - relativedelta(years=2)
            approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
            assert approval.is_valid()

            # Ended yesterday.
            end_at = now_date - relativedelta(days=1)
            start_at = end_at - relativedelta(years=2)
            approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
            assert not approval.is_valid()

            # Starts tomorrow.
            start_at = now_date + relativedelta(days=1)
            end_at = start_at + relativedelta(years=2)
            approval = PoleEmploiApprovalFactory(start_at=start_at, end_at=end_at)
            assert approval.is_valid()

    @freeze_time("2022-11-22")
    def test_remainder(self):
        pole_emploi_approval = PoleEmploiApprovalFactory(
            start_at=datetime.date(2021, 3, 25),
            end_at=datetime.date(2023, 3, 24),
        )
        assert pole_emploi_approval.remainder == datetime.timedelta(days=123)


class PoleEmploiApprovalManagerTest(TestCase):
    def test_find_for_no_queries(self):
        user = JobSeekerFactory(jobseeker_profile__pole_emploi_id="")
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 0

        user = JobSeekerFactory(birthdate=None)
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 0

    def test_find_for_user(self):
        # given a User, ensure we can find a PE approval using its pole_emploi_id and not the others.
        user = JobSeekerFactory(with_pole_emploi_id=True)
        today = datetime.date.today()
        pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=today,
        )
        # just another approval, to be sure we don't find the other one "by chance"
        PoleEmploiApprovalFactory()
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 1
        assert search_results.first() == pe_approval

        # ensure we can find **all** PE approvals using their pole_emploi_id and not the others.
        other_valid_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.birthdate,
            start_at=today - datetime.timedelta(days=1),
        )
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 2
        assert search_results[0] == pe_approval
        assert search_results[1] == other_valid_approval

        # ensure we **also** find PE approvals using the user's NIR.
        nir_approval = PoleEmploiApprovalFactory(
            nir=user.jobseeker_profile.nir,
            start_at=today - datetime.timedelta(days=2),
        )
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 3
        assert search_results[0] == pe_approval
        assert search_results[1] == other_valid_approval
        assert search_results[2] == nir_approval

        # since we can have multiple PE approvals with the same nir, let's fetch them all
        other_nir_approval = PoleEmploiApprovalFactory(
            nir=user.jobseeker_profile.nir,
            start_at=today - datetime.timedelta(days=3),
        )
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 4
        assert search_results[0] == pe_approval
        assert search_results[1] == other_valid_approval
        assert search_results[2] == nir_approval
        assert search_results[3] == other_nir_approval

        # ensure it's not an issue if the PE approval matches both NIR, pole_emploi_id and birthdate.
        nir_approval.birthdate = user.birthdate
        nir_approval.pole_emploi_id = user.jobseeker_profile.pole_emploi_id
        nir_approval.save()

        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 4
        assert search_results[0] == pe_approval
        assert search_results[1] == other_valid_approval
        assert search_results[2] == nir_approval
        assert search_results[3] == other_nir_approval

    def test_find_for_no_nir(self):
        user = JobSeekerFactory(jobseeker_profile__nir="")
        PoleEmploiApprovalFactory(nir=None)  # entirely unrelated
        with self.assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 0


class AutomaticApprovalAdminViewsTest(TestCase):
    def test_create_approval_with_a_wrong_number(self):
        """
        We cannot create an approval starting with ASP_ITOu_PREFIX
        """
        user = ItouStaffFactory()
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="add_approval")
        user.user_permissions.add(permission)

        self.client.force_login(user)

        url = reverse("admin:approvals_approval_add")

        diagnosis = EligibilityDiagnosisFactory()
        post_data = {
            "start_at": "01/01/2100",
            "end_at": "31/12/2102",
            "user": diagnosis.job_seeker_id,
            "eligibility_diagnosis": diagnosis.pk,
            "origin": Origin.DEFAULT,  # Will be overriden
            "number": "XXXXX1234567",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        self.assertFormError(
            response.context["adminform"],
            "number",
            [ApprovalAdminForm.ERROR_NUMBER],
        )

    def test_edit_approval_with_a_wrong_number(self):
        """
        Given an existing approval, when setting a different number,
        then the save is rejected.
        """
        user = ItouStaffFactory()
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="change_approval")
        user.user_permissions.add(permission)

        self.client.force_login(user)

        job_app = JobApplicationFactory(with_approval=True)
        approval = job_app.approval

        url = reverse("admin:approvals_approval_change", args=[approval.pk])

        response = self.client.get(url)
        assert response.status_code == 200

        post_data = {
            "start_at": approval.start_at.strftime("%d/%m/%Y"),
            "end_at": approval.end_at.strftime("%d/%m/%Y"),
            "user": job_app.job_seeker.pk,
            "number": "XXXXX1234567",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        self.assertFormError(
            response.context["adminform"],
            "number",
            [ApprovalAdminForm.ERROR_NUMBER_CANNOT_BE_CHANGED % approval.number],
        )

    def test_edit_approval_with_an_existing_employee_record(self):
        user = ItouStaffFactory()
        user.user_permissions.add(
            Permission.objects.get(
                content_type=ContentType.objects.get_for_model(Approval),
                codename="change_approval",
            )
        )
        self.client.force_login(user)

        approval = ApprovalFactory()
        employee_record = EmployeeRecordFactory(approval_number=approval.number, status=Status.PROCESSED)

        response = self.client.post(
            reverse("admin:approvals_approval_change", args=[approval.pk]),
            data=model_to_dict(
                approval,
                fields={
                    "start_at",
                    "end_at",
                    "user",
                    "number",
                    "origin",
                    "eligibility_diagnosis",
                },
            ),
            follow=True,
        )
        assert response.status_code == 200
        assert (
            f"Il existe une ou plusieurs fiches salarié bloquantes "
            f'(<a href="/admin/employee_record/employeerecord/{employee_record.pk}/change/">{employee_record.pk}</a>) '
            f"pour la modification de ce PASS IAE ({approval.number})." == str(list(response.context["messages"])[0])
        )

    def test_create_approval(self):
        user = ItouStaffFactory()
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="add_approval")
        user.user_permissions.add(permission)
        self.client.force_login(user)

        diagnosis = EligibilityDiagnosisFactory()
        other_job_seeker = JobSeekerFactory()
        url = reverse("admin:approvals_approval_add")

        post_data = {
            "start_at": "01/01/2100",
            "end_at": "31/12/2102",
            "user": other_job_seeker.pk,
            "eligibility_diagnosis": diagnosis.pk,
            "origin": Origin.DEFAULT,  # Will be overriden
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        self.assertFormError(
            response.context["adminform"],
            "eligibility_diagnosis",
            ["Le diagnostic doit appartenir au même utilisateur que le PASS"],
        )
        assert not Approval.objects.exists()

        post_data = {
            "start_at": "01/01/2100",
            "end_at": "31/12/2102",
            "user": diagnosis.job_seeker_id,
            "eligibility_diagnosis": diagnosis.pk,
            "origin": Origin.DEFAULT,  # Will be overriden
        }
        response = self.client.post(url, data=post_data)
        assert Approval.objects.count() == 1
        approval = Approval.objects.get()
        assert approval.eligibility_diagnosis == diagnosis
        assert approval.origin == Origin.ADMIN

    def test_create_pe_approval_manually(self):
        user = ItouStaffFactory()
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="add_approval")
        user.user_permissions.add(permission)
        self.client.force_login(user)

        other_job_seeker = JobSeekerFactory()
        url = reverse("admin:approvals_approval_add")

        post_data = {
            "start_at": "01/01/2100",
            "end_at": "31/12/2102",
            "user": other_job_seeker.pk,
            "number": "123456789123",
            "origin": Origin.DEFAULT,  # Will be overriden
        }
        self.client.post(url, data=post_data)
        approval = Approval.objects.get()
        assert approval.origin == Origin.PE_APPROVAL


@pytest.mark.usefixtures("unittest_compatibility")
class CustomApprovalAdminViewsTest(MessagesTestMixin, TestCase):
    @pytest.mark.ignore_unknown_variable_template_error
    def test_manually_add_approval(self):
        # When a Pôle emploi ID has been forgotten and the user has no NIR, an approval must be delivered
        # with a manual verification.
        job_seeker = JobSeekerFactory(
            jobseeker_profile__nir="",
            jobseeker_profile__pole_emploi_id="",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            approval=None,
            approval_number_sent_by_email=False,
        )
        job_application.accept(user=job_application.to_company.members.first())

        # Delete emails sent by previous transition.
        mail.outbox = []

        url = reverse("admin:approvals_approval_manually_add_approval", args=[job_application.pk])

        # Not enough perms.
        user = JobSeekerFactory()
        self.client.force_login(user)
        response = self.client.get(url)
        assert response.status_code == 302

        # With good perms.
        user = ItouStaffFactory()
        self.client.force_login(user)
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="add_approval")
        user.user_permissions.add(permission)
        response = self.client.get(url)
        assert response.status_code == 200
        assert response.context["form"].initial == {
            "start_at": job_application.hiring_start_at,
            "end_at": Approval.get_default_end_date(job_application.hiring_start_at),
        }

        # Without an eligibility diangosis on the job application.
        eligibility_diagnosis = job_application.eligibility_diagnosis
        job_application.eligibility_diagnosis = None
        job_application.save()
        response = self.client.get(url, follow=True)
        self.assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Impossible de créer un PASS IAE car la candidature n'a pas de diagnostique d'éligibilité.",
                )
            ],
        )

        # Put back the eligibility diangosis
        job_application.eligibility_diagnosis = eligibility_diagnosis
        job_application.save()

        # Les numéros avec le préfixe `ASP_ITOU_PREFIX` ne doivent pas pouvoir
        # être délivrés à la main dans l'admin.
        post_data = {
            "start_at": job_application.hiring_start_at.strftime("%d/%m/%Y"),
            "end_at": job_application.hiring_end_at.strftime("%d/%m/%Y"),
            "number": f"{Approval.ASP_ITOU_PREFIX}1234567",
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 200
        assert "number" in response.context["form"].errors, ApprovalAdminForm.ERROR_NUMBER

        # Create an approval.
        post_data = {
            "start_at": job_application.hiring_start_at.strftime("%d/%m/%Y"),
            "end_at": job_application.hiring_end_at.strftime("%d/%m/%Y"),
        }
        response = self.client.post(url, data=post_data)
        assert response.status_code == 302

        # An approval should have been created, attached to the job
        # application, and sent by email.
        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.approval_number_sent_by_email
        assert job_application.approval_number_sent_at is not None
        assert job_application.approval_manually_delivered_by == user
        assert job_application.approval_delivery_mode == job_application.APPROVAL_DELIVERY_MODE_MANUAL

        approval = job_application.approval
        assert approval.created_by == user
        assert approval.user == job_application.job_seeker
        assert approval.origin == Origin.ADMIN
        assert approval.eligibility_diagnosis == job_application.eligibility_diagnosis

        assert approval.origin_sender_kind == SenderKind.JOB_SEEKER
        assert approval.origin_siae_kind == job_application.to_company.kind
        assert approval.origin_siae_siret == job_application.to_company.siret
        assert not approval.origin_prescriber_organization_kind

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert approval.number_with_spaces in email.body

    def test_employee_record_status(self):
        # When an employee record exists
        employee_record = EmployeeRecordFactory()
        url = reverse("admin:employee_record_employeerecord_change", args=[employee_record.id])
        msg = JobApplicationInline.employee_record_status(employee_record.job_application)
        assert msg == f'<a href="{url}"><b>Nouvelle (ID: {employee_record.pk})</b></a>'

        # When the job application will lead to a duplicate employee record but is still proposed
        job_application = JobApplicationFactory(
            state=JobApplicationState.ACCEPTED,
            to_company=employee_record.job_application.to_company,
            approval=employee_record.job_application.approval,
        )
        msg = JobApplicationInline.employee_record_status(job_application)
        assert msg == "En attente de création (doublon)"

        # When employee record creation is disabled for that job application
        job_application = JobApplicationFactory(create_employee_record=False)
        msg = JobApplicationInline.employee_record_status(job_application)
        assert msg == "Non proposé à la création"

        # When hiring start date is before employee record availability date
        job_application = JobApplicationFactory(hiring_start_at="2021-09-26")
        msg = JobApplicationInline.employee_record_status(job_application)
        assert msg == "Date de début du contrat avant l'interopérabilité"

        # When employee records are allowed (or not) for the SIAE
        for kind in CompanyKind:
            with self.subTest("SIAE doesn't use employee records", kind=kind):
                job_application = JobApplicationFactory(with_approval=True, to_company__kind=kind)
                msg = JobApplicationInline.employee_record_status(job_application)
                if not job_application.to_company.can_use_employee_record:
                    assert msg == "La SIAE ne peut pas utiliser la gestion des fiches salarié"
                else:
                    assert msg == "En attente de création"

        # When an employee record already exists for the candidate
        employee_record = EmployeeRecordFactory(status=Status.READY)
        job_application = JobApplicationFactory(
            to_company=employee_record.job_application.to_company,
            approval=employee_record.job_application.approval,
        )
        msg = JobApplicationInline.employee_record_status(job_application)
        assert msg == "Une fiche salarié existe déjà pour ce candidat"


class SuspensionQuerySetTest(TestCase):
    def test_in_progress(self):
        start_at = timezone.localdate()  # Starts today so it's in progress.
        expected_num = 5
        SuspensionFactory.create_batch(expected_num, start_at=start_at)
        assert expected_num == Suspension.objects.in_progress().count()

    def test_not_in_progress(self):
        start_at = timezone.localdate() - relativedelta(years=1)
        end_at = start_at + relativedelta(months=6)
        expected_num = 3
        SuspensionFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        assert expected_num == Suspension.objects.not_in_progress().count()

    def test_old(self):
        # Starting today.
        start_at = timezone.localdate()
        SuspensionFactory.create_batch(2, start_at=start_at)
        assert 0 == Suspension.objects.old().count()
        # Old.
        start_at = timezone.localdate() - relativedelta(years=3)
        end_at = Suspension.get_max_end_at(start_at)
        expected_num = 3
        SuspensionFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        assert expected_num == Suspension.objects.old().count()


class SuspensionModelTest(TestCase):
    def test_clean(self):
        today = timezone.localdate()
        start_at = today - relativedelta(days=Suspension.MAX_RETROACTIVITY_DURATION_DAYS * 2)
        end_at = start_at + relativedelta(months=2)
        approval = ApprovalFactory.build(start_at=start_at, end_at=end_at, eligibility_diagnosis=None)

        # Suspension.start_date is too old.
        suspension = SuspensionFactory.build(approval=approval)
        suspension.start_at = start_at - relativedelta(days=Suspension.MAX_RETROACTIVITY_DURATION_DAYS + 1)
        with pytest.raises(ValidationError):
            suspension.clean()

        # suspension.end_at < suspension.start_at
        suspension = SuspensionFactory.build(approval=approval)
        suspension.start_at = start_at
        suspension.end_at = start_at - relativedelta(months=1)
        with pytest.raises(ValidationError):
            suspension.clean()

        # Suspension.start_at is in the future.
        suspension = SuspensionFactory.build(approval=approval)
        suspension.start_at = today + relativedelta(days=2)
        suspension.end_at = end_at
        with pytest.raises(ValidationError):
            suspension.clean()

    def test_duration(self):
        expected_duration = datetime.timedelta(days=2)
        start_at = timezone.localdate()
        end_at = start_at + expected_duration
        suspension = SuspensionFactory(start_at=start_at, end_at=end_at)
        assert suspension.duration == expected_duration

    def test_start_in_approval_boundaries(self):
        start_at = timezone.localdate()
        end_at = start_at + relativedelta(days=10)
        approval = ApprovalFactory(start_at=start_at, end_at=end_at)
        # Build provides a local object without saving it to the database.
        suspension = SuspensionFactory.build(approval=approval, start_at=start_at)

        # Equal to lower boundary.
        assert suspension.start_in_approval_boundaries

        # In boundaries.
        suspension.start_at = approval.start_at + relativedelta(days=5)
        assert suspension.start_in_approval_boundaries

        # Equal to upper boundary.
        suspension.start_at = approval.end_at
        assert suspension.start_in_approval_boundaries

        # Before lower boundary.
        suspension.start_at = approval.start_at - relativedelta(days=1)
        assert not suspension.start_in_approval_boundaries

        # After upper boundary.
        suspension.start_at = approval.end_at + relativedelta(days=1)
        assert not suspension.start_in_approval_boundaries

    def test_is_in_progress(self):
        start_at = timezone.localdate() - relativedelta(days=10)
        # Build provides a local object without saving it to the database.
        suspension = SuspensionFactory.build(start_at=start_at, approval__eligibility_diagnosis=None)
        assert suspension.is_in_progress

    def test_displayed_choices_for_siae(self):
        # EI and ACI kind have one more choice
        for kind in [CompanyKind.EI, CompanyKind.ACI]:
            company = CompanyFactory(kind=kind)
            result = Suspension.Reason.displayed_choices_for_siae(company)
            assert len(result) == 5
            assert result[-1][0] == Suspension.Reason.CONTRAT_PASSERELLE.value

        # Some other cases
        for kind in [CompanyKind.ETTI, CompanyKind.AI]:
            company = CompanyFactory(kind=kind)
            result = Suspension.Reason.displayed_choices_for_siae(company)
            assert len(result) == 4

    def test_next_min_start_date(self):
        today = timezone.localdate()
        start_at = today - relativedelta(days=10)

        job_application_1 = JobApplicationFactory(with_approval=True, hiring_start_at=today)
        job_application_2 = JobApplicationFactory(with_approval=True, hiring_start_at=start_at)
        job_application_3 = JobApplicationFactory(
            with_approval=True, hiring_start_at=start_at, origin=Origin.PE_APPROVAL
        )
        job_application_4 = JobApplicationFactory(with_approval=True, hiring_start_at=None, origin=Origin.PE_APPROVAL)

        # TODO: must be checked with PO
        # - empty hiring start date
        # - `with_retroactivity_limitation` set to `False`
        # What should be the expected suspension mimimum start date ?

        min_start_at = Suspension.next_min_start_at(job_application_1.approval)
        assert min_start_at == today

        # Same rules apply for PE approval and PASS IAE
        min_start_at = Suspension.next_min_start_at(job_application_2.approval)
        assert min_start_at == start_at
        min_start_at = Suspension.next_min_start_at(job_application_3.approval)
        assert min_start_at == start_at

        # Fix a type error when creating a suspension:
        min_start_at = Suspension.next_min_start_at(job_application_4.approval)
        assert min_start_at == today - datetime.timedelta(days=Suspension.MAX_RETROACTIVITY_DURATION_DAYS)

    def test_next_min_start_date_without_job_application(self):
        today = timezone.localdate()
        approval = ApprovalFactory()
        company = CompanyFactory()
        suspension = Suspension(approval=approval, siae=company, start_at=today, end_at=today)
        suspension.clean()

    def test_overlapping_dates(self):
        approval = ApprovalFactory()
        SuspensionFactory(approval=approval)
        with pytest.raises(IntegrityError):
            SuspensionFactory(approval=approval)


class SuspensionModelTestTrigger(TestCase):
    def test_save(self):
        """
        Test `trigger_update_approval_end_at` with SQL INSERT.
        An approval's `end_at` is automatically pushed forward when it's suspended.
        """
        start_at = timezone.localdate()

        approval = ApprovalFactory(start_at=start_at, pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS)
        initial_updated_at = approval.updated_at
        initial_duration = approval.duration

        suspension = SuspensionFactory(approval=approval, start_at=start_at)

        approval.refresh_from_db()
        assert approval.duration == initial_duration + suspension.duration
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING
        assert approval.updated_at != initial_updated_at

    def test_delete(self):
        """
        Test `trigger_update_approval_end_at` with SQL DELETE.
        An approval's `end_at` is automatically pushed back when it's suspended.
        """
        start_at = timezone.localdate()

        approval = ApprovalFactory(start_at=start_at, pe_notification_status=api_enums.PEApiNotificationStatus.ERROR)
        initial_updated_at = approval.updated_at
        initial_duration = approval.duration

        suspension = SuspensionFactory(approval=approval, start_at=start_at)
        approval.refresh_from_db()
        assert approval.duration == initial_duration + suspension.duration
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING

        suspension.delete()

        approval.refresh_from_db()
        assert approval.duration == initial_duration
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING
        assert approval.updated_at != initial_updated_at

    def test_save_and_edit(self):
        """
        Test `trigger_update_approval_end_at` with SQL UPDATE.
        An approval's `end_at` is automatically pushed back and forth when
        one of its suspension is saved, then edited to be shorter.
        """
        start_at = timezone.localdate()

        approval = ApprovalFactory(
            start_at=start_at, pe_notification_status=api_enums.PEApiNotificationStatus.SHOULD_RETRY
        )
        initial_updated_at = approval.updated_at
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
        assert suspension_duration_1 != suspension_duration_2
        # Check approval duration.
        assert initial_duration != approval_duration_2
        assert approval_duration_2 != approval_duration_3
        assert approval_duration_3 == initial_duration + suspension_duration_2
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING
        assert approval.updated_at != initial_updated_at


class ProlongationQuerySetTest(TestCase):
    def test_in_progress(self):
        start_at = timezone.localdate()  # Starts today so it's in progress.
        expected_num = 5
        ProlongationFactory.create_batch(expected_num, start_at=start_at)
        assert expected_num == Prolongation.objects.in_progress().count()

    def test_not_in_progress(self):
        start_at = timezone.localdate() - relativedelta(years=1)
        end_at = start_at + relativedelta(months=6)
        expected_num = 3
        ProlongationFactory.create_batch(expected_num, start_at=start_at, end_at=end_at)
        assert expected_num == Prolongation.objects.not_in_progress().count()


class ProlongationManagerTest(TestCase):
    def test_get_cumulative_duration_for(self):
        approval = ApprovalFactory()

        prolongation1_days = 30

        prolongation1 = ProlongationFactory(
            approval=approval,
            start_at=approval.end_at,
            end_at=approval.end_at + relativedelta(days=prolongation1_days),
            reason=ProlongationReason.COMPLETE_TRAINING.value,
        )

        prolongation2_days = 14

        prolongation2 = ProlongationFactory(
            approval=approval,
            start_at=prolongation1.end_at,
            end_at=prolongation1.end_at + relativedelta(days=prolongation2_days),
            reason=ProlongationReason.RQTH.value,
        )

        prolongation3_days = 60

        ProlongationFactory(
            approval=approval,
            start_at=prolongation2.end_at,
            end_at=prolongation2.end_at + relativedelta(days=prolongation3_days),
            reason=ProlongationReason.RQTH.value,
        )

        expected_duration = datetime.timedelta(days=prolongation2_days + prolongation3_days)
        assert expected_duration == Prolongation.objects.get_cumulative_duration_for(
            approval, ProlongationReason.RQTH.value
        )


class ProlongationModelTestTrigger(TestCase):
    """
    Test `update_approval_end_at`.
    """

    def test_save(self):
        """
        Test `update_approval_end_at` with SQL INSERT.
        An approval's `end_at` is automatically pushed forward when it is prolongated.
        """
        start_at = timezone.localdate()

        approval = ApprovalFactory(start_at=start_at, pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS)
        initial_updated_at = approval.updated_at
        initial_duration = approval.duration

        prolongation = ProlongationFactory(approval=approval, start_at=start_at)

        approval.refresh_from_db()
        assert approval.duration == initial_duration + prolongation.duration
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING
        assert approval.updated_at != initial_updated_at

    def test_delete(self):
        """
        Test `update_approval_end_at` with SQL DELETE.
        An approval's `end_at` is automatically pushed back when its prolongation
        is deleted.
        """
        start_at = timezone.localdate()

        approval = ApprovalFactory(start_at=start_at, pe_notification_status=api_enums.PEApiNotificationStatus.ERROR)
        initial_updated_at = approval.updated_at
        initial_duration = approval.duration

        prolongation = ProlongationFactory(approval=approval, start_at=start_at)
        approval.refresh_from_db()
        assert approval.duration == initial_duration + prolongation.duration
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING

        prolongation.delete()

        approval.refresh_from_db()
        assert approval.duration == initial_duration
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING
        assert approval.updated_at != initial_updated_at

    def test_save_and_edit(self):
        """
        Test `update_approval_end_at` with SQL UPDATE.
        An approval's `end_at` is automatically pushed back and forth when
        one of its valid prolongation is saved, then edited to be shorter.
        """
        start_at = timezone.localdate()

        approval = ApprovalFactory(
            start_at=start_at, pe_notification_status=api_enums.PEApiNotificationStatus.SHOULD_RETRY
        )
        initial_updated_at = approval.updated_at
        initial_approval_duration = approval.duration

        # New prolongation.
        prolongation = ProlongationFactory(approval=approval, start_at=start_at)
        prolongation_duration_1 = prolongation.duration
        approval.refresh_from_db()
        approval_duration_2 = approval.duration

        # Edit prolongation to be shorter.
        prolongation.end_at -= relativedelta(days=2)
        prolongation.save()
        prolongation_duration_2 = prolongation.duration
        approval.refresh_from_db()
        approval_duration_3 = approval.duration

        # Prolongation durations must be different.
        assert prolongation_duration_1 != prolongation_duration_2

        # Approval durations must be different.
        assert initial_approval_duration != approval_duration_2
        assert approval_duration_2 != approval_duration_3

        assert approval_duration_3 == initial_approval_duration + prolongation_duration_2
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING
        assert approval.updated_at != initial_updated_at


class ProlongationModelTestConstraint(TestCase):
    def test_exclusion_constraint(self):
        approval = ApprovalFactory()

        initial_prolongation = ProlongationFactory(
            approval=approval,
            start_at=approval.end_at,
        )

        with pytest.raises(IntegrityError):
            # A prolongation that starts the same day as initial_prolongation.
            ProlongationFactory(
                approval=approval,
                declared_by_siae=initial_prolongation.declared_by_siae,
                start_at=approval.end_at,
            )


@pytest.mark.usefixtures("unittest_compatibility")
class ProlongationModelTest(TestCase):
    def test_clean_with_wrong_start_at(self):
        """
        Given an existing prolongation, when setting a wrong `start_at`
        then a call to `clean()` is rejected.
        """

        approval = ApprovalFactory()

        start_at = approval.end_at - relativedelta(days=2)
        end_at = start_at + relativedelta(months=1)

        # We need an object without `pk` to test `clean()`, so we use `build`
        # which provides a local object without saving it to the database.
        prolongation = ProlongationFactory.build(
            start_at=start_at,
            end_at=end_at,
            approval=approval,
            # Force unneeded dependant fields to None as we are using .build()
            declared_by=None,
            declared_by_siae=None,
            validated_by=None,
        )

        with pytest.raises(ValidationError) as error:
            prolongation.clean()
        assert "La date de début doit être la même que la date de fin du PASS IAE" in error.value.message

    def test_clean_minimum_duration_error(self):
        prolongation = ProlongationFactory()

        # When end_at before start_at
        prolongation.end_at = prolongation.start_at - datetime.timedelta(days=1)
        with pytest.raises(ValidationError) as error:
            prolongation.clean()
        assert error.match("La durée minimale doit être d'au moins un jour.")

        # When end_at is the same day than start_at
        prolongation.end_at = prolongation.start_at
        with pytest.raises(ValidationError) as error:
            prolongation.clean()
        assert error.match("La durée minimale doit être d'au moins un jour.")

        # When end_at if after start_at
        prolongation.end_at = prolongation.start_at + datetime.timedelta(days=1)
        prolongation.clean()

    def test_clean_too_long_reason_duration_error(self):
        for reason, info in Prolongation.MAX_CUMULATIVE_DURATION.items():
            with self.subTest(reason=reason):
                prolongation = ProlongationFactory(
                    reason=reason,
                    end_at=factory.LazyAttribute(
                        lambda obj: obj.start_at + info["duration"] + datetime.timedelta(days=1)
                    ),
                    declared_by_siae__kind=CompanyKind.AI,
                )
                with pytest.raises(ValidationError) as error:
                    prolongation.clean()
                assert error.match("La durée totale est trop longue pour le motif")

    def test_clean_end_at_do_not_block_edition(self):
        max_cumulative_duration = Prolongation.MAX_CUMULATIVE_DURATION[ProlongationReason.SENIOR]["duration"]
        first_prolongation = ProlongationFactory(
            reason=ProlongationReason.SENIOR,
        )
        first_prolongation.clean()

        # Create a second prolongation to max-out duration
        second_prolongation = ProlongationFactory(
            approval=first_prolongation.approval,
            reason=ProlongationReason.SENIOR,
            start_at=first_prolongation.end_at,
            end_at=first_prolongation.start_at + max_cumulative_duration,
        )
        second_prolongation.clean()

        # Edit last prolongation to make space for a new one
        second_prolongation.end_at -= datetime.timedelta(days=30)
        second_prolongation.clean()
        second_prolongation.save()

        third_prolongation = ProlongationFactory(
            approval=first_prolongation.approval,
            reason=ProlongationReason.SENIOR,
            start_at=second_prolongation.end_at,
            end_at=first_prolongation.start_at + max_cumulative_duration,
        )
        third_prolongation.clean()

    def test_clean_limit_particular_difficulties_to_some_siaes_error(self):
        prolongation = ProlongationFactory(
            reason=ProlongationReason.PARTICULAR_DIFFICULTIES,
        )

        for kind in CompanyKind:
            with self.subTest(kind=kind):
                prolongation.declared_by_siae.kind = kind
                if kind in [CompanyKind.AI, CompanyKind.ACI]:
                    prolongation.clean()
                else:
                    with pytest.raises(ValidationError) as error:
                        prolongation.clean()
                    assert error.match(r"Le motif .* est réservé aux AI et ACI.")

    def test_clean_not_authorized_prescriber_error(self):
        prolongation = ProlongationFactory()
        prolongation.clean()  # With an authorized prescriber

        # Unauthorize the prescriber organization
        prolongation.validated_by.prescriberorganization_set.update(is_authorized=False)
        del prolongation.validated_by.is_prescriber_with_authorized_org

        with pytest.raises(ValidationError) as error:
            prolongation.clean()
        assert error.match("Cet utilisateur n'est pas un prescripteur habilité.")

    def test_get_max_end_at(self):
        start_at = datetime.date(2021, 2, 1)
        approval = ApprovalFactory()
        for reason, expected_max_end_at in [
            (ProlongationReason.SENIOR_CDI, datetime.date(2031, 1, 30)),  # 3650 days (~10 years).
            (ProlongationReason.COMPLETE_TRAINING, datetime.date(2023, 2, 1)),  # 730 days (2 years).
            (ProlongationReason.RQTH, datetime.date(2024, 2, 1)),  # 1095 days (3 years).
            (ProlongationReason.SENIOR, datetime.date(2026, 1, 31)),  # 1825 days (~5 years).
            (ProlongationReason.PARTICULAR_DIFFICULTIES, datetime.date(2024, 2, 1)),  # 1095 days (3 years).
            (ProlongationReason.HEALTH_CONTEXT, datetime.date(2022, 2, 1)),  # 365 days.
        ]:
            with self.subTest(reason):
                assert Prolongation.get_max_end_at(approval.pk, start_at, reason) == expected_max_end_at

    @freeze_time("2023-08-21")
    def test_year_after_year_prolongation(self):
        today = datetime.date(2023, 8, 21)
        approval = ApprovalFactory(start_at=today - relativedelta(years=2), end_at=today)
        reason = ProlongationReason.PARTICULAR_DIFFICULTIES
        # Approval.end_at is inclusive.
        start_at = today + datetime.timedelta(days=1)
        for _ in range(3):
            end = start_at + datetime.timedelta(days=365)
            ProlongationFactory(
                approval=approval,
                start_at=start_at,
                end_at=end,
                reason=reason,
            )
            start_at = end
        approval.refresh_from_db()
        assert approval.end_at == datetime.date(2026, 8, 20)
        # Total of three years is used up.
        assert Prolongation.get_max_end_at(
            approval.pk,
            datetime.date(2026, 8, 21),
            reason,
            # Prolongation end date is exclusive, this is an empty day [2026-08-21,2026-08-21).
        ) == datetime.date(2026, 8, 21)

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
            reason=ProlongationReason.COMPLETE_TRAINING.value,
        )

        approval.refresh_from_db()
        assert prolongation1.end_at == expected_end_at
        assert approval.end_at == expected_end_at

        # Prolongation 2.

        expected_end_at = datetime.date(2021, 4, 30)

        prolongation2 = ProlongationFactory(
            approval=approval,
            start_at=prolongation1.end_at,
            end_at=expected_end_at,
            reason=ProlongationReason.COMPLETE_TRAINING.value,
        )

        approval.refresh_from_db()
        assert prolongation2.end_at == expected_end_at
        assert approval.end_at == expected_end_at

        # Check duration.

        assert approval.duration == initial_approval_duration + prolongation1.duration + prolongation2.duration


class ApprovalConcurrentModelTest(TransactionTestCase):
    """
    Uses TransactionTestCase that truncates all tables after every test, instead of TestCase
    that uses transaction.
    This way we can appropriately test the select_for_update() behaviour.
    """

    def test_nominal_process(self):
        with transaction.atomic():
            # create a first approval out of the blue, ensure the number is correct.
            approval_1 = ApprovalFactory.build(user=JobSeekerFactory(), number=None, origin_pe_approval=True)
            assert Approval.objects.count() == 0
            approval_1.save()
            assert approval_1.number == "XXXXX0000001"
            assert Approval.objects.count() == 1

            # if a second one is created after the save, no worries man.
            approval_2 = ApprovalFactory.build(user=JobSeekerFactory(), number=None, origin_pe_approval=True)
            approval_2.save()
            assert approval_2.number == "XXXXX0000002"

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
            ApprovalFactory(user=JobSeekerFactory(), number=None)

        user1 = JobSeekerFactory()
        user2 = JobSeekerFactory()

        approval = None
        approval2 = None

        # We are going to simulate two concurrent requests inside two atomic transaction blocks.
        # The goal is to simulate two concurrent Approval.accept() requests.
        # Let's do like they do in the Django tests themselves: use threads and sleep().
        def first_request():
            nonlocal approval
            try:
                with transaction.atomic():
                    approval = ApprovalFactory.build(
                        # eligibility_diagnosis=None,
                        user=user1,
                        number=Approval.get_next_number(),
                        origin_pe_approval=True,
                    )
                    time.sleep(0.2)  # sleep long enough for the concurrent request to start
                    approval.save()
            finally:
                connection.close()

        def concurrent_request():
            nonlocal approval2
            try:
                with transaction.atomic():
                    time.sleep(0.1)  # ensure we are not the first to take the lock
                    approval2 = ApprovalFactory.build(
                        # eligibility_diagnosis=None,
                        user=user2,
                        number=Approval.get_next_number(),
                        origin_pe_approval=True,
                    )
                    time.sleep(0.2)  # sleep long enough to save() after the first request's save()
                    approval2.save()
            finally:
                connection.close()

        t1 = threading.Thread(target=first_request)
        t2 = threading.Thread(target=concurrent_request)
        t1.start()
        t2.start()
        t1.join()
        t2.join()  # without the singleton we would suffer from IntegrityError here

        assert approval.number == "XXXXX0000002"
        assert approval2.number == "XXXXX0000003"


class PENotificationMixinTestCase(TestCase):
    def test_base_values(self):
        approval = ApprovalFactory()
        assert approval.pe_notification_status == "notification_pending"
        assert approval.pe_notification_time is None
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code is None

    def test_save_error(self):
        now = timezone.now()
        approval = ApprovalFactory()
        approval.pe_save_error("foo", "bar", at=now)
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_error"
        assert approval.pe_notification_time == now
        assert approval.pe_notification_endpoint == "foo"
        assert approval.pe_notification_exit_code == "bar"

    def test_save_success(self):
        now = timezone.now()
        approval = ApprovalFactory()
        approval.pe_save_success(at=now)
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_success"
        assert approval.pe_notification_time == now
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code is None

    def test_save_should_retry(self):
        now = timezone.now()
        approval = ApprovalFactory()
        approval.pe_save_should_retry(at=now)
        approval.refresh_from_db()
        assert approval.pe_notification_status == "notification_should_retry"
        assert approval.pe_notification_time == now
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code is None


# Pytest


def test_prolongation_report_file_constraint_ok():
    # PASS: valid reasons + report file
    for reason in (
        ProlongationReason.PARTICULAR_DIFFICULTIES,
        ProlongationReason.SENIOR,
        ProlongationReason.RQTH,
    ):
        report_file = File(key="random/" + str(uuid.uuid4()), last_modified=timezone.now())
        report_file.save()
        ProlongationFactory(reason=reason)


@pytest.mark.django_db(transaction=True)
def test_prolongation_report_file_constraint_invalid_reasons_ko():
    # FAIL: invalid reasons + report file
    report_file = File(key="random/" + str(uuid.uuid4()), last_modified=timezone.now())
    report_file.save()

    for reason in (
        ProlongationReason.COMPLETE_TRAINING,
        ProlongationReason.SENIOR_CDI,
        ProlongationReason.HEALTH_CONTEXT,
    ):
        with pytest.raises(IntegrityError):
            ProlongationFactory(reason=reason, report_file=report_file)

    # Check message on clean() / validate_constraints()
    with pytest.raises(ValidationError, match="Incohérence entre le fichier de bilan et la raison de prolongation"):
        Prolongation(report_file=File()).validate_constraints()


@pytest.mark.parametrize("reason", PROLONGATION_REPORT_FILE_REASONS)
def test_mandatory_contact_fields_validation(reason, faker):
    # Contact details are mandatory for these reasons
    prolongation = ProlongationFactory(
        reason=reason, declared_by_siae__kind=CompanyKind.ACI, require_phone_interview=True
    )

    for phone, email in [
        ([phone, email])
        for phone in (None, faker.phone_number())
        for email in (None, faker.email())
        if not (phone and email)
    ]:
        prolongation.contact_email = email
        prolongation.contact_phone = phone
        with pytest.raises(
            ValidationError,
            match="L'adresse email et le numéro de téléphone sont obligatoires pour ce motif",
        ):
            prolongation.clean()

    # Must pass with both contact fields filled
    prolongation.contact_email = faker.email()
    prolongation.contact_phone = faker.phone_number()
    prolongation.clean()


@pytest.mark.parametrize("reason", (ProlongationReason.SENIOR_CDI, ProlongationReason.HEALTH_CONTEXT))
def test_optional_contact_fields_validation(reason, faker):
    # ProlongationReason.COMPLETE_TRAINING is a specific case
    prolongation = ProlongationFactory(
        reason=reason, declared_by_siae__kind=CompanyKind.ACI, require_phone_interview=False
    )
    prolongation.clean()

    for phone, email in [
        ([phone, email]) for phone in (None, faker.phone_number()) for email in (None, faker.email()) if phone or email
    ]:
        prolongation.contact_email = email
        prolongation.contact_phone = phone
        with pytest.raises(
            ValidationError,
            match="L'adresse email et le numéro de téléphone ne peuvent être saisis pour ce motif",
        ):
            prolongation.clean()


def test_prolongation_from_prolongation_request():
    prolongation_request = ProlongationRequestFactory(processed=True)

    prolongation = Prolongation.from_prolongation_request(prolongation_request)
    assert prolongation.request == prolongation_request
    assert prolongation.validated_by == prolongation_request.processed_by
    # Copied fields
    assert prolongation.approval == prolongation_request.approval
    assert prolongation.start_at == prolongation_request.start_at
    assert prolongation.end_at == prolongation_request.end_at
    assert prolongation.reason == prolongation_request.reason
    assert prolongation.reason_explanation == prolongation_request.reason_explanation
    assert prolongation.declared_by == prolongation_request.declared_by
    assert prolongation.declared_by_siae == prolongation_request.declared_by_siae
    assert prolongation.prescriber_organization == prolongation_request.prescriber_organization
    assert prolongation.created_by == prolongation_request.created_by
    assert prolongation.report_file == prolongation_request.report_file
    assert prolongation.require_phone_interview == prolongation_request.require_phone_interview
    assert prolongation.contact_email == prolongation_request.contact_email
    assert prolongation.contact_phone == prolongation_request.contact_phone


@pytest.mark.parametrize(
    "reason,outcome",
    [
        ("DETOXIFICATION", False),
        ("FORCE_MAJEURE", False),
        ("INCARCERATION", False),
        ("MATERNITY", False),
        ("SICKNESS", False),
        ("TRIAL_OUTSIDE_IAE", False),
        ("CONTRACT_SUSPENDED", True),
        ("APPROVAL_BETWEEN_CTA_MEMBERS", True),
        ("CONTRACT_BROKEN", True),
        ("CONTRAT_PASSERELLE", True),
        ("FINISHED_CONTRACT", True),
    ],
)
def test_approval_can_be_unsuspended(reason, outcome):
    today = timezone.localdate()
    approval_start_at = today - relativedelta(months=3)

    ja = JobApplicationFactory(with_approval=True, approval__start_at=approval_start_at)
    SuspensionFactory(
        approval=ja.approval,
        start_at=today - relativedelta(days=1),
        end_at=today + relativedelta(months=1),
        reason=reason,
    )
    assert ja.approval.can_be_unsuspended is outcome
