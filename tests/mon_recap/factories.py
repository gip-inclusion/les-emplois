import string

import factory.fuzzy
from django.utils import timezone

from itou.mon_recap.enums import NotebookOrderKind
from itou.mon_recap.models import NotebookOrder
from tests.utils.testing import create_fake_postcode


class NotebookOrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = NotebookOrder

    class Params:
        in_qpv = factory.Trait(organization_is_in_qpv_or_zrr="Oui, QPV")
        in_zrr = factory.Trait(organization_is_in_qpv_or_zrr="Oui, ZRR")
        with_coworkers_emails = factory.Trait(
            coworkers_will_distribute=True, coworkers_emails=[factory.Faker("email", locale="fr_FR")]
        )

    created_at = factory.LazyFunction(timezone.now)
    email = factory.Faker("email", locale="fr_FR")
    is_in_priority_department = False
    is_first_order = False
    is_first_order_in_department = False
    organization_name = factory.Faker("name", locale="fr_FR")
    organization_type = "Service public"
    organization_is_in_network = True
    organization_network = ["France Travail"]
    organization_is_in_qpv_or_zrr = False
    role = "Accompagnateur"
    coworkers_will_distribute = False
    source = "Google"
    kind = NotebookOrderKind.DISCOVERY
    unit_price = 1.4
    amount = 15
    amount_wished = 15
    full_name = factory.Faker("name", locale="fr_FR")
    address = factory.Faker("address")
    siret = factory.fuzzy.FuzzyText(length=13, chars=string.digits, prefix="1")
    city = factory.Faker("city", locale="fr_FR")
    post_code = factory.LazyFunction(create_fake_postcode)
    phone_number = factory.fuzzy.FuzzyText(length=10, chars=string.digits)
