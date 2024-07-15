from datetime import date

import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from faker import Faker

from itou.communications.models import AnnouncementCampaign, AnnouncementItem
from itou.users.enums import UserKind


faker = Faker()


class AnnouncementCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnnouncementCampaign
        skip_postgeneration_save = True

    class Params:
        for_snapshot = factory.Trait(start_date=date(2024, 1, 1))

    @factory.post_generation
    def with_item(obj, create, extracted, **kwargs):
        if create and extracted:
            AnnouncementItemFactory(campaign=obj)

    @factory.post_generation
    def with_items_for_every_user_kind(obj, create, extracted, **kwargs):
        if create and extracted:
            for i, user_kind in enumerate(UserKind.values):
                AnnouncementItemFactory(campaign=obj, for_snapshot=True, user_kind_tags=[user_kind], priority=i + 1)
            AnnouncementItemFactory(campaign=obj, for_snapshot=True, user_kind_tags=[], priority=0)

    start_date = factory.Sequence(lambda n: (timezone.localdate() - relativedelta(months=n)).replace(day=1))


class AnnouncementItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnnouncementItem

    class Params:
        with_image = factory.Trait(
            image=factory.django.ImageField(width=1, height=1, format="JPEG"),
            image_alt_text=factory.Faker("sentence", locale="fr_FR"),
        )
        for_snapshot = factory.Trait(
            title="Nouvelle fonctionnalité sur notre site",
            description="Il est désormais possible de faire de nouvelles actions avec votre compte",
            user_kind_tags=[UserKind.JOB_SEEKER, UserKind.PRESCRIBER],
            link="https://example.com/",
            priority=999,
        )

    campaign = factory.SubFactory(AnnouncementCampaignFactory)
    title = factory.Faker("sentence", locale="fr_FR")
    description = factory.Faker("paragraph", locale="fr_FR")
    priority = factory.Sequence(lambda n: n + 1)
    user_kind_tags = faker.random_elements(UserKind.values, unique=True)
    link = factory.Faker("url")
