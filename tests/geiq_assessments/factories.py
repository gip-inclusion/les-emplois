import datetime
import random

import factory
import factory.fuzzy
from django.utils import timezone

from itou.companies.enums import CompanyKind
from itou.geiq.sync import _nb_days
from itou.geiq_assessments.models import (
    MIN_DAYS_IN_YEAR_FOR_ALLOWANCE,
    Assessment,
    AssessmentCampaign,
    Employee,
    EmployeeContract,
    EmployeePrequalification,
)
from itou.users.enums import Title
from tests.files.factories import FileFactory
from tests.users.factories import EmployerFactory
from tests.utils.factory_boy import AutoNowOverrideMixin


class AssessmentCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AssessmentCampaign
        django_get_or_create = ("year",)

    year = factory.fuzzy.FuzzyInteger(2020, 2023)
    submission_deadline = factory.LazyAttribute(lambda obj: datetime.date(obj.year + 1, 7, 1))
    review_deadline = factory.LazyAttribute(lambda obj: datetime.date(obj.year + 1, 8, 1))


class AssessmentFactory(AutoNowOverrideMixin, factory.django.DjangoModelFactory):
    class Meta:
        model = Assessment
        skip_postgeneration_save = True

    class Params:
        with_submission_requirements = factory.Trait(
            created_at=factory.LazyFunction(timezone.now),
            contracts_synced_at=factory.LazyAttribute(lambda obj: obj.created_at),
            contracts_selection_validated_at=factory.LazyAttribute(lambda obj: obj.contracts_synced_at),
            geiq_comment=factory.Faker("sentence", nb_words=6),
            structure_financial_assessment_file=factory.SubFactory(FileFactory),
            action_financial_assessment_file=factory.SubFactory(FileFactory),
            summary_document_file=factory.SubFactory(FileFactory),
        )

    campaign = factory.SubFactory(AssessmentCampaignFactory)
    created_by = factory.SubFactory(EmployerFactory, with_company__company__kind=CompanyKind.GEIQ)
    label_geiq_id = factory.Sequence(int)
    label_antennas = []

    @factory.post_generation
    def companies(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return

        if extracted:
            # A list of companies were passed in, use them.
            for company in extracted:
                assert company.kind == CompanyKind.GEIQ
                self.companies.add(company)


class EmployeeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Employee

    assessment = factory.SubFactory(AssessmentFactory)
    label_id = factory.Sequence(int)
    last_name = factory.Faker("last_name")
    first_name = factory.Faker("first_name")
    birthdate = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(2000, 1, 1))
    title = factory.fuzzy.FuzzyChoice(Title.values)
    other_data = factory.LazyFunction(dict)
    allowance_amount = 0


class EmployeePrequalificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmployeePrequalification

    employee = factory.SubFactory(EmployeeFactory)
    label_id = factory.Sequence(int)
    start_at = factory.Faker("date_between", start_date="-5y", end_date="-6M")
    end_at = factory.LazyAttribute(lambda obj: obj.start_at + datetime.timedelta(days=random.randint(0, 500)))
    other_data = factory.LazyFunction(dict)


class EmployeeContractFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmployeeContract

    employee = factory.SubFactory(EmployeeFactory)
    label_id = factory.Sequence(int)
    start_at = factory.Faker("date_between", start_date="-5y", end_date="-6M")
    planned_end_at = factory.LazyAttribute(
        lambda obj: obj.start_at + datetime.timedelta(days=10 + random.randint(0, 500))
    )
    end_at = factory.LazyAttribute(
        lambda obj: obj.planned_end_at - random.randint(0, 1) * datetime.timedelta(days=random.randint(0, 10))
    )
    other_data = factory.LazyFunction(dict)
    nb_days_in_campaign_year = factory.LazyAttribute(
        lambda obj: _nb_days(
            [(obj.start_at, obj.end_at or obj.planned_end_at)],
            year=obj.employee.assessment.campaign.year,
        )
    )
    allowance_requested = factory.LazyAttribute(
        lambda obj: obj.nb_days_in_campaign_year > MIN_DAYS_IN_YEAR_FOR_ALLOWANCE
    )
    allowance_granted = False
