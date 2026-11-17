import datetime

import pytest
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains

from itou.approvals.enums import ProlongationRequestStatus
from itou.approvals.models import Suspension
from itou.companies.enums import CompanyKind
from itou.job_applications.enums import JobApplicationState
from itou.www.next_steps_views.period_bar import duration_display, prolongation_bar, situation_bar, suspension_bar
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory, SuspensionFactory
from tests.companies.factories import CompanyFactory, ContractFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory


NBSP = " "


def edges(bar):
    return [
        (edge.date_display, edge.caption)
        for block in bar.blocks
        for edge in (block.left, block.right)
        if edge is not None
    ]


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (datetime.date(2027, 2, 1), datetime.date(2027, 5, 31), f"4{NBSP}mois"),
        (datetime.date(2027, 2, 1), datetime.date(2027, 2, 12), f"12{NBSP}jours"),
        (datetime.date(2027, 2, 1), datetime.date(2028, 3, 31), f"1{NBSP}an et 2{NBSP}mois"),
        (datetime.date(2027, 2, 1), datetime.date(2027, 3, 15), f"1{NBSP}mois et 15{NBSP}jours"),
    ],
)
def test_duration_display(start, end, expected):
    assert duration_display(start, end) == expected


@freeze_time("2026-11-16")
def test_prolongation_bar():
    approval = ApprovalFactory(start_at=datetime.date(2025, 2, 1), end_at=datetime.date(2027, 1, 31))

    bar = prolongation_bar(
        approval,
        datetime.date(2027, 2, 1),
        datetime.date(2027, 5, 31),
        contract_end=datetime.date(2027, 5, 31),
    )

    # A "PASS IAE" block with its start and planned end, then a "Prolongation" block with the requested end.
    assert [(block.kind, block.label, block.duration) for block in bar.blocks] == [
        ("pass", f"PASS{NBSP}IAE", f"2{NBSP}ans"),
        ("prolongation", "Prolongation", f"+ 4{NBSP}mois"),
    ]
    assert edges(bar) == [("01/02/2025", "Début"), ("31/01/2027", "Fin prévue"), ("31/05/2027", "Fin demandée")]
    # Widths follow the durations on twelve columns, each block staying readable.
    assert [block.columns for block in bar.blocks] == [8, 4]
    # Today falls in the PASS IAE block, near its end: 653 days out of 730.
    assert [block.today for block in bar.blocks] == ["89.5", ""]
    assert bar.blocks[0].today_align == "center"
    assert bar.today_display == "16/11/2026"
    # The PASS IAE fills up to today and says what is left of it, today included: 77 days.
    assert [block.elapsed for block in bar.blocks] == ["89.5", ""]
    assert [block.remaining for block in bar.blocks] == [f"2{NBSP}mois et 16{NBSP}jours", ""]
    assert [note.text for note in bar.notes] == [
        f"Fin du contrat le 31/05/2027{NBSP}: couverte par la prolongation",
    ]


