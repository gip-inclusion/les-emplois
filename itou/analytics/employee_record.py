from django.db.models import Count, Max, Min

from itou.analytics import models
from itou.employee_record import models as employee_record_models


def collect_employee_records_count(before):
    return {
        models.DatumCode.EMPLOYEE_RECORD_COUNT: employee_record_models.EmployeeRecord.objects.filter(
            created_at__lt=before
        ).count(),
    }


def collect_probably_deleted_employee_records(before):
    data = employee_record_models.EmployeeRecord.objects.filter(created_at__lt=before).aggregate(
        first_pk=Min("pk"),
        last_pk=Max("pk"),
        count_pk=Count("pk"),
    )

    value = ((data["last_pk"] - data["first_pk"] + 1) - data["count_pk"]) if None not in data.values() else 0
    return {models.DatumCode.EMPLOYEE_RECORD_DELETED: value}


def collect_employee_records_processing_code_of_first_exchange(before):
    data = (
        employee_record_models.EmployeeRecord.objects.filter(created_at__lt=before)
        .values("asp_processing_code")
        .annotate(
            count=Count("asp_processing_code"),
        )
    )
    count_by_processing_code = {item["asp_processing_code"]: item["count"] for item in data}

    return {
        models.DatumCode.EMPLOYEE_RECORD_PROCESSED_AT_FIRST_EXCHANGE: count_by_processing_code.get(
            employee_record_models.EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE, 0
        ),
        models.DatumCode.EMPLOYEE_RECORD_WITH_ERROR_AT_FIRST_EXCHANGE: sum(
            count
            for code, count in count_by_processing_code.items()
            if code != employee_record_models.EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE
        ),
        models.DatumCode.EMPLOYEE_RECORD_WITH_ERROR_3436_AT_FIRST_EXCHANGE: count_by_processing_code.get(
            employee_record_models.EmployeeRecord.ASP_DUPLICATE_ERROR_CODE, 0
        ),
    }


def collect_employee_record_with_at_least_one_error(before):
    employee_records_with_at_least_one_error = employee_record_models.EmployeeRecordQuerySet.union(
        employee_record_models.EmployeeRecord.objects.filter(created_at__lt=before)
        .exclude(
            asp_processing_code=employee_record_models.EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
        )
        .values("pk"),
        employee_record_models.EmployeeRecordUpdateNotification.objects.filter(created_at__lt=before)
        .exclude(
            asp_processing_code=employee_record_models.EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE,
        )
        .values("employee_record"),
    )

    value = (
        employee_record_models.EmployeeRecord.objects.filter(pk__in=employee_records_with_at_least_one_error)
        .distinct()
        .count()
    )
    return {models.DatumCode.EMPLOYEE_RECORD_WITH_AT_LEAST_ONE_ERROR: value}


def collect_analytics_data(before):
    return {
        **collect_employee_records_count(before),
        **collect_probably_deleted_employee_records(before),
        **collect_employee_records_processing_code_of_first_exchange(before),
        **collect_employee_record_with_at_least_one_error(before),
    }
