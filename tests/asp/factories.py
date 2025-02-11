import random

import factory

from itou.asp import models


_COMMUNES_CODES = ["64483", "97108", "97107", "37273", "13200", "67152", "85146", "58273"]


class CommuneFactory(factory.django.DjangoModelFactory):
    """Factory for ASP INSEE commune:
    - if `code` or `name` are build parameters, object values will taken from the given commune (if available)
    - otherwise, fields `code` and `name` will be set from a randomly picked sample commune
    """

    class Meta:
        model = models.Commune
        django_get_or_create = (
            "code",
            "start_date",
            "end_date",
        )

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        # Allow creation with parameters `code` or `name` (first matched)
        # either field must be a match in `_sample_communes`
        match kwargs:
            case {"code": code}:
                return models.Commune.objects.filter(code=code).values()[0]
            case {"name": name}:
                return models.Commune.objects.filter(name=name).values()[0]
            case _:
                return random.choice(models.Commune.objects.filter(code__in=_COMMUNES_CODES).values())
