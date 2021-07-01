import string

import factory

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


class EmployeeRecordWithProfileFactory(EmployeeRecordFactory):
    """
    Employee record with a complete job seeker profile
    """

    job_application = factory.SubFactory(JobApplicationWithCompleteJobSeekerProfileFactory)
