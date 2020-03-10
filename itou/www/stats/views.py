from collections import OrderedDict, defaultdict
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import Avg, Count, DateTimeField, ExpressionWrapper, F, Q
from django.db.models.functions import ExtractWeek, ExtractYear, TruncWeek
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_page

from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae
from itou.users.models import User
from itou.utils.address.departments import DEPARTMENTS

DATA_UNAVAILABLE_BY_DEPARTMENT_ERROR_MESSAGE = _(
    "donnée non disponible par département"
)


@cache_page(60 * 30)
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
    # This is needed so that we can deliver at least some nationwide stats
    # for prescribers even if they have no organization or an unauthorized one.
    nationwide_prescriber_users = User.objects.filter(
        is_prescriber=True, is_active=True
    ).distinct()
    # Warning: filtering by department here filters out all prescribers without
    # organization, as those have no geolocation whatsoever. It also filters
    # out prescribers with unauthorized organizations, as those also do
    # not have geolocation in practice.
    authorized_prescriber_users = nationwide_prescriber_users.filter(
        prescriberorganization__department__in=current_departments,
        prescriberorganization__is_authorized=True,
    ).distinct()
    # Note that filtering by departement here also filters out unauthorized
    # organizations as they do not have geolocation in practice.
    authorized_prescriber_orgs = PrescriberOrganization.active_objects.filter(
        department__in=current_departments, is_authorized=True
    ).distinct()

    hirings = job_applications.filter(state=JobApplicationWorkflow.STATE_ACCEPTED)

    # Job seeker data has no geolocalization and thus cannot be filtered by department.
    nationwide_job_seeker_users = User.objects.filter(
        is_job_seeker=True, is_active=True
    )

    data.update(get_siae_stats(siaes))
    if department_filter_is_selected:
        data["siaes_by_dpt"] = None

    data.update(
        get_candidate_stats(job_applications, hirings, nationwide_job_seeker_users)
    )
    if department_filter_is_selected:
        data["total_job_seeker_users"] = DATA_UNAVAILABLE_BY_DEPARTMENT_ERROR_MESSAGE
        data[
            "total_job_seeker_users_without_opportunity"
        ] = DATA_UNAVAILABLE_BY_DEPARTMENT_ERROR_MESSAGE

    data.update(
        get_prescriber_stats(
            nationwide_prescriber_users,
            authorized_prescriber_users,
            authorized_prescriber_orgs,
            job_applications,
        )
    )
    if department_filter_is_selected:
        data["total_prescriber_users"] = DATA_UNAVAILABLE_BY_DEPARTMENT_ERROR_MESSAGE
        data[
            "total_unauthorized_prescriber_users"
        ] = DATA_UNAVAILABLE_BY_DEPARTMENT_ERROR_MESSAGE
        data["prescriber_users_per_creation_week"] = None
        data["orgs_by_dpt"] = None

    context = {
        "data": data,
        "departments": departments,
        "current_department": current_department,
        "current_department_name": dict(departments)[current_department],
    }
    return render(request, template_name, context)


