"""The periods timeline of the "Prochaines étapes" job seeker page.

Contracts and PASS IAE drawn on whole years, server side, as SVG rectangles: positions are SVG attributes, not inline
styles, and no JavaScript is needed. The window is announced in words: in the interviews, a cut past read as an error,
so it always spans every period shown, and today.
"""

import dataclasses
import datetime

from django.utils import dateformat, timezone

from itou.approvals.enums import ProlongationRequestStatus


# Width of the SVG coordinate system: segments are placed in thousandths of the window.
WIDTH = 1000


@dataclasses.dataclass
class Segment:
    # running, done (contracts); valid, expired, paused, asked (PASS IAE)
    kind: str
    label: str
    start: datetime.date
    end: datetime.date
    x: str = ""
    width: str = ""

    @property
    def dates_display(self):
        return f"du {self.start:%d/%m/%Y} au {self.end:%d/%m/%Y}"


@dataclasses.dataclass
class Lane:
    name: str
    segments: list


@dataclasses.dataclass
class Timeline:
    lanes: list
    start: datetime.date
    end: datetime.date
    today_x: str

    @property
    def years(self):
        return list(range(self.start.year, self.end.year + 1))

    @property
    def window_display(self):
        return f"Affiché de {dateformat.format(self.start, 'F Y')} à {dateformat.format(self.end, 'F Y')}."


def _contract_segments(contracts, today):
    for contract in contracts:
        yield Segment(
            kind="done" if contract.has_ended else "running",
            label=contract.company.display_name if contract.company else "Structure inconnue",
            start=contract.start_date,
            end=contract.end_date or today,
        )


def _approval_segments(approvals):
    pass_iae = "PASS IAE"
    for approval in approvals:
        yield Segment(
            kind="valid" if approval.is_valid else "expired",
            label=f"{pass_iae} {approval.number_with_spaces}" + ("" if approval.is_valid else " (expiré)"),
            start=approval.start_at,
            end=approval.end_at,
        )
    # Drawn over the PASS IAE they belong to.
    for approval in approvals:
        for suspension in approval.suspension_set.all():
            yield Segment(kind="paused", label="Suspension", start=suspension.start_at, end=suspension.end_at)
        for prolongation_request in approval.prolongationrequest_set.all():
            if prolongation_request.status == ProlongationRequestStatus.PENDING:
                yield Segment(
                    kind="asked",
                    label="Prolongation demandée",
                    start=prolongation_request.start_at,
                    end=prolongation_request.end_at,
                )


def build_timeline(approvals=None, contracts=None):
    """Lanes for what the user may see: pass None for approvals or contracts to leave their lane out."""
    today = timezone.localdate()
    lanes = []
    if contracts is not None:
        lanes.append(Lane(name="Contrats", segments=list(_contract_segments(contracts, today))))
    if approvals is not None:
        lanes.append(Lane(name="PASS IAE", segments=list(_approval_segments(approvals))))
    segments = [segment for lane in lanes for segment in lane.segments]
    if not segments:
        return None

    start = datetime.date(min([today] + [s.start for s in segments]).year, 1, 1)
    end = datetime.date(max([today] + [s.end for s in segments]).year, 12, 31)
    days = (end - start).days + 1

    def position(date):
        return (date - start).days / days * WIDTH

    for segment in segments:
        x = position(segment.start)
        # end is inclusive. A very short period stays visible.
        width = max(position(segment.end + datetime.timedelta(days=1)) - x, 2)
        # Formatted here: the template localization would write decimals with a comma.
        segment.x, segment.width = f"{x:.1f}", f"{width:.1f}"
    return Timeline(lanes=lanes, start=start, end=end, today_x=f"{position(today):.1f}")
