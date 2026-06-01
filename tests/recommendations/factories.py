import string

import factory
import factory.fuzzy

from itou.recommendations import models


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
