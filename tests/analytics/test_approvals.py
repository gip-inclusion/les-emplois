from django.utils import timezone

from itou.analytics import approvals, models
from itou.utils.apis import enums as api_enums
from tests.approvals import factories as approvals_factories


def test_datum_name_value():
    assert models.DatumCode.APPROVAL_COUNT.value == "AP-001"
    assert models.DatumCode.APPROVAL_CANCELLED.value == "AP-002"

    assert models.DatumCode.APPROVAL_PE_NOTIFY_SUCCESS.value == "AP-101"
    assert models.DatumCode.APPROVAL_PE_NOTIFY_PENDING.value == "AP-102"
    assert models.DatumCode.APPROVAL_PE_NOTIFY_ERROR.value == "AP-103"


def test_collect_analytics_data_return_all_codes():
    assert approvals.collect_analytics_data(timezone.now()).keys() == {
        models.DatumCode.APPROVAL_COUNT,
        models.DatumCode.APPROVAL_CANCELLED,
        models.DatumCode.APPROVAL_PE_NOTIFY_SUCCESS,
        models.DatumCode.APPROVAL_PE_NOTIFY_PENDING,
        models.DatumCode.APPROVAL_PE_NOTIFY_ERROR,
    }


def test_collect_analytics_when_approvals_do_not_exist():
    assert approvals.collect_analytics_data(timezone.now()) == {
        models.DatumCode.APPROVAL_COUNT: 0,
        models.DatumCode.APPROVAL_CANCELLED: 0,
        models.DatumCode.APPROVAL_PE_NOTIFY_SUCCESS: 0,
        models.DatumCode.APPROVAL_PE_NOTIFY_PENDING: 0,
        models.DatumCode.APPROVAL_PE_NOTIFY_ERROR: 0,
    }


def test_collect_analytics_with_data():
    approvals_factories.ApprovalFactory.create_batch(
        3, pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS
    )
    approvals_factories.ApprovalFactory.create_batch(
        2, pe_notification_status=api_enums.PEApiNotificationStatus.PENDING
    )
    approvals_factories.ApprovalFactory.create_batch(
        2, pe_notification_status=api_enums.PEApiNotificationStatus.SHOULD_RETRY
    )
    approvals_factories.ApprovalFactory.create_batch(2, pe_notification_status=api_enums.PEApiNotificationStatus.ERROR)

    approvals_factories.CancelledApprovalFactory.create_batch(
        1, pe_notification_status=api_enums.PEApiNotificationStatus.SUCCESS
    )
    approvals_factories.CancelledApprovalFactory.create_batch(
        2, pe_notification_status=api_enums.PEApiNotificationStatus.PENDING
    )
    approvals_factories.CancelledApprovalFactory.create_batch(
        3, pe_notification_status=api_enums.PEApiNotificationStatus.SHOULD_RETRY
    )
    approvals_factories.CancelledApprovalFactory.create_batch(
        4, pe_notification_status=api_enums.PEApiNotificationStatus.ERROR
    )

    assert approvals.collect_analytics_data(timezone.now()) == {
        models.DatumCode.APPROVAL_COUNT: 9,
        models.DatumCode.APPROVAL_CANCELLED: 10,
        models.DatumCode.APPROVAL_PE_NOTIFY_SUCCESS: 4,
        models.DatumCode.APPROVAL_PE_NOTIFY_PENDING: 9,
        models.DatumCode.APPROVAL_PE_NOTIFY_ERROR: 6,
    }
