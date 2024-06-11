import datetime
import random

import factory
import factory.fuzzy

from itou.companies.enums import CompanyKind
from itou.geiq.models import (
    Employee,
    EmployeePrequalification,
    ImplementationAssessment,
    ImplementationAssessmentCampaign,
)
from itou.users.enums import Title
from tests.companies import factories as companies_factories


class ImplementationAssessmentCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImplementationAssessmentCampaign

    year = factory.fuzzy.FuzzyInteger(2020, 2023)
    submission_deadline = factory.LazyAttribute(lambda obj: datetime.date(obj.year + 1, 7, 1))
    review_deadline = factory.LazyAttribute(lambda obj: datetime.date(obj.year + 1, 8, 1))


class ImplementationAssessmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImplementationAssessment

    campaign = factory.SubFactory(ImplementationAssessmentCampaignFactory)
    company = factory.SubFactory(companies_factories.CompanyFactory, kind=CompanyKind.GEIQ)
    label_id = factory.Sequence(int)
    other_data = factory.LazyFunction(dict)


class EmployeeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Employee

    assessment = factory.SubFactory(ImplementationAssessmentFactory)
    label_id = factory.Sequence(int)
    last_name = factory.Faker("last_name")
    first_name = factory.Faker("first_name")
    birthdate = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(2000, 1, 1))
    title = factory.fuzzy.FuzzyChoice(Title.values)
    other_data = factory.LazyFunction(dict)
    annex1_nb = 0
    annex2_level1_nb = 0
    annex2_level2_nb = 0
    allowance_amount = 0
    support_days_nb = 0


class PrequalificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmployeePrequalification

    employee = factory.SubFactory(EmployeeFactory)
    label_id = factory.Sequence(int)
    start_at = factory.Faker("date_time_between", start_date="-5y", end_date="-6M", tzinfo=datetime.UTC)
    end_at = factory.LazyAttribute(lambda obj: obj.start_at + datetime.timedelta(days=random.randint(0, 500)))
    other_data = factory.LazyFunction(dict)
