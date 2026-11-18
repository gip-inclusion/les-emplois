"""The job seeker's contracts under their PASS IAE: whether one runs, and whether the PASS IAE covers it.

Each contract is a line under the situation strip, which opens its details in the side drawer.
"""

import dataclasses
import datetime

from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from itou.www.next_steps_views.period_bar import NBSP, PASS_IAE, Note, duration_display


def _fr(date):
    return f"{date:%d/%m/%Y}"


def period(contract):
    if contract.end_date:
        return f"Du {_fr(contract.start_date)} au {_fr(contract.end_date)}"
    return f"Depuis le {_fr(contract.start_date)}"


def coverage(approval, contract):
    """How the PASS IAE covers a contract, as a note: ok, warn or info."""
    today = timezone.localdate()
    if approval is None:
        return Note(f"Aucun {PASS_IAE} pour ce contrat", variant="warn", icon="ri-error-warning-line")
    if contract.has_ended:
        end = contract.end_date
        if end is None:
            return Note("Terminé", variant="info", icon="ri-information-line")
        if end > approval.end_at:
            beyond = duration_display(approval.end_at + datetime.timedelta(days=1), end)
            return Note(f"A dépassé la fin du {PASS_IAE} de {beyond}", variant="warn", icon="ri-error-warning-line")
        if not approval.is_valid:
            return Note(f"Terminé le {_fr(end)}, avant la fin du {PASS_IAE}", variant="info", icon="ri-check-line")
        # The PASS IAE keeps running after the contract, until a suspension stops it.
        suspension_start = min(
            (suspension.start_at for suspension in approval.suspension_set.all() if suspension.start_at > end),
            default=None,
        )
        stop = suspension_start - datetime.timedelta(days=1) if suspension_start else today
        if stop <= end:
            return Note(
                f"Terminé le {_fr(end)}, {PASS_IAE} suspendu dès le lendemain", variant="ok", icon="ri-check-line"
            )
        used = duration_display(end + datetime.timedelta(days=1), stop)
        if suspension_start:
            return Note(
                f"Terminé le {_fr(end)}{NBSP}: {used} de {PASS_IAE} consommés avant sa suspension",
                variant="info",
                icon="ri-information-line",
            )
        return Note(
            f"Terminé le {_fr(end)}{NBSP}: {used} de {PASS_IAE} consommés depuis, sans contrat",
            variant="warn",
            icon="ri-error-warning-line",
        )
    if not approval.is_valid:
        return Note(
            f"En cours sans {PASS_IAE} valide depuis le {_fr(approval.end_at + datetime.timedelta(days=1))}",
            variant="warn",
            icon="ri-error-warning-line",
        )
    if contract.end_date is None:
        return Note(
            f"Sans date de fin{NBSP}; le {PASS_IAE} court jusqu’au {_fr(approval.end_at)}",
            variant="info",
            icon="ri-information-line",
        )
    if contract.end_date > approval.end_at:
        beyond = duration_display(approval.end_at + datetime.timedelta(days=1), contract.end_date)
        return Note(
            f"Se termine {beyond} après la fin du {PASS_IAE} ({_fr(approval.end_at)})",
            variant="warn",
            icon="ri-error-warning-line",
        )
    return Note(
        f"Couvert par le {PASS_IAE} jusqu’à sa fin, le {_fr(contract.end_date)}", variant="ok", icon="ri-check-line"
    )


@dataclasses.dataclass
class ContractLine:
    label: str
    period: str
    ongoing: bool
    coverage: Note
    # Its details in the side drawer.
    url: str


def contract_lines(job_seeker, approval, contracts, where):
    """The contracts, latest first, each with how the PASS IAE covers it."""
    return [
        ContractLine(
            label=f"Contrat {where(contract)}",
            period=period(contract),
            ongoing=not contract.has_ended,
            coverage=coverage(approval, contract),
            url=reverse(
                "next_steps_views:contract", kwargs={"public_id": job_seeker.public_id, "contract_id": contract.pk}
            ),
        )
        for contract in sorted(contracts, key=lambda contract: contract.start_date, reverse=True)
    ]


@dataclasses.dataclass
class Step:
    """A record of the contract in the ASP data: its first one, a renewal..."""

    kind: str
    start: datetime.date | None
    end: datetime.date | None
    # The actual end, when the person left before the planned one.
    left: datetime.date | None


def _date(value):
    return parse_date(value) if isinstance(value, str) else value


def contract_steps(contract):
    """The contract's records as the ASP sends them (fetch_riae_contracts), in order. None when there are none."""
    records = contract.details if isinstance(contract.details, list) else []
    steps = [
        Step(
            kind=(record.get("Type Contrat") or "").capitalize(),
            start=_date(record.get("Contrat Date Embauche")),
            end=_date(record.get("Contrat Date Fin Contrat")),
            left=_date(record.get("Contrat Date Sortie Definitive")),
        )
        for record in records
        if isinstance(record, dict)
    ]
    return sorted(steps, key=lambda step: step.start or datetime.date.min)
