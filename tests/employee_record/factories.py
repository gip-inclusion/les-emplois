import datetime

import factory

from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecord, EmployeeRecordUpdateNotification
from tests.job_applications.factories import (
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

    job_application = factory.SubFactory(
        JobApplicationWithApprovalNotCancellableFactory, to_siae__use_employee_record=True
    )
    asp_id = factory.SelfAttribute(".job_application.to_siae.convention.asp_id")
    approval_number = factory.SelfAttribute(".job_application.approval.number")
    siret = factory.SelfAttribute(".job_application.to_siae.siret")

    class Params:
        archivable = factory.Trait(
            job_application__approval__expired=True,
            created_at=factory.Faker("date_time_between", end_date="-6M", tzinfo=datetime.UTC),
        )
        orphan = factory.Trait(asp_id=0)
        with_batch_information = factory.Trait(
            asp_batch_file=factory.Faker("asp_batch_filename"), asp_batch_line_number=factory.Sequence(int)
        )
        ready_for_transfer = factory.Trait(
            status=Status.READY,
            job_application=factory.SubFactory(
                JobApplicationWithCompleteJobSeekerProfileFactory,
                to_siae__use_employee_record=True,
            ),
        )


class EmployeeRecordWithProfileFactory(EmployeeRecordFactory):
    """
    Employee record with a complete job seeker profile
    """

    job_application = factory.SubFactory(JobApplicationWithCompleteJobSeekerProfileFactory)


class BareEmployeeRecordUpdateNotificationFactory(factory.django.DjangoModelFactory):
    employee_record = factory.SubFactory(BareEmployeeRecordFactory)
    status = NotificationStatus.NEW

    class Meta:
        model = EmployeeRecordUpdateNotification


class EmployeeRecordUpdateNotificationFactory(BareEmployeeRecordUpdateNotificationFactory):
    employee_record = factory.SubFactory(EmployeeRecordWithProfileFactory)

    class Params:
        ready_for_transfer = factory.Trait(status=Status.NEW)
