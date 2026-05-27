import string

import factory


class BeneficiaryFactory(factory.django.DjangoModelFactory):
    email = factory.Sequence("email{}@domain.com".format)
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")

    referent_email = factory.Sequence("email{}@domain.com".format)
    france_travail_id = factory.fuzzy.FuzzyText(length=11, chars=string.digits)
    organization_safir = factory.fuzzy.FuzzyText(length=5, chars=string.digits)
