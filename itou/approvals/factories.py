import datetime
import string

from dateutil.relativedelta import relativedelta
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
    end_at = factory.LazyAttribute(
        lambda obj: obj.start_at + relativedelta(years=2) - relativedelta(days=1)
    )
