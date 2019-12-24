from collections import defaultdict, OrderedDict
from dateutil.relativedelta import relativedelta

from django.shortcuts import render
from django.utils import timezone

from django.db.models import Avg, Count, DateTimeField, F, Q
from django.db.models.functions import ExtractWeek, ExtractYear

from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.models import Siae
from itou.users.models import User


def stats(request, template_name="stats/stats.html"):
    data = {}

    # --- Siae stats.

    kpi_name = "SIAE à ce jour"
    siaes_subset = Siae.active_objects
    data = inject_siaes_subset_total_and_by_kind(data, kpi_name, siaes_subset)

    kpi_name = "SIAE ayant au moins un utilisateur à ce jour"
    siaes_subset = Siae.active_objects.filter(
        siaemembership__user__is_active=True
    ).distinct()
    data = inject_siaes_subset_total_and_by_kind(
        data, kpi_name, siaes_subset, visible=False
    )

    kpi_name = "SIAE ayant au moins une FDP à ce jour"
    siaes_subset = Siae.active_objects.exclude(
        job_description_through__isnull=True
    ).distinct()
    data = inject_siaes_subset_total_and_by_kind(
        data, kpi_name, siaes_subset, visible=False
    )

    kpi_name = "SIAE ayant au moins une FDP active à ce jour"
    siaes_subset = Siae.active_objects.filter(
        job_description_through__is_active=True
    ).distinct()
    data = inject_siaes_subset_total_and_by_kind(
        data, kpi_name, siaes_subset, visible=False
    )

    kpi_name = "SIAE ayant au moins un utilisateur et une FDP à ce jour"
    siaes_subset = (
        Siae.active_objects.filter(siaemembership__user__is_active=True)
        .exclude(job_description_through__isnull=True)
        .distinct()
    )
    data = inject_siaes_subset_total_and_by_kind(
        data, kpi_name, siaes_subset, visible=False
    )

    kpi_name = "SIAE ayant au moins un utilisateur et une FDP active à ce jour"
    siaes_subset = (
        Siae.active_objects.filter(siaemembership__user__is_active=True)
        .filter(job_description_through__is_active=True)
        .distinct()
    )
    data = inject_siaes_subset_total_and_by_kind(
        data, kpi_name, siaes_subset, visible=False
    )

    kpi_name = "SIAE actives à ce jour"
    today = timezone.localtime(timezone.now()).date()
    two_weeks_ago = today + relativedelta(weeks=-2)
    siaes_subset = Siae.active_objects.filter(
        Q(updated_at__date__gte=two_weeks_ago)
        | Q(created_at__date__gte=two_weeks_ago)
        | Q(siaemembership__user__date_joined__date__gte=two_weeks_ago)
        | Q(job_description_through__created_at__date__gte=two_weeks_ago)
        | Q(job_description_through__updated_at__date__gte=two_weeks_ago)
        | Q(job_applications_received__created_at__date__gte=two_weeks_ago)
        | Q(job_applications_received__updated_at__date__gte=two_weeks_ago)
    ).distinct()
    data = inject_siaes_subset_total_and_by_kind(data, kpi_name, siaes_subset)

    kpi_name = "SIAE ayant au moins une embauche"
    siaes_subset = Siae.active_objects.filter(
        job_applications_received__state=JobApplicationWorkflow.STATE_ACCEPTED
    ).distinct()
    data = inject_siaes_subset_total_and_by_kind(data, kpi_name, siaes_subset)

    # --- Candidate stats.

    job_applications = JobApplication.objects
    hirings = job_applications.filter(state=JobApplicationWorkflow.STATE_ACCEPTED)

    data["total_job_applications"] = job_applications.count()

    data["total_hirings"] = hirings.count()

    data["job_applications_per_creation_week"] = get_total_per_week(
        job_applications, date_field="created_at", total_expression=Count("pk")
    )

    data["hirings_per_creation_week"] = get_total_per_week(
        hirings, date_field="created_at", total_expression=Count("pk")
    )

    data["job_applications_per_sender_kind"] = get_donut_chart_data_per_sender_kind(
        job_applications
    )

    data["hirings_per_sender_kind"] = get_donut_chart_data_per_sender_kind(hirings)

    data[
        "hirings_per_eligibility_author_kind"
    ] = get_donut_chart_data_per_eligibility_author_kind(hirings)

    data.update(get_hiring_delays(hirings))

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
        job_applications.filter(sender_kind=JobApplication.SENDER_KIND_PRESCRIBER),
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


