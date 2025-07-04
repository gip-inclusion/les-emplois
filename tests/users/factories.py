import datetime
import functools
import random
import string

import factory.fuzzy
from allauth.account import models as allauth_models
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from django.utils.text import slugify

from itou.asp.models import AllocationDuration, Commune, Country, EducationLevel, EITIContributions, LaneType
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENTS
from itou.communications.models import NotificationRecord, NotificationSettings
from itou.users import models
from itou.users.enums import IdentityProvider, Title, UserKind
from itou.utils.mocks.address_format import (
    BAN_GEOCODING_API_RESULTS_MOCK,
    get_random_geocoding_api_result,
)
from itou.utils.validators import validate_nir
from tests.cities.factories import create_city_in_zrr, create_city_partially_in_zrr
from tests.geo.factories import QPVFactory, ZRRFactory


DEFAULT_PASSWORD = "P4ssw0rd!*****"


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
        for_snapshot = factory.Trait(
            first_name="John",
            last_name="Doe",
            email="john.doe@test.local",
            phone="0606060606",
            public_id="c0fee70e-cf34-4d37-919d-a1ae3e3bf7e5",
        )

    username = factory.Sequence("user_name{}".format)
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    email = factory.Sequence("email{}@domain.com".format)
    password = factory.LazyFunction(default_password)
    phone = factory.Faker("phone_number", locale="fr_FR")

    @factory.post_generation
    def with_disabled_notifications(obj, create, extracted, **kwargs):
        if create and extracted is True:
            settings, _ = NotificationSettings.get_or_create(obj)
            settings.disabled_notifications.set(NotificationRecord.objects.all())

    @factory.post_generation
    def joined_days_ago(obj, create, extracted, **kwargs):
        if extracted:
            obj.date_joined = timezone.now() - datetime.timedelta(days=extracted)
            if create:
                obj.save(update_fields=["date_joined"])

    @factory.post_generation
    def notified_days_ago(obj, create, extracted, **kwargs):
        if extracted:
            obj.upcoming_deletion_notified_at = timezone.now() - datetime.timedelta(days=extracted)
            if create:
                obj.save(update_fields=["upcoming_deletion_notified_at"])

    @factory.post_generation
    def last_login_days_ago(obj, create, extracted, **kwargs):
        if extracted:
            obj.last_login = timezone.now() - datetime.timedelta(days=extracted)
            if create:
                obj.save(update_fields=["last_login"])


class ItouStaffFactory(UserFactory):
    kind = UserKind.ITOU_STAFF


