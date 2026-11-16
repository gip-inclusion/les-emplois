import datetime

from freezegun import freeze_time

from itou.approvals.enums import ProlongationRequestStatus
from itou.www.next_steps_views.timeline import build_timeline
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory, SuspensionFactory
from tests.companies.factories import ContractFactory


def test_nothing_to_draw():
    assert build_timeline() is None
    assert build_timeline(approvals=[], contracts=[]) is None


@freeze_time("2026-11-16")
def test_window_spans_whole_years_from_every_period_to_today():
    contract = ContractFactory(start_date=datetime.date(2025, 3, 16), end_date=datetime.date(2025, 10, 31))
    approval = ApprovalFactory(start_at=datetime.date(2025, 3, 16), end_at=datetime.date(2027, 3, 15))

    timeline = build_timeline(approvals=[approval], contracts=[contract])

    assert (timeline.start, timeline.end) == (datetime.date(2025, 1, 1), datetime.date(2027, 12, 31))
    assert timeline.years == [2025, 2026, 2027]
    assert timeline.window_display == "Affiché de janvier 2025 à décembre 2027."
    assert [lane.name for lane in timeline.lanes] == ["Contrats", "PASS IAE"]
    [contract_segment] = timeline.lanes[0].segments
    assert contract_segment.kind == "done"
    # 74 days into a 1095 days window.
    assert contract_segment.x == "67.6"
    # Today: 319 days into the window.
    assert timeline.today_x == f"{(365 + 319) / 1095 * 1000:.1f}"


@freeze_time("2026-11-16")
def test_lanes_are_left_out_when_not_allowed():
    approval = ApprovalFactory(start_at=datetime.date(2026, 1, 1))
    timeline = build_timeline(approvals=[approval], contracts=None)
    assert [lane.name for lane in timeline.lanes] == ["PASS IAE"]


@freeze_time("2026-11-16")
def test_ongoing_contract_without_end_date_runs_until_today():
    contract = ContractFactory(start_date=datetime.date(2026, 6, 1), end_date=None)
    [segment] = build_timeline(contracts=[contract]).lanes[0].segments
    assert segment.kind == "running"
    assert segment.end == datetime.date(2026, 11, 16)


@freeze_time("2026-11-16")
def test_suspensions_and_pending_prolongation_requests_over_the_pass():
    approval = ApprovalFactory(start_at=datetime.date(2025, 2, 1), end_at=datetime.date(2027, 1, 31))
    SuspensionFactory(approval=approval, start_at=datetime.date(2026, 11, 1), end_at=datetime.date(2026, 12, 31))
    ProlongationRequestFactory(
        approval=approval, start_at=datetime.date(2027, 2, 1), end_at=datetime.date(2027, 5, 31)
    )
    ProlongationRequestFactory(
        approval=approval,
        start_at=datetime.date(2026, 2, 1),
        end_at=datetime.date(2026, 3, 31),
        status=ProlongationRequestStatus.DENIED,
        processed=True,
    )

    [lane] = build_timeline(approvals=[approval]).lanes
    assert [(segment.kind, segment.label) for segment in lane.segments] == [
        ("valid", f"PASS IAE {approval.number_with_spaces}"),
        ("paused", "Suspension"),
        ("asked", "Prolongation demandée"),
    ]
