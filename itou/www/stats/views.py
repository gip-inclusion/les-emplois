import datetime

from django.shortcuts import render

from django.db.models import Q
from django.db.models.functions import ExtractWeek, ExtractYear
from django.db.models import Count

from itou.siaes.models import Siae
from itou.users.models import User
from itou.job_applications.models import JobApplication, JobApplicationWorkflow


def stats(request, template_name="stats/stats.html"):
    data = {}

    # --- Siae stats.

    data["total_siaes"] = Siae.active_objects.count()

    data["total_siaes_with_user"] = (
        Siae.active_objects.filter(siaemembership__user__is_active=True)
        .distinct()
        .count()
    )

    data["total_siaes_with_job_description"] = (
        Siae.active_objects.exclude(job_description_through__isnull=True)
        .distinct()
        .count()
    )

    data["total_siaes_with_active_job_description"] = (
        Siae.active_objects.filter(job_description_through__is_active=True)
        .distinct()
        .count()
    )

    two_weeks_ago = datetime.date.today() - datetime.timedelta(2 * 7)
    data["total_active_siaes"] = (
        Siae.active_objects.filter(
            Q(updated_at__gte=two_weeks_ago)
            # FIXME weird fact: most siae were created on Dec 5th o_O why??
            # | Q(created_at__gte=two_weeks_ago)
            | Q(siaemembership__user__date_joined__gte=two_weeks_ago)
            | Q(job_description_through__created_at__gte=two_weeks_ago)
            | Q(job_description_through__updated_at__gte=two_weeks_ago)
            | Q(job_applications_received__created_at__gte=two_weeks_ago)
            | Q(job_applications_received__updated_at__gte=two_weeks_ago)
        )
        .distinct()
        .count()
    )

    # --- Candidate stats.

    data["total_job_applications"] = JobApplication.objects.count()

    data["job_applications_per_creation_week"] = get_total_per_week(
        JobApplication.objects, date_field="created_at", total_expression=Count("pk")
    )

    data["total_accepted_job_applications"] = JobApplication.objects.filter(
        state=JobApplicationWorkflow.STATE_ACCEPTED
    ).count()

    data["accepted_job_applications_per_creation_week"] = get_total_per_week(
        JobApplication.objects.filter(state=JobApplicationWorkflow.STATE_ACCEPTED),
        date_field="created_at",
        total_expression=Count("pk"),
    )

    # --- Prescriber stats.

    data["total_prescriber_users"] = User.objects.filter(is_prescriber=True).count()

    data["prescriber_users_per_creation_week"] = get_total_per_week(
        User.objects.filter(is_prescriber=True),
        date_field="date_joined",
        total_expression=Count("pk"),
    )

    # Active prescriber means created at least one job
    # application in the given timeframe.
    data["active_prescriber_users_per_week"] = get_total_per_week(
        JobApplication.objects.filter(
            sender_kind=JobApplication.SENDER_KIND_PRESCRIBER
        ),
        date_field="created_at",
        total_expression=Count("sender_id", distinct=True),
    )

    context = {"data": data}
    return render(request, template_name, context)


def get_total_per_week(queryset, date_field, total_expression):
    result = list(
        queryset.annotate(year=ExtractYear(date_field))
        .annotate(week=ExtractWeek(date_field))
        .values("year", "week")
        .annotate(total=total_expression)
        .order_by("year", "week")
    )
    return result
