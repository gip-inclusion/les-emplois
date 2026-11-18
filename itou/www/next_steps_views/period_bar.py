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
    # pass, expired, prolongation, suspension, gap: no PASS IAE (CSS modifiers)
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
    # Contracts' starts and ends that fall in the block, as lines on it (situation_bar's "markers").
    markers: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Marker:
    """A contract's start or end on a block: where, in percent of the block, and what it is."""

    position: str
    title: str
    # start, end (CSS modifiers)
    kind: str


@dataclasses.dataclass
class Note:
    text: str
    # info, ok, warn (CSS modifiers)
    variant: str = "info"
    icon: str = "ri-information-line"


@dataclasses.dataclass
class Lane:
    """A contract under the blocks, from its start to its end on their grid."""

    label: str
    # ongoing, ended (CSS modifiers)
    kind: str
    # Its bar's left and right, as CSS.
    style: str
    # Its label, under the bar, from the bar's start, or up to its end when it starts late in the strip.
    label_style: str
    label_align: str
    # It starts before the strip, or goes on after it: its bar is cut there.
    before: bool = False
    after: bool = False


@dataclasses.dataclass
class PeriodBar:
    blocks: list
    notes: list = dataclasses.field(default_factory=list)
    # Set when today falls in one of the blocks.
    today_display: str = ""
    # Contracts drawn under the blocks, and where today runs through them, as CSS.
    lanes: list = dataclasses.field(default_factory=list)
    today_style: str = ""


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


# The blocks' row has the gutter `g-1`: each column keeps .125rem on either side of its block.
HALF_GUTTER_REM = 0.125


def _grid_point(bar, index, share):
    """Where a point `share` (0 to 1) of the way through block `index` falls: a percentage and a correction in rem.

    Positioned against the row's box, which the columns tile: the block runs from the start of its column plus half
    a gutter to its end minus half a gutter.
    """
    start = sum(block.columns for block in bar.blocks[:index]) / COLUMNS * 100
    width = bar.blocks[index].columns / COLUMNS * 100
    return start + share * width, HALF_GUTTER_REM - 2 * HALF_GUTTER_REM * share


def _date_point(bar, day, *, at_end=False):
    """The grid point at the start of `day`, or at its end, and whether `day` falls before or after the strip.

    A start and an end on the same boundary between two blocks fall in their own block: a contract ending on the
    day before a suspension ends at the end of the PASS IAE block, not at the start of the suspension block.
    """
    first, last = bar.blocks[0], bar.blocks[-1]
    if day < first.start or (day == first.start and not at_end):
        return _grid_point(bar, 0, 0), day < first.start, False
    if day > last.end:
        return _grid_point(bar, len(bar.blocks) - 1, 1), False, True
    for index, block in enumerate(bar.blocks):
        if block.start <= day <= block.end:
            days = (day - block.start).days + (1 if at_end else 0)
            return _grid_point(bar, index, days / ((block.end - block.start).days + 1)), False, False
    # Between two blocks that do not follow each other: at the end of the previous one.
    index = max(i for i, block in enumerate(bar.blocks) if block.end < day)
    return _grid_point(bar, index, 1), False, False


def _calc(percent, rem):
    sign = "+" if rem >= 0 else "-"
    return f"calc({percent:.3f}% {sign} {abs(rem):.3f}rem)"


def _contract_lane(bar, contract, where):
    (start, start_rem), before, _ = _date_point(bar, contract.start_date)
    # Without an end, it goes on after the strip.
    if contract.end_date is None:
        (end, end_rem), after = _grid_point(bar, len(bar.blocks) - 1, 1), True
    else:
        (end, end_rem), _, after = _date_point(bar, contract.end_date, at_end=True)
    note = _contract_note(contract, where)
    left, right = _calc(start, start_rem), _calc(100 - end, -end_rem)
    from_start = start < 50
    return Lane(
        label=note.text,
        kind="ended" if contract.has_ended else "ongoing",
        style=f"left: {left}; right: {right}",
        label_style=f"padding-left: {left}" if from_start else f"padding-right: {right}",
        label_align="start" if from_start else "end",
        before=before,
        after=after,
    )


def _on_the_strip(bar, contract):
    first, last = bar.blocks[0], bar.blocks[-1]
    return contract.start_date <= last.end and (contract.end_date is None or contract.end_date >= first.start)


def _today_style(bar):
    for index, block in enumerate(bar.blocks):
        if block.today:
            percent, rem = _grid_point(bar, index, float(block.today) / 100)
            return f"left: {_calc(percent, rem)}"
    return ""


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


