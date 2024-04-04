import datetime

import factory

from itou.asp import models as asp_models
from itou.employee_record.enums import NotificationStatus, Status
from itou.employee_record.models import EmployeeRecord, EmployeeRecordUpdateNotification
from tests.job_applications.factories import (
    JobApplicationFactory,
    JobApplicationWithApprovalNotCancellableFactory,
    JobApplicationWithCompleteJobSeekerProfileFactory,
)
from tests.utils.factory_boy import AutoNowOverrideMixin


class BareEmployeeRecordFactory(factory.django.DjangoModelFactory):
    job_application = factory.SubFactory(
        JobApplicationFactory,
        sender=None,
        eligibility_diagnosis=None,
        to_company__with_membership=False,
        to_company__convention=None,
    )
    asp_id = factory.Faker("pyint")
    approval_number = factory.Faker("pystr_format", string_format="#" * 12)

    class Meta:
        model = EmployeeRecord


class EmployeeRecordFactory(AutoNowOverrideMixin, BareEmployeeRecordFactory):
    """
    "Basic" employee record factory:
    At the first stage of its lifecycle (NEW)
    (no job seeker profile linked => not updatable)
    """

    job_application = factory.SubFactory(
        JobApplicationWithApprovalNotCancellableFactory, to_company__use_employee_record=True
    )
    asp_id = factory.SelfAttribute(".job_application.to_company.convention.asp_id")
    asp_measure = factory.LazyAttribute(
        lambda obj: asp_models.SiaeMeasure.from_siae_kind(obj.job_application.to_company.kind)
    )
    approval_number = factory.SelfAttribute(".job_application.approval.number")
    siret = factory.SelfAttribute(".job_application.to_company.siret")

    class Params:
        archivable = factory.Trait(
            job_application__approval__expired=True,
            created_at=factory.Faker("date_time_between", end_date="-6M", tzinfo=datetime.UTC),
            updated_at=factory.Faker("date_time_between", end_date="-3M", tzinfo=datetime.UTC),
        )
        with_batch_information = factory.Trait(
            asp_batch_file=factory.Faker("asp_batch_filename"), asp_batch_line_number=factory.Sequence(int)
        )
        ready_for_transfer = factory.Trait(
            status=Status.READY,
            job_application=factory.SubFactory(
                JobApplicationWithCompleteJobSeekerProfileFactory,
                to_company__use_employee_record=True,
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
