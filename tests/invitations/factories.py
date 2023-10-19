from datetime import timedelta

import factory
from django.utils import timezone

from itou.invitations import models
from tests.companies.factories import SiaeFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from tests.users.factories import EmployerFactory, PrescriberFactory


class EmployerInvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EmployerInvitation

    email = factory.Sequence("email{}@employer.com".format)
    first_name = factory.Sequence("first_name{}".format)
    last_name = factory.Sequence("last_name{}".format)
    sender = factory.SubFactory(EmployerFactory)
    siae = factory.SubFactory(SiaeFactory, with_membership=True)


class SentEmployerInvitationFactory(EmployerInvitationFactory):
    sent = True
    sent_at = factory.LazyFunction(timezone.now)


class ExpiredEmployerInvitationFactory(EmployerInvitationFactory):
    sent = True
    sent_at = factory.LazyFunction(
        lambda: timezone.now() - timedelta(days=models.InvitationAbstract.DEFAULT_VALIDITY_DAYS)
    )


class PrescriberWithOrgSentInvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.PrescriberWithOrgInvitation

    email = factory.Faker("email", locale="fr_FR")
    first_name = factory.Faker("first_name", locale="fr_FR")
    last_name = factory.Faker("last_name", locale="fr_FR")
    sender = factory.SubFactory(PrescriberFactory)
    sent = True
    sent_at = factory.LazyFunction(timezone.now)
    organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory)
