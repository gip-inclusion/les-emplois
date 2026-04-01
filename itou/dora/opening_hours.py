import re
from typing import TypedDict


DAYS = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}

DAY_NAMES_LONG = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


class DaySchedule(TypedDict):
    times: list[str]
    comment: str | None


class OpeningHoursEntry(TypedDict):
    label: str
    hours: str
    comment: str | None


class FormattedOpeningHours(TypedDict):
    entries: list[OpeningHoursEntry]
    has_ph_off: bool


def _expand_day_selector(selector: str) -> list[int]:
    days = []
    for part in selector.split(","):
        if "-" in part:
            start, end = part.split("-")
            days.extend(range(DAYS[start], DAYS[end] + 1))
        else:
            days.append(DAYS[part])
    return days


def _format_time(time_str: str) -> str:
    h, m = time_str.split(":")
    return f"{int(h)}h{m}"


def _format_time_range(time_range: str) -> str:
    start, end = time_range.split("-")
    return f"{_format_time(start)} à {_format_time(end)}"


def parse_osm_hours(value: str) -> tuple[dict[int, DaySchedule], bool]:
    schedule: dict[int, DaySchedule] = {}
    has_ph_off = False

    for rule in value.split(";"):
        rule = rule.strip()
        if not rule:
            continue

        if "PH off" in rule:
            has_ph_off = True
            continue

        comment_match = re.search(r'"([^"]*)"', rule)
        comment = comment_match.group(1) if comment_match else None

        rule = re.sub(r'"[^"]*"', "", rule).strip()
        parts = rule.split()

        if not parts or parts[0].split(",")[0].split("-")[0] not in DAYS:
            continue

        if "off" in parts:
            continue

        time_ranges = []
        for p in parts[1:]:
            for tr in p.split(","):
                if re.match(r"\d{2}:\d{2}-\d{2}:\d{2}$", tr):
                    time_ranges.append(tr)

        if not time_ranges:
            continue

        for day in _expand_day_selector(parts[0]):
            if day not in schedule:
                schedule[day] = {"times": [], "comment": comment}
            schedule[day]["times"].extend(time_ranges)

    return schedule, has_ph_off


def format_osm_hours(value: str) -> FormattedOpeningHours | None:
    if not value:
        return None
    try:
        schedule, has_ph_off = parse_osm_hours(value)
        if not schedule:
            return None
        entries: list[OpeningHoursEntry] = [
            {
                "label": DAY_NAMES_LONG[day_idx],
                "hours": " - ".join(_format_time_range(tr) for tr in sorted(schedule[day_idx]["times"])),
                "comment": schedule[day_idx]["comment"],
            }
            for day_idx in sorted(schedule.keys())
        ]
        return {"entries": entries, "has_ph_off": has_ph_off}
    except Exception:
        # todo: log the error?
        return None
