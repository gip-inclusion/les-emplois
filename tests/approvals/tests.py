import datetime
import threading
import time
import uuid

import factory
import pytest
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.contrib.admin import AdminSite
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, ProgrammingError, connection, transaction
from django.forms import model_to_dict
from django.urls import reverse
from django.utils import timezone
from freezegun import freeze_time
from pytest_django.asserts import assertContains, assertMessages, assertNumQueries, assertQuerySetEqual

from itou.approvals.admin import JobApplicationInline
from itou.approvals.admin_forms import ApprovalAdminForm
from itou.approvals.constants import PROLONGATION_REPORT_FILE_REASONS
from itou.approvals.enums import ApprovalStatus, Origin, ProlongationReason
from itou.approvals.models import Approval, CancelledApproval, PoleEmploiApproval, Prolongation, Suspension
from itou.approvals.utils import get_user_last_accepted_siae_job_application, last_hire_was_made_by_siae
from itou.companies.enums import CompanyKind
from itou.employee_record.enums import Status
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.job_applications.models import JobApplication
from itou.prescribers.enums import PrescriberAuthorizationStatus
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
from tests.eligibility.factories import IAEEligibilityDiagnosisFactory
from tests.employee_record.factories import EmployeeRecordFactory
from tests.files.factories import FileFactory
from tests.job_applications.factories import JobApplicationFactory, JobApplicationSentByJobSeekerFactory
from tests.users.factories import EmployerFactory, ItouStaffFactory, JobSeekerFactory


class TestCommonApprovalQuerySet:
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

    def test_can_be_deleted_even_if_other_applications(self):
        job_app = JobApplicationFactory(with_approval=True)
        JobApplicationFactory(
            job_seeker=job_app.job_seeker, approval=job_app.approval, state=JobApplicationState.CANCELLED
        )
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


class TestCommonApprovalMixin:
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
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id, birthdate=user.jobseeker_profile.birthdate
        )
        assert not approval.is_pass_iae
        # Approval.
        approval = ApprovalFactory(user=user)
        assert approval.is_pass_iae


