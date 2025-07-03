import datetime

from django.db import models
from django.db.models import Count, OuterRef
from django.db.models.functions import Coalesce
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


def count_related_subquery(model, fk_field, outer_ref_field, extra_filters=None):
    filters = {fk_field: OuterRef(outer_ref_field)}
    if extra_filters:
        filters.update(extra_filters)
    return Coalesce(
        model.objects.filter(**filters).values(fk_field).annotate(count=Count(outer_ref_field)).values("count"), 0
    )
