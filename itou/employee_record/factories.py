import string

import factory

from itou.employee_record.models import EmployeeRecord
from itou.job_applications.factories import JobApplicationWithApprovalNotCancellableFactory


class EmployeeRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmployeeRecord

    job_application = factory.SubFactory(JobApplicationWithApprovalNotCancellableFactory)

    asp_id = factory.fuzzy.FuzzyText(length=7, chars=string.digits)
    approval_number = factory.fuzzy.FuzzyText(length=7, chars=string.digits, prefix="99999")
