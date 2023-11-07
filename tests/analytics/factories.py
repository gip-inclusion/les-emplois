import factory
import factory.fuzzy

from itou.analytics.models import Datum, StatsDashboardVisit
from itou.common_apps.address.departments import DEPARTMENTS
from itou.users.enums import UserKind


class DatumFactory(factory.django.DjangoModelFactory):
    value = factory.Faker("pyint")

    class Meta:
        model = Datum


class StatsDashboardVisitFactory(factory.django.DjangoModelFactory):
    dashboard_id = factory.Faker("pyint")
    department = factory.fuzzy.FuzzyChoice(DEPARTMENTS.keys())
    region = factory.Faker("region", locale="fr_FR")
    current_company_id = factory.Faker("pyint")
    current_prescriber_organization_id = factory.Faker("pyint")
    current_institution_id = factory.Faker("pyint")
    user_kind = factory.fuzzy.FuzzyChoice(UserKind.values)
    user_id = factory.Faker("pyint")

    class Meta:
        model = StatsDashboardVisit