def _add_markers(bar, contract, where):
    """The contract's start and end as lines on the blocks they fall in, and a note saying what they are."""
    points = [(contract.start_date, False, "start", "Début")]
    if contract.end_date:
        points.append((contract.end_date, True, "end", "Fin"))
    for day, at_end, kind, word in points:
        for block in bar.blocks:
            if block.start <= day <= block.end:
                days = (day - block.start).days + (1 if at_end else 0)
                share = days / ((block.end - block.start).days + 1)
                block.markers.append(Marker(f"{share * 100:.1f}", f"{word} du contrat {where(contract)}", kind))
    note = _contract_note(contract, where)
    bar.notes.append(Note(f"{note.text}{NBSP}: ses dates en vert sur la frise", note.variant, "ri-flag-line"))


def situation_bar(approval, contracts, where, contracts_mode="lanes"):
    """The job seeker's PASS IAE with its suspensions and a pending prolongation, then their contracts as notes.

    approval may be None and contracts empty; where(contract) says where the contract is, "chez vous" for instance.
    contracts_mode says how the contracts the strip covers are drawn: "lanes" under the blocks, "markers" on them, or
    "none" when they are shown elsewhere. Returns None when there is nothing to show.
    """
    blocks = []
    # Suspensions shown only in part, said in a note so that the strip does not hide a date the database holds.
    clipped = []
    if approval is not None:
        expired = approval.end_at < timezone.localdate()
        kind = "expired" if expired else "pass"
        # Greyed out when expired: the block without PASS IAE that follows says since when.
        label = PASS_IAE
        cursor = approval.start_at
        pieces = []
        for suspension in sorted(approval.suspension_set.all(), key=lambda suspension: suspension.start_at):
            # Within the PASS IAE and after the previous suspension: the application refuses anything else, but older
            # or imported data may hold it, and the blocks would overlap.
            start, end = max(suspension.start_at, cursor), min(suspension.end_at, approval.end_at)
            if (start, end) != (suspension.start_at, suspension.end_at):
                outside = suspension.start_at < approval.start_at or suspension.end_at > approval.end_at
                clipped.append((suspension, f"en partie hors du {PASS_IAE}" if outside else "sur une autre"))
            if start > end:
                continue
            if start > cursor:
                pieces.append(Block(kind, label, "", cursor, start - datetime.timedelta(days=1)))
            pieces.append(
                Block(
                    "suspension",
                    "Suspension",
                    short_duration(start, end),
                    start,
                    end,
                    left=Edge(start, "Du"),
                    right=Edge(end, "Au"),
                )
            )
            cursor = end + datetime.timedelta(days=1)
        if cursor <= approval.end_at:
            pieces.append(Block(kind, label, "", cursor, approval.end_at))
        for piece in pieces:
            if piece.kind != "suspension":
                piece.duration = short_duration(piece.start, piece.end)
        # The PASS IAE's dates go under the strip's ends, whatever block is there.
        if pieces:
            pieces[0].left = Edge(approval.start_at, "Début")
            pieces[-1].right = Edge(approval.end_at, "Fin" if expired else "Fin prévue")
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
        # Today is always on the strip: when it falls before or after the PASS IAE, a block without PASS IAE leads
        # to it, so that the strip reads "there was one, there is none today" or "there will be one".
        today = timezone.localdate()
        if blocks and today > blocks[-1].end:
            start = blocks[-1].end + datetime.timedelta(days=1)
            blocks.append(Block("gap", f"Sans {PASS_IAE}", f"depuis {short_duration(start, today)}", start, today))
        elif blocks and today < blocks[0].start:
            end = blocks[0].start - datetime.timedelta(days=1)
            blocks.insert(0, Block("gap", f"{PASS_IAE} à venir", f"dans {short_duration(today, end)}", today, end))
    notes = [
        Note(
            f"Suspension du {_fr(suspension.start_at)} au {_fr(suspension.end_at)} enregistrée {where_}",
            variant="warn",
            icon="ri-error-warning-line",
        )
        for suspension, where_ in clipped
    ]
    if not blocks and not notes and (not contracts or contracts_mode == "none"):
        return None
    bar = PeriodBar(blocks=_share_columns(blocks) if blocks else [], notes=notes)
    _mark_today(bar, _remaining(approval) if approval else "")
    # The contracts the strip covers, under its blocks at their dates; the others as notes.
    for contract in contracts:
        if contracts_mode == "none":
            continue
        if not (bar.blocks and _on_the_strip(bar, contract)):
            bar.notes.append(_contract_note(contract, where))
        elif contracts_mode == "markers":
            _add_markers(bar, contract, where)
        else:
            bar.lanes.append(_contract_lane(bar, contract, where))
    if bar.lanes:
        bar.today_style = _today_style(bar)
    return bar
