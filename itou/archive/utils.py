import datetime

from django.db import models
from django.utils import timezone

from itou.users.models import User


def get_filter_kwargs_on_user_for_related_objects_to_check():
    """
    Returns a dictionary of filter parameters to check for objects related
    to the User model that are not cascade deleted.
    """
    return {
        f"{obj.name}__isnull": True
        for obj in User._meta.related_objects
        if getattr(obj, "on_delete", None) and obj.on_delete != models.CASCADE
    }


def get_year_month_or_none(date=None):
    if not date:
        return None

    if isinstance(date, datetime.datetime):
        return timezone.localdate(date).replace(day=1)

    return date.replace(day=1)
