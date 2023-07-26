import datetime
import string

import factory.fuzzy
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from faker import Faker

from itou.approvals.enums import Origin, ProlongationReason
from itou.approvals.models import Approval, PoleEmploiApproval, Prolongation, ProlongationRequest, Suspension
from itou.job_applications.models import JobApplicationWorkflow
from itou.siaes.enums import SiaeKind
from tests.eligibility.factories import EligibilityDiagnosisFactory
from tests.files.factories import FileFactory
from tests.prescribers.factories import PrescriberOrganizationFactory
from tests.siaes.factories import SiaeFactory
from tests.users.factories import JobSeekerFactory, PrescriberFactory


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
        origin_pe_approval = factory.Trait(origin=Origin.PE_APPROVAL, eligibility_diagnosis=None)
        origin_ai_stock = factory.Trait(origin=Origin.AI_STOCK, eligibility_diagnosis=None)
        for_snapshot = factory.Trait(
            number="999999999999",
            user__for_snapshot=True,
            start_at=datetime.date(2000, 1, 1),
            end_at=datetime.date(3000, 1, 1),
            origin_pe_approval=True,
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
            from tests.job_applications.factories import JobApplicationFactory

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


class BaseProlongationFactory(factory.django.DjangoModelFactory):
    class Meta:
        abstract = True

    class Params:
        for_snapshot = factory.Trait(
            pk=666,
            approval__for_snapshot=True,
            start_at=factory.SelfAttribute("approval.start_at"),
            declared_by_siae__for_snapshot=True,
            validated_by__for_snapshot=True,
            reason=ProlongationReason.SENIOR.value,
            report_file=factory.SubFactory(FileFactory, for_snapshot=True),
            require_phone_interview=True,
            contact_email="email@example.com",
            contact_phone="+33123456789",
            created_at=datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC),
        )

    approval = factory.SubFactory(ApprovalFactory)
    start_at = factory.Faker("date_between", start_date=factory.SelfAttribute("..approval.start_at"))
    end_at = factory.LazyAttribute(lambda obj: Prolongation.get_max_end_at(obj.start_at, reason=obj.reason))
    reason = ProlongationReason.COMPLETE_TRAINING.value
    reason_explanation = "Lorem ipsum dolor sit amet, consectetur adipiscing elit."
    declared_by = factory.LazyAttribute(lambda obj: obj.declared_by_siae.members.first())
    declared_by_siae = factory.SubFactory(SiaeFactory, with_membership=True)
    validated_by = factory.SubFactory(PrescriberFactory, membership__organization__authorized=True)
    created_by = factory.SelfAttribute("declared_by")


class ProlongationRequestFactory(BaseProlongationFactory):
    prescriber_organization = factory.SubFactory(
        PrescriberOrganizationFactory,
        authorized=True,
    )
    validated_by = factory.SubFactory(
        PrescriberFactory, membership__organization=factory.SelfAttribute("...prescriber_organization")
    )

    class Meta:
        model = ProlongationRequest

    class Params:
        processed = factory.Trait(
            processed_by=factory.SelfAttribute("validated_by"),
            processed_at=factory.Maybe(
                "for_snapshot",
                datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC),
                factory.LazyFunction(timezone.now),
            ),
        )
        for_snapshot = factory.Trait(
            **BaseProlongationFactory._meta.parameters["for_snapshot"].overrides,
            prescriber_organization__for_snapshot=True,
        )


class ProlongationFactory(BaseProlongationFactory):
    class Meta:
        model = Prolongation


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
