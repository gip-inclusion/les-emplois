import factory

from itou.employee_record.enums import NotificationStatus, NotificationType
from itou.employee_record.models import EmployeeRecord, EmployeeRecordUpdateNotification
from itou.job_applications.factories import (
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
)


class BareEmployeeRecordFactory(factory.django.DjangoModelFactory):
    asp_id = factory.Faker("pyint")
    approval_number = factory.Faker("pystr_format", string_format="#" * 12)

    class Meta:
        model = EmployeeRecord


class EmployeeRecordFactory(BareEmployeeRecordFactory):
    """
    "Basic" employee record factory:
    At the first stage of its lifecycle (NEW)
    (no job seeker profile linked => not updatable)
    """

    job_application = factory.SubFactory(JobApplicationWithApprovalNotCancellableFactory)
    asp_id = factory.SelfAttribute(".job_application.to_siae.convention.asp_id")
    approval_number = factory.SelfAttribute(".job_application.approval.number")
    siret = factory.SelfAttribute(".job_application.to_siae.siret")


class EmployeeRecordWithProfileFactory(EmployeeRecordFactory):
    """
    Employee record with a complete job seeker profile
    """

    job_application = factory.SubFactory(JobApplicationWithCompleteJobSeekerProfileFactory)


class BareEmployeeRecordUpdateNotificationFactory(factory.django.DjangoModelFactory):
    employee_record = factory.SubFactory(BareEmployeeRecordFactory)
    notification_type = NotificationType.APPROVAL
    status = NotificationStatus.NEW

    class Meta:
        model = EmployeeRecordUpdateNotification


class EmployeeRecordUpdateNotificationFactory(BareEmployeeRecordUpdateNotificationFactory):
    employee_record = factory.SubFactory(EmployeeRecordWithProfileFactory)
