from django.db.models import Count, Exists, OuterRef

from itou.analytics import models
from itou.companies.models import CompanyMembership
from itou.institutions.models import InstitutionMembership
from itou.prescribers.models import PrescriberMembership
from itou.users import models as users_models
from itou.users.enums import UserKind


def collect_analytics_data(before):
    counts = list(
        users_models.User.objects.filter(is_active=True)
        .annotate(
            is_employer=Exists(CompanyMembership.objects.filter(user=OuterRef("pk"))),
            is_prescriber=Exists(PrescriberMembership.objects.filter(user=OuterRef("pk"))),
            is_labor_inspector=Exists(InstitutionMembership.objects.filter(user=OuterRef("pk"))),
        )
        .values("kind", "is_employer", "is_prescriber", "is_labor_inspector")
        .annotate(count=Count("pk"))
        # Exclude pro without memberships, they are similar to inactive users
        .exclude(kind__in=UserKind.professionals(), is_employer=False, is_prescriber=False, is_labor_inspector=False)
        .values("kind", "count", "is_employer", "is_prescriber", "is_labor_inspector")
    )

    return {
        models.DatumCode.USER_COUNT: sum([c["count"] for c in counts]),
        models.DatumCode.USER_JOB_SEEKER_COUNT: sum([c["count"] for c in counts if c["kind"] == UserKind.JOB_SEEKER]),
        models.DatumCode.USER_PRESCRIBER_COUNT: sum(
            [c["count"] for c in counts if c["kind"] in UserKind.professionals() and c["is_prescriber"]]
        ),
        models.DatumCode.USER_EMPLOYER_COUNT: sum(
            [c["count"] for c in counts if c["kind"] in UserKind.professionals() and c["is_employer"]]
        ),
        models.DatumCode.USER_LABOR_INSPECTOR_COUNT: sum(
            [c["count"] for c in counts if c["kind"] in UserKind.professionals() and c["is_labor_inspector"]]
        ),
        models.DatumCode.USER_ITOU_STAFF_COUNT: sum([c["count"] for c in counts if c["kind"] == UserKind.ITOU_STAFF]),
    }
