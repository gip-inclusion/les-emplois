from django.db import models

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
