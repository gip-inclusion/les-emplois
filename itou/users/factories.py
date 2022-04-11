import datetime
import random
import string

import factory
import factory.fuzzy

from itou.asp.factories import CommuneFactory, CountryFranceFactory
from itou.asp.mocks.providers import INSEECommuneProvider, INSEECountryProvider
from itou.asp.models import AllocationDuration, EducationLevel, LaneType
from itou.common_apps.address.departments import DEPARTMENTS
from itou.users import models
from itou.users.enums import Title
from itou.utils.mocks.address_format import BAN_GEOCODING_API_RESULTS_MOCK
from itou.utils.validators import validate_nir


DEFAULT_PASSWORD = "P4ssw0rd!*"

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
    title = random.choice(Title.values)
    is_job_seeker = True
    pole_emploi_id = factory.fuzzy.FuzzyText(length=8, chars=string.digits)
    birth_country = factory.SubFactory(CountryFranceFactory)
    birth_place = factory.SubFactory(CommuneFactory)

    @factory.lazy_attribute
    def nir(self):
        gender = random.choice([1, 2])
        year = self.birthdate.strftime("%y")
        month = self.birthdate.strftime("%m")
        department = str(random.randint(1, 99)).zfill(2)
        random_1 = str(random.randint(0, 399)).zfill(3)
        random_2 = str(random.randint(0, 399)).zfill(3)
        incomplete_nir = f"{gender}{year}{month}{department}{random_1}{random_2}"
        assert len(incomplete_nir) == 13
        control_key = str(97 - int(incomplete_nir) % 97).zfill(2)
        nir = f"{incomplete_nir}{control_key}"
        validate_nir(nir)
        return nir


class JobSeekerWithAddressFactory(JobSeekerFactory):
    address_line_1 = factory.Faker("street_address", locale="fr_FR")
    department = factory.fuzzy.FuzzyChoice(DEPARTMENTS.keys())
    post_code = factory.Faker("postalcode")
    city = factory.Faker("city", locale="fr_FR")


class JobSeekerWithMockedAddressFactory(JobSeekerFactory):
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


class JobSeekerProfileWithHexaAddressFactory(JobSeekerProfileFactory):
    # Adding a minimum profile with all mandatory fields
    # will avoid many mocks and convolutions during testing.
    hexa_lane_type = random.choice(LaneType.values)
    hexa_lane_name = factory.Faker("street_address", locale="fr_FR")
    hexa_commune = factory.SubFactory(CommuneFactory)
    hexa_post_code = factory.Faker("postalcode")


class PrescriberFactory(UserFactory):
    is_prescriber = True


class SiaeStaffFactory(UserFactory):
    is_siae_staff = True


class LaborInspectorFactory(UserFactory):
    is_labor_inspector = True
