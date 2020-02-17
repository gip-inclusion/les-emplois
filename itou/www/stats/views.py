from collections import defaultdict, OrderedDict
from datetime import timedelta
from dateutil.relativedelta import relativedelta

from django.conf import settings
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import cache_page

from django.db.models import Avg, Count, Max, DateTimeField, F, Q, ExpressionWrapper
from django.db.models.functions import ExtractWeek, ExtractYear, TruncWeek

from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.siaes.models import Siae
from itou.users.models import User
from itou.utils.address.departments import DEPARTMENTS


DATA_UNAVAILABLE_BY_DEPARTEMENT_ERROR_MESSAGE = "donnée non disponible par département"


# TODO FIXME Run a cronjob to regenerate the stats page every X minutes,
# so that the user never has to wait!
# see https://stackoverflow.com/questions/4631865/caching-query-results-in-django
@cache_page(60 * 5)
def stats(request, template_name="stats/stats.html"):
    data = {}

    departments = get_department_choices()
    current_department = get_current_department(request, departments)

    current_departments = settings.ITOU_TEST_DEPARTMENTS
    department_filter_is_selected = False
    if current_department:
        current_departments = [current_department]
        department_filter_is_selected = True

    siaes = Siae.active_objects.filter(department__in=current_departments)
    job_applications = JobApplication.objects.filter(
        to_siae__department__in=current_departments
    )
    nationwide_prescriber_users = (
        User.objects.filter(is_prescriber=True, is_active=True)
        # We cannot filter by department otherwise we would filter out
        # prescribers without organization!
        # .filter(prescriberorganization__department__in=current_departments)
        .distinct()
    )

    hirings = job_applications.filter(state=JobApplicationWorkflow.STATE_ACCEPTED)

    # Job seeker data has no geolocalization and thus cannot be filtered by department.
    nationwide_job_seeker_users = User.objects.filter(
        is_job_seeker=True, is_active=True
    )

    data.update(get_siae_stats(siaes))

    data.update(
        get_candidate_stats(job_applications, hirings, nationwide_job_seeker_users)
    )
    if department_filter_is_selected:
        data["total_job_seeker_users"] = DATA_UNAVAILABLE_BY_DEPARTEMENT_ERROR_MESSAGE
        data[
            "total_job_seeker_users_without_opportunity"
        ] = DATA_UNAVAILABLE_BY_DEPARTEMENT_ERROR_MESSAGE

    data.update(get_prescriber_stats(nationwide_prescriber_users, job_applications))
    if department_filter_is_selected:
        data["total_prescriber_users"] = DATA_UNAVAILABLE_BY_DEPARTEMENT_ERROR_MESSAGE
        data["total_authorized_prescriber_users"] = (
            nationwide_prescriber_users.filter(
                prescriberorganization__department__in=current_departments
            )
            .distinct()
            .count()
        )
        data[
            "total_unauthorized_prescriber_users"
        ] = DATA_UNAVAILABLE_BY_DEPARTEMENT_ERROR_MESSAGE
        data["prescriber_users_per_creation_week"] = None

    context = {
        "data": data,
        "departments": departments,
        "current_department": current_department,
        "current_department_name": dict(departments)[current_department],
    }
    return render(request, template_name, context)


def get_department_choices():
    all_departments_text = (
        f"Tous les départements ({ ', '.join(settings.ITOU_TEST_DEPARTMENTS) })"
    )
    departments = [(None, all_departments_text)]
    departments += [(d, DEPARTMENTS[d]) for d in settings.ITOU_TEST_DEPARTMENTS]
    return departments


def get_current_department(request, departments):
    current_department = request.POST.get("department", None)
    if current_department not in dict(departments):
        current_department = None
    return current_department


