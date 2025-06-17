import datetime

import pytest
import pytz
from django.db import models
from django.utils import timezone

from itou.archive.utils import get_filter_kwargs_on_user_for_related_objects_to_check, get_year_month_or_none
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


@pytest.mark.parametrize(
    "date_input, expected_output",
    [
        (timezone.make_aware(datetime.datetime(2023, 10, 15)), datetime.date(2023, 10, 1)),
        (timezone.make_aware(datetime.datetime(2024, 8, 31, 23, 0, 0), pytz.utc), datetime.date(2024, 9, 1)),
        (datetime.date(2023, 10, 15), datetime.date(2023, 10, 1)),
        (None, None),
    ],
)
def test_get_year_month_or_none(date_input, expected_output):
    assert get_year_month_or_none(date_input) == expected_output
