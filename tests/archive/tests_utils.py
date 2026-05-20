import datetime

import pytest
from django.db.models.functions import Coalesce
from django.utils import timezone

from itou.archive.utils import (
    count_related_subquery,
    exclude_users_with_blocking_relations,
    get_user_reverse_relations,
    get_year_month_or_none,
)
from itou.invitations.models import EmployerInvitation
from itou.users.models import User
from tests.invitations.factories import EmployerInvitationFactory
from tests.job_applications.factories import JobApplicationFactory
from tests.users.factories import EmployerFactory


class TestRelatedObjectsConsistency:
    def test_exclude_users_with_blocking_relations(self):
        # Smoke test: a user with a reverse FK to a non-CASCADE relation must be
        # excluded from the queryset, including hidden relations
        clean = EmployerFactory()
        blocked = EmployerFactory()
        # JobApplication.archived_by has on_delete=PROTECT, so it should block deletion
        # even if it has related_name="+" (which makes it hidden to User._meta.related_objects)
        JobApplicationFactory(sent_by_prescriber_alone=True, archived_at="2025-01-01T00:00:00Z", archived_by=blocked)
        result_ids = set(
            exclude_users_with_blocking_relations(User.objects.filter(id__in=[clean.id, blocked.id])).values_list(
                "id", flat=True
            )
        )
        assert clean.id in result_ids
        assert blocked.id not in result_ids

    @pytest.mark.parametrize("is_cascade", [True, False])
    def test_user_related_objects_blocking_deletion(self, is_cascade, snapshot):
        """Needs to be updated if a new CASCADE / non-CASCADE relation to User is added."""
        relations = [
            {
                "model": field.related_model._meta.label,
                "field": field.field.name,
                "hidden": field.hidden,
            }
            for field in get_user_reverse_relations(is_cascade=is_cascade)
        ]
        relations.sort(key=lambda r: (r["model"], r["field"]))
        assert relations == snapshot()


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