def inject_siaes_subset_total_and_by_kind(data, kpi_name, siaes_subset, visible=True):
    if "siaes_by_kind" not in data:
        data["siaes_by_kind"] = {}
        data["siaes_by_kind"]["categories"] = Siae.KIND_CHOICES
        data["siaes_by_kind"]["series"] = []

    siaes_by_kind_as_list = (
        siaes_subset.values("kind")
        .annotate(total=Count("pk", distinct=True))
        .order_by("kind")
    )

    siaes_by_kind_as_dict = {}
    for item in siaes_by_kind_as_list:
        siaes_by_kind_as_dict[item["kind"]] = item["total"]

    serie_values = []
    for kind_choice in data["siaes_by_kind"]["categories"]:
        kind = kind_choice[0]
        if kind in siaes_by_kind_as_dict:
            serie_values.append(siaes_by_kind_as_dict[kind])
        else:
            serie_values.append(0)

    total = siaes_subset.count()
    if sum(serie_values) != total:
        raise ValueError("Inconsistent results.")

    data["siaes_by_kind"]["series"].append(
        {"name": kpi_name, "values": serie_values, "total": total, "visible": visible}
    )
    return data


def get_hiring_delays(hirings):
    # Fetch several key dates of hirings.
    # Job application date is field created_at.
    # Approval date is found in the hiring transition logs.
    # Start of contract is field date_of_hiring.
    hiring_dates = (
        hirings.filter(logs__transition="accept", logs__to_state="accepted")
        .distinct()
        .values("created_at", "logs__timestamp", "date_of_hiring")
    )

    hiring_delays = hiring_dates.aggregate(
        average_delay_from_application_to_approval=Avg(
            F("logs__timestamp") - F("created_at"), output_field=DateTimeField()
        ),
        average_delay_from_approval_to_hiring=Avg(
            F("date_of_hiring") - F("logs__timestamp"), output_field=DateTimeField()
        ),
    )
    return hiring_delays


def get_donut_chart_data_per_eligibility_author_kind(job_applications):
    kind_choices_as_dict = OrderedDict(EligibilityDiagnosis.AUTHOR_KIND_CHOICES)

    # Ensure an entry exists even for author_kind values which have zero records.
    job_applications_per_eligibility_author_kind = {
        author_kind: 0 for author_kind in kind_choices_as_dict
    }

    # FIXME Find how to make a proper GROUP BY on a second order related field.
    for job_application in job_applications.values(
        "job_seeker__eligibility_diagnoses__author_kind"
    ):
        author_kind = job_application["job_seeker__eligibility_diagnoses__author_kind"]
        job_applications_per_eligibility_author_kind[author_kind] += 1

    donut_chart_data = _get_donut_chart_data(
        job_applications=job_applications,
        job_applications_per_kind=job_applications_per_eligibility_author_kind,
        kind_choices_as_dict=kind_choices_as_dict,
        prescriber_kind=EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER,
        siae_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
    )
    return donut_chart_data


def get_donut_chart_data_per_sender_kind(job_applications):
    kind_choices_as_dict = OrderedDict(JobApplication.SENDER_KIND_CHOICES)

    job_applications_per_sender_kind_as_list = (
        job_applications.values("sender_kind")
        .annotate(total=Count("pk", distinct=True))
        .order_by("sender_kind")
    )
    job_applications_per_sender_kind_as_dict = defaultdict(
        int,
        {
            item["sender_kind"]: item["total"]
            for item in job_applications_per_sender_kind_as_list
        },
    )

    donut_chart_data = _get_donut_chart_data(
        job_applications=job_applications,
        job_applications_per_kind=job_applications_per_sender_kind_as_dict,
        kind_choices_as_dict=kind_choices_as_dict,
        prescriber_kind=JobApplication.SENDER_KIND_PRESCRIBER,
        siae_kind=JobApplication.SENDER_KIND_SIAE_STAFF,
    )
    return donut_chart_data


def _get_donut_chart_data(
    job_applications,
    job_applications_per_kind,
    kind_choices_as_dict,
    prescriber_kind,
    siae_kind,
):
    """
    Internal method designed to factorize as much code as possible
    between various donut charts (DNRY).
    """
    job_applications_having_authorized_prescriber = (
        job_applications.filter(sender_prescriber_organization__is_authorized=True)
        .distinct()
        .count()
    )

    if (
        job_applications_per_kind[prescriber_kind]
        < job_applications_having_authorized_prescriber
    ):
        raise ValueError("Inconsistent prescriber data.")

    # At this point data is split this way : job_seeker / prescriber / siae_staff.
    donut_chart_data_as_dict = OrderedDict(
        (kind_choices_as_dict[k], v) for k, v in job_applications_per_kind.items()
    )

    # Split prescriber data even more : authorized / unauthorized.
    del donut_chart_data_as_dict[kind_choices_as_dict[prescriber_kind]]
    donut_chart_data_as_dict["Prescripteur non habilité"] = (
        job_applications_per_kind[prescriber_kind]
        - job_applications_having_authorized_prescriber
    )
    donut_chart_data_as_dict[
        "Prescripteur habilité"
    ] = job_applications_having_authorized_prescriber

    # Move SIAE data last for aesthetics.
    siae_value = donut_chart_data_as_dict.get(kind_choices_as_dict[siae_kind], 0)
    donut_chart_data_as_dict.pop(kind_choices_as_dict[siae_kind], None)
    donut_chart_data_as_dict[kind_choices_as_dict[siae_kind]] = siae_value

    donut_chart_data = [
        {"name": k, "value": v} for k, v in donut_chart_data_as_dict.items()
    ]
    return donut_chart_data
