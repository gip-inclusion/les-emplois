import datetime

import factory.fuzzy
from django.conf import settings
from django.utils import timezone

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership, FranceTravailContact
from tests.users.factories import JobSeekerFactory, JobSeekerProfileFactory, PrescriberFactory


class FollowUpGroupFactory(factory.django.DjangoModelFactory):
    """Generates FollowUpGroup() objects for unit tests."""

    class Meta:
        model = FollowUpGroup
        skip_postgeneration_save = True

    class Params:
        for_snapshot = factory.Trait(
            beneficiary__for_snapshot=True,
            created_at=datetime.datetime(2024, 6, 21, 0, 0, 0, tzinfo=datetime.UTC),
        )

    beneficiary = factory.SubFactory(JobSeekerFactory)
    created_at = factory.LazyAttribute(
        lambda o: datetime.datetime.combine(
            settings.GPS_GROUPS_CREATED_AT_DATE, datetime.time(12, 0, 0), tzinfo=datetime.UTC
        )
        if o.created_in_bulk
        else timezone.now()
    )
    created_in_bulk = False

    @factory.post_generation
    def memberships(self, create, extracted, **kwargs):
        if not create:
            # Simple build, do nothing.
            return

        if extracted:
            # Create x memberships
            for i in range(extracted):
                FollowUpGroupMembershipFactory(
                    member=kwargs["member"] if i == 0 and "member" in kwargs else PrescriberFactory(),
                    creator=PrescriberFactory(),
                    follow_up_group=self,
                    is_referent=True if i == 0 else False,
                    created_at=self.created_at,
                    created_in_bulk=self.created_in_bulk,
                )


class FollowUpGroupMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FollowUpGroupMembership

    created_at = factory.LazyAttribute(
        lambda o: datetime.datetime.combine(
            settings.GPS_GROUPS_CREATED_AT_DATE, datetime.time(12, 0, 0), tzinfo=datetime.UTC
        )
        if o.created_in_bulk
        else timezone.now()
    )

    created_in_bulk = False
    follow_up_group = factory.SubFactory(FollowUpGroupFactory)
    member = factory.SubFactory(PrescriberFactory)
    creator = factory.SubFactory(PrescriberFactory)


class FranceTravailContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FranceTravailContact

    jobseeker_profile = factory.SubFactory(JobSeekerProfileFactory)
    name = factory.Faker("name", locale="fr_FR")
    email = factory.Faker("email", locale="fr_FR")
