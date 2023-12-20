import datetime
import functools
import random
import string

import factory.fuzzy
from allauth.account import models as allauth_models
from django.contrib.auth.hashers import make_password

from itou.asp.models import AllocationDuration, EducationLevel, LaneType
from itou.common_apps.address.departments import DEPARTMENTS
from itou.users import models
from itou.users.enums import IdentityProvider, Title, UserKind
from itou.utils.mocks.address_format import get_random_geocoding_api_result
from itou.utils.validators import validate_nir
from tests.asp.factories import CommuneFactory, CountryFactory, CountryFranceFactory
from tests.cities.factories import create_city_in_zrr, create_city_partially_in_zrr
from tests.geo.factories import QPVFactory, ZRRFactory


DEFAULT_PASSWORD = "P4ssw0rd!***"


@functools.cache
def default_password():
    return make_password(DEFAULT_PASSWORD)


def _verify_emails_for_user(self, create, extracted, **kwargs):
    if not create:
        # Simple build, do nothing.
        return

    emails = extracted or [self.email]
    for email in emails:
        email_address, _ = allauth_models.EmailAddress.objects.get_or_create(user=self, email=email)
        email_address.verified = True
        email_address.primary = True
        email_address.save()
        self.emailaddress_set.add(email_address)


class UserFactory(factory.django.DjangoModelFactory):
    """Generates User() objects for unit tests."""

    class Meta:
        model = models.User
        skip_postgeneration_save = True

    class Params:
        with_verified_email = factory.Trait(
            is_active=True,
            emails=factory.PostGeneration(_verify_emails_for_user),
        )
        for_snapshot = factory.Trait(first_name="John", last_name="Doe", birthdate=datetime.date(2000, 1, 1))

    username = factory.Sequence("user_name{}".format)
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.Sequence("email{}@domain.com".format)
    password = factory.LazyFunction(default_password)
    birthdate = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(2000, 1, 1))
    phone = factory.Faker("phone_number", locale="fr_FR")


class ItouStaffFactory(UserFactory):
    kind = UserKind.ITOU_STAFF