class TestApprovalModel:
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

    def test_get_next_number_with_demo_prefix(self, mocker):
        demo_prefix = "XXXXX"
        mocker.patch.object(Approval, "ASP_ITOU_PREFIX", demo_prefix)

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

        expired_approval = ApprovalFactory(expired=True, end_at=timezone.localdate() - relativedelta(years=2))
        expiring_soon_approval = ApprovalFactory(
            expired=True, end_at=expired_approval.end_at + datetime.timedelta(days=1)
        )

        Approval.objects.filter(id=expired_approval.id).delete(enable_mass_delete=True)

        with pytest.raises(NotImplementedError):
            Approval.objects.filter(id=expiring_soon_approval.id).delete(enable_mass_delete=True)

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
    @pytest.mark.parametrize(
        "reason",
        [
            Suspension.Reason.BROKEN_CONTRACT.value,
            Suspension.Reason.FINISHED_CONTRACT.value,
            Suspension.Reason.APPROVAL_BETWEEN_CTA_MEMBERS.value,
            Suspension.Reason.CONTRAT_PASSERELLE.value,
            Suspension.Reason.SUSPENDED_CONTRACT.value,
        ],
    )
    def test_unsuspend_valid(self, reason):
        today = timezone.localdate()
        approval_start_at = datetime.date(2022, 6, 17)
        suspension_start_date = datetime.date(2022, 7, 17)
        suspension_end_date = datetime.date(2022, 12, 17)
        suspension_expected_end_date = datetime.date(2022, 9, 16)

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
    @pytest.mark.parametrize(
        "reason",
        [
            Suspension.Reason.SICKNESS.value,
            Suspension.Reason.MATERNITY.value,
            Suspension.Reason.INCARCERATION.value,
            Suspension.Reason.TRIAL_OUTSIDE_IAE.value,
            Suspension.Reason.DETOXIFICATION.value,
            Suspension.Reason.FORCE_MAJEURE.value,
        ],
    )
    def test_unsuspend_invalid(self, reason):
        today = timezone.localdate()
        approval_start_at = datetime.date(2022, 6, 17)
        suspension_start_date = datetime.date(2022, 7, 17)
        suspension_end_date = datetime.date(2022, 12, 17)

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
        suspension = SuspensionFactory(
            approval=suspended_approval,
            start_at=now - relativedelta(days=1),
            end_at=now + relativedelta(days=1),
        )

        assertQuerySetEqual(Approval.objects.invalid(), [expired_approval])
        assert expired_approval.state == ApprovalStatus.EXPIRED
        assert expired_approval.get_state_display() == "Expiré"

        assertQuerySetEqual(Approval.objects.starts_in_the_future(), [future_approval])
        assert future_approval.state == ApprovalStatus.FUTURE
        assert future_approval.get_state_display() == "Valide (non démarré)"

        assertQuerySetEqual(
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

        assert suspended_approval.ongoing_suspension == suspension

    def tests_is_suspended(self):
        now = timezone.localdate()
        ApprovalFactory(start_at=now - relativedelta(years=1))
        ApprovalFactory(start_at=now - relativedelta(years=1))

        # No prefetch
        num_queries = 1  # fetch approvals
        num_queries += 2  # check suspensions for each approvals
        with assertNumQueries(num_queries):
            approvals = Approval.objects.all()
            for approval in approvals:
                approval.state

        # With prefetch
        num_queries = 1  # fetch approvals
        num_queries += 1  # check suspensions based on prefetched data
        with assertNumQueries(num_queries):
            approvals = Approval.objects.all().prefetch_related("suspension_set")
            for approval in approvals:
                approval.state

    def tests_ongoing_suspension(self):
        now = timezone.localdate()
        ApprovalFactory(start_at=now - relativedelta(years=1))
        ApprovalFactory(start_at=now - relativedelta(years=1))

        # No prefetch
        num_queries = 1  # fetch approvals
        num_queries += 2  # check suspensions for each approvals
        with assertNumQueries(num_queries):
            approvals = Approval.objects.all()
            for approval in approvals:
                approval.ongoing_suspension is None

        # With prefetch
        num_queries = 1  # fetch approvals
        num_queries += 1  # check suspensions based on prefetched data
        with assertNumQueries(num_queries):
            approvals = Approval.objects.all().prefetch_related("suspension_set")
            for approval in approvals:
                approval.ongoing_suspension is None

    @freeze_time("2022-11-22")
    def test_remainder(self):
        approval = ApprovalFactory(
            start_at=datetime.date(2021, 3, 25),
            end_at=datetime.date(2023, 3, 24),
        )
        assert approval.remainder == datetime.timedelta(days=123)
        assert approval.get_remainder_display() == "123 jours (Environ 4 mois)"

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
        assert approval.get_remainder_display() == "162 jours (Environ 5 mois et 1 semaine)"

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
        assert approval.get_remainder_display() == "187 jours (Environ 6 mois)"

    def test_human_readable_estimate(self):
        approval = Approval()
        for delta, expected_display in [
            (datetime.timedelta(days=730), "Environ 2 ans"),
            (datetime.timedelta(days=729), "Environ 1 an et 11 mois"),
            (datetime.timedelta(days=375), "Environ 1 an"),
            (datetime.timedelta(days=238), "Environ 7 mois et 3 semaines"),
            (datetime.timedelta(days=161), "Environ 5 mois et 1 semaine"),
            (datetime.timedelta(days=123), "Environ 4 mois"),
            (datetime.timedelta(days=15), "2 semaines et 1 jour"),
            (datetime.timedelta(days=14), "2 semaines"),
            (datetime.timedelta(days=13), "1 semaine et 6 jours"),
            (datetime.timedelta(days=7), "1 semaine"),
            (datetime.timedelta(days=6), "6 jours"),
            (datetime.timedelta(days=1), "1 jour"),
        ]:
            assert approval._get_human_readable_estimate(delta) == expected_display

    @pytest.mark.parametrize(
        "now,expected",
        [
            ("2021-07-01", datetime.date(2023, 7, 25)),  # Yet to start
            ("2022-07-26", datetime.date(2023, 7, 25)),  # In progress
            ("2023-08-01", datetime.date(2023, 7, 25)),  # Is already ended
        ],
    )
    def test_remainder_as_date(self, now, expected):
        """
        Only test return type and value as the algorithm is already tested in `self.test_remainder`.
        """
        approval = ApprovalFactory(
            start_at=datetime.date(2021, 7, 26),
            end_at=datetime.date(2023, 7, 25),
        )
        with freeze_time(now):
            assert approval.remainder_as_date == expected

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
        approval.save(update_fields=("start_at", "updated_at"))
        approval.refresh_from_db()
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING

        approval.pe_notification_status = api_enums.PEApiNotificationStatus.ERROR
        approval.save(update_fields=("pe_notification_status", "updated_at"))

        approval.refresh_from_db()
        approval.end_at += datetime.timedelta(days=1)
        approval.save(update_fields=("end_at", "updated_at"))
        approval.refresh_from_db()
        assert approval.pe_notification_status == api_enums.PEApiNotificationStatus.PENDING

    def test_date_and_pe_notification_status_modification_impossible(self):
        approval = ApprovalFactory(pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS)
        approval.start_at += datetime.timedelta(days=1)
        approval.pe_notification_status = api_enums.PEApiNotificationStatus.SHOULD_RETRY
        with pytest.raises(ProgrammingError):
            approval.save()

    def test_public_id_is_unique_uuid(self):
        approval = ApprovalFactory(public_id="95aeabb1-f0ad-4ec8-9305-d8184607bae7")

        with pytest.raises(IntegrityError):
            ApprovalFactory(public_id=approval.public_id)


class TestPoleEmploiApprovalModel:
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

    @freeze_time()
    def test_is_valid(self):
        now_date = timezone.localdate()

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

    @pytest.mark.parametrize(
        "date,expected",
        [
            ("2022-11-22", "123 jours (Environ 4 mois)"),
            ("2023-03-18", "7 jours (1 semaine)"),
            ("2023-03-19", "6 jours"),
            ("2023-03-24", "1 jour"),
        ],
    )
    def test_get_remainder_display(self, date, expected):
        pole_emploi_approval = PoleEmploiApprovalFactory(
            start_at=datetime.date(2021, 3, 25),
            end_at=datetime.date(2023, 3, 24),
        )
        with freeze_time(date):
            assert pole_emploi_approval.get_remainder_display() == expected


class TestPoleEmploiApprovalManager:
    def test_find_for_no_queries(self):
        user = JobSeekerFactory(jobseeker_profile__pole_emploi_id="")
        with assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 0

        user = JobSeekerFactory(jobseeker_profile__birthdate=None)
        with assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 0

    def test_find_for_user(self):
        # given a User, ensure we can find a PE approval using its pole_emploi_id and not the others.
        user = JobSeekerFactory(with_pole_emploi_id=True)
        today = timezone.localdate()
        pe_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
            start_at=today,
        )
        # just another approval, to be sure we don't find the other one "by chance"
        PoleEmploiApprovalFactory()
        with assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 1
        assert search_results.first() == pe_approval

        # ensure we can find **all** PE approvals using their pole_emploi_id and not the others.
        other_valid_approval = PoleEmploiApprovalFactory(
            pole_emploi_id=user.jobseeker_profile.pole_emploi_id,
            birthdate=user.jobseeker_profile.birthdate,
            start_at=today - datetime.timedelta(days=1),
        )
        with assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 2
        assert search_results[0] == pe_approval
        assert search_results[1] == other_valid_approval

        # ensure we **also** find PE approvals using the user's NIR.
        nir_approval = PoleEmploiApprovalFactory(
            nir=user.jobseeker_profile.nir,
            start_at=today - datetime.timedelta(days=2),
        )
        with assertNumQueries(0):
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
        with assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 4
        assert search_results[0] == pe_approval
        assert search_results[1] == other_valid_approval
        assert search_results[2] == nir_approval
        assert search_results[3] == other_nir_approval

        # ensure it's not an issue if the PE approval matches both NIR, pole_emploi_id and birthdate.
        nir_approval.birthdate = user.jobseeker_profile.birthdate
        nir_approval.pole_emploi_id = user.jobseeker_profile.pole_emploi_id
        nir_approval.save()

        with assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 4
        assert search_results[0] == pe_approval
        assert search_results[1] == other_valid_approval
        assert search_results[2] == nir_approval
        assert search_results[3] == other_nir_approval

    def test_find_for_no_nir(self):
        user = JobSeekerFactory(jobseeker_profile__nir="")
        PoleEmploiApprovalFactory(nir=None)  # entirely unrelated
        with assertNumQueries(0):
            search_results = PoleEmploiApproval.objects.find_for(user)
        assert search_results.count() == 0


