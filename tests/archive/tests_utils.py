import datetime

import pytest
from django.db import models
from django.db.models.functions import Coalesce
from django.utils import timezone

from itou.archive.utils import (
    count_related_subquery,
    get_filter_kwargs_on_user_for_related_objects_to_check,
    get_year_month_or_none,
)
from itou.invitations.models import EmployerInvitation
from itou.users.models import User
from tests.invitations.factories import EmployerInvitationFactory
from tests.users.factories import EmployerFactory


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


class TestCountRelatedSubquery:
    def test_count_related_subquery(self):
        sqs = count_related_subquery(EmployerInvitation, "sender", "pk")
        assert sqs.identity[0] == Coalesce
        assert sqs.source_expressions[0].model == EmployerInvitation
        assert sqs.source_expressions[1].value == 0

    def test_count_related_subquery_results(self, subtests):
        employer = EmployerFactory()
        EmployerInvitationFactory(sender=employer, accepted_at=timezone.now())
        EmployerInvitationFactory(sender=employer)

        qs = User.objects.filter(id=employer.id)

        assert list(qs.annotate(nbr=count_related_subquery(EmployerInvitation, "sender", "pk")).values("nbr")) == [
            {"nbr": 2}
        ]
        assert list(
            qs.annotate(
                nbr=count_related_subquery(
                    EmployerInvitation, "sender", "pk", extra_filters={"accepted_at__isnull": False}
                )
            ).values("nbr")
        ) == [{"nbr": 1}]
        assert list(
            qs.annotate(
                nbr=count_related_subquery(
                    EmployerInvitation,
                    "sender",
                    "pk",
                    extra_filters={"accepted_at__isnull": True, "sender__isnull": True},
                )
            ).values("nbr")
        ) == [{"nbr": 0}]


@pytest.mark.parametrize(
    "date_input, expected_output",
    [
        (timezone.make_aware(datetime.datetime(2023, 10, 15)), datetime.date(2023, 10, 1)),
        (timezone.make_aware(datetime.datetime(2024, 8, 31, 23, 0, 0), datetime.UTC), datetime.date(2024, 9, 1)),
        (datetime.date(2023, 10, 15), datetime.date(2023, 10, 1)),
        (None, None),
    ],
)
def test_get_year_month_or_none(date_input, expected_output):
    assert get_year_month_or_none(date_input) == expected_output
