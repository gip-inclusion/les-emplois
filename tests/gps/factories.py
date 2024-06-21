import datetime

import factory.fuzzy
from django.conf import settings

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from tests.users.factories import JobSeekerFactory, PrescriberFactory


class FollowUpGroupFactory(factory.django.DjangoModelFactory):
    """Generates FollowUpGroup() objects for unit tests."""

    class Meta:
        model = FollowUpGroup
        skip_postgeneration_save = True

    class Params:
        created_in_bulk = factory.Trait(
            created_at=(
                datetime.datetime.combine(settings.GPS_GROUPS_CREATED_AT_DATE, datetime.time(), tzinfo=datetime.UTC)
            )
        )
        for_snapshot = factory.Trait(
            beneficiary__for_snapshot=True,
            created_at=datetime.datetime(2024, 6, 21, 0, 0, 0, tzinfo=datetime.UTC),
        )

    beneficiary = factory.SubFactory(JobSeekerFactory)

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
                )


class FollowUpGroupMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FollowUpGroupMembership

    class Params:
        created_in_bulk = factory.Trait(
            created_at=(
                datetime.datetime.combine(settings.GPS_GROUPS_CREATED_AT_DATE, datetime.time(), tzinfo=datetime.UTC)
            )
        )

    follow_up_group = factory.SubFactory(FollowUpGroupFactory)
    member = factory.SubFactory(PrescriberFactory)
    creator = factory.SubFactory(PrescriberFactory)
