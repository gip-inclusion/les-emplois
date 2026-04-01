import re


DAYS = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}

DAY_NAMES_SHORT = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."]
DAY_NAMES_LONG = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _expand_day_selector(selector):
    days = []
    for part in selector.split(","):
        if "-" in part:
            start, end = part.split("-")
            days.extend(range(DAYS[start], DAYS[end] + 1))
        else:
            days.append(DAYS[part])
    return days


def _format_time(time_str):
    h, m = time_str.split(":")
    return f"{h}h" if m == "00" else f"{h}h{m}"


def _format_time_range(time_range):
    start, end = time_range.split("-")
    return f"de {_format_time(start)} à {_format_time(end)}"


def _format_hours(time_ranges):
    return " et ".join(_format_time_range(tr) for tr in sorted(time_ranges))


def _day_label(start, end, only_group):
    prefix = "Tous les jours " if only_group and start != end else ""
    if start == end:
        return f"{prefix}{DAY_NAMES_SHORT[start]}"
    return f"{prefix}du {DAY_NAMES_LONG[start]} au {DAY_NAMES_LONG[end]}"


def _group_days(schedule):
    active = [{"idx": i, **schedule[i]} for i in range(7) if i in schedule]
    if not active:
        return []

    groups = []
    i = 0
    while i < len(active):
        current = active[i]
        j = i + 1
        while (
            j < len(active)
            and active[j]["idx"] == active[j - 1]["idx"] + 1
            and active[j]["times"] == current["times"]
            and active[j]["comment"] == current["comment"]
        ):
            j += 1
        groups.append({
            "start": current["idx"],
            "end": active[j - 1]["idx"],
            "hours": _format_hours(current["times"]),
            "comment": current["comment"],
        })
        i = j

    only_group = len(groups) == 1
    return [
        {
            "label": _day_label(g["start"], g["end"], only_group),
            "hours": g["hours"],
            "comment": g["comment"],
        }
        for g in groups
    ]


def parse_osm_hours(value):
    schedule = {}

    for rule in value.split(";"):
        rule = rule.strip()
        if not rule or rule.startswith("PH"):
            continue

        comment_match = re.search(r'"([^"]*)"', rule)
        comment = comment_match.group(1) if comment_match else None

        rule = re.sub(r'"[^"]*"', "", rule).strip()
        parts = rule.split()

        if not parts or parts[0].split(",")[0].split("-")[0] not in DAYS:
            continue

        if "off" in parts:
            continue

        time_range = next((p for p in parts[1:] if re.match(r"\d{2}:\d{2}-\d{2}:\d{2}", p)), None)
        if not time_range:
            continue

        for day in _expand_day_selector(parts[0]):
            if day not in schedule:
                schedule[day] = {"times": [], "comment": comment}
            schedule[day]["times"].append(time_range)

    return schedule


def format_osm_hours(value):
    if not value:
        return None
    try:
        schedule = parse_osm_hours(value)
        return _group_days(schedule) or None
    except Exception:
        return None