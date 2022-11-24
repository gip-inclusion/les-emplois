import factory

from itou.employee_record.enums import NotificationStatus, NotificationType
from itou.employee_record.models import EmployeeRecord, EmployeeRecordUpdateNotification
from itou.job_applications.factories import (
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
)


class EmployeeRecordFactory(factory.django.DjangoModelFactory):
    """
    "Basic" employee record factory:
    At the first stage of its lifecycle (NEW)
    (no job seeker profile linked => not updatable)
    """

    class Meta:
        model = EmployeeRecord

    job_application = factory.SubFactory(JobApplicationWithApprovalNotCancellableFactory)
    asp_id = factory.SelfAttribute(".job_application.to_siae.convention.asp_id")
    approval_number = factory.SelfAttribute(".job_application.approval.number")
    siret = factory.SelfAttribute(".job_application.to_siae.siret")


class EmployeeRecordWithProfileFactory(EmployeeRecordFactory):
    """
    Employee record with a complete job seeker profile
    """

    job_application = factory.SubFactory(JobApplicationWithCompleteJobSeekerProfileFactory)


class EmployeeRecordUpdateNotificationFactory(factory.django.DjangoModelFactory):
    employee_record = factory.SubFactory(EmployeeRecordWithProfileFactory)
    notification_type = NotificationType.APPROVAL
    status = NotificationStatus.NEW

    class Meta:
        model = EmployeeRecordUpdateNotification
