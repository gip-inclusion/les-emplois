"""Five ways to read the job seeker's contracts against their PASS IAE, to compare on their page (?contrat=1 to 5).

1. relation: a note per contract saying how it stands against the PASS IAE;
2. table: the PASS IAE and the contracts as rows of the same columns;
3. chronology: the dates of both, in order, with today among them;
4. markers: the contracts' start and end as lines on the strip (see period_bar.situation_bar);
5. cards: a card with a gauge for the PASS IAE and for each contract, with the note of 1.

A prototype: one of them is to be kept.
"""

import dataclasses
import datetime

from django.utils import timezone

from itou.approvals.enums import ApprovalStatus
from itou.www.next_steps_views.period_bar import NBSP, PASS_IAE, Note, duration_display


LAYOUTS = [
    ("1", "Relation"),
    ("2", "Tableau"),
    ("3", "Chronologie"),
    ("4", "Repères"),
    ("5", "Cartes"),
]
DEFAULT_LAYOUT = "1"


def _fr(date):
    return f"{date:%d/%m/%Y}"


def layout_of(request):
    layout = request.GET.get("contrat", DEFAULT_LAYOUT)
    return layout if layout in dict(LAYOUTS) else DEFAULT_LAYOUT


def contract_label(contract, where):
    return f"Contrat {where(contract)}"


def relation(approval, contract):
    """How a contract stands against the PASS IAE, as a note: ok, warn or info."""
    today = timezone.localdate()
    if approval is None:
        return Note(f"Aucun {PASS_IAE} pour ce contrat", variant="warn", icon="ri-error-warning-line")
    if contract.has_ended:
        end = contract.end_date
        if end is None:
            return Note("Terminé", variant="info", icon="ri-information-line")
        if end > approval.end_at:
            beyond = duration_display(approval.end_at + datetime.timedelta(days=1), end)
            return Note(
                f"A dépassé la fin du {PASS_IAE} de {beyond}",
                variant="warn",
                icon="ri-error-warning-line",
            )
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
        return Note(
            f"Se termine {duration_display(approval.end_at + datetime.timedelta(days=1), contract.end_date)} après "
            f"la fin du {PASS_IAE} ({_fr(approval.end_at)})",
            variant="warn",
            icon="ri-error-warning-line",
        )
    return Note(
        f"Couvert par le {PASS_IAE} jusqu’à sa fin, le {_fr(contract.end_date)}", variant="ok", icon="ri-check-line"
    )


@dataclasses.dataclass
class Row:
    label: str
    badge_label: str
    badge_classes: str
    start: str
    end: str
    remaining: str
    note: Note = None


APPROVAL_BADGES = {
    ApprovalStatus.VALID: ("Valide", "bg-success-lighter text-success"),
    ApprovalStatus.FUTURE: ("À venir", "bg-success-lighter text-success"),
    ApprovalStatus.SUSPENDED: ("Suspendu", "bg-info-lighter text-info"),
    ApprovalStatus.EXPIRED: ("Expiré", "bg-danger-lighter text-danger"),
}


def _left(end):
    today = timezone.localdate()
    if end is None:
        return "Sans fin"
    if end < today:
        return "—"
    return duration_display(today, end)


def table(approval, contracts, where):
    rows = []
    if approval is not None:
        badge_label, badge_classes = APPROVAL_BADGES[approval.state]
        rows.append(
            Row(
                PASS_IAE,
                badge_label,
                badge_classes,
                _fr(approval.start_at),
                _fr(approval.end_at),
                _left(approval.end_at) if approval.is_valid else "—",
            )
        )
    for contract in contracts:
        rows.append(
            Row(
                contract_label(contract, where),
                "Terminé" if contract.has_ended else "En cours",
                "bg-light text-muted" if contract.has_ended else "bg-success-lighter text-success",
                _fr(contract.start_date),
                _fr(contract.end_date) if contract.end_date else "—",
                "—" if contract.has_ended else _left(contract.end_date),
                relation(approval, contract),
            )
        )
    return rows


@dataclasses.dataclass
class Event:
    date: datetime.date
    text: str
    # pass, contract, suspension, today (the colour of its dot)
    kind: str

    @property
    def date_display(self):
        return _fr(self.date)


def chronology(approval, contracts, where):
    today = timezone.localdate()
    events = [Event(today, "Aujourd’hui", "today")]
    if approval is not None:
        events.append(Event(approval.start_at, f"Début du {PASS_IAE}", "pass"))
        ended = approval.end_at < today
        events.append(Event(approval.end_at, f"{'Fin' if ended else 'Fin prévue'} du {PASS_IAE}", "pass"))
        for suspension in approval.suspension_set.all():
            events.append(Event(suspension.start_at, f"Début de la suspension du {PASS_IAE}", "suspension"))
            events.append(Event(suspension.end_at, "Fin de la suspension", "suspension"))
    for contract in contracts:
        label = contract_label(contract, where).lower()
        events.append(Event(contract.start_date, f"Début du {label}", "contract"))
        if contract.end_date:
            planned = "" if contract.has_ended else "prévue "
            events.append(Event(contract.end_date, f"Fin {planned}du {label}", "contract"))
    # Today comes after what happens on the same day.
    return sorted(events, key=lambda event: (event.date, event.kind == "today"))


@dataclasses.dataclass
class Card:
    title: str
    badge_label: str
    badge_classes: str
    period: str
    # How much of it has run, in percent, formatted for the CSS.
    elapsed: str
    remaining: str
    note: Note = None


def _elapsed(start, end):
    today = timezone.localdate()
    if end is None or end <= start:
        return "100.0" if today > start else "0.0"
    share = (today - start).days / (end - start).days
    return f"{min(max(share, 0), 1) * 100:.1f}"


def cards(approval, contracts, where):
    result = []
    if approval is not None:
        badge_label, badge_classes = APPROVAL_BADGES[approval.state]
        result.append(
            Card(
                PASS_IAE,
                badge_label,
                badge_classes,
                f"Du {_fr(approval.start_at)} au {_fr(approval.end_at)}",
                _elapsed(approval.start_at, approval.end_at),
                f"Reste {_left(approval.end_at)}" if approval.is_valid else f"Expiré le {_fr(approval.end_at)}",
            )
        )
    for contract in contracts:
        period = (
            f"Du {_fr(contract.start_date)} au {_fr(contract.end_date)}"
            if contract.end_date
            else (f"Depuis le {_fr(contract.start_date)}")
        )
        result.append(
            Card(
                contract_label(contract, where),
                "Terminé" if contract.has_ended else "En cours",
                "bg-light text-muted" if contract.has_ended else "bg-success-lighter text-success",
                period,
                _elapsed(contract.start_date, contract.end_date),
                "Terminé" if contract.has_ended else f"Reste {_left(contract.end_date)}",
                relation(approval, contract),
            )
        )
    return result
