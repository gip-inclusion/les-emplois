import datetime

from django.utils import timezone


def monday_of_the_week(value=None):
    the_day = timezone.localdate(value)
    return the_day - datetime.timedelta(days=the_day.weekday())