def get_siae_stats(siaes):
    data = {}

    kpi_name = "Employeurs à ce jour"
    siaes_subset = siaes
    data = inject_siaes_subset_total_and_by_kind(data, kpi_name, siaes_subset)

    kpi_name = "Employeurs ayant au moins un utilisateur à ce jour"
    siaes_subset = siaes.filter(siaemembership__user__is_active=True).distinct()
    data = inject_siaes_subset_total_and_by_kind(
        data, kpi_name, siaes_subset, visible=False
    )

    kpi_name = "Employeurs ayant au moins une FDP à ce jour"
    siaes_subset = siaes.exclude(job_description_through__isnull=True).distinct()
    data = inject_siaes_subset_total_and_by_kind(
        data, kpi_name, siaes_subset, visible=False
    )

    kpi_name = "Employeurs ayant au moins une FDP active à ce jour"
    siaes_subset = siaes.filter(job_description_through__is_active=True).distinct()
    data = inject_siaes_subset_total_and_by_kind(
        data, kpi_name, siaes_subset, visible=False
    )

    kpi_name = "Employeurs ayant au moins un utilisateur et une FDP à ce jour"
    siaes_subset = (
        siaes.filter(siaemembership__user__is_active=True)
        .exclude(job_description_through__isnull=True)
        .distinct()
    )
    data = inject_siaes_subset_total_and_by_kind(
        data, kpi_name, siaes_subset, visible=False
    )

    kpi_name = "Employeurs ayant au moins un utilisateur et une FDP active à ce jour"
    siaes_subset = (
        siaes.filter(siaemembership__user__is_active=True)
        .filter(job_description_through__is_active=True)
        .distinct()
    )
    data = inject_siaes_subset_total_and_by_kind(
        data, kpi_name, siaes_subset, visible=False
    )

    kpi_name = "Employeurs actifs à ce jour"
    today = get_today()
    data["days_for_siae_to_be_considered_active"] = 15
    some_time_ago = today + relativedelta(
        days=-data["days_for_siae_to_be_considered_active"]
    )
    siaes_subset = siaes.filter(
        Q(updated_at__date__gte=some_time_ago)
        | Q(created_at__date__gte=some_time_ago)
        | Q(siaemembership__user__date_joined__date__gte=some_time_ago)
        | Q(job_description_through__created_at__date__gte=some_time_ago)
        | Q(job_description_through__updated_at__date__gte=some_time_ago)
        | Q(job_applications_received__created_at__date__gte=some_time_ago)
        | Q(job_applications_received__updated_at__date__gte=some_time_ago)
    ).distinct()
    data = inject_siaes_subset_total_and_by_kind(data, kpi_name, siaes_subset)

    kpi_name = "Employeurs ayant au moins une embauche"
    siaes_subset = siaes.filter(
        job_applications_received__state=JobApplicationWorkflow.STATE_ACCEPTED
    ).distinct()
    data = inject_siaes_subset_total_and_by_kind(data, kpi_name, siaes_subset)

    return data


def get_today():
    return timezone.localtime(timezone.now()).date()


def get_candidate_stats(job_applications, hirings, nationwide_job_seeker_users):
    data = {}
    data["total_job_applications"] = job_applications.count()

    data["total_hirings"] = hirings.count()

    data["total_job_seeker_users"] = nationwide_job_seeker_users.count()

    # Job seekers registered for more than X days, having
    # at least one job_application but no hiring.
    days = 45
    data["days_for_total_job_seeker_users_without_opportunity"] = days
    data["total_job_seeker_users_without_opportunity"] = (
        nationwide_job_seeker_users.filter(
            date_joined__date__lte=get_today() - relativedelta(days=days)
        )
        .exclude(job_applications__isnull=True)
        .exclude(job_applications__state=JobApplicationWorkflow.STATE_ACCEPTED)
        .distinct()
        .count()
    )

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

    data[
        "job_applications_per_destination_kind"
    ] = get_donut_chart_data_per_destination_kind(job_applications)

    data["hirings_per_destination_kind"] = get_donut_chart_data_per_destination_kind(
        hirings
    )

    data.update(get_hiring_delays(hirings))
    return data


