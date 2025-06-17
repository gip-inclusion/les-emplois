from django.db import models

from itou.archive.utils import get_filter_kwargs_on_user_for_related_objects_to_check
from itou.users.models import User


class TestRelatedObjectsConsistency:
    # Theses tests aims to prevent any add or update FK relationship on User model
    # that would not be handled by the management command `notify_archive_users`.
    # If one of these tests fails, consider looking at this command and updating it
    def test_get_filter_kwargs_on_user_for_related_objects_to_check(self, snapshot):
        filter_kwargs = get_filter_kwargs_on_user_for_related_objects_to_check()
        assert filter_kwargs == snapshot(name="filter_kwargs_on_user_for_related_objects_to_check")

    def test_user_related_objects_deleted_on_cascade(self, snapshot):
        user_related_objects = [
            {obj.name: obj.related_model}
            for obj in User._meta.related_objects
            if getattr(obj, "on_delete", None) and obj.on_delete == models.CASCADE
        ]
        assert user_related_objects == snapshot(name="user_related_objects_deleted_on_cascade")
