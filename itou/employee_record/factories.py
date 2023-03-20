import factory
from django.utils import timezone

from itou.employee_record import constants
from itou.employee_record.enums import NotificationStatus, NotificationType, Status
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

    class Params:
        archivable = factory.Trait(
            status=Status.PROCESSED,
            processed_at=factory.LazyFunction(
                lambda: timezone.now() - timezone.timedelta(days=constants.EMPLOYEE_RECORD_ARCHIVING_DELAY_IN_DAYS)
            ),
        )


class EmployeeRecordFactory(BareEmployeeRecordFactory):
    """
    "Basic" employee record factory:
    At the first stage of its lifecycle (NEW)
    (no job seeker profile linked => not updatable)
    """

    job_application = factory.SubFactory(
        JobApplicationWithApprovalNotCancellableFactory, to_siae__use_employee_record=True
    )
    asp_id = factory.SelfAttribute(".job_application.to_siae.convention.asp_id")
    approval_number = factory.SelfAttribute(".job_application.approval.number")
    siret = factory.SelfAttribute(".job_application.to_siae.siret")

    class Params:
        orphan = factory.Trait(asp_id=0)
        with_batch_information = factory.Trait(
            asp_batch_file=factory.Faker("asp_batch_filename"), asp_batch_line_number=factory.Sequence(int)
        )


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