def get_department_choices():
    all_departments_text = _(
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
    data = {"siaes_by_kind": {}, "siaes_by_dpt": {}}

    kpi_name = _("Structures connues à ce jour")
    siaes_subset = siaes
    data = inject_siaes_subset_total_by_kind_and_by_dpt(data, kpi_name, siaes_subset)

    kpi_name = _("Structures inscrites à ce jour")
    siaes_subset = siaes.filter(siaemembership__user__is_active=True).distinct()
    data = inject_siaes_subset_total_by_kind_and_by_dpt(data, kpi_name, siaes_subset)

    kpi_name = _("Structures actives à ce jour")
    today = get_today()
    data["days_for_siae_to_be_considered_active"] = 7
    some_time_ago = today + relativedelta(
        days=-data["days_for_siae_to_be_considered_active"]
    )
    siaes_subset = siaes.filter(
        Q(created_at__date__gte=some_time_ago)
        # Any migration updating all siaes can incorrectly make us believe
        # the number of active siaes has skyrocketed. Thus we no longer trust
        # siae.updated_at to mean the siae is "active".
        # | Q(updated_at__date__gte=some_time_ago)
        | Q(siaemembership__user__date_joined__date__gte=some_time_ago)
        | Q(job_description_through__created_at__date__gte=some_time_ago)
        | Q(job_description_through__updated_at__date__gte=some_time_ago)
        | Q(job_applications_received__created_at__date__gte=some_time_ago)
        | Q(job_applications_received__updated_at__date__gte=some_time_ago)
    ).distinct()
    data = inject_siaes_subset_total_by_kind_and_by_dpt(data, kpi_name, siaes_subset)

    data["siaes_by_kind"] = inject_table_data_from_series(data["siaes_by_kind"])
    data["siaes_by_dpt"] = inject_table_data_from_series(data["siaes_by_dpt"])

    return data


def get_today():
    return timezone.localtime(timezone.now()).date()


def get_candidate_stats(job_applications, hirings, nationwide_job_seeker_users):
    data = {}

    data["total_job_applications"] = job_applications.count()
    data["total_hirings"] = hirings.count()
    data.update(get_hiring_delays(hirings))
    data["total_auto_approval_deliveries"] = job_applications.filter(
        approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_AUTOMATIC
    ).count()
    data["total_manual_approval_deliveries"] = job_applications.filter(
        approval_delivery_mode=JobApplication.APPROVAL_DELIVERY_MODE_MANUAL
    ).count()

    data["total_job_seeker_users"] = nationwide_job_seeker_users.count()

    # Job seekers without opportunity are those registered for more
    # than X days, having at least one job_application but no hiring.
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
    return data


def get_prescriber_stats(
    nationwide_prescriber_users,
    authorized_prescriber_users,
    authorized_prescriber_orgs,
    job_applications,
):
    data = {"orgs_by_kind": {}, "orgs_by_dpt": {}}
    data["total_prescriber_users"] = nationwide_prescriber_users.count()

    data["total_authorized_prescriber_users"] = authorized_prescriber_users.count()
    data["total_unauthorized_prescriber_users"] = (
        data["total_prescriber_users"] - data["total_authorized_prescriber_users"]
    )

    data["total_authorized_prescriber_orgs"] = authorized_prescriber_orgs.count()

    kpi_name = _("Organisations connues à ce jour")
    orgs_subset = authorized_prescriber_orgs
    data = inject_orgs_subset_total_by_kind_and_by_dpt(data, kpi_name, orgs_subset)

    kpi_name = _("Organisations inscrites à ce jour")
    orgs_subset = authorized_prescriber_orgs.filter(members__is_active=True)
    data = inject_orgs_subset_total_by_kind_and_by_dpt(data, kpi_name, orgs_subset)

    kpi_name = _("Organisations actives à ce jour")
    today = get_today()
    data["days_for_orgs_to_be_considered_active"] = 7
    some_time_ago = today + relativedelta(
        days=-data["days_for_orgs_to_be_considered_active"]
    )
    orgs_subset = authorized_prescriber_orgs.filter(
        members__job_applications_sent__created_at__date__gte=some_time_ago
    )
    data = inject_orgs_subset_total_by_kind_and_by_dpt(data, kpi_name, orgs_subset)

    data["orgs_by_dpt"] = inject_table_data_from_series(data["orgs_by_dpt"])

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


def inject_siaes_subset_total_by_kind_and_by_dpt(data, kpi_name, siaes_subset):
    data["siaes_by_kind"] = inject_siaes_subset_total_by_kind(
        data["siaes_by_kind"], kpi_name, siaes_subset
    )
    data["siaes_by_dpt"] = inject_siaes_subset_total_by_dpt(
        data["siaes_by_dpt"], kpi_name, siaes_subset
    )
    return data


def inject_siaes_subset_total_by_kind(data, kpi_name, siaes_subset):
    data = _inject_subset_total_by_category(
        data=data,
        kpi_name=kpi_name,
        items_subset=siaes_subset,
        category_choices=Siae.KIND_CHOICES,
        category_field="kind",
    )
    return data


def inject_siaes_subset_total_by_dpt(data, kpi_name, siaes_subset):
    data = _inject_subset_total_by_category(
        data=data,
        kpi_name=kpi_name,
        items_subset=siaes_subset,
        category_choices=[(d, DEPARTMENTS[d]) for d in settings.ITOU_TEST_DEPARTMENTS],
        category_field="department",
    )
    return data


def inject_orgs_subset_total_by_kind_and_by_dpt(data, kpi_name, orgs_subset):
    data["orgs_by_dpt"] = inject_orgs_subset_total_by_dpt(
        data["orgs_by_dpt"], kpi_name, orgs_subset
    )
    # TODO stats by kind as soon as we have a proper PrescriberOrganization.kind field!
    return data


def inject_orgs_subset_total_by_dpt(data, kpi_name, orgs_subset):
    data = _inject_subset_total_by_category(
        data=data,
        kpi_name=kpi_name,
        items_subset=orgs_subset,
        category_choices=[(d, DEPARTMENTS[d]) for d in settings.ITOU_TEST_DEPARTMENTS],
        category_field="department",
    )
    return data


def _inject_subset_total_by_category(
    data, kpi_name, items_subset, category_choices, category_field
):
    if data == {}:
        data["categories"] = category_choices
        data["series"] = []

    items_by_category_as_list = (
        items_subset.values(category_field)
        .annotate(total=Count("pk", distinct=True))
        .order_by(category_field)
    )

    items_by_category_as_dict = defaultdict(
        int, {item[category_field]: item["total"] for item in items_by_category_as_list}
    )

    serie_values = [items_by_category_as_dict[choice[0]] for choice in category_choices]

    total = items_subset.count()
    if sum(serie_values) != total:
        raise ValueError("Inconsistent results.")

    data["series"].append({"name": kpi_name, "values": serie_values, "total": total})
    return data


def inject_table_data_from_series(data):
    """
    Transform series data into a format suitable for easy
    display as a table (thead / tbody), compute percentage (%)
    value for all columns but the first one, relative to the first one,
    and add a final total row.
    """
    thead = ["#"]
    for index, serie in enumerate(data["series"]):
        thead.append(serie["name"])
        if index != 0:
            thead.append("(%)")

    def inject_value_and_its_percentage_into_row(row, value, index_serie):
        row.append(value)
        if index_serie != 0:
            first_column_value = row[1]
            if first_column_value == 0:
                row.append(_("N/A"))
            else:
                pct_value = round(100 * value / first_column_value)
                row.append(f"{pct_value}%")

    tbody = []
    for index_category, category in enumerate(data["categories"]):
        if category[1].endswith(f"({category[0]})"):
            # Department choices already have department number as a suffix.
            category_name = category[1]
        else:
            # Siae kind choices do not.
            category_name = f"{category[1]} ({category[0]})"
        row = [category_name]
        for index_serie, serie in enumerate(data["series"]):
            value = serie["values"][index_category]
            inject_value_and_its_percentage_into_row(row, value, index_serie)
        tbody.append(row)

    row = [_("Total")]
    for index_serie, serie in enumerate(data["series"]):
        value = serie["total"]
        inject_value_and_its_percentage_into_row(row, value, index_serie)
    tbody.append(row)

    data["as_table"] = {"thead": thead, "tbody": tbody}
    return data


def get_hiring_delays(hirings):
    # Fetch several key dates of hirings, in chronological order:
    # 1) Job application date is job_application.created_at
    # 2) Approval date (aka "Hiring date") is job_application.logs__timestamp
    #    where job_application.logs__state="accepted"
    # 3) IAE Pass delivery date is job_application.approval_number_sent_at
    # 4) Start of contract is job_application.approval__start_at
    hiring_dates = (
        hirings.filter(logs__transition="accept", logs__to_state="accepted")
        .distinct()
        .values(
            "created_at",
            "logs__timestamp",
            "approval_number_sent_at",
            "approval__start_at",
        )
        # We ignore hirings whose events are in the wrong chronological order.
        .filter(
            logs__timestamp__gte=F("created_at"),
            approval_number_sent_at__gte=F("logs__timestamp"),
            approval__start_at__gte=F("approval_number_sent_at"),
        )
    )

    hiring_delays = hiring_dates.aggregate(
        average_delay_from_application_to_hiring=Avg(
            F("logs__timestamp") - F("created_at"), output_field=DateTimeField()
        ),
        average_delay_from_hiring_to_pass_delivery=Avg(
            F("approval_number_sent_at") - F("logs__timestamp"),
            output_field=DateTimeField(),
        ),
        average_delay_from_pass_delivery_to_contract_start=Avg(
            F("approval__start_at") - F("approval_number_sent_at"),
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
        if author_kind is None:
            # Some hirings have a job_seeker without any eligibility_diagnosis,
            # this happens because they have an implicit eligibility_diagnosis
            # from the fact that their approval comes from PE and not Itou.
            pass
        else:
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

    # Let's hardcode colors for aesthetics and consistency between charts.
    colors = ["#2f7ed8", "#0d233a", "#8bbc21", "#910000"]

    for idx, val in enumerate(donut_chart_data):
        val["color"] = colors[idx]

    return donut_chart_data
