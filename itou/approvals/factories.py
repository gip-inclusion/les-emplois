import datetime
import string

import factory
import factory.fuzzy

from itou.approvals import models
from itou.users.factories import JobSeekerFactory


class ApprovalFactory(factory.django.DjangoModelFactory):
    """Generate an Approval() object for unit tests."""

    class Meta:
        model = models.Approval

    user = factory.SubFactory(JobSeekerFactory)
    number = factory.fuzzy.FuzzyText(length=12, chars=string.digits)
    start_at = datetime.date.today()
    end_at = datetime.date.today() + datetime.timedelta(days=365 * 2)