@freeze_time("2026-11-16")
def test_prolongation_request_shows_the_bar(client, settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True
    membership = PrescriberMembershipFactory(organization__authorized=True)
    approval = ApprovalFactory(start_at=datetime.date(2025, 2, 1), end_at=datetime.date(2027, 1, 31))
    ContractFactory(
        job_seeker=approval.user, start_date=datetime.date(2026, 6, 1), end_date=datetime.date(2027, 6, 30)
    )
    prolongation_request = ProlongationRequestFactory(
        approval=approval,
        prescriber_organization=membership.organization,
        assigned_to=membership.user,
        start_at=datetime.date(2027, 2, 1),
        end_at=datetime.date(2027, 5, 31),
    )
    client.force_login(membership.user)

    url = reverse("next_steps_views:journey", kwargs={"kind": "prolongation", "pk": prolongation_request.pk})
    response = client.get(url, HTTP_HX_REQUEST="true")
    assertContains(response, "next-step-frise__block--prolongation")
    assertContains(response, "Fin demandée")
    assertContains(response, f"Fin du contrat le 30/06/2027{NBSP}: après la fin demandée")


@freeze_time("2026-11-16")
def test_suspension_bar():
    approval = ApprovalFactory(start_at=datetime.date(2026, 3, 16), end_at=datetime.date(2028, 3, 15))

    bar = suspension_bar(approval, datetime.date(2026, 11, 1), datetime.date(2027, 4, 30))

    # The PASS IAE until the suspension, the suspension, then the days left, pushed back after it.
    assert [(block.kind, block.start, block.end) for block in bar.blocks] == [
        ("pass", datetime.date(2026, 3, 16), datetime.date(2026, 10, 31)),
        ("suspension", datetime.date(2026, 11, 1), datetime.date(2027, 4, 30)),
        ("pass", datetime.date(2027, 5, 1), datetime.date(2028, 9, 11)),
    ]
    assert edges(bar) == [
        ("16/03/2026", "Début"),
        ("01/11/2026", "Du"),
        ("30/04/2027", "Au"),
        ("11/09/2028", "Nouvelle fin"),
    ]
    # The suspension carries two dates: it keeps room for them, however short it is.
    assert [block.columns for block in bar.blocks] == [3, 4, 5]
    # Today falls in the suspension: the PASS IAE before it has run, the one after it has not started.
    assert [(block.elapsed, block.remaining) for block in bar.blocks] == [("100", ""), ("", ""), ("", "")]
    assert [note.text for note in bar.notes] == [
        f"Fin prévue avant la suspension{NBSP}: 15/03/2028, repoussée au 11/09/2028"
    ]


@freeze_time("2026-11-16")
def test_suspension_journey_shows_the_bars_and_matches_the_database(client, settings):
    settings.NEXT_STEPS_FOR_EVERYONE = True
    company = CompanyFactory(with_membership=True, kind=CompanyKind.AI)
    employer = company.members.first()
    contract = ContractFactory(
        company=company, start_date=datetime.date(2026, 3, 16), end_date=datetime.date(2026, 10, 31)
    )
    approval = ApprovalFactory(
        user=contract.job_seeker, start_at=datetime.date(2026, 3, 16), end_at=datetime.date(2028, 3, 15)
    )
    JobApplicationFactory(
        job_seeker=contract.job_seeker,
        to_company=company,
        state=JobApplicationState.ACCEPTED,
        sent_by_authorized_prescriber=True,
        hiring_start_at=contract.start_date,
        approval=approval,
    )
    client.force_login(employer)
    url = reverse("next_steps_views:journey", kwargs={"kind": "suspension", "pk": approval.pk})

    # The PASS IAE as it stands, with the end of the contract.
    response = client.get(url, HTTP_HX_REQUEST="true")
    assertContains(response, "Contrat terminé le 31/10/2026")

    answers = {
        "start_at": "2026-11-01",
        "end_at": "2027-04-30",
        "reason": Suspension.Reason.FINISHED_CONTRACT,
        "reason_explanation": "",
    }
    shown = list(answers)
    response = client.post(url, {**answers, "step": 0, "nav": "next", "shown": shown}, HTTP_HX_REQUEST="true")
    announced = f"Fin prévue avant la suspension{NBSP}: 15/03/2028, repoussée au 11/09/2028"
    assertContains(response, announced)

    response = client.post(url, {**answers, "step": 1, "nav": "next", "shown": shown}, HTTP_HX_REQUEST="true")
    approval.refresh_from_db()
    # The strip announced the date the database trigger set.
    assert approval.end_at == datetime.date(2028, 9, 11)
    assertContains(response, announced)


def where(contract):
    return f"chez {contract.company.display_name}"


@freeze_time("2026-11-16")
def test_situation_bar():
    approval = ApprovalFactory(start_at=datetime.date(2025, 2, 1), end_at=datetime.date(2027, 3, 31))
    SuspensionFactory(approval=approval, start_at=datetime.date(2025, 9, 1), end_at=datetime.date(2025, 10, 31))
    ProlongationRequestFactory(
        approval=approval, start_at=datetime.date(2027, 4, 1), end_at=datetime.date(2027, 7, 31)
    )
    ProlongationRequestFactory(
        approval=approval,
        start_at=datetime.date(2027, 4, 1),
        end_at=datetime.date(2027, 5, 31),
        status=ProlongationRequestStatus.DENIED,
        processed=True,
    )
    done = ContractFactory(start_date=datetime.date(2025, 2, 1), end_date=datetime.date(2025, 8, 31))
    running = ContractFactory(start_date=datetime.date(2025, 11, 1), end_date=datetime.date(2027, 3, 31))

    bar = situation_bar(approval, [done, running], where)

    # The PASS IAE around its suspension, then the pending prolongation request only.
    assert [(block.kind, block.label, block.start, block.end) for block in bar.blocks] == [
        ("pass", f"PASS{NBSP}IAE", datetime.date(2025, 2, 1), datetime.date(2025, 8, 31)),
        ("suspension", "Suspension", datetime.date(2025, 9, 1), datetime.date(2025, 10, 31)),
        ("pass", f"PASS{NBSP}IAE", datetime.date(2025, 11, 1), datetime.date(2027, 3, 31)),
        ("prolongation", "Prolongation demandée", datetime.date(2027, 4, 1), datetime.date(2027, 7, 31)),
    ]
    assert edges(bar) == [
        ("01/02/2025", "Début"),
        ("01/09/2025", "Du"),
        ("31/10/2025", "Au"),
        ("31/03/2027", "Fin prévue"),
        ("31/07/2027", "Fin demandée"),
    ]
    assert sum(block.columns for block in bar.blocks) == 12
    assert [block.today != "" for block in bar.blocks] == [False, False, True, False]
    assert [(note.text, note.variant) for note in bar.notes] == [
        (f"Contrat chez {done.company.display_name} du 01/02/2025 au 31/08/2025", "info"),
        (f"Contrat chez {running.company.display_name} depuis le 01/11/2025, jusqu’au 31/03/2027", "ok"),
    ]


@freeze_time("2026-11-16")
def test_situation_bar_clips_a_suspension_outside_the_approval():
    # The application refuses it, but older or imported data may hold a suspension starting before the PASS IAE.
    approval = ApprovalFactory(start_at=datetime.date(2025, 8, 1), end_at=datetime.date(2027, 7, 31))
    SuspensionFactory(approval=approval, start_at=datetime.date(2024, 1, 1), end_at=datetime.date(2025, 9, 1))
    approval.refresh_from_db()

    bar = situation_bar(approval, [], where)

    # Only the part within the PASS IAE is on the strip: the blocks follow each other, the PASS IAE's start first.
    assert [(block.kind, block.start, block.end) for block in bar.blocks] == [
        ("suspension", datetime.date(2025, 8, 1), datetime.date(2025, 9, 1)),
        ("pass", datetime.date(2025, 9, 2), approval.end_at),
    ]
    assert edges(bar) == [
        ("01/08/2025", "Début"),
        ("01/09/2025", "Au"),
        (f"{approval.end_at:%d/%m/%Y}", "Fin prévue"),
    ]
    # The dates the database holds are not hidden.
    assert [(note.text, note.variant) for note in bar.notes] == [
        (f"Suspension du 01/01/2024 au 01/09/2025 enregistrée en partie hors du PASS{NBSP}IAE", "warn"),
    ]


@freeze_time("2026-11-16")
def test_situation_bar_expired_or_empty():
    approval = ApprovalFactory(start_at=datetime.date(2023, 2, 1), end_at=datetime.date(2025, 1, 31))

    bar = situation_bar(approval, [], where)

    [block] = bar.blocks
    assert (block.kind, block.label) == ("expired", f"PASS{NBSP}IAE expiré")
    assert edges(bar) == [("01/02/2023", "Début"), ("31/01/2025", "Fin")]
    # Today is past the strip: no marker.
    assert bar.today_display == ""
    assert situation_bar(None, [], where) is None
