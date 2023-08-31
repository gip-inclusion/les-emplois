import contextlib
import datetime
import io
import itertools

import pytest
from dateutil.relativedelta import relativedelta
from django.db.utils import IntegrityError
from django.utils import timezone
from freezegun import freeze_time

from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.management.commands import prolongation_requests_chores
from itou.approvals.models import Prolongation, ProlongationRequest
from tests.approvals.factories import ProlongationRequestFactory


@pytest.fixture(name="command")
def command_fixture():
    return prolongation_requests_chores.Command(stdout=io.StringIO(), stderr=io.StringIO())


def test_unique_approval_for_pending_constraint():
    prolongation_request = ProlongationRequestFactory(status=ProlongationRequestStatus.PENDING)

    with pytest.raises(IntegrityError, match="unique_prolongationrequest_approval_for_pending"):
        ProlongationRequest(approval=prolongation_request.approval, status=ProlongationRequestStatus.PENDING).save()


def test_non_empty_proposed_actions_constraint():
    with pytest.raises(IntegrityError, match="non_empty_proposed_actions"):
        ProlongationRequestDenyInformationFactory(proposed_actions=[])


@pytest.mark.parametrize(
    "email,phone,expected",
    [
        ("email", "phone", contextlib.nullcontext()),
        ("email", "", pytest.raises(IntegrityError, match="check_prolongationrequest_require_phone_interview")),
        ("", "phone", pytest.raises(IntegrityError, match="check_prolongationrequest_require_phone_interview")),
        ("", "", pytest.raises(IntegrityError, match="check_prolongationrequest_require_phone_interview")),
    ],
)
def test_check_require_phone_interview_constraint(email, phone, expected):
    with expected:
        ProlongationRequestFactory(require_phone_interview=True, contact_email=email, contact_phone=phone)


@freeze_time()
def test_grant():
    prolongation_request = ProlongationRequestFactory()

    new_prolongation = prolongation_request.grant(prolongation_request.validated_by)

    prolongation_request.refresh_from_db()
    assert prolongation_request.status == ProlongationRequestStatus.GRANTED
    assert prolongation_request.processed_by == prolongation_request.validated_by
    assert prolongation_request.processed_at == timezone.now()
    assert prolongation_request.updated_by == prolongation_request.validated_by
    assert list(prolongation_request.approval.prolongation_set.all()) == [new_prolongation]


@freeze_time()
def test_deny():
    prolongation_request = ProlongationRequestFactory()

    prolongation_request.deny(prolongation_request.validated_by)

    prolongation_request.refresh_from_db()
    assert prolongation_request.status == ProlongationRequestStatus.DENIED
    assert prolongation_request.processed_by == prolongation_request.validated_by
    assert prolongation_request.processed_at == timezone.now()
    assert prolongation_request.updated_by == prolongation_request.validated_by
    assert prolongation_request.approval.prolongation_set.count() == 0


@pytest.mark.parametrize(
    "wet_run,expected",
    [
        (True, 1),  # Only the old PENDING will be granted
        (False, 0),
    ],
)
def test_chores_grant_older_pending_requests(faker, snapshot, command, wet_run, expected):
    parameters = itertools.product(
        ProlongationRequestStatus,
        [
            faker.date_time_between(end_date="-30d", tzinfo=datetime.UTC),
            faker.date_time_between(start_date="-30d", tzinfo=datetime.UTC),
        ],
    )
    for status, created_at in parameters:
        ProlongationRequestFactory(status=status, created_at=created_at)

    command.handle(command="auto_grant", wet_run=wet_run)
    assert Prolongation.objects.count() == expected
    assert command.stdout.getvalue() == snapshot


@pytest.mark.parametrize(
    "wet_run,expected",
    [
        (True, 2),  # Created more than 7 days ago, and without reminder_sent_at
        (False, 0),
    ],
)
def test_chores_send_reminder_to_prescriber_organization_other_members(
    snapshot, mailoutbox, command, wet_run, expected
):
    parameters = itertools.product(
        ProlongationRequestStatus,
        [
            timezone.now() - relativedelta(days=8),
            timezone.now() - relativedelta(days=7),
            timezone.now() - relativedelta(days=6),
        ],
        [None, timezone.now()],
    )
    for status, created_at, reminder_sent_at in parameters:
        ProlongationRequestFactory(status=status, created_at=created_at, reminder_sent_at=reminder_sent_at)

    with freeze_time():
        command.handle(command="email_reminder", wet_run=wet_run)
        assert len(mailoutbox) == expected
        assert ProlongationRequest.objects.filter(reminder_sent_at=timezone.now()).count() == expected
    assert command.stdout.getvalue() == snapshot
