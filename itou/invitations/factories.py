from datetime import timedelta

import factory
from django.utils import timezone

from itou.invitations import models
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeFactory
from itou.users.factories import UserFactory


class SiaeStaffInvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.SiaeStaffInvitation

    email = factory.Sequence("email{0}@siaestaff.com".format)
    first_name = factory.Sequence("first_name{0}".format)
    last_name = factory.Sequence("last_name{0}".format)
    sender = factory.SubFactory(UserFactory)
    siae = factory.SubFactory(SiaeFactory, with_membership=True)


class SentSiaeStaffInvitationFactory(SiaeStaffInvitationFactory):
    sent = True
    sent_at = factory.LazyFunction(timezone.now)


class ExpiredSiaeStaffInvitationFactory(SiaeStaffInvitationFactory):
    sent = True
    sent_at = factory.LazyFunction(lambda: timezone.now() - timedelta(days=models.InvitationAbstract.EXPIRATION_DAYS))


class PrescriberWithOrgSentInvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.PrescriberWithOrgInvitation

    email = factory.Faker("email", locale="fr_FR")
    first_name = factory.Faker("first_name", locale="fr_FR")
    last_name = factory.Faker("last_name", locale="fr_FR")
    sender = factory.SubFactory(UserFactory)
    sent = True
    sent_at = factory.LazyFunction(timezone.now)
    organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory)
