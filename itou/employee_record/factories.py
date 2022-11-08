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
    asp_id = factory.fuzzy.FuzzyInteger(10000)

    @factory.post_generation
    def set_job_seeker_profile(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return

        self.siret = self.job_application.to_siae.siret
        self.approval_number = self.approval_number or self.job_application.approval.number
        self.asp_id = self.job_application.to_siae.convention.asp_id


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
