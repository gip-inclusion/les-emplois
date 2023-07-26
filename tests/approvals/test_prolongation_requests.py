import contextlib

import pytest
from django.db.utils import IntegrityError
from django.utils import timezone
from freezegun import freeze_time

from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import ProlongationRequest
from tests.approvals.factories import ProlongationRequestFactory


def test_unique_approval_for_pending_constraint():
    prolongation_request = ProlongationRequestFactory(status=ProlongationRequestStatus.PENDING)

    with pytest.raises(IntegrityError, match="unique_prolongationrequest_approval_for_pending"):
        ProlongationRequest(approval=prolongation_request.approval, status=ProlongationRequestStatus.PENDING).save()


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
