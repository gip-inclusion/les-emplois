import datetime
import random
import string

import factory
import factory.fuzzy

from itou.asp.mocks.providers import INSEECommuneProvider, INSEECountryProvider
from itou.asp.models import AllocationDuration, EducationLevel
from itou.users import models
from itou.utils.address.departments import DEPARTMENTS
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK


DEFAULT_PASSWORD = "p4ssw0rd"

# Register ASP fakers
factory.Faker.add_provider(INSEECommuneProvider)
factory.Faker.add_provider(INSEECountryProvider)


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


class JobSeekerWithMockedAddressFactory(JobSeekerFactory):
    # birth_place = factory.Faker("asp_insee_commune")
    birth_country = factory.Faker("asp_country")
    title = random.choice(models.User.Title.values)

    @factory.post_generation
    def set_approval_user(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return
        # We did not create test fixtures for this
        address = BAN_GEOCODING_API_RESULTS_MOCK[0]
        self.address_line_1 = address.get("address_line_1")
        self.post_code = address.get("post_code")
        self.insee_code = address.get("insee_code")
        self.city = address.get("city")


class JobSeekerProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.JobSeekerProfile

    user = factory.SubFactory(JobSeekerWithAddressFactory)
    education_level = random.choice(EducationLevel.values)
    # JobSeeker are created with a Pôle emploi ID
    pole_emploi_since = AllocationDuration.MORE_THAN_24_MONTHS


class PrescriberFactory(UserFactory):
    is_prescriber = True


class SiaeStaffFactory(UserFactory):
    is_siae_staff = True
