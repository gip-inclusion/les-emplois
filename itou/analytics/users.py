from django.db.models import Count

from itou.users import enums as users_enums, models as users_models

from . import models


def collect_analytics_data(before):
    counts = {
        info["kind"]: info["count"]
        for info in users_models.User.objects.values("kind").annotate(count=Count("pk")).values("kind", "count")
    }
    return {
        models.DatumCode.USER_COUNT: sum(counts.values()),
        models.DatumCode.USER_JOB_SEEKER_COUNT: counts.get(users_enums.KIND_JOB_SEEKER, 0),
        models.DatumCode.USER_PRESCRIBER_COUNT: counts.get(users_enums.KIND_PRESCRIBER, 0),
        models.DatumCode.USER_EMPLOYER_COUNT: counts.get(users_enums.KIND_EMPLOYER, 0),
        models.DatumCode.USER_LABOR_INSPECTOR_COUNT: counts.get(users_enums.KIND_LABOR_INSPECTOR, 0),
        models.DatumCode.USER_ITOU_STAFF_COUNT: counts.get(users_enums.KIND_ITOU_STAFF, 0),
    }