class TestAutomaticApprovalAdminViews:
    def test_create_is_forbidden(self, client):
        """
        We cannot create an approval starting with ASP_ITOu_PREFIX
        """
        user = ItouStaffFactory()
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="add_approval")
        user.user_permissions.add(permission)

        client.force_login(user)

        url = reverse("admin:approvals_approval_add")

        diagnosis = IAEEligibilityDiagnosisFactory(from_prescriber=True)
        post_data = {
            "start_at": "01/01/2100",
            "end_at": "31/12/2102",
            "user": diagnosis.job_seeker_id,
            "eligibility_diagnosis": diagnosis.pk,
            "origin": Origin.DEFAULT,  # Will be overriden
            "number": "XXXXX1234567",
        }
        response = client.post(url, data=post_data)
        assert response.status_code == 403

    def test_edit_approval_with_an_existing_employee_record(self, client):
        user = ItouStaffFactory()
        user.user_permissions.add(
            Permission.objects.get(
                content_type=ContentType.objects.get_for_model(Approval),
                codename="change_approval",
            )
        )
        client.force_login(user)

        approval = ApprovalFactory()
        employee_record = EmployeeRecordFactory(approval_number=approval.number, status=Status.PROCESSED)

        response = client.post(
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
            f"pour la modification de ce PASS IAE ({approval.number})." == str(list(response.context["messages"])[0])
        )


