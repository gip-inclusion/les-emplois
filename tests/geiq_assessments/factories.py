import datetime
import random

import factory
import factory.fuzzy

from itou.companies.enums import CompanyKind
from itou.geiq.sync import _more_than_3_months_in_year
from itou.geiq_assessments.models import (
    Assessment,
    AssessmentCampaign,
    Employee,
    EmployeeContract,
    EmployeePrequalification,
)
from itou.users.enums import Title
from tests.users.factories import EmployerFactory


class AssessmentCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AssessmentCampaign
        django_get_or_create = ("year",)

    year = factory.fuzzy.FuzzyInteger(2020, 2023)
    submission_deadline = factory.LazyAttribute(lambda obj: datetime.date(obj.year + 1, 7, 1))
    review_deadline = factory.LazyAttribute(lambda obj: datetime.date(obj.year + 1, 8, 1))


class AssessmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Assessment
        skip_postgeneration_save = True

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
    with_3_months_in_assessment_year = factory.LazyAttribute(
        lambda obj: _more_than_3_months_in_year(
            obj.start_at,
            obj.end_at or obj.planned_end_at,
            year=obj.employee.assessment.campaign.year,
        )
    )
    allowance_requested = factory.LazyAttribute(lambda obj: obj.with_3_months_in_assessment_year)
    allowance_granted = False
