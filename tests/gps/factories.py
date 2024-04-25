import factory.fuzzy

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from tests.users.factories import JobSeekerFactory, PrescriberFactory


class FollowUpGroupFactory(factory.django.DjangoModelFactory):
    """Generates FollowUpGroup() objects for unit tests."""

    class Meta:
        model = FollowUpGroup
        skip_postgeneration_save = True

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

    follow_up_group = factory.SubFactory(FollowUpGroupFactory)
    member = factory.SubFactory(PrescriberFactory)
    creator = factory.SubFactory(PrescriberFactory)
