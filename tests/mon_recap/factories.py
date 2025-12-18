import datetime
import json
import pathlib
import string

import factory.fuzzy

from itou.mon_recap import enums, models
from tests.utils.testing import create_fake_postcode


NOTEBOOK_UNIT_PRICE = 1.40
NOTEBOOK_QUANTITY_ELEMENTS = [2, 15, 40, 60, 100, 140, 200, 300, 400, 500]


class WebhookEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.WebhookEvent

    body = json.loads(pathlib.Path("tests/mon_recap/tally.json").read_text())
    # FIXME: add valid headers
    headers = {}
    is_processed = factory.Faker("boolean", chance_of_getting_true=30)


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Organization

    name = factory.Faker("name", locale="fr_FR")
    siret = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    kind = enums.OrganizationKind.PUBLIC_SERVICE
    is_in_network = True
    networks = [enums.OrganizationNetwork.FT]
    is_in_qpv = False
    is_in_zrr = False
    email = factory.Faker("email", locale="fr_FR")


class OrganizationAddressFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.OrganizationAddress

    full_name = factory.Faker("name", locale="fr_FR")
    street_address = factory.Faker("address")
    city = factory.Faker("city", locale="fr_FR")
    post_code = factory.LazyFunction(create_fake_postcode)
    phone = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
    organization = factory.SubFactory(OrganizationFactory)


class NotebookOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.NotebookOrder
        exclude = ("quantity",)

    class Params:
        with_coworkers_emails = factory.Trait(
            with_coworkers_distribution=True,
            coworkers_emails=[factory.Faker("email", locale="fr_FR") for _ in range(2)],
        )
        with_obstacles = factory.Trait(
            public_has_obstacles=True,
            public_main_obstacles=[
                enums.PublicObstacles.HOUSING,
                enums.PublicObstacles.HEALTH,
                enums.PublicObstacles.LANGUAGE,
            ],
        )

    state = enums.NotebookOrderState.NEW
    kind = enums.NotebookOrderKind.DISCOVERY
    requested_at = factory.Faker("date_time", end_datetime="-1d", tzinfo=datetime.UTC)
    requester_kind = enums.RequesterKind.COUNSELOR
    unit_price = NOTEBOOK_UNIT_PRICE
    quantity = factory.Faker("random_element", elements=NOTEBOOK_QUANTITY_ELEMENTS)
    quantity_requested = quantity
    quantity_delivered = quantity
    is_in_priority_department = False
    is_organization_first_order = False
    is_organization_first_order_in_department = False
    with_coworkers_distribution = False
    source = enums.DiscoverySource.MEETING
    public_is_autonomous = True
    public_has_other_tools = False
    public_has_obstacles = False
    organization = factory.SubFactory(OrganizationFactory)
    address = factory.SubFactory(OrganizationAddressFactory)
    webhook_event = factory.SubFactory(WebhookEventFactory)
