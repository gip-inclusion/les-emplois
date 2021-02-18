import datetime
import string

import factory
import factory.fuzzy
from dateutil.relativedelta import relativedelta
from faker import Faker

from itou.approvals.models import Approval, PoleEmploiApproval, Prolongation, Suspension
from itou.siaes.factories import SiaeFactory, SiaeWithMembershipFactory
from itou.users.factories import JobSeekerFactory


fake = Faker("fr_FR")


class ApprovalFactory(factory.django.DjangoModelFactory):
    """Generate an Approval() object for unit tests."""

    class Meta:
        model = Approval

    user = factory.SubFactory(JobSeekerFactory)
    number = factory.fuzzy.FuzzyText(length=7, chars=string.digits, prefix=Approval.ASP_ITOU_PREFIX)
    start_at = datetime.date.today()
    end_at = factory.LazyAttribute(lambda obj: Approval.get_default_end_date(obj.start_at))


class SuspensionFactory(factory.django.DjangoModelFactory):
    """Generate a Suspension() object for unit tests."""

    class Meta:
        model = Suspension

    approval = factory.SubFactory(ApprovalFactory)
    start_at = factory.LazyAttribute(lambda obj: obj.approval.start_at)
    end_at = factory.LazyAttribute(lambda obj: Suspension.get_max_end_at(obj.start_at))
    siae = factory.SubFactory(SiaeFactory)


class ProlongationFactory(factory.django.DjangoModelFactory):
    """Generate a Prolongation() object for unit tests."""

    class Meta:
        model = Prolongation

    approval = factory.SubFactory(ApprovalFactory)
    start_at = factory.LazyAttribute(lambda obj: obj.approval.start_at)
    end_at = factory.LazyAttribute(lambda obj: Prolongation.get_max_end_at(obj.start_at, reason=obj.reason))
    reason = Prolongation.Reason.COMPLETE_TRAINING.value
    reason_explanation = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
    siae = factory.SubFactory(SiaeWithMembershipFactory)
    requested_by = factory.LazyAttribute(lambda obj: obj.siae.members.first())


class PoleEmploiApprovalFactory(factory.django.DjangoModelFactory):
    """Generate an PoleEmploiApproval() object for unit tests."""

    class Meta:
        model = PoleEmploiApproval

    pe_structure_code = factory.fuzzy.FuzzyText(length=5, chars=string.digits)
    pole_emploi_id = factory.fuzzy.FuzzyText(length=8, chars=string.digits)
    number = factory.fuzzy.FuzzyText(length=12, chars=string.digits)
    birth_name = factory.LazyAttribute(lambda obj: obj.last_name)
    birthdate = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(2000, 1, 1))
    start_at = datetime.date.today()
    end_at = factory.LazyAttribute(lambda obj: obj.start_at + relativedelta(years=2) - relativedelta(days=1))

    @factory.lazy_attribute
    def first_name(self):
        return PoleEmploiApproval.format_name_as_pole_emploi(fake.first_name())

    @factory.lazy_attribute
    def last_name(self):
        return PoleEmploiApproval.format_name_as_pole_emploi(fake.last_name())

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        """
        If any `*_name` is passed through kwargs, ensure that it's
        formatted like it is in the Pôle emploi export file.
        """
        kwargs["first_name"] = PoleEmploiApproval.format_name_as_pole_emploi(kwargs["first_name"])
        kwargs["last_name"] = PoleEmploiApproval.format_name_as_pole_emploi(kwargs["last_name"])
        kwargs["birth_name"] = PoleEmploiApproval.format_name_as_pole_emploi(kwargs["birth_name"])
        return kwargs
