import string
from datetime import timedelta

import factory
from django.utils import timezone

from itou.employee_record.models import EmployeeRecord
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

    asp_id = factory.fuzzy.FuzzyText(length=7, chars=string.digits)
    approval_number = factory.fuzzy.FuzzyText(length=7, chars=string.digits, prefix="99999")

    @factory.post_generation
    def set_job_seeker_profile(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return

        self.siret = self.job_application.to_siae.siret


class EmployeeRecordWithProfileFactory(EmployeeRecordFactory):
    """
    Employee record with a complete job seeker profile
    """

    job_application = factory.SubFactory(JobApplicationWithCompleteJobSeekerProfileFactory)


class EmployeeRecordUpdateNotificationFactory(factory.django.DjangoModelFactory):
    employee_record = factory.SubFactory(EmployeeRecordFactory)
    start_at = timezone.now().date()
    end_at = timezone.now().date() + timedelta(weeks=52)
