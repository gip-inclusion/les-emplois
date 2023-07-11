import datetime
import string

import factory
import factory.fuzzy
from dateutil.relativedelta import relativedelta
from faker import Faker

from itou.approvals.enums import ProlongationReason
from itou.approvals.models import Approval, PoleEmploiApproval, Prolongation, Suspension
from itou.job_applications.models import JobApplicationWorkflow
from itou.siaes.enums import SiaeKind
from tests.eligibility.factories import EligibilityDiagnosisFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.siaes.factories import SiaeFactory
from tests.users.factories import JobSeekerFactory


fake = Faker("fr_FR")


class ApprovalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Approval

    class Params:
        # Use old (but realistic) dates so `expired` can be used anywhere without triggering specials cases
        expired = factory.Trait(
            start_at=factory.Faker("date_time_between", start_date="-5y", end_date="-3y"),
            end_at=factory.Faker("date_time_between", start_date="-3y", end_date="-2y"),
        )

    user = factory.SubFactory(JobSeekerFactory)
    number = factory.fuzzy.FuzzyText(length=7, chars=string.digits, prefix=Approval.ASP_ITOU_PREFIX)
    start_at = factory.LazyFunction(datetime.date.today)
    end_at = factory.LazyAttribute(lambda obj: Approval.get_default_end_date(obj.start_at))
    eligibility_diagnosis = factory.SubFactory(EligibilityDiagnosisFactory, job_seeker=factory.SelfAttribute("..user"))

    @factory.post_generation
    def with_jobapplication(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            from tests.job_applications.factories import (
                JobApplicationFactory,  # pylint: disable=import-outside-toplevel
            )

            state = kwargs.pop("state", JobApplicationWorkflow.STATE_ACCEPTED)
            self.jobapplication_set.add(JobApplicationFactory(state=state, job_seeker=self.user, **kwargs))


class SuspensionFactory(factory.django.DjangoModelFactory):
    """Generate a Suspension() object for unit tests."""

    class Meta:
        model = Suspension

    approval = factory.SubFactory(ApprovalFactory)
    start_at = factory.Faker("date_between", start_date=factory.SelfAttribute("..approval.start_at"))
    end_at = factory.LazyAttribute(lambda obj: Suspension.get_max_end_at(obj.start_at))
    siae = factory.SubFactory(SiaeFactory)


class ProlongationFactory(factory.django.DjangoModelFactory):
    """Generate a Prolongation() object for unit tests."""

    class Meta:
        model = Prolongation

    approval = factory.SubFactory(ApprovalFactory)
    start_at = factory.Faker("date_between", start_date=factory.SelfAttribute("..approval.start_at"))
    end_at = factory.LazyAttribute(lambda obj: Prolongation.get_max_end_at(obj.start_at, reason=obj.reason))
    reason = ProlongationReason.COMPLETE_TRAINING.value
    reason_explanation = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
    declared_by = factory.LazyAttribute(lambda obj: obj.declared_by_siae.members.first())
    declared_by_siae = factory.SubFactory(SiaeFactory, with_membership=True)
    created_by = factory.SelfAttribute("declared_by")

    @factory.post_generation
    def set_validated_by(self, create, extracted, **kwargs):
        if not create:
            return
        # Ignore setting validated_by:
        # ProlongationFactory(set_validated_by=False)
        if extracted is False:
            return

        authorized_prescriber_org = PrescriberOrganizationWithMembershipFactory(authorized=True)
        self.validated_by = authorized_prescriber_org.members.first()


class PoleEmploiApprovalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PoleEmploiApproval

    pe_structure_code = factory.fuzzy.FuzzyText(length=5, chars=string.digits)
    pole_emploi_id = factory.fuzzy.FuzzyText(length=8, chars=string.digits)
    number = factory.fuzzy.FuzzyText(length=12, chars=string.digits)
    birth_name = factory.SelfAttribute("last_name")
    birthdate = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(2000, 1, 1))
    start_at = factory.LazyFunction(datetime.date.today)
    end_at = factory.LazyAttribute(lambda obj: obj.start_at + relativedelta(years=2) - relativedelta(days=1))
    siae_siret = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    siae_kind = factory.fuzzy.FuzzyChoice(SiaeKind.values)

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
