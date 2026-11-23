import datetime

from django.utils import timezone
from django.utils.timesince import timeuntil

from itou.utils.templatetags.str_filters import pluralizefr


def monday_of_the_week(value=None):
    the_day = timezone.localdate(value)
    return the_day - datetime.timedelta(days=the_day.weekday())


def nb_days_in_year(start: datetime.date, end: datetime.date, *, year: int):
    if start.year < year:
        start = datetime.date(year, 1, 1)
    elif start.year > year:
        # This shouldn't happen
        return 0
    if end.year < year:
        return 0
    elif end.year > year:
        end = datetime.date(year, 12, 31)
    return (end - start).days + 1


def time_left(start: datetime.date, end: datetime.date, end_inclusive: bool = True):
    today = timezone.localdate()
    return max(end - today + datetime.timedelta(int(end_inclusive)), datetime.timedelta(0)) - max(
        start - today, datetime.timedelta(0)
    )


def get_human_readable_estimate(delta: datetime.timedelta, now=None) -> str:
    until_day = now or timezone.localdate()
    res = timeuntil(until_day + delta, now=until_day)
    res = res.replace("année", "an")
    res = res.split(", ")
    if any(v in res[0] for v in ["an", "mois"]):
        return "Environ " + " et ".join(res)
    return " et ".join(res)


def get_delta_in_days_display(delta: datetime.timedelta) -> str:
    display = f"{delta.days} jour{pluralizefr(delta.days)}"
    if delta.days >= 7:  # Prevent displaying "2 jours (2 jours)"
        display += f" ({get_human_readable_estimate(delta)})"
    return display