class PrescriberFactory(UserFactory):
    kind = UserKind.PRESCRIBER
    identity_provider = IdentityProvider.PRO_CONNECT

    class Params:
        for_snapshot = factory.Trait(
            first_name="Pierre",
            last_name="Dupont",
            email="pierre.dupont@test.local",
            public_id="03580247-b036-4578-bf9d-f92c9c2f68cd",
            phone="0612345678",
        )

    @factory.post_generation
    def membership(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted or kwargs:
            from tests.prescribers.factories import PrescriberMembershipFactory

            PrescriberMembershipFactory(user=self, **kwargs)

    @factory.post_generation
    def with_disabled_notifications(obj, create, extracted, **kwargs):
        from tests.prescribers.factories import PrescriberMembershipFactory

        if create and extracted is True:
            organization = obj.prescriberorganization_set.first() or PrescriberMembershipFactory(user=obj).organization
            settings, _ = NotificationSettings.get_or_create(obj, organization)
            settings.disabled_notifications.set(NotificationRecord.objects.all())


class EmployerFactory(UserFactory):
    kind = UserKind.EMPLOYER
    identity_provider = IdentityProvider.PRO_CONNECT

    @factory.post_generation
    def with_company(self, created, extracted, **kwargs):
        from tests.companies.factories import CompanyMembershipFactory

        if created and extracted is True:
            CompanyMembershipFactory(user=self, **kwargs)

    @factory.post_generation
    def with_disabled_notifications(obj, create, extracted, **kwargs):
        from tests.companies.factories import CompanyMembershipFactory

        if create and extracted is True:
            company = obj.company_set.first() or CompanyMembershipFactory(user=obj).company
            settings, _ = NotificationSettings.get_or_create(obj, company)
            settings.disabled_notifications.set(NotificationRecord.objects.all())


class LaborInspectorFactory(UserFactory):
    kind = UserKind.LABOR_INSPECTOR

    @factory.post_generation
    def membership(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted or kwargs:
            from tests.institutions.factories import InstitutionMembershipFactory

            InstitutionMembershipFactory(user=self, **kwargs)


class JobSeekerFactory(UserFactory):
    title = random.choice(Title.values)
    kind = UserKind.JOB_SEEKER
    jobseeker_profile = factory.RelatedFactory("tests.users.factories.JobSeekerProfileFactory", "user")

    class Params:
        certifiable = factory.Trait(
            born_in_france=True,
        )
        born_in_france = factory.Trait(
            jobseeker_profile__birth_place=factory.LazyAttribute(
                lambda instance: Commune.objects.order_by("?")
                .filter(
                    start_date__lte=instance.birthdate,
                    end_date__gte=instance.birthdate,
                )
                .first(),
            ),
            jobseeker_profile__birth_country=factory.LazyAttribute(lambda _: Country.objects.get(name="FRANCE")),
        )
        born_outside_france = factory.Trait(
            jobseeker_profile__birth_country=factory.LazyAttribute(
                lambda _: Country.objects.order_by("?").exclude(group=Country.Group.FRANCE).first()
            ),
        )
        with_pole_emploi_id = factory.Trait(
            jobseeker_profile__pole_emploi_id=factory.fuzzy.FuzzyText(length=8, chars=string.digits),
            jobseeker_profile__pole_emploi_since=AllocationDuration.MORE_THAN_24_MONTHS,
        )

        with_ban_geoloc_address = factory.Trait(
            address_line_1="37 B Rue du Général De Gaulle",
            post_code="67118",
            city="Geispolsheim",
            coords="POINT (7.644817 48.515883)",
            geocoding_score=0.8745736363636364,
        )

        with_address = factory.Trait(
            address_line_1=factory.Faker("street_address", locale="fr_FR"),
            department=factory.fuzzy.FuzzyChoice(DEPARTMENTS.keys()),
            post_code=factory.Faker("postalcode"),
            city=factory.Faker("city", locale="fr_FR"),
            with_geoloc=True,
        )
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
        with_geoloc = factory.Trait(
            coords="POINT(0 0)",
            geocoding_score=0.5,
        )
        without_geoloc = factory.Trait(
            coords=None,
            geocoding_score=None,
        )

        for_snapshot = factory.Trait(
            public_id="7614fc4b-aef9-4694-ab17-12324300180a",
            title="MME",
            first_name="Jane",
            last_name="Doe",
            email="jane.doe@test.local",
            phone="0612345678",
            address_line_1="12 rue Georges Bizet",
            post_code="35000",
            city="Rennes",
            department="35",
            jobseeker_profile__for_snapshot=True,
        )

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        # Deactivate automatic creation of JobSeekerProfile in User.save
        # since the RelatedFactory will take care of it
        kwargs["_auto_create_job_seeker_profile"] = False

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

    @factory.post_generation
    def with_ban_api_mocked_address(self, create, extracted, **kwargs):
        # Needs ASP test fixtures installed
        if not extracted:
            # Do nothing
            return

        address = (
            next(address for address in BAN_GEOCODING_API_RESULTS_MOCK if address.get("ban_api_resolved_address"))
            if extracted is True
            else extracted
        )

        city, _ = City.objects.get_or_create(
            name=address["city"],
            defaults={
                "slug": slugify(address["city"]),
                "department": address["post_code"][:2],
                "coords": f"POINT({address['longitude']} {address['latitude']})",
                "post_codes": [address["post_code"]],
                "code_insee": address["insee_code"],
            },
        )

        self.address_line_1 = address.get("address_line_1")
        self.post_code = city.post_codes[0]
        self.insee_code = city.code_insee
        self.geocoding_score = address.get("score")
        self.coords = city.coords
        # String...
        self.city = city.name
        # Foreign key
        self.insee_city = city

        if create:
            self.save()

    @factory.post_generation
    def with_mocked_address(self, create, extracted, **kwargs):
        # Needs ASP test fixtures installed
        if not extracted:
            # Do nothing
            return

        address = get_random_geocoding_api_result() if extracted is True else extracted

        self.address_line_1 = address.get("address_line_1")
        self.post_code = address.get("post_code")
        self.insee_code = address.get("insee_code")
        self.city = address.get("city")
        self.geocoding_score = address.get("score")
        self.coords = f"POINT({address.get('longitude')} {address.get('latitude')})"
        if create:
            self.save()


class JobSeekerProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.JobSeekerProfile
        skip_postgeneration_save = True

    class Params:
        with_education_level = factory.Trait(education_level=factory.fuzzy.FuzzyChoice(EducationLevel.values))
        with_hexa_address = factory.Trait(
            hexa_lane_type=factory.fuzzy.FuzzyChoice(LaneType.values),
            hexa_lane_name=factory.Faker("street_address", locale="fr_FR"),
            hexa_post_code=factory.Faker("postalcode"),
            hexa_commune=factory.LazyAttribute(lambda _: Commune.objects.order_by("?").first()),
        )
        with_required_eiti_fields = factory.Trait(
            actor_met_for_business_creation=factory.Faker("word", locale="en_GB"),  # To match validator
            mean_monthly_income_before_process=factory.Faker("pydecimal", left_digits=5, right_digits=2),
            eiti_contributions=factory.fuzzy.FuzzyChoice(EITIContributions.values),
        )
        for_snapshot = factory.Trait(
            birthdate=datetime.date(1990, 1, 1),
            nir="290010101010125",
            asp_uid="a08dbdb523633cfc59dfdb297307a1",
            education_level=EducationLevel.BAC_LEVEL,
            hexa_lane_number=12,
            hexa_lane_type=LaneType.RUE,
            hexa_lane_name="Georges Bizet",
            hexa_post_code="35000",
        )

    user = factory.SubFactory(JobSeekerFactory, jobseeker_profile=None)
    # Limit the upper value to 1999-12-31 so we don't exclude 36995 (of 76777) `Commune()` with a "1999-12-31" end date
    birthdate = factory.fuzzy.FuzzyDate(datetime.date(1968, 1, 1), datetime.date(1999, 12, 31))

    education_level = factory.fuzzy.FuzzyChoice(EducationLevel.values + [""])

    @factory.lazy_attribute
    def nir(self):
        gender = "1" if self.user.title == Title.M else "2"
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


def random_user_kind_factory(**kwargs):
    return random.choice(
        [
            ItouStaffFactory,
            JobSeekerFactory,
            PrescriberFactory,
            functools.partial(EmployerFactory, with_company=True),
            functools.partial(LaborInspectorFactory, membership=True),
        ]
    )(**kwargs)
