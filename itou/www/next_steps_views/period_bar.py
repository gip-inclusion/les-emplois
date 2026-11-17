"""Period strips: a PASS IAE and what changes it, as labelled blocks in a row.

Each block names its period ("PASS IAE", "Prolongation", "Suspension") with its duration, and carries its dates
under its edges ("Début", "Fin prévue", "Fin demandée"), so the change reads at a glance. Block widths follow the
durations on a twelve-column grid, with a minimum so that every block stays readable: they are indicative, the
dates are exact. What does not fit in a block (days left, the end of the contract) comes as small notes below.
"""

import dataclasses
import datetime

from dateutil.relativedelta import relativedelta
from django.utils import timezone


NBSP = " "
PASS_IAE = f"PASS{NBSP}IAE"
COLUMNS = 12


def _fr(date):
    return f"{date:%d/%m/%Y}"


def duration_display(start, end):
    """Human duration of a period, both ends included: "4 mois", "1 an et 2 mois", "12 jours"."""
    delta = relativedelta(end + datetime.timedelta(days=1), start)
    parts = []
    if delta.years:
        parts.append(f"{delta.years}{NBSP}an{'s' if delta.years > 1 else ''}")
    if delta.months:
        parts.append(f"{delta.months}{NBSP}mois")
    # Days only matter for periods under a year.
    if delta.days and not delta.years or not parts:
        parts.append(f"{delta.days}{NBSP}jour{'s' if delta.days > 1 else ''}")
    return " et ".join(parts)


def short_duration(start, end):
    """A block's duration, rounded to the month past one month: the exact dates are written under the block."""
    delta = relativedelta(end + datetime.timedelta(days=1), start)
    months = delta.years * 12 + delta.months + (1 if delta.days >= 15 else 0)
    if months < 1:
        return duration_display(start, end)
    years, months = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years}{NBSP}an{'s' if years > 1 else ''}")
    if months:
        parts.append(f"{months}{NBSP}mois")
    return " et ".join(parts)


@dataclasses.dataclass
class Edge:
    """A date written under a block's edge."""

    date: datetime.date
    caption: str

    @property
    def date_display(self):
        return _fr(self.date)


@dataclasses.dataclass
class Block:
    # pass, prolongation, suspension (CSS modifiers)
    kind: str
    label: str
    duration: str
    start: datetime.date
    end: datetime.date
    # Dates under the left and right edges, if any.
    left: Edge | None = None
    right: Edge | None = None
    columns: int = COLUMNS


@dataclasses.dataclass
class Note:
    text: str
    # info, ok, warn (CSS modifiers)
    variant: str = "info"
    icon: str = "ri-information-line"


@dataclasses.dataclass
class PeriodBar:
    blocks: list
    notes: list = dataclasses.field(default_factory=list)


def _share_columns(blocks):
    """Columns proportional to the durations, 12 in all, with a minimum to stay readable.

    At least 3 columns, 4 for a block with a date under each edge or when there are only two blocks.
    """
    days = [(block.end - block.start).days + 1 for block in blocks]
    total = sum(days)
    columns = [
        max(4 if len(blocks) == 2 or (block.left and block.right) else 3, round(COLUMNS * d / total))
        for block, d in zip(blocks, days)
    ]
    # Give or take the difference from the largest block, which can spare it.
    largest = columns.index(max(columns))
    columns[largest] += COLUMNS - sum(columns)
    for block, count in zip(blocks, columns):
        block.columns = count
    return blocks


def _days_left_note(approval, today):
    if approval.start_at <= today < approval.end_at:
        return Note(
            f"Il reste {duration_display(today + datetime.timedelta(days=1), approval.end_at)} sur le {PASS_IAE}.",
            icon="ri-hourglass-line",
        )
    return None


def approval_bar(approval, contract_end=None):
    """The PASS IAE as it stands, with the days left and the end of the contract."""
    today = timezone.localdate()
    block = Block(
        "pass",
        PASS_IAE,
        short_duration(approval.start_at, approval.end_at),
        approval.start_at,
        approval.end_at,
        left=Edge(approval.start_at, "Début"),
        right=Edge(approval.end_at, "Fin prévue"),
    )
    notes = [note for note in [_days_left_note(approval, today)] if note]
    if contract_end and contract_end < today:
        notes.append(Note(f"Contrat terminé le {_fr(contract_end)}", variant="warn", icon="ri-file-text-line"))
    elif contract_end:
        notes.append(Note(f"Contrat jusqu’au {_fr(contract_end)}", icon="ri-file-text-line"))
    return PeriodBar(blocks=[block], notes=notes)


def prolongation_bar(approval, start_at, end_at, contract_end=None):
    """The PASS IAE as planned, then the requested prolongation right after it."""
    today = timezone.localdate()
    blocks = _share_columns(
        [
            Block(
                "pass",
                PASS_IAE,
                short_duration(approval.start_at, approval.end_at),
                approval.start_at,
                approval.end_at,
                left=Edge(approval.start_at, "Début"),
                right=Edge(approval.end_at, "Fin prévue"),
            ),
            Block(
                "prolongation",
                "Prolongation",
                f"+ {short_duration(start_at, end_at)}",
                start_at,
                end_at,
                right=Edge(end_at, "Fin demandée"),
            ),
        ]
    )
    notes = [note for note in [_days_left_note(approval, today)] if note]
    if contract_end:
        if contract_end <= end_at:
            notes.append(
                Note(
                    f"Fin du contrat le {_fr(contract_end)}{NBSP}: couverte par la prolongation",
                    variant="ok",
                    icon="ri-checkbox-circle-line",
                )
            )
        else:
            notes.append(
                Note(
                    f"Fin du contrat le {_fr(contract_end)}{NBSP}: après la fin demandée",
                    variant="warn",
                    icon="ri-error-warning-line",
                )
            )
    return PeriodBar(blocks=blocks, notes=notes)


def suspended_end(approval_end, start_at, end_at):
    """The PASS IAE's end once suspended: same rule as the database trigger `update_approval_end_at`."""
    return approval_end + (end_at - start_at)


def suspension_bar(approval, start_at, end_at, approval_end=None):
    """The PASS IAE until the suspension, the suspension, then the days left, pushed back after it.

    approval_end is the PASS IAE's end before the suspension: by default its current end, for a suspension to come.
    """
    approval_end = approval_end or approval.end_at
    new_end = suspended_end(approval_end, start_at, end_at)
    after_start = end_at + datetime.timedelta(days=1)
    blocks = []
    if approval.start_at < start_at:
        before_end = start_at - datetime.timedelta(days=1)
        blocks.append(
            Block(
                "pass",
                PASS_IAE,
                short_duration(approval.start_at, before_end),
                approval.start_at,
                before_end,
                left=Edge(approval.start_at, "Début"),
            )
        )
    blocks += [
        Block(
            "suspension",
            "Suspension",
            short_duration(start_at, end_at),
            start_at,
            end_at,
            left=Edge(start_at, "Du"),
            right=Edge(end_at, "Au"),
        ),
        Block(
            "pass",
            PASS_IAE,
            short_duration(after_start, new_end),
            after_start,
            new_end,
            right=Edge(new_end, "Nouvelle fin"),
        ),
    ]
    notes = [
        Note(
            f"Fin prévue avant la suspension{NBSP}: {_fr(approval_end)}, repoussée au {_fr(new_end)}",
            variant="ok",
            icon="ri-arrow-right-line",
        )
    ]
    return PeriodBar(blocks=_share_columns(blocks), notes=notes)
