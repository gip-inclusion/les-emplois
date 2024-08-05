import random
from datetime import date
import factory
from factory.fuzzy import FuzzyChoice

from itou.communications.models import AnnouncementCampaign, AnnouncementItem
from itou.users.enums import UserKind


class FuzzyChoiceList(FuzzyChoice):
    def fuzz(self):
        if self.choices is None:
            self.choices = list(self.choices_generator)

        # set used to ensure uniqueness
        choice_length = random.randint(0, len(self.choices))
        return list(set(random.sample(self.choices, choice_length)))


class AnnouncementCampaignFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnnouncementCampaign
        skip_postgeneration_save = True

    @factory.post_generation
    def with_item(obj, create, extracted, **kwargs):
        if create and extracted is True:
            AnnouncementItemFactory(campaign=obj)

    @factory.post_generation
    def for_snapshot(obj, create, extracted, **kwargs):
        if extracted is True:
            obj.start_date = date(2024, 1, 1)
            for user_kind in UserKind.values:
                assert (
                    AnnouncementItemFactory(campaign=obj, for_snapshot=True, user_kind_tags=[user_kind]).user_kind_tags
                    == [user_kind]
                )
            AnnouncementItemFactory(campaign=obj, for_snapshot=True, user_kind_tags=[])
            obj.save()

    start_date = factory.LazyFunction(lambda: date.today().replace(day=1))


class AnnouncementItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AnnouncementItem

    class Params:
        with_image = factory.Trait(image=factory.django.ImageField(width=1, height=1, format="JPEG"))
        for_snapshot = factory.Trait(
            title="Nouveau fonctionnalité sur notre site",
            description="C'est désormais possible de faire des nouveaux actions avec votre compte",
            user_kind_tags=[UserKind.JOB_SEEKER, UserKind.PRESCRIBER],
            link="https://emplois.inclusion.beta.gouv.fr/",
        )

    campaign = factory.SubFactory(AnnouncementCampaignFactory)
    title = factory.Faker("sentence", locale="fr_FR")
    description = factory.Faker("paragraph", locale="fr_FR")
    priority = factory.Sequence(lambda n: n + 1)
    user_kind_tags = FuzzyChoiceList(choices=UserKind.values)
    link = factory.Faker("url")
