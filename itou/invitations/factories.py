from datetime import timedelta

import factory
from django.utils import timezone

from itou.invitations import models
from itou.prescribers.factories import PrescriberOrganizationWithMembershipFactory
from itou.siaes.factories import SiaeFactory
from itou.users.factories import PrescriberFactory, SiaeStaffFactory


class SiaeStaffInvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.SiaeStaffInvitation

    email = factory.Sequence("email{}@siaestaff.com".format)
    first_name = factory.Sequence("first_name{}".format)
    last_name = factory.Sequence("last_name{}".format)
    sender = factory.SubFactory(SiaeStaffFactory)
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
    sender = factory.SubFactory(PrescriberFactory)
    sent = True
    sent_at = factory.LazyFunction(timezone.now)
    organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory)