class TestCustomApprovalAdminViews:
    def test_manually_add_approval(self, client, mailoutbox):
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
            with_iae_eligibility_diagnosis=True,
        )
        job_application.accept(user=job_application.to_company.members.first())

        url = reverse("admin:approvals_approval_manually_add_approval", args=[job_application.pk])

        # Not enough perms.
        user = JobSeekerFactory()
        client.force_login(user)
        response = client.get(url)
        assert response.status_code == 302

        # With good perms.
        user = ItouStaffFactory()
        client.force_login(user)
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="handle_manual_approval_requests")
        user.user_permissions.add(permission)
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["form"].initial == {
            "start_at": job_application.hiring_start_at,
            "end_at": Approval.get_default_end_date(job_application.hiring_start_at),
        }

        # Without an eligibility diangosis on the job application.
        eligibility_diagnosis = job_application.eligibility_diagnosis
        job_application.eligibility_diagnosis = None
        job_application.save()
        response = client.get(url, follow=True)
        assertMessages(
            response,
            [
                messages.Message(
                    messages.ERROR,
                    "Impossible de créer un PASS IAE car la candidature n'a pas de diagnostic d'éligibilité.",
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
        response = client.post(url, data=post_data)
        assert response.status_code == 200
        assert "number" in response.context["form"].errors, ApprovalAdminForm.ERROR_NUMBER

        # Create an approval.
        post_data = {
            "start_at": job_application.hiring_start_at.strftime("%d/%m/%Y"),
            "end_at": job_application.hiring_end_at.strftime("%d/%m/%Y"),
        }
        response = client.post(url, data=post_data)
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

        assert len(mailoutbox) == 1
        email = mailoutbox[0]
        assert approval.number_with_spaces in email.body

    def test_manually_refuse_approval(self, client, mailoutbox, snapshot):
        # When a Pôle emploi ID has been forgotten and the user has no NIR, an approval must be delivered
        # with a manual verification.
        job_seeker = JobSeekerFactory(
            first_name="Jean",
            last_name="Dupont",
            jobseeker_profile__nir="",
            jobseeker_profile__pole_emploi_id="",
            jobseeker_profile__lack_of_pole_emploi_id_reason=LackOfPoleEmploiId.REASON_FORGOTTEN,
        )
        job_application = JobApplicationSentByJobSeekerFactory(
            pk=uuid.UUID("00000000-1111-2222-3333-444444444444"),
            job_seeker=job_seeker,
            state=JobApplicationState.PROCESSING,
            approval=None,
            approval_number_sent_by_email=False,
            with_iae_eligibility_diagnosis=True,
        )
        employer = job_application.to_company.members.first()
        job_application.accept(user=employer)

        add_url = reverse("admin:approvals_approval_manually_add_approval", args=[job_application.pk])
        refuse_url = reverse("admin:approvals_approval_manually_refuse_approval", args=[job_application.pk])

        # Not enough perms.
        user = JobSeekerFactory()
        client.force_login(user)
        response = client.get(refuse_url)
        assert response.status_code == 302

        # With good perms.
        user = ItouStaffFactory()
        client.force_login(user)
        content_type = ContentType.objects.get_for_model(Approval)
        permission = Permission.objects.get(content_type=content_type, codename="handle_manual_approval_requests")
        user.user_permissions.add(permission)
        response = client.get(add_url)
        assertContains(response, refuse_url)

        response = client.get(refuse_url)
        assertContains(response, "PASS IAE refusé pour")

        post_data = {"confirm": "yes"}
        response = client.post(refuse_url, data=post_data)
        assert response.status_code == 302

        job_application = JobApplication.objects.get(pk=job_application.pk)
        assert job_application.approval_manually_refused_by == user
        assert job_application.approval_manually_refused_at is not None
        assert job_application.approval is None

        [email] = mailoutbox
        assert email.to == [employer.email]
        assert email.subject == snapshot(name="email_subject")
        assert email.body == snapshot(name="email_body")

    def test_employee_record_status(self, subtests):
        inline = JobApplicationInline(JobApplication, AdminSite())
        # When an employee record exists
        employee_record = EmployeeRecordFactory()
        url = reverse("admin:employee_record_employeerecord_change", args=[employee_record.id])
        msg = inline.employee_record_status(employee_record.job_application)
        assert msg == f'<a href="{url}"><b>Nouvelle (ID: {employee_record.pk})</b></a>'

        # When employee record creation is disabled for that job application
        job_application = JobApplicationFactory(create_employee_record=False)
        msg = inline.employee_record_status(job_application)
        assert msg == "Non proposé à la création"

        # When hiring start date is before employee record availability date
        job_application = JobApplicationFactory(hiring_start_at=datetime.date(2021, 9, 26))
        msg = inline.employee_record_status(job_application)
        assert msg == "Date de début du contrat avant l'interopérabilité"

        # When employee records are allowed (or not) for the SIAE
        for kind in CompanyKind:
            with subtests.test("SIAE doesn't use employee records", kind=kind.name):
                job_application = JobApplicationFactory(with_approval=True, to_company__kind=kind)
                msg = inline.employee_record_status(job_application)
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
        msg = inline.employee_record_status(job_application)
        assert msg == "Une fiche salarié existe déjà pour ce candidat"


class TestSuspensionQuerySet:
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


class TestSuspensionModel:
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

        min_start_at = Suspension.next_min_start_at(job_application_1.approval)
        assert min_start_at == today

        # Same rules apply for PE approval and PASS IAE
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


class TestSuspensionModelTrigger:
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


class TestProlongationQuerySet:
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


class TestProlongationManager:
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

        expected_duration = datetime.timedelta(days=prolongation1_days + prolongation2_days + prolongation3_days)
        assert expected_duration == Prolongation.objects.get_cumulative_duration_for(approval)


class TestProlongationModelTrigger:
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


class TestProlongationModelConstraint:
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


class TestProlongationModel:
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

    @pytest.mark.parametrize("reason,info", Prolongation.PROLONGATION_RULES.items())
    def test_clean_too_long_reason_duration_error(self, reason, info):
        prolongation = ProlongationFactory(
            reason=reason,
            end_at=factory.LazyAttribute(
                lambda obj: obj.start_at
                + (info["max_cumulative_duration"] or info["max_duration"])
                + datetime.timedelta(days=1)
            ),
            declared_by_siae__kind=CompanyKind.AI,
        )
        with pytest.raises(ValidationError) as error:
            prolongation.clean()
        assert error.match("La durée totale est trop longue pour le motif")

    def test_clean_end_at_do_not_block_edition(self):
        max_cumulative_duration = Prolongation.PROLONGATION_RULES[ProlongationReason.SENIOR]["max_cumulative_duration"]
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

    @pytest.mark.parametrize("kind", CompanyKind)
    def test_clean_limit_particular_difficulties_to_some_siaes_error(self, kind):
        prolongation = ProlongationFactory(
            reason=ProlongationReason.PARTICULAR_DIFFICULTIES,
        )

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
        prolongation.validated_by.prescriberorganization_set.update(
            authorization_status=PrescriberAuthorizationStatus.REFUSED
        )
        del prolongation.validated_by.is_prescriber_with_authorized_org_memberships

        with pytest.raises(ValidationError) as error:
            prolongation.clean()
        assert error.match("Cet utilisateur n'est pas un prescripteur habilité.")

    def test_clean_declared_by_coherence(self):
        prolongation = ProlongationFactory()
        prolongation.clean()

        employer = EmployerFactory()
        prolongation.declared_by = employer
        with pytest.raises(ValidationError) as error:
            prolongation.clean()
        assert error.match(
            "Le déclarant doit être un membre de la SIAE du déclarant. "
            f"Déclarant: {employer.id}, SIAE: {prolongation.declared_by_siae_id}."
        )

    def test_get_max_end_at(self, subtests):
        start_at = datetime.date(2021, 2, 1)
        approval = ApprovalFactory()
        for reason, expected_max_end_at in [
            (ProlongationReason.SENIOR_CDI, datetime.date(2031, 1, 30)),  # 3650 days (~10 years).
            (ProlongationReason.COMPLETE_TRAINING, datetime.date(2022, 2, 1)),  # 365 days.
            (ProlongationReason.RQTH, datetime.date(2024, 2, 1)),  # 1095 days (3 years).
            (ProlongationReason.SENIOR, datetime.date(2026, 1, 31)),  # 1825 days (~5 years).
            (ProlongationReason.PARTICULAR_DIFFICULTIES, datetime.date(2024, 2, 1)),  # 1095 days (3 years).
            (ProlongationReason.HEALTH_CONTEXT, datetime.date(2022, 2, 1)),  # 365 days.
        ]:
            with subtests.test(reason.name):
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


@pytest.mark.django_db(transaction=True)
class TestApprovalConcurrentModel:
    """
    Uses transaction=True that truncates all tables after every test.
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


class TestPENotificationMixin:
    def test_base_values(self):
        approval = ApprovalFactory()
        assert approval.pe_notification_status == "notification_pending"
        assert approval.pe_notification_time is None
        assert approval.pe_notification_endpoint is None
        assert approval.pe_notification_exit_code is None

    def test_save_error(self):
        now = timezone.now()
        approval = ApprovalFactory()
        approval.pe_save_error(now, endpoint="foo", exit_code="bar")
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
        ProlongationFactory(reason=reason, report_file=FileFactory())


@pytest.mark.django_db(transaction=True)
def test_prolongation_report_file_constraint_invalid_reasons_ko():
    # FAIL: invalid reasons + report file
    report_file = FileFactory()
    for reason in (
        ProlongationReason.COMPLETE_TRAINING,
        ProlongationReason.SENIOR_CDI,
        ProlongationReason.HEALTH_CONTEXT,
    ):
        with pytest.raises(IntegrityError):
            ProlongationFactory(reason=reason, report_file=report_file)

        # Check message on clean() / validate_constraints()
        with pytest.raises(
            ValidationError, match="Incohérence entre le fichier de bilan et la raison de prolongation"
        ):
            Prolongation(reason=reason, report_file=report_file).validate_constraints()


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


def test_get_user_last_accepted_siae_job_application():
    # Set 2 job applications with:
    # - origin set to PE_APPROVAL (the simplest method to test created_at ordering)
    # - different creation date
    # `last_accepted_job_application` is the one with the greater `created_at`
    now = timezone.now()
    job_application_1 = JobApplicationFactory(
        state=JobApplicationState.ACCEPTED,
        to_company__subject_to_eligibility=True,
        origin=Origin.PE_APPROVAL,
        created_at=now + relativedelta(days=1),
    )

    user = job_application_1.job_seeker

    job_application_2 = JobApplicationFactory(
        job_seeker=user,
        state=JobApplicationState.ACCEPTED,
        to_company__subject_to_eligibility=True,
        origin=Origin.PE_APPROVAL,
        created_at=now,
    )

    assert job_application_1 == get_user_last_accepted_siae_job_application(user)
    assert job_application_2 != get_user_last_accepted_siae_job_application(user)


def test_get_user_last_accepted_siae_job_application_full_ordering():
    # Set 2 job applications with:
    # - origin set to PE_APPROVAL (the simplest method to test created_at ordering)
    # - same creation date
    # - different hiring date
    # `last_accepted_job_application` is the one with the greater `hiring_start_at`
    now = timezone.now()
    job_application_1 = JobApplicationFactory(
        state=JobApplicationState.ACCEPTED,
        to_company__subject_to_eligibility=True,
        origin=Origin.PE_APPROVAL,
        created_at=now,
        hiring_start_at=timezone.localdate(now) + relativedelta(days=1),
    )

    user = job_application_1.job_seeker

    job_application_2 = JobApplicationFactory(
        job_seeker=user,
        state=JobApplicationState.ACCEPTED,
        to_company__subject_to_eligibility=True,
        origin=Origin.PE_APPROVAL,
        created_at=now,
        hiring_start_at=timezone.localdate(now),
    )

    assert job_application_1 == get_user_last_accepted_siae_job_application(user)
    assert job_application_2 != get_user_last_accepted_siae_job_application(user)


def test_last_hire_was_made_by_siae():
    siae_job_application = JobApplicationSentByJobSeekerFactory(
        state=JobApplicationState.ACCEPTED,
        to_company__subject_to_eligibility=True,
    )
    user = siae_job_application.job_seeker
    newer_non_siae_job_application = JobApplicationSentByJobSeekerFactory(
        state=JobApplicationState.ACCEPTED,
        to_company__not_subject_to_eligibility=True,
        job_seeker=user,
    )
    company_1 = siae_job_application.to_company
    company_2 = newer_non_siae_job_application.to_company
    assert last_hire_was_made_by_siae(user, company_1)
    assert not last_hire_was_made_by_siae(user, company_2)
