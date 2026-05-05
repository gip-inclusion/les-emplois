import datetime

from django.utils import timezone


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
