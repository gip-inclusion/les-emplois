import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.invitations import models
from itou.users.factories import UserFactory


class InvitationFactory(factory.django.DjangoModelFactory):
    """Generate an Invitation() object for unit tests."""

    class Meta:
        model = models.Invitation

    email = factory.Faker("email", locale="fr_FR")
    first_name = factory.Faker("first_name", locale="fr_FR")
    last_name = factory.Faker("last_name", locale="fr_FR")
    sender = factory.SubFactory(UserFactory)


class SentInvitationFactory(InvitationFactory):
    sent = True
    sent_at = factory.LazyFunction(timezone.now)


class ExpiredInvitationFactory(SentInvitationFactory):
    sent_at = factory.LazyAttribute(
        lambda self: timezone.now() - relativedelta(days=models.Invitation.EXPIRATION_DAYS) - relativedelta(days=1)
    )
