import random
from urllib.parse import urlencode

import factory
import factory.fuzzy
from django.utils import timezone

from itou.cities.models import City
from itou.search import models
from tests.users.factories import PrescriberFactory


def generate_query_params():
    query_dict = {"city": City.objects.order_by("?").first().slug, "distance": random.choice(["5", "25", "50"])}

    if random.randint(0, 1):
        query_dict |= {
            "departments": random.choice([["38"], ["38", "39", "69"], ["38", "39", "69", "71", "73", "74"]])
        }

    if random.randint(0, 1):
        query_dict |= {"kinds": random.choice([["EI"], ["EA", "ETTI"], ["EI", "EA", "ETTI", "GEIQ", "OPCS"]])}
    if random.randint(0, 1):
        query_dict |= {
            "contract_types": random.choice(
                [
                    ["PERMANENT"],
                    ["PERMANENT", "FIXED_TERM_TREMPLIN"],
                    ["PERMANENT", "FIXED_TERM_TREMPLIN", "BUSINESS_CREATION", "OTHER"],
                ]
            )
        }
    if random.randint(0, 1):
        query_dict |= {"domains": random.choice([["A"], ["A", "B"], ["A", "B", "H", "L"]])}

    return urlencode(query_dict)


class SavedSearchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.SavedSearch
        skip_postgeneration_save = True

    class Params:
        for_snapshot = factory.Trait(
            user__for_snapshot=True,
            name="Grand Lyon",
            query_params="city=lyon-69&distance=50&kinds=ACI&kinds=EI&kinds=OPCS&departments=69&district_69=69001&district_69=69003",
        )
        with_districts = factory.Trait(
            query_params="city=lyon-69&distance=25&districts_69=69001&districts_69=69003&districts_69=69006"
        )

    user = factory.SubFactory(PrescriberFactory)
    name = factory.Faker("sentence", nb_words=2)
    query_params = factory.LazyFunction(generate_query_params)
    created_at = factory.LazyFunction(timezone.now)
