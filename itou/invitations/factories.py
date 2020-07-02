import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from itou.invitations import models
from itou.siaes.factories import SiaeWith2MembershipsFactory
from itou.users.factories import UserFactory


class InvitationFactory(factory.django.DjangoModelFactory):
    """Generate an Invitation() object for unit tests."""

    class Meta:
        model = models.SiaeStaffInvitation

    email = factory.Faker("email", locale="fr_FR")
    first_name = factory.Faker("first_name", locale="fr_FR")
    last_name = factory.Faker("last_name", locale="fr_FR")
    sender = factory.SubFactory(UserFactory)
    siae = factory.SubFactory(SiaeWith2MembershipsFactory)


class SentInvitationFactory(InvitationFactory):
    sent = True
    sent_at = factory.LazyFunction(timezone.now)


class ExpiredInvitationFactory(SentInvitationFactory):
    sent_at = factory.LazyAttribute(
        lambda self: timezone.now()
        - relativedelta(days=models.InvitationAbstract.EXPIRATION_DAYS)
        - relativedelta(days=1)
    )


class SiaeSentInvitationFactory(SentInvitationFactory):
    """
    Same as InvitationFactory but lets us test
    Siae invitations specific use cases.
    """

    class Meta:
        model = models.SiaeStaffInvitation

    siae = factory.SubFactory(SiaeWith2MembershipsFactory)
