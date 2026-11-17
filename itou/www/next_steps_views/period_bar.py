"""A period bar: a period's base dates, then what is added after it, on one line.

Used where a change of dates is easier seen than read: a prolongation request shows the PASS IAE as it stands (days
used, days left) and the requested period appended after its end. Drawn server side as SVG rectangles placed by
attributes, like the timeline, with the dates written out in a legend: the bar illustrates, the text informs.
"""

import dataclasses
import datetime

from dateutil.relativedelta import relativedelta
from django.utils import timezone


WIDTH = 1000
NBSP = " "


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


@dataclasses.dataclass
class Part:
    # used, remaining, added (CSS modifiers)
    kind: str
    start: datetime.date
    end: datetime.date
    x: str = ""
    width: str = ""


@dataclasses.dataclass
class Marker:
    # today, contract (CSS modifiers)
    kind: str
    date: datetime.date
    x: str = ""


@dataclasses.dataclass
class LegendItem:
    kind: str
    text: str


@dataclasses.dataclass
class PeriodBar:
    parts: list
    markers: list
    legend: list
    start: datetime.date
    end: datetime.date

    @property
    def start_display(self):
        return _fr(self.start)

    @property
    def end_display(self):
        return _fr(self.end)


def _place(bar):
    days = (bar.end - bar.start).days + 1

    def position(date):
        return (date - bar.start).days / days * WIDTH

    for part in bar.parts:
        x = position(part.start)
        # end is inclusive. A very short period stays visible.
        part.x, part.width = f"{x:.1f}", f"{max(position(part.end + datetime.timedelta(days=1)) - x, 3):.1f}"
    for marker in bar.markers:
        marker.x = f"{position(marker.date):.1f}"
    return bar


def prolongation_bar(approval, start_at, end_at, contract_end=None):
    """The PASS IAE as it stands, then the requested prolongation from start_at to end_at."""
    today = timezone.localdate()
    parts = []
    if approval.start_at <= today:
        parts.append(Part("used", approval.start_at, min(today, approval.end_at)))
    if today < approval.end_at:
        parts.append(Part("remaining", max(today + datetime.timedelta(days=1), approval.start_at), approval.end_at))
    parts.append(Part("added", start_at, end_at))
    markers = []
    if approval.start_at <= today <= end_at:
        markers.append(Marker("today", today))
    legend = [
        LegendItem(
            "used",
            f"PASS{NBSP}IAE du {_fr(approval.start_at)} au {_fr(approval.end_at)}"
            + (
                f", dont {duration_display(today + datetime.timedelta(days=1), approval.end_at)} restants"
                if today < approval.end_at
                else ""
            ),
        ),
        LegendItem(
            "added",
            f"Prolongation demandée{NBSP}: + {duration_display(start_at, end_at)}, jusqu’au {_fr(end_at)}",
        ),
    ]
    if contract_end and approval.start_at <= contract_end:
        markers.append(Marker("contract", contract_end))
        covered = "couverte" if contract_end <= end_at else "non couverte"
        legend.append(LegendItem("contract", f"Fin du contrat le {_fr(contract_end)}, {covered} par la prolongation"))
    if markers and markers[0].kind == "today":
        legend.append(LegendItem("today", "Aujourd’hui"))
    end = max([end_at, approval.end_at] + [marker.date for marker in markers])
    return _place(PeriodBar(parts=parts, markers=markers, legend=legend, start=approval.start_at, end=end))
