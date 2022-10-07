import datetime
import random
import string

import factory
import factory.fuzzy
from allauth.account import models as allauth_models

from itou.asp.factories import CommuneFactory, CountryFactory, CountryFranceFactory
from itou.asp.models import AllocationDuration, EducationLevel, LaneType
from itou.common_apps.address.departments import DEPARTMENTS
from itou.users import models
from itou.users.enums import Title
from itou.utils.mocks.address_format import get_random_geocoding_api_result
from itou.utils.validators import validate_nir


DEFAULT_PASSWORD = "P4ssw0rd!***"


def _verify_emails_for_user(self, create, extracted, **kwargs):
    if not create:
        # Simple build, do nothing.
        return

    emails = extracted or [self.email]
    for email in emails:
        email_address, _ = allauth_models.EmailAddress.objects.get_or_create(user=self, email=email)
        email_address.verified = True
        email_address.save()
        self.emailaddress_set.add(email_address)


class UserFactory(factory.django.DjangoModelFactory):
    """Generates User() objects for unit tests."""

    class Meta:
        model = models.User

    class Params:
        with_verified_email = factory.Trait(
            is_active=True,
            emails=factory.PostGeneration(_verify_emails_for_user),
        )

    username = factory.Sequence("user_name{0}".format)
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.Sequence("email{0}@domain.com".format)
    password = factory.PostGenerationMethodCall("set_password", DEFAULT_PASSWORD)
    birthdate = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(2000, 1, 1))
    phone = factory.Faker("phone_number", locale="fr_FR")


class JobSeekerFactory(UserFactory):
    title = random.choice(Title.values)
    is_job_seeker = True
    pole_emploi_id = factory.fuzzy.FuzzyText(length=8, chars=string.digits)

    class Params:
        # Birth place and birth country removed from default:
        # only created when creating a new job seeker profile (employee records)
        with_birth_place = factory.Trait(birth_place=factory.SubFactory(CommuneFactory))
        with_birth_country = factory.Trait(birth_country=factory.SubFactory(CountryFactory))
        born_in_france = factory.Trait(
            with_birth_place=True,
            birth_country=factory.SubFactory(CountryFranceFactory),
        )

    @factory.lazy_attribute
    def nir(self):
        gender = random.choice([1, 2])
        if self.birthdate:
            year = self.birthdate.strftime("%y")
            month = self.birthdate.strftime("%m")
        else:
            year = "87"
            month = "06"
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
    # Needs ASP test fixtures installed

    @factory.post_generation
    def set_approval_user(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return

        # Format user address randomly from an API mock: these are all valid addresses
        address = get_random_geocoding_api_result()

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
