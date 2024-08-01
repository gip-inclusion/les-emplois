from datetime import date

import factory

from itou.communications.models import AnnouncementCampaign, AnnouncementItem


class AnnouncementCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnnouncementCampaign
        skip_postgeneration_save = True

    start_date = factory.LazyFunction(lambda: date.today().replace(day=1))

    @factory.post_generation
    def with_item(obj, create, extracted, **kwargs):
        if create and extracted is True:
            AnnouncementItemFactory(campaign=obj)


class AnnouncementItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnnouncementItem

    campaign = factory.SubFactory(AnnouncementCampaignFactory)
    title = factory.Faker("sentence", locale="fr_FR")
    description = factory.Faker("paragraph", locale="fr_FR")
    priority = factory.Sequence(lambda n: n + 1)
