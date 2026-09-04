import datetime

import pytest
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from freezegun import freeze_time

from itou.approvals.constants import CLOSURE_PENDING_APPLICATION_MAX_AGE
from itou.approvals.utils import can_close_approval
from itou.job_applications.enums import JobApplicationState
from tests.approvals.factories import ApprovalFactory, SuspensionFactory
from tests.companies.factories import ContractFactory
from tests.job_applications.factories import JobApplicationFactory


TODAY = datetime.date(2024, 6, 1)


def _make_long_suspension(approval, *, in_progress=True):
    end_at = TODAY if in_progress else TODAY - datetime.timedelta(days=1)
    return SuspensionFactory(approval=approval, long_enough_to_close=True, end_at=end_at)


@freeze_time(TODAY)
class TestCanCloseApproval:
    def test_all_conditions_met(self):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval)
        assert can_close_approval(approval) is True

    # --- Condition 1: long suspension ---

    def test_no_suspension_at_all(self):
        approval = ApprovalFactory(with_jobapplication=True)
        assert can_close_approval(approval) is False

    def test_suspension_too_short(self):
        approval = ApprovalFactory(with_jobapplication=True)
        SuspensionFactory(approval=approval, start_at=TODAY - relativedelta(months=6))
        assert can_close_approval(approval) is False

    def test_long_suspension_in_progress(self):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval, in_progress=True)
        assert can_close_approval(approval) is True

    def test_long_suspension_ended_no_rehiring(self):
        approval = ApprovalFactory()
        _make_long_suspension(approval, in_progress=False)
        assert can_close_approval(approval) is True

    def test_long_suspension_ended_rehired_after(self):
        approval = ApprovalFactory()
        suspension = _make_long_suspension(approval, in_progress=False)
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=approval.user,
            approval=approval,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=suspension.end_at + datetime.timedelta(days=2),
        )
        assert can_close_approval(approval) is False

    def test_long_suspension_ended_rehired_before(self):
        approval = ApprovalFactory()
        suspension = _make_long_suspension(approval, in_progress=False)
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=approval.user,
            approval=approval,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=suspension.end_at - datetime.timedelta(days=2),
        )
        assert can_close_approval(approval) is True

    def test_long_suspension_ended_no_hiring_start_at(self):
        """Accepted applications without a hiring_start_at don't block closure."""
        approval = ApprovalFactory()
        _make_long_suspension(approval, in_progress=False)
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=approval.user,
            approval=approval,
            state=JobApplicationState.ACCEPTED,
            hiring_start_at=None,
        )
        assert can_close_approval(approval) is True

    # --- Condition 2: no recent pending applications ---

    def test_pending_application_recent(self):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval)
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=approval.user,
            state=JobApplicationState.NEW,
            created_at=timezone.make_aware(datetime.datetime(2024, 5, 22)),
        )
        assert can_close_approval(approval) is False

    @pytest.mark.parametrize(
        "state",
        [JobApplicationState.NEW, JobApplicationState.PROCESSING, JobApplicationState.POSTPONED],
    )
    def test_pending_states_all_block(self, state):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval)
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=approval.user,
            state=state,
            created_at=timezone.make_aware(datetime.datetime(2024, 5, 22)),
        )
        assert can_close_approval(approval) is False

    def test_pending_application_older_than_window(self):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval)
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=approval.user,
            state=JobApplicationState.NEW,
            created_at=timezone.make_aware(
                datetime.datetime.combine(
                    TODAY - CLOSURE_PENDING_APPLICATION_MAX_AGE - datetime.timedelta(days=1),
                    datetime.time.min,
                )
            ),
        )
        assert can_close_approval(approval) is True

    def test_non_pending_application_does_not_block(self):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval)
        JobApplicationFactory(
            sent_by_prescriber_alone=True,
            job_seeker=approval.user,
            state=JobApplicationState.REFUSED,
            created_at=timezone.make_aware(datetime.datetime(2024, 5, 27)),
        )
        assert can_close_approval(approval) is True

    # --- Condition 3: no ongoing ASP contract ---

    def test_ongoing_contract_no_end_date(self):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval)
        ContractFactory(job_seeker=approval.user, end_date=None)
        assert can_close_approval(approval) is False

    def test_ongoing_contract_end_date_today(self):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval)
        ContractFactory(job_seeker=approval.user, end_date=TODAY)
        assert can_close_approval(approval) is False

    def test_ongoing_contract_end_date_future(self):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval)
        ContractFactory(job_seeker=approval.user, end_date=TODAY + datetime.timedelta(days=30))
        assert can_close_approval(approval) is False

    def test_ended_contract_does_not_block(self):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval)
        ContractFactory(job_seeker=approval.user, end_date=TODAY - datetime.timedelta(days=1))
        assert can_close_approval(approval) is True

    def test_contract_of_another_job_seeker_ignored(self):
        approval = ApprovalFactory(with_jobapplication=True)
        _make_long_suspension(approval)
        ContractFactory(end_date=None)  # different job_seeker
        assert can_close_approval(approval) is True
