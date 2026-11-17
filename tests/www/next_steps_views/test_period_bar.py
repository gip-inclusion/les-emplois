import datetime

import pytest
from django.urls import reverse
from freezegun import freeze_time
from pytest_django.asserts import assertContains

from itou.www.next_steps_views.period_bar import duration_display, prolongation_bar
from tests.approvals.factories import ApprovalFactory, ProlongationRequestFactory
from tests.companies.factories import ContractFactory
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
