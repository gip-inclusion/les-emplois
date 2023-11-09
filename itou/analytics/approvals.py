from django.db.models import Count, Q

from itou.approvals import models as approvals_models
from itou.utils.apis import enums as api_enums

from . import models


def collect_approvals_counts(before):
    counts = approvals_models.Approval.objects.filter(created_at__lt=before).aggregate(
        total=Count("pk"),
        pe_notify_success=Count("pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS)),
        pe_notify_pending=Count(
            "pk",
            filter=Q(
                pe_notification_status__in=(
                    api_enums.PEApiNotificationStatus.PENDING,
                    api_enums.PEApiNotificationStatus.SHOULD_RETRY,
                )
            ),
        ),
        pe_notify_error=Count("pk", filter=Q(pe_notification_status=api_enums.PEApiNotificationStatus.ERROR)),
    )
    return {
        models.DatumCode.APPROVAL_COUNT: counts["total"],
        models.DatumCode.APPROVAL_PE_NOTIFY_SUCCESS: counts["pe_notify_success"],
        models.DatumCode.APPROVAL_PE_NOTIFY_PENDING: counts["pe_notify_pending"],
        models.DatumCode.APPROVAL_PE_NOTIFY_ERROR: counts["pe_notify_error"],
    }


def collect_cancelled_approvals(before):
    cancelled_count = approvals_models.CancelledApproval.objects.filter(created_at__lt=before).count()
    return {models.DatumCode.APPROVAL_CANCELLED: cancelled_count}


def collect_analytics_data(before):
    return {
        **collect_approvals_counts(before),
        **collect_cancelled_approvals(before),
    }
