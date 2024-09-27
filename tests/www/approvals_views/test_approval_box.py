import datetime

from django.template import Context
from freezegun import freeze_time

from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory, SuspensionFactory
from tests.utils.test import load_template


@freeze_time("2024-08-06")
def test_expired_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2022, 1, 1), number="XXXXX1234567")

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": approval})) == snapshot


@freeze_time("2024-08-06")
def test_future_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2025, 1, 1), number="XXXXX1234567")

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": approval})) == snapshot


@freeze_time("2024-08-06")
def test_valid_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number="XXXXX1234567")

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": approval})) == snapshot


@freeze_time("2024-08-06")
def test_valid_approval_with_pending_prolongation_request(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number="XXXXX1234567")
    ProlongationRequestFactory(approval=approval, start_at=approval.end_at)

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": approval})) == snapshot


@freeze_time("2024-08-06")
def test_suspended_approval(snapshot):
    approval = ApprovalFactory(start_at=datetime.date(2024, 1, 1), number="XXXXX1234567")
    SuspensionFactory(
        approval=approval,
        start_at=datetime.date(2024, 8, 1),
        end_at=datetime.date(2024, 8, 31),
    )

    template = load_template("approvals/includes/box.html")
    assert template.render(Context({"approval": approval})) == snapshot
