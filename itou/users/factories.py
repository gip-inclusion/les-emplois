import factory

from itou.users import models


DEFAULT_PASSWORD = "p4ssw0rd"


class UserFactory(factory.django.DjangoModelFactory):
    """Generates User() objects for unit tests."""

    class Meta:
        model = models.User

    username = factory.Faker('user_name')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    email = factory.Faker('email')
    password = factory.PostGenerationMethodCall('set_password', DEFAULT_PASSWORD)


class JobSeekerFactory(UserFactory):
    is_job_seeker = True


class PrescriberFactory(UserFactory):
    is_prescriber = True


class SiaeStaffFactory(UserFactory):
    is_siae_staff = True
