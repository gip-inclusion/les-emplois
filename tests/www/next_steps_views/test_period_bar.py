import datetime

import pytest
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains

from itou.approvals.models import Suspension
from itou.companies.enums import CompanyKind
from itou.job_applications.enums import JobApplicationState
from itou.www.next_steps_views.period_bar import duration_display, prolongation_bar, suspension_bar
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
from tests.companies.factories import CompanyFactory, ContractFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.prescribers.factories import PrescriberMembershipFactory


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (datetime.date(2027, 2, 1), datetime.date(2027, 5, 31), "4 mois"),
        (datetime.date(2027, 2, 1), datetime.date(2027, 2, 12), "12 jours"),
        (datetime.date(2027, 2, 1), datetime.date(2028, 3, 31), "1 an et 2 mois"),
        (datetime.date(2027, 2, 1), datetime.date(2027, 3, 15), "1 mois et 15 jours"),
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

    # The PASS IAE as it stands, days used then days left, and the requested period right after its end.
    assert [(part.kind, part.start, part.end) for part in bar.parts] == [
        ("used", datetime.date(2025, 2, 1), datetime.date(2026, 11, 16)),
        ("remaining", datetime.date(2026, 11, 17), datetime.date(2027, 1, 31)),
        ("added", datetime.date(2027, 2, 1), datetime.date(2027, 5, 31)),
    ]
    assert (bar.start_display, bar.end_display) == ("01/02/2025", "31/05/2027")
    assert bar.parts[0].x == "0.0"
    assert float(bar.parts[2].x) + float(bar.parts[2].width) == pytest.approx(1000, abs=0.2)
    assert [marker.kind for marker in bar.markers] == ["today", "contract"]
    assert [item.text for item in bar.legend] == [
        "PASS IAE du 01/02/2025 au 31/01/2027, dont 2 mois et 15 jours restants",
        "Prolongation demandée : + 4 mois, jusqu’au 31/05/2027",
        "Fin du contrat le 31/05/2027, couverte par la prolongation",
        "Aujourd’hui",
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
    assertContains(response, "next-step-bar__part--added")
    assertContains(response, "Fin du contrat le 30/06/2027, non couverte par la prolongation")


@freeze_time("2026-11-16")
def test_suspension_bar():
    approval = ApprovalFactory(start_at=datetime.date(2026, 3, 16), end_at=datetime.date(2028, 3, 15))

    bar = suspension_bar(approval, datetime.date(2026, 11, 1), datetime.date(2027, 4, 30))

    # Days used, the suspension, then the days left, pushed back after it.
    assert [(part.kind, part.start, part.end) for part in bar.parts] == [
        ("used", datetime.date(2026, 3, 16), datetime.date(2026, 10, 31)),
        ("paused", datetime.date(2026, 11, 1), datetime.date(2027, 4, 30)),
        ("remaining", datetime.date(2027, 5, 1), datetime.date(2028, 9, 11)),
    ]
    assert [marker.kind for marker in bar.markers] == ["previous-end"]
    assert bar.legend[1].text == "Suspension du 01/11/2026 au 30/04/2027 : 6 mois"
    assert bar.legend[2].text == "Fin du PASS IAE repoussée du 15/03/2028 au 11/09/2028"


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
    assertContains(response, "Fin du contrat le 31/10/2026")

    answers = {
        "start_at": "2026-11-01",
        "end_at": "2027-04-30",
        "reason": Suspension.Reason.FINISHED_CONTRACT,
        "reason_explanation": "",
    }
    shown = list(answers)
    response = client.post(url, {**answers, "step": 0, "nav": "next", "shown": shown}, HTTP_HX_REQUEST="true")
    assertContains(response, "Fin du PASS IAE repoussée du 15/03/2028 au 11/09/2028")

    response = client.post(url, {**answers, "step": 1, "nav": "next", "shown": shown}, HTTP_HX_REQUEST="true")
    approval.refresh_from_db()
    # The bar announced the date the database trigger set.
    assert approval.end_at == datetime.date(2028, 9, 11)
    assertContains(response, "Fin du PASS IAE repoussée du 15/03/2028 au 11/09/2028")
