import datetime
import string

import factory
import factory.fuzzy

from itou.users import models
from itou.utils.address.departments import DEPARTMENTS


DEFAULT_PASSWORD = "p4ssw0rd"


class UserFactory(factory.django.DjangoModelFactory):
    """Generates User() objects for unit tests."""

    class Meta:
        model = models.User

    username = factory.Sequence("user_name{0}".format)
    first_name = factory.Sequence("first_name{0}".format)
    last_name = factory.Sequence("last_name{0}".format)
    email = factory.Sequence("email{0}@domain.com".format)
    password = factory.PostGenerationMethodCall("set_password", DEFAULT_PASSWORD)
    birthdate = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(2000, 1, 1))
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)


class JobSeekerFactory(UserFactory):
    is_job_seeker = True
    pole_emploi_id = factory.fuzzy.FuzzyText(length=8, chars=string.digits)


class JobSeekerWithAddressFactory(JobSeekerFactory):
    address_line_1 = factory.Faker("street_address", locale="fr_FR")
    department = factory.fuzzy.FuzzyChoice(DEPARTMENTS.keys())
    post_code = factory.Faker("postalcode")
    city = factory.Faker("city", locale="fr_FR")


class PrescriberFactory(UserFactory):
    is_prescriber = True


class SiaeStaffFactory(UserFactory):
    is_siae_staff = True
