import re
from typing import TypedDict


DAYS = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}

DAY_NAMES_LONG = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

MONTHS_FR = {
    "Jan": "janvier",
    "Feb": "février",
    "Mar": "mars",
    "Apr": "avril",
    "May": "mai",
    "Jun": "juin",
    "Jul": "juillet",
    "Aug": "août",
    "Sep": "septembre",
    "Oct": "octobre",
    "Nov": "novembre",
    "Dec": "décembre",
}


class DaySchedule(TypedDict):
    times: list[str]
    comment: str | None
    open_all_day: bool


class OpeningHoursEntry(TypedDict):
    label: str
    hours: str
    comment: str | None


class FormattedOpeningHours(TypedDict):
    entries: list[OpeningHoursEntry]
    has_ph_off: bool
    comments: list[str]


def _format_day(day: str) -> str:
    return "1er" if day == "1" else day


def _translate_month_off(selector: str) -> str | None:
    try:
        # Cross-month date range: "Dec 25-Jan 1"
        m = re.match(r"^([A-Z][a-z]{2}) (\d{1,2})-([A-Z][a-z]{2}) (\d{1,2})$", selector)
        if m:
            m1, d1, m2, d2 = m.groups()
            return f"Fermé du {_format_day(d1)} {MONTHS_FR[m1]} au {_format_day(d2)} {MONTHS_FR[m2]}"

        # Same-month date range: "Dec 20-31"
        m = re.match(r"^([A-Z][a-z]{2}) (\d{1,2})-(\d{1,2})$", selector)
        if m:
            month, d1, d2 = m.groups()
            return f"Fermé du {_format_day(d1)} au {_format_day(d2)} {MONTHS_FR[month]}"

        # Single day: "Dec 25"
        m = re.match(r"^([A-Z][a-z]{2}) (\d{1,2})$", selector)
        if m:
            month, day = m.groups()
            return f"Fermé le {_format_day(day)} {MONTHS_FR[month]}"

        if "-" in selector:
            start, end = selector.split("-")
            return f"Fermé de {MONTHS_FR[start]} à {MONTHS_FR[end]}"
        if "," in selector:
            names = [MONTHS_FR[m] for m in selector.split(",")]
            return "Fermé en " + ", ".join(names)
        return f"Fermé en {MONTHS_FR[selector]}"
    except KeyError:
        return None


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


def parse_osm_hours(value: str) -> tuple[dict[int, DaySchedule], bool, list[str]]:
    schedule: dict[int, DaySchedule] = {}
    has_ph_off = False
    comments: list[str] = []

    value = re.sub(r"\bclosed\b", "off", value)
    value = re.sub(r"(open|off)\s*,", r"\1;", value)

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
            if parts and parts[-1] == "off":
                selector = " ".join(parts[:-1])
                translated = _translate_month_off(selector)
                if translated:
                    comments.append(translated)
            continue

        if "off" in parts:
            continue

        time_ranges = []
        for p in parts[1:]:
            for tr in p.split(","):
                if re.match(r"\d{2}:\d{2}-\d{2}:\d{2}$", tr):
                    time_ranges.append(tr)

        open_all_day = not time_ranges and "open" in parts
        if not time_ranges and not open_all_day:
            continue

        for day in _expand_day_selector(parts[0]):
            if day not in schedule:
                schedule[day] = {"times": [], "comment": comment, "open_all_day": False}
            schedule[day]["times"].extend(time_ranges)
            if open_all_day:
                schedule[day]["open_all_day"] = True

    return schedule, has_ph_off, comments


def format_osm_hours(value: str) -> FormattedOpeningHours | None:
    if not value:
        return None
    try:
        schedule, has_ph_off, comments = parse_osm_hours(value)
        if not schedule:
            return None
        entries: list[OpeningHoursEntry] = [
            {
                "label": DAY_NAMES_LONG[day_idx],
                "hours": (
                    "ouvert"
                    if schedule[day_idx]["open_all_day"] and not schedule[day_idx]["times"]
                    else " - ".join(_format_time_range(tr) for tr in sorted(schedule[day_idx]["times"]))
                ),
                "comment": schedule[day_idx]["comment"],
            }
            for day_idx in sorted(schedule.keys())
        ]
        return {"entries": entries, "has_ph_off": has_ph_off, "comments": comments}
    except (KeyError, ValueError):
        return None
