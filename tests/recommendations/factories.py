import datetime
import string

import factory
import factory.fuzzy
from django.contrib.gis.geos import Point

from itou.recommendations import models
from itou.recommendations.criteria import StructuredSolutionCandidate, StructuredSolutionKind
from itou.recommendations.profile import BeneficiaryProfile


_PARIS = Point(2.3488, 48.8534, srid=4326)
_CLOSE_TO_PARIS = Point(2.35, 48.86, srid=4326)  # ~1 km
_MARSEILLE = Point(5.37, 43.30, srid=4326)  # Marseille, ~660 km
_90KM_NORTH_OF_PARIS = Point(2.35, 49.63, srid=4326)  # ~90 km, within EPIDE range


class BeneficiaryProfileFactory(factory.Factory):
    france_travail_id = factory.Sequence(lambda n: f"{n:011d}")

    class Meta:
        model = BeneficiaryProfile
        exclude = ["age"]

    age = None

    @factory.lazy_attribute
    def birthdate(self):
        if self.age is not None:
            today = datetime.date.today()
            return today.replace(year=today.year - self.age)
        return None

    class Params:
        in_paris = factory.Trait(coords=_PARIS, code_insee="75056")


class StructuredSolutionCandidateFactory(factory.Factory):
    kind = StructuredSolutionKind.PLIE
    coordinates = _CLOSE_TO_PARIS

    class Meta:
        model = StructuredSolutionCandidate

    class Params:
        in_marseille = factory.Trait(coordinates=_MARSEILLE)
        within_epide_range = factory.Trait(coordinates=_90KM_NORTH_OF_PARIS)
        without_coordinates = factory.Trait(coordinates=None)


class BeneficiaryFactory(factory.django.DjangoModelFactory):
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")

    referent_email = factory.Sequence("email{}@domain.com".format)
    france_travail_id = factory.fuzzy.FuzzyText(length=11, chars=string.digits)
    organization_safir = factory.fuzzy.FuzzyText(length=5, chars=string.digits)

    class Meta:
        model = models.Beneficiary
        skip_postgeneration_save = True

    class Params:
        for_snapshot = factory.Trait(
            first_name="Alice",
            last_name="Martin",
            france_travail_id="12345678901",
            referent_email="ref@example.com",
            organization_safir="12345",
        )