class PrescriberFactory(UserFactory):
    kind = UserKind.PRESCRIBER
    identity_provider = IdentityProvider.INCLUSION_CONNECT

    @factory.post_generation
    def membership(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted or kwargs:
            from tests.prescribers.factories import PrescriberMembershipFactory

            PrescriberMembershipFactory(user=self, **kwargs)


class EmployerFactory(UserFactory):
    kind = UserKind.EMPLOYER
    identity_provider = IdentityProvider.INCLUSION_CONNECT

    @factory.post_generation
    def with_company(self, created, extracted, **kwargs):
        from tests.companies.factories import CompanyMembershipFactory

        if created and extracted is True:
            CompanyMembershipFactory(user=self)


class LaborInspectorFactory(UserFactory):
    kind = UserKind.LABOR_INSPECTOR

    @factory.post_generation
    def membership(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted or kwargs:
            from tests.institutions.factories import InstitutionMembershipFactory

            InstitutionMembershipFactory(user=self, **kwargs)


# `JobSeeker` and `JobSeekerProfile` factories are mainly used for employee record testing

# In order to use these factories, you must load these fixtures:
# - `test_asp_INSEE_communes_factory.json`
# - `test_asp_INSEE_countries_factory.json`
# in your Django unit tests (set `fixtures` field).


class JobSeekerFactory(UserFactory):
    title = random.choice(Title.values)
    kind = UserKind.JOB_SEEKER
    jobseeker_profile = factory.RelatedFactory("tests.users.factories.JobSeekerProfileFactory", "user")

    class Params:
        # Reminder : ASP models are "read-only", they must not be saved.
        # These traits must not be used with a `CREATE` strategy,
        # or they will try to create new Country or Commune objects in DB.
        # Use `BUILD` strategy or `build()` method when creating these traits.
        # They are currently only used to test employee records, which is
        # the only part relying on ASP reference files / models.
        with_birth_place = factory.Trait(jobseeker_profile__birth_place=factory.SubFactory(CommuneFactory))
        with_birth_country = factory.Trait(jobseeker_profile__birth_country=factory.SubFactory(CountryFactory))
        born_in_france = factory.Trait(
            with_birth_place=True,
            jobseeker_profile__birth_country=factory.SubFactory(CountryFranceFactory),
        )
        with_pole_emploi_id = factory.Trait(
            pole_emploi_id=factory.fuzzy.FuzzyText(length=8, chars=string.digits),
            jobseeker_profile__pole_emploi_since=AllocationDuration.MORE_THAN_24_MONTHS,
        )
        with_hexa_address = factory.Trait(
            jobseeker_profile=factory.RelatedFactory(
                "tests.users.factories.JobSeekerProfileWithHexaAddressFactory", "user"
            )
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

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        # Deactivate automatic creation of JobSeekerProfile in User.save
        # since the RelatedFactory will take care of it
        kwargs["_auto_create_job_seeker_profile"] = False
        return kwargs


class JobSeekerWithAddressFactory(JobSeekerFactory):
    class Params:
        with_address_in_qpv = factory.Trait(
            address_line_1="Rue du turfu",
            post_code="93300",
            city="Aubervilliers",
            coords="POINT (2.387311 48.917735)",
            geocoding_score=0.99,
        )
        with_city_in_zrr = factory.Trait(
            address_line_1="Rue paumée",
            post_code="12260",
            city="Balaguier d'Olt",
        )
        with_city_partially_in_zrr = factory.Trait(
            address_line_1="Rue exotique",
            post_code="97429",
            city="Petite-Île",
        )
        without_geoloc = factory.Trait(
            coords=None,
            geocoding_score=None,
        )
        for_snapshot = factory.Trait(
            public_id="7614fc4b-aef9-4694-ab17-12324300180a",
            title="MME",
            first_name="Sacha",
            last_name="Dupont",
            birthdate="1990-05-01",
            nir="290010101010125",
            address_line_1="Rue du clos de la Grange",
            post_code="91234",
            city="Choufleury",
        )

    address_line_1 = factory.Faker("street_address", locale="fr_FR")
    department = factory.fuzzy.FuzzyChoice(DEPARTMENTS.keys())
    post_code = factory.Faker("postalcode")
    city = factory.Faker("city", locale="fr_FR")

    coords = "POINT(0 0)"
    geocoding_score = 0.5

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        kwargs = super()._adjust_kwargs(**kwargs)
        # Using ZRR or QPV means that we must have some factories / data ready beforehand
        # Did not find a better way to do Traits additional setup...
        if kwargs.get("with_address_in_qpv"):
            QPVFactory(code="QP093028")  # Aubervilliers : in QPV

        if kwargs.get("with_city_in_zrr"):
            ZRRFactory(insee_code="12018")
            create_city_in_zrr()

        if kwargs.get("with_city_partially_in_zrr"):
            ZRRFactory(insee_code="97405")
            create_city_partially_in_zrr()

        return kwargs


class JobSeekerWithMockedAddressFactory(JobSeekerFactory):
    # Needs ASP test fixtures installed

    born_in_france = True

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
        self.save()


class JobSeekerProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.JobSeekerProfile

    user = factory.SubFactory(JobSeekerFactory)


class JobSeekerProfileWithHexaAddressFactory(JobSeekerProfileFactory):
    education_level = random.choice(EducationLevel.values)
    # Adding a minimum profile with all mandatory fields
    # will avoid many mocks and convolutions during testing.
    hexa_lane_type = random.choice(LaneType.values)
    hexa_lane_name = factory.Faker("street_address", locale="fr_FR")
    hexa_post_code = factory.Faker("postalcode")
    hexa_commune = factory.SubFactory(CommuneFactory)
