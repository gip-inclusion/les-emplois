from datetime import timedelta

import factory
from django.utils import timezone

from itou.invitations import models
from tests.companies.factories import CompanyFactory
from tests.institutions.factories import InstitutionWithMembershipFactory
from tests.prescribers.factories import PrescriberOrganizationWithMembershipFactory


class EmployerInvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.EmployerInvitation

    class Params:
        expired = factory.Trait(
            sent_at=factory.LazyFunction(
                lambda: timezone.now() - timedelta(days=models.InvitationAbstract.DEFAULT_VALIDITY_DAYS)
            )
        )

    email = factory.Sequence("email{}@employer.com".format)
    first_name = factory.Sequence("first_name{}".format)
    last_name = factory.Sequence("last_name{}".format)
    sent = True
    sent_at = factory.LazyFunction(timezone.now)
    company = factory.SubFactory(CompanyFactory, with_membership=True)
    sender = factory.LazyAttribute(lambda o: o.company.members.first())


class PrescriberWithOrgSentInvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.PrescriberWithOrgInvitation

    class Params:
        expired = factory.Trait(
            sent_at=factory.LazyFunction(
                lambda: timezone.now() - timedelta(days=models.InvitationAbstract.DEFAULT_VALIDITY_DAYS)
            )
        )

    email = factory.Faker("email", locale="fr_FR")
    first_name = factory.Faker("first_name", locale="fr_FR")
    last_name = factory.Faker("last_name", locale="fr_FR")
    sent = True
    sent_at = factory.LazyFunction(timezone.now)
    organization = factory.SubFactory(PrescriberOrganizationWithMembershipFactory)
    sender = factory.LazyAttribute(lambda o: o.organization.members.first())


class LaborInspectorInvitationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.LaborInspectorInvitation

    class Params:
        expired = factory.Trait(
            sent_at=factory.LazyFunction(
                lambda: timezone.now() - timedelta(days=models.InvitationAbstract.DEFAULT_VALIDITY_DAYS)
            )
        )

    email = factory.Sequence("email{}@employer.com".format)
    first_name = factory.Sequence("first_name{}".format)
    last_name = factory.Sequence("last_name{}".format)
    sent = True
    sent_at = factory.LazyFunction(timezone.now)
    institution = factory.SubFactory(InstitutionWithMembershipFactory)
    sender = factory.LazyAttribute(lambda o: o.institution.members.first())