def get_prescriber_stats(nationwide_prescriber_users, job_applications):
    data = {}
    data["total_prescriber_users"] = nationwide_prescriber_users.count()
    data["total_authorized_prescriber_users"] = nationwide_prescriber_users.filter(
        prescriberorganization__is_authorized=True
    ).count()
    data["total_unauthorized_prescriber_users"] = (
        data["total_prescriber_users"] - data["total_authorized_prescriber_users"]
    )

    # FIXME TODO stats V9
    # Répartition des prescripteurs par type (PE, ML, Cap Emploi, PJJ, etc)

    data["prescriber_users_per_creation_week"] = get_total_per_week(
        nationwide_prescriber_users,
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
    return data


def get_total_per_week(queryset, date_field, total_expression):
    # Getting correct week and year of Monday Dec 30th 2019 is tricky,
    # because ExtractWeek will give correct week number 1,
    # but ExtractYear will give 2019 instead of 2020.
    # Thus we have to focus on the last day of the week
    # instead of the actual day.
    result = list(
        queryset.annotate(
            # TruncWeek truncates to midnight on the Monday of the week.
            monday_of_week=TruncWeek(date_field)
        )
        .annotate(
            # Unfortunately relativedelta is not supported by Django ORM: we get a
            # `django.db.utils.ProgrammingError: can't adapt type 'relativedelta'` error.
            sunday_of_week=ExpressionWrapper(
                F("monday_of_week") + timedelta(days=6, hours=20), DateTimeField()
            )
        )
        .annotate(year=ExtractYear("sunday_of_week"))
        .annotate(week=ExtractWeek("sunday_of_week"))
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
    # Fetch several key dates of hirings, in chronological order:
    # 1) Job application date is job_application.created_at
    # 2) Approval date (aka "Hiring date") is job_application.logs__timestamp
    #    where job_application.logs__state="accepted"
    # 3) IAE Pass delivery date is job_application.job_seeker__approvals__created_at
    # 4) Start of contract is job_application.job_seeker__approvals__start_at
    hiring_dates = (
        hirings.filter(logs__transition="accept", logs__to_state="accepted")
        # only seek most recent approval
        .annotate(max_date=Max("job_seeker__approvals__created_at"))
        .filter(job_seeker__approvals__created_at=F("max_date"))
        .distinct()
        .values(
            "created_at",
            "logs__timestamp",
            "job_seeker__approvals__created_at",
            "job_seeker__approvals__start_at",
        )
        # We ignore hirings whose events are in the wrong chronological order.
        .filter(
            logs__timestamp__gte=F("created_at"),
            job_seeker__approvals__created_at__gte=F("logs__timestamp"),
            job_seeker__approvals__start_at__gte=F("job_seeker__approvals__created_at"),
        )
    )

    hiring_delays = hiring_dates.aggregate(
        average_delay_from_application_to_hiring=Avg(
            F("logs__timestamp") - F("created_at"), output_field=DateTimeField()
        ),
        average_delay_from_hiring_to_pass_delivery=Avg(
            F("job_seeker__approvals__created_at") - F("logs__timestamp"),
            output_field=DateTimeField(),
        ),
        average_delay_from_pass_delivery_to_contract_start=Avg(
            F("job_seeker__approvals__start_at")
            - F("job_seeker__approvals__created_at"),
            output_field=DateTimeField(),
        ),
    )
    return hiring_delays


def get_donut_chart_data_per_destination_kind(job_applications):
    job_applications_per_destination_kind_as_list = (
        job_applications.values("to_siae__kind")
        .annotate(total=Count("pk", distinct=True))
        .order_by("to_siae__kind")
    )
    donut_chart_data = [
        {"name": item["to_siae__kind"], "value": item["total"]}
        for item in job_applications_per_destination_kind_as_list
    ]
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
    total_with_authorized_prescriber = (
        job_applications.filter(sender_prescriber_organization__is_authorized=True)
        .distinct()
        .count()
    )

    donut_chart_data = _get_donut_chart_data(
        job_applications=job_applications,
        job_applications_per_kind=job_applications_per_sender_kind_as_dict,
        total_with_authorized_prescriber=total_with_authorized_prescriber,
        kind_choices_as_dict=kind_choices_as_dict,
        prescriber_kind=JobApplication.SENDER_KIND_PRESCRIBER,
        siae_kind=JobApplication.SENDER_KIND_SIAE_STAFF,
        siae_kind_custom_name="Employeur",
        job_seeker_kind=JobApplication.SENDER_KIND_JOB_SEEKER,
    )
    return donut_chart_data


def get_donut_chart_data_per_eligibility_author_kind(job_applications):
    kind_choices_as_dict = OrderedDict(EligibilityDiagnosis.AUTHOR_KIND_CHOICES)

    # Ensure an entry exists even for author_kind values which have zero records.
    job_applications_per_eligibility_author_kind = {
        author_kind: 0 for author_kind in kind_choices_as_dict
    }

    # Only consider applications which are supposed to actually have eligibility diagnoses.
    job_applications = job_applications.filter(
        to_siae__kind__in=Siae.ELIGIBILITY_REQUIRED_KINDS
    )

    # TODO Find how to make a proper GROUP BY on a second order related field.
    for job_application in job_applications.values(
        "job_seeker__eligibility_diagnoses__author_kind"
    ):
        author_kind = job_application["job_seeker__eligibility_diagnoses__author_kind"]
        job_applications_per_eligibility_author_kind[author_kind] += 1

    total_with_authorized_prescriber = (
        job_applications.filter(
            job_seeker__eligibility_diagnoses__author_kind=EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER,
            job_seeker__eligibility_diagnoses__author_prescriber_organization__is_authorized=True,
        )
        .distinct()
        .count()
    )

    donut_chart_data = _get_donut_chart_data(
        job_applications=job_applications,
        job_applications_per_kind=job_applications_per_eligibility_author_kind,
        total_with_authorized_prescriber=total_with_authorized_prescriber,
        kind_choices_as_dict=kind_choices_as_dict,
        prescriber_kind=EligibilityDiagnosis.AUTHOR_KIND_PRESCRIBER,
        siae_kind=EligibilityDiagnosis.AUTHOR_KIND_SIAE_STAFF,
        siae_kind_custom_name="SIAE",
        job_seeker_kind=EligibilityDiagnosis.AUTHOR_KIND_JOB_SEEKER,
    )
    return donut_chart_data


def _get_donut_chart_data(
    job_applications,
    job_applications_per_kind,
    total_with_authorized_prescriber,
    kind_choices_as_dict,
    prescriber_kind,
    siae_kind,
    siae_kind_custom_name,
    job_seeker_kind,
):
    """
    Internal method designed to factorize as much code as possible
    between various donut charts (DNRY).
    """
    # At this point data is split this way : job_seeker / prescriber / siae_staff.
    # Hardcode order and colors for consistency between heterogeneous charts.
    donut_chart_data_as_dict = OrderedDict()
    donut_chart_data_as_dict[
        kind_choices_as_dict[job_seeker_kind]
    ] = job_applications_per_kind[job_seeker_kind]
    donut_chart_data_as_dict[siae_kind_custom_name] = job_applications_per_kind[
        siae_kind
    ]
    # Split prescriber data even more : authorized / unauthorized.
    donut_chart_data_as_dict["Prescripteur habilité"] = total_with_authorized_prescriber
    donut_chart_data_as_dict["Prescripteur non habilité"] = (
        job_applications_per_kind[prescriber_kind] - total_with_authorized_prescriber
    )

    donut_chart_data = [
        {"name": k, "value": v} for k, v in donut_chart_data_as_dict.items()
    ]

    # Let's hardcode colors for aesthetics.
    colors = ["#2f7ed8", "#0d233a", "#8bbc21", "#910000"]

    for idx, val in enumerate(donut_chart_data):
        val["color"] = colors[idx]

    return donut_chart_data
