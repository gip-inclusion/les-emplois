"""Period strips: a PASS IAE and what changes it, as labelled blocks in a row, with today marked.

Each block names its period ("PASS IAE", "Prolongation", "Suspension") with its duration, and carries its dates
under its edges ("Début", "Fin prévue", "Fin demandée"), so the change reads at a glance. Block widths follow the
durations on a twelve-column grid, with a minimum so that every block stays readable: they are indicative, the
dates are exact. A PASS IAE fills up as it runs, like a gauge, and its block says how long is left. What does not
fit in a block (the end of the contract) comes as small notes below.
"""

import dataclasses
import datetime

from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.approvals.enums import ProlongationRequestStatus


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
    # Where today falls in the block, in percent, and how its caption leans: start, center, end.
    today: str = ""
    today_align: str = "center"
    # For a PASS IAE: how much of the block has run, in percent, and what is left once today is in it.
    elapsed: str = ""
    remaining: str = ""


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
    # Set when today falls in one of the blocks.
    today_display: str = ""


def _share_columns(blocks):
    """Columns proportional to the durations, 12 in all, with a minimum to stay readable.

    At least 3 columns, 4 for a block with a date under each edge or when there are only two blocks, and less when
    there are many blocks.
    """
    days = [(block.end - block.start).days + 1 for block in blocks]
    total = sum(days)
    minimums = [
        min(4 if len(blocks) == 2 or (block.left and block.right) else 3, COLUMNS // len(blocks)) for block in blocks
    ]
    columns = [max(minimum, round(COLUMNS * d / total)) for minimum, d in zip(minimums, days)]
    # Give or take the difference from the largest blocks, which can spare it.
    while sum(columns) > COLUMNS:
        spare = max(range(len(blocks)), key=lambda i: columns[i] - minimums[i])
        columns[spare] -= 1
    while sum(columns) < COLUMNS:
        columns[columns.index(max(columns))] += 1
    for block, count in zip(blocks, columns):
        block.columns = count
    return blocks


def _mark_today(bar, remaining=""):
    """Place today in the block that holds it: its position in the block, and how its caption leans.

    The PASS IAE blocks fill up to today; the one that holds today says what is left of the PASS IAE.
    """
    today = timezone.localdate()
    before = 0
    for block in bar.blocks:
        if block.start <= today <= block.end:
            share = ((today - block.start).days + 0.5) / ((block.end - block.start).days + 1)
            # Formatted here: the template localization would write decimals with a comma.
            block.today = f"{share * 100:.1f}"
            position = (before + share * block.columns) / COLUMNS
            # Near an end of the strip, the caption leans inwards rather than overflowing.
            block.today_align = "start" if position < 0.15 else "end" if position > 0.85 else "center"
            bar.today_display = _fr(today)
            if block.kind == "pass":
                block.elapsed = block.today
                block.remaining = remaining
        elif block.kind == "pass" and block.end < today:
            block.elapsed = "100"
        before += block.columns
    return bar


def _remaining(approval):
    """What is left of a running PASS IAE, today included and future suspensions excluded: its "reliquat"."""
    today = timezone.localdate()
    days = approval.remainder.days
    if approval.start_at > today or not days:
        return ""
    return duration_display(today, today + datetime.timedelta(days=days - 1))


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
    notes = []
    if contract_end and contract_end < today:
        notes.append(Note(f"Contrat terminé le {_fr(contract_end)}", variant="warn", icon="ri-file-text-line"))
    elif contract_end:
        notes.append(Note(f"Contrat jusqu’au {_fr(contract_end)}", icon="ri-file-text-line"))
    return _mark_today(PeriodBar(blocks=[block], notes=notes), _remaining(approval))


def prolongation_bar(approval, start_at, end_at, contract_end=None):
    """The PASS IAE as planned, then the requested prolongation right after it."""
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
    notes = []
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
    return _mark_today(PeriodBar(blocks=blocks, notes=notes), _remaining(approval))


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
    return _mark_today(PeriodBar(blocks=_share_columns(blocks), notes=notes))


def _contract_note(contract, where):
    if contract.has_ended:
        dates = f"du {_fr(contract.start_date)} au {_fr(contract.end_date)}" if contract.end_date else "terminé"
        return Note(f"Contrat {where(contract)} {dates}", icon="ri-file-text-line")
    dates = f"depuis le {_fr(contract.start_date)}"
    if contract.end_date:
        dates += f", jusqu’au {_fr(contract.end_date)}"
    return Note(f"Contrat {where(contract)} {dates}", variant="ok", icon="ri-file-text-line")


def situation_bar(approval, contracts, where):
    """The job seeker's PASS IAE with its suspensions and a pending prolongation, then their contracts as notes.

    approval may be None and contracts empty; where(contract) says where the contract is, "chez vous" for instance.
    Returns None when there is nothing to show.
    """
    blocks = []
    if approval is not None:
        expired = approval.end_at < timezone.localdate()
        kind = "expired" if expired else "pass"
        label = f"{PASS_IAE} expiré" if expired else PASS_IAE
        cursor = approval.start_at
        pieces = []
        for suspension in sorted(approval.suspension_set.all(), key=lambda suspension: suspension.start_at):
            if suspension.start_at > cursor:
                pieces.append(Block(kind, label, "", cursor, suspension.start_at - datetime.timedelta(days=1)))
            pieces.append(
                Block(
                    "suspension",
                    "Suspension",
                    short_duration(suspension.start_at, suspension.end_at),
                    suspension.start_at,
                    suspension.end_at,
                    left=Edge(suspension.start_at, "Du"),
                    right=Edge(suspension.end_at, "Au"),
                )
            )
            cursor = suspension.end_at + datetime.timedelta(days=1)
        if cursor <= approval.end_at:
            pieces.append(Block(kind, label, "", cursor, approval.end_at))
        for piece in pieces:
            if piece.kind != "suspension":
                piece.duration = short_duration(piece.start, piece.end)
        passes = [piece for piece in pieces if piece.kind != "suspension"]
        if passes:
            passes[0].left = Edge(approval.start_at, "Début")
            passes[-1].right = Edge(approval.end_at, "Fin" if expired else "Fin prévue")
        blocks += pieces
        pending = [
            request
            for request in approval.prolongationrequest_set.all()
            if request.status == ProlongationRequestStatus.PENDING
        ]
        for request in pending:
            blocks.append(
                Block(
                    "prolongation",
                    "Prolongation demandée",
                    f"+ {short_duration(request.start_at, request.end_at)}",
                    request.start_at,
                    request.end_at,
                    right=Edge(request.end_at, "Fin demandée"),
                )
            )
    notes = [_contract_note(contract, where) for contract in contracts]
    if not blocks and not notes:
        return None
    if blocks:
        _share_columns(blocks)
    return _mark_today(PeriodBar(blocks=blocks, notes=notes), _remaining(approval) if approval else "")
